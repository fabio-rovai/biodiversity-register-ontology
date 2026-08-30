#!/usr/bin/env python3
"""ZooBank recovery census, 30 Aug 2026.

The 28 Aug build recorded ZooBank as machine-dead: every zoobank.org route
except the homepage returned 404, and the Bishop Museum IPT, ZooBank's
declared publication endpoint, returned 404 for the resource page, the EML
and the archive. The register content was reachable only through two stale
mirrors.

On 29 Aug 2026 the IPT was rebuilt by the ZooBank registrar. This script
re-runs the census against the recovered archive so that the article's
recovery correction rests on measurements rather than on the announcement.

Set-based counts are written to reports/zoobank_recovery.json. 09 recomputes
every headline over the emitted Turtle with SPARQL and exits non-zero on any
disagreement, and open-ontologies validate/lint is the third path.
"""
import csv, io, json, hashlib, pathlib, random, re, sys, urllib.request, zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "reports"
OUT.mkdir(exist_ok=True)

ARCHIVE_URL = "http://ipt.bishopmuseum.org:8080/ipt/archive.do?r=zoobank"
CACHE = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else OUT / "zoobank_dwca.zip"

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
OBSERVED = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

# Prior snapshots, from the 28 Aug build. Used for the delta only.
PRIOR = {
    "checklistbank_2037": {"records": 399326, "pubDate": "2023-01-09"},
    "gbif_c8227bb4": {"records": 478746, "pubDate": "2025-03-28"},
}

if not CACHE.exists():
    print(f"fetching {ARCHIVE_URL} ...")
    urllib.request.urlretrieve(ARCHIVE_URL, CACHE)

sha = hashlib.sha256(CACHE.read_bytes()).hexdigest()
print(f"archive: {CACHE} {CACHE.stat().st_size:,} bytes sha256={sha[:16]}...")

z = zipfile.ZipFile(CACHE)
eml = z.read("eml.xml").decode("utf-8", "replace")
pub_date = re.search(r"<pubDate>(.*?)</pubDate>", eml, re.S)
pub_date = pub_date.group(1).strip() if pub_date else None

r = {
    "observed_at": OBSERVED,
    "archive_bytes": CACHE.stat().st_size,
    "archive_sha256": sha,
    "eml_pubDate": pub_date,
    "prior_snapshots": PRIOR,
}

# ---------------------------------------------------------------- pass 1
ids, dup_ids = set(), Counter()
rows = 0
id_taxonid_mismatch = 0
nonuuid_taxonid, nonuuid_examples = 0, []
parent_of, accepted_of, original_of = {}, {}, {}
napid, npid = set(), set()
refs_host = Counter()
refs_bad_form, refs_missing = 0, 0
license_vals, status_vals, code_vals, rank_vals = Counter(), Counter(), Counter(), Counter()
modified_bad, modified_future, modified_min, modified_max = 0, 0, None, None
year_vals, year_bad, year_pre1758 = [], 0, 0
no_authorship = 0
blank_scientific_name = 0
sample_pool = []

with z.open("taxon.txt") as fh:
    t = io.TextIOWrapper(fh, encoding="utf-8", errors="replace", newline="")
    rdr = csv.DictReader(t, delimiter="\t", quoting=csv.QUOTE_NONE)
    for row in rdr:
        rows += 1
        tid = (row.get("taxonID") or "").strip()
        rid = (row.get("id") or "").strip()
        if tid in ids:
            dup_ids[tid] += 1
        ids.add(tid)
        if rid != tid:
            id_taxonid_mismatch += 1
        if not UUID_RE.match(tid):
            nonuuid_taxonid += 1
            if len(nonuuid_examples) < 20:
                nonuuid_examples.append(tid)

        p = (row.get("parentNameUsageID") or "").strip()
        a = (row.get("acceptedNameUsageID") or "").strip()
        o = (row.get("originalNameUsageID") or "").strip()
        if p:
            parent_of[tid] = p
        if a:
            accepted_of[tid] = a
        if o:
            original_of[tid] = o
        n1 = (row.get("nameAccordingToID") or "").strip()
        n2 = (row.get("namePublishedInID") or "").strip()
        if n1:
            napid.add(n1)
        if n2:
            npid.add(n2)

        ref = (row.get("references") or "").strip()
        if not ref:
            refs_missing += 1
        else:
            m = re.match(r"^https?://([^/]+)/(.*)$", ref)
            if not m:
                refs_bad_form += 1
            else:
                refs_host[m.group(1)] += 1
                if not UUID_RE.match(m.group(2)):
                    refs_bad_form += 1
                elif len(sample_pool) < 400000:
                    sample_pool.append(ref)

        license_vals[(row.get("license") or "").strip()] += 1
        status_vals[(row.get("taxonomicStatus") or "").strip()] += 1
        code_vals[(row.get("nomenclaturalCode") or "").strip()] += 1
        rank_vals[(row.get("taxonRank") or "").strip()] += 1

        if not (row.get("scientificNameAuthorship") or "").strip():
            no_authorship += 1
        if not (row.get("scientificName") or "").strip():
            blank_scientific_name += 1

        mod = (row.get("modified") or "").strip()
        if mod:
            try:
                d = datetime.fromisoformat(mod.replace("Z", "+00:00"))
                dn = d.replace(tzinfo=None)
                modified_min = dn if modified_min is None else min(modified_min, dn)
                modified_max = dn if modified_max is None else max(modified_max, dn)
                if dn > datetime.utcnow():
                    modified_future += 1
            except ValueError:
                modified_bad += 1

        y = (row.get("namePublishedInYear") or "").strip()
        if y:
            if re.match(r"^\d{4}$", y):
                yi = int(y)
                year_vals.append(yi)
                if yi < 1758:
                    year_pre1758 += 1
            else:
                year_bad += 1

