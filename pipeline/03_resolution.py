#!/usr/bin/env python3
"""Resolution census: do the identifiers the registers publish dereference?

Samples are seeded (seed 42) and every observation is cached to
reports/resolution_observations.jsonl so the run is resumable and the
graph build can replay observations without re-fetching. DOIs are
checked against the doi.org handle API (the registry of record), not
against publisher landing pages. ZooBank act URLs are checked against
zoobank.org exactly as GBIF's copy of the register publishes them in
`references`.
"""
import csv, json, random, re, subprocess, sys, pathlib, collections, datetime

RAW = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("raw")
OUT = pathlib.Path(__file__).resolve().parent.parent / "reports"
OUT.mkdir(exist_ok=True)
CACHE = OUT / "resolution_observations.jsonl"
csv.field_size_limit(10_000_000)
random.seed(42)
TODAY = datetime.date.today().isoformat()

seen = {}
if CACHE.exists():
    for line in open(CACHE):
        o = json.loads(line)
        seen[o["url"]] = o
cache_f = open(CACHE, "a")

def observe(url, kind):
    if url in seen:
        return seen[url]
    r = subprocess.run(["curl", "-sS", "-m", "20", "-o", "/dev/null",
                        "-w", "%{http_code}", "-L", url],
                       capture_output=True, text=True)
    try:
        code = int(r.stdout.strip() or 0)
    except ValueError:
        code = 0
    o = {"url": url, "kind": kind, "http_status": code, "date": TODAY}
    seen[url] = o
    cache_f.write(json.dumps(o) + "\n")
    cache_f.flush()
    return o

def handle_status(doi):
    """doi.org handle API responseCode: 1 = registered, 100 = not found."""
    url = "https://doi.org/api/handles/" + doi
    if url in seen:
        return seen[url]
    r = subprocess.run(["curl", "-sS", "-m", "20", url],
                       capture_output=True, text=True)
    try:
        rc = json.loads(r.stdout).get("responseCode")
    except Exception:
        rc = None
    o = {"url": url, "kind": "doi-handle", "doi": doi,
         "handle_response_code": rc, "date": TODAY}
    seen[url] = o
    cache_f.write(json.dumps(o) + "\n")
    cache_f.flush()
    return o

report = {"date": TODAY, "seed": 42}

# ---- BHL DOIs: stratified sample against the handle registry ----
rows = list(csv.DictReader(open(RAW / "bhl_doi.txt", encoding="utf-8-sig"),
                           delimiter="\t", quoting=csv.QUOTE_NONE))
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
good = [r["DOI"].strip() for r in rows if DOI_RE.match(r["DOI"].strip())]
bad = [r["DOI"].strip() for r in rows if not DOI_RE.match(r["DOI"].strip())]
bhl_own = [d for d in good if d.startswith("10.5962/")]
external = [d for d in good if not d.startswith("10.5962/")]
sample_own = random.sample(bhl_own, 40)
sample_ext = random.sample(external, 25)

def doi_tally(dois):
    tally = collections.Counter()
    misses = []
    for d in dois:
        rc = handle_status(d)["handle_response_code"]
        tally[str(rc)] += 1
        if rc != 1:
            misses.append(d)
    return tally, misses

t_own, m_own = doi_tally(sample_own)
t_ext, m_ext = doi_tally(sample_ext)
t_bad, m_bad = doi_tally([b for b in set(bad) if b != "Array"][:10] + ["10.5962/Array-placeholder-check"])
report["bhl_doi_handles"] = {
    "own_prefix_sample": 40, "own_prefix_registered": t_own.get("1", 0),
    "own_prefix_misses": m_own,
    "external_sample": 25, "external_registered": t_ext.get("1", 0),
    "external_misses": m_ext,
    "bad_syntax_checked": dict(t_bad),
}

# ---- ZooBank act URLs exactly as GBIF's copy publishes them ----
zb = list(csv.DictReader(open(RAW / "zoobank" / "NameUsage.tsv"),
                         delimiter="\t"))
uuid_re = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
zb_ids = [r["col:ID"] for r in zb if uuid_re.match(r["col:ID"])]
non_uuid = [r["col:ID"] for r in zb if not uuid_re.match(r["col:ID"])]
zb_sample = random.sample(zb_ids, 50)
zb_tally = collections.Counter()
for u in zb_sample:
    o = observe(f"https://zoobank.org/{u}", "zoobank-act")
    zb_tally[o["http_status"]] += 1
report["zoobank"] = {
    "register_records": len(zb),
    "non_uuid_ids": len(non_uuid),
    "sample": 50,
    "status_histogram": {str(k): v for k, v in zb_tally.items()},
    "resolved_200": zb_tally.get(200, 0),
}

# ---- NHM dataset DOIs ----
nhm = [json.loads(l) for l in open(RAW / "nhm_packages.jsonl")]
nhm_dois = [r["doi"] for r in nhm if r.get("doi")]
nhm_sample = random.sample(nhm_dois, 25)
t_nhm, m_nhm = doi_tally(nhm_sample)
report["nhm_dois"] = {"sample": 25, "registered": t_nhm.get("1", 0), "misses": m_nhm}

# ---- controls: registers that resolve ----
worms = [127160, 105838, 141433, 137094, 219839, 106331, 126436, 140528, 148744, 234025]
w_ok = sum(1 for i in worms if observe(
    f"https://www.marinespecies.org/rest/AphiaRecordByAphiaID/{i}", "worms")["http_status"] == 200)
ipni = ["296689-1", "30000959-2", "77126626-1", "60447743-2", "320035-2"]
i_ok = sum(1 for i in ipni if observe(
    f"https://www.ipni.org/n/{i}", "ipni")["http_status"] == 200)
report["controls"] = {"worms_ok": f"{w_ok}/10", "ipni_ok": f"{i_ok}/5"}

with open(OUT / "resolution_census.json", "w") as f:
    json.dump(report, f, indent=2)
print(json.dumps(report, indent=2))