r["rows"] = rows
r["distinct_taxonID"] = len(ids)
r["duplicate_taxonID_values"] = len(dup_ids)
r["duplicate_surplus_rows"] = sum(dup_ids.values())
r["id_vs_taxonID_mismatch"] = id_taxonid_mismatch
r["nonuuid_taxonID"] = nonuuid_taxonid
r["nonuuid_examples"] = nonuuid_examples

# ------------------------------------------------- referential integrity
def dangling(mapping):
    return sorted(k for k, v in mapping.items() if v not in ids)

orphan_parent = dangling(parent_of)
orphan_accepted = dangling(accepted_of)
orphan_original = dangling(original_of)
self_parent = sorted(k for k, v in parent_of.items() if k == v)

r["rows_with_parent"] = len(parent_of)
r["orphan_parentNameUsageID"] = len(orphan_parent)
r["orphan_parent_examples"] = orphan_parent[:20]
r["rows_with_acceptedNameUsageID"] = len(accepted_of)
r["orphan_acceptedNameUsageID"] = len(orphan_accepted)
r["orphan_accepted_examples"] = orphan_accepted[:20]
r["rows_with_originalNameUsageID"] = len(original_of)
r["orphan_originalNameUsageID"] = len(orphan_original)
r["self_parenting"] = len(self_parent)

# nameAccordingToID / namePublishedInID point at publication records that are
# not rows of the taxon core. Reported separately, never as orphans.
r["distinct_nameAccordingToID"] = len(napid)
r["distinct_namePublishedInID"] = len(npid)
r["nameAccordingToID_also_a_taxonID"] = len(napid & ids)

# cycles in the parent chain
seen_state = {}
cycles = 0
cycle_examples = []
for start in parent_of:
    path, cur = [], start
    while cur in parent_of and cur not in seen_state:
        seen_state[cur] = "open"
        path.append(cur)
        cur = parent_of[cur]
        if cur in path:
            cycles += 1
            if len(cycle_examples) < 10:
                cycle_examples.append(path[path.index(cur):][:6])
            break
    for n in path:
        seen_state[n] = "closed"
r["parent_chain_cycles"] = cycles
r["parent_chain_cycle_examples"] = cycle_examples

# -------------------------------------------------------- vocabularies
r["license_values"] = dict(license_vals.most_common(10))
r["taxonomicStatus_values"] = dict(status_vals.most_common(15))
r["nomenclaturalCode_values"] = dict(code_vals.most_common(10))
r["taxonRank_values"] = dict(rank_vals.most_common(15))
r["references_hosts"] = dict(refs_host.most_common(10))
r["references_missing"] = refs_missing
r["references_bad_form"] = refs_bad_form
r["no_authorship"] = no_authorship
r["blank_scientificName"] = blank_scientific_name
r["modified_unparseable"] = modified_bad
r["modified_in_future"] = modified_future
r["modified_min"] = modified_min.isoformat() if modified_min else None
r["modified_max"] = modified_max.isoformat() if modified_max else None
r["namePublishedInYear_malformed"] = year_bad
r["namePublishedInYear_pre_1758"] = year_pre1758
r["namePublishedInYear_min"] = min(year_vals) if year_vals else None
r["namePublishedInYear_max"] = max(year_vals) if year_vals else None
r["namePublishedInYear_after_observation"] = sum(1 for y in year_vals if y > 2026)

# ----------------------------------------------------------- the delta
r["delta_vs_gbif_served"] = rows - PRIOR["gbif_c8227bb4"]["records"]
r["delta_vs_checklistbank"] = rows - PRIOR["checklistbank_2037"]["records"]

json.dump(r, open(OUT / "zoobank_recovery.json", "w"), indent=2, default=str)
print(json.dumps({k: v for k, v in r.items() if not k.endswith("examples")}, indent=2, default=str))
print(f"\nwrote {OUT / 'zoobank_recovery.json'}")

# resolution sample is written separately so the census can be re-run offline
random.seed(42)
pool = sorted(set(sample_pool))
json.dump(random.sample(pool, min(50, len(pool))),
          open(OUT / "zoobank_recovery_sample.json", "w"), indent=2)
print(f"wrote {OUT / 'zoobank_recovery_sample.json'} (seed 42, 50 canonical act URLs)")
