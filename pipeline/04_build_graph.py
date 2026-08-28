#!/usr/bin/env python3
"""Emit the BDRO instance graph as Turtle text.

Emits three files under graph/:
  identifiers.ttl  - every BHL DOI assertion and every title/part
                     identifier assertion in a validated scheme, plus
                     the NHM dataset DOI assertions
  rights.ttl       - one RightsAssertion per BHL item and per NHM dataset
  registers.ttl    - register snapshots, staleness, resolution observations
  defects.ttl      - the partition of nodes SHACL layers 2-3 run over:
                     all non-conformant assertions, all multiply-assigned
                     identifiers, all rights defects, all observations and
                     snapshots, plus a seeded 5,000-node sample of
                     conformant assertions (control)
Emitted as text and parse-verified afterwards; never built through rdflib.
"""
import csv, json, re, sys, random, collections, pathlib, datetime

RAW = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("raw")
ROOT = pathlib.Path(__file__).resolve().parent.parent
G = ROOT / "graph"; G.mkdir(exist_ok=True)
OUT = ROOT / "reports"; OUT.mkdir(exist_ok=True)
csv.field_size_limit(10_000_000)
random.seed(42)
TODAY = datetime.date.today()

B = "https://gov.tesseract.academy/def/biodiversity#"
S = "https://gov.tesseract.academy/def/biodiversity/scheme#"
PREFIX = f"""@prefix biodiv: <{B}> .
@prefix scheme: <{S}> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

"""

def esc(s):
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")

DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")

def issn_reason(v):
    s = v.replace("-", "").replace(" ", "").upper()
    if not re.fullmatch(r"\d{7}[\dX]", s):
        return "malformed-syntax"
    total = sum(int(c) * w for c, w in zip(s[:7], range(8, 1, -1)))
    check = (11 - total % 11) % 11
    return None if s[7] == ("X" if check == 10 else str(check)) else "checksum-failure"

def isbn_reason(v):
    s = re.sub(r"[- ]", "", v).upper()
    if re.fullmatch(r"\d{9}[\dX]", s):
        total = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(s))
        return None if total % 11 == 0 else "checksum-failure"
    if re.fullmatch(r"\d{13}", s):
        total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(s))
        return None if total % 10 == 0 else "checksum-failure"
    if re.search(r"[()\[\]a-wyzA-WYZ.:]", v):
        return "qualifier-contamination"
    return "malformed-syntax"

def oclc_reason(v):
    return None if re.fullmatch(r"(ocm|ocn|on)?\d{1,12}", v.strip().lower()) else "malformed-syntax"

def doi_reason(v):
    if v.startswith("https://doi.org/") or v.startswith("http://doi.org/") or v.startswith("http://dx.doi.org/"):
        return "resolver-prefix"
    if DOI_RE.match(v):
        return None
    return "not-a-doi"

stats = collections.Counter()
defect_nodes = []   # (node_id, turtle_text) for the defects partition
conformant_pool = []

# ---------------- identifiers.ttl ----------------
f = open(G / "identifiers.ttl", "w")
f.write(PREFIX)

def emit_assertion(fh, node, register, resource_cls, resource_id, scheme_c, value,
                   reason, cardinality=None, collect=True):
    lines = [f"biodiv:{node} a biodiv:IdentifierAssertion ;"]
    lines.append(f"    biodiv:assertedBy biodiv:{register} ;")
    lines.append(f"    biodiv:aboutResource biodiv:{resource_id} ;")
    lines.append(f"    biodiv:usesScheme scheme:{scheme_c} ;")
    lines.append(f'    biodiv:identifierValue "{esc(value)}" ;')
    if cardinality is not None and cardinality > 1:
        lines.append(f"    biodiv:resolutionCardinality {cardinality} ;")
    if reason:
        lines.append("    biodiv:schemeConformant false ;")
        lines.append(f'    biodiv:nonConformanceReason "{reason}" .')
    else:
        lines.append("    biodiv:schemeConformant true .")
    txt = "\n".join(lines) + "\n"
    txt += f"biodiv:{resource_id} a biodiv:{resource_cls} .\n"
    fh.write(txt)
    if collect:
        if reason or (cardinality is not None and cardinality > 1):
            defect_nodes.append(txt)
        else:
            conformant_pool.append(txt)

# BHL DOI assertions
doi_rows = list(csv.DictReader(open(RAW / "bhl_doi.txt", encoding="utf-8-sig"),
                               delimiter="\t", quoting=csv.QUOTE_NONE))
doi_card = collections.Counter()
for r in doi_rows:
    doi_card[r["DOI"].strip().lower()] += 0  # ensure key
doi_targets = collections.defaultdict(set)
for r in doi_rows:
    doi_targets[r["DOI"].strip().lower()].add((r["EntityType"], r["EntityID"]))
for i, r in enumerate(doi_rows):
    v = r["DOI"].strip()
    reason = doi_reason(v)
    card = len(doi_targets[v.lower()])
    cls = "BibliographicTitle" if r["EntityType"] == "Title" else "BibliographicPart"
    rid = f"bhl-{r['EntityType'].lower()}-{r['EntityID']}"
    emit_assertion(f, f"doia-{i}", "BHL", cls, rid, "DOI", v, reason, card)
    stats["doi_total"] += 1
    if reason:
        stats["doi_nonconformant"] += 1
    if card > 1:
        stats["doi_multiply_assigned_assertions"] += 1
stats["doi_values_multiply_assigned"] = sum(1 for v, t in doi_targets.items() if len(t) > 1)

# fix: emit_assertion signature used positionally above; keep scheme arg coherent
def ident_pass(fh, fname, idcol, cls, prefix):
    for j, r in enumerate(csv.DictReader(open(RAW / fname, encoding="utf-8-sig"),
                                         delimiter="\t", quoting=csv.QUOTE_NONE)):
        schemek = r["IdentifierName"].strip()
        v = r["IdentifierValue"].strip()
        if schemek == "ISSN":
            reason, sc = issn_reason(v), "ISSN"
        elif schemek == "ISBN":
            reason, sc = isbn_reason(v), "ISBN"
        elif schemek == "OCLC":
            reason, sc = oclc_reason(v), "OCLC"
        elif schemek == "DOI":
            reason, sc = doi_reason(v), "DOI"
        else:
            continue
        rid = f"{prefix}-{r[idcol]}"
        emit_assertion(fh, f"{prefix}a-{sc}-{j}", "BHL", cls, rid, sc, v, reason)
        stats[f"{sc}_checked"] += 1
        if reason:
            stats[f"{sc}_nonconformant"] += 1
            stats[f"{sc}_reason_{reason}"] += 1

ident_pass(f, "bhl_titleidentifier.txt", "TitleID", "BibliographicTitle", "bhl-title")
ident_pass(f, "bhl_partidentifier.txt", "PartID", "BibliographicPart", "bhl-part")

# NHM dataset DOI assertions
nhm = [json.loads(l) for l in open(RAW / "nhm_packages.jsonl")]
for k, r in enumerate(nhm):
    d = (r.get("doi") or "").strip()
    if d:
        reason = doi_reason(d)
        emit_assertion(f, f"nhmdoia-{k}", "NHMDataPortal", "DatasetDescription",
                       f"nhm-{r['name'].replace('.', '-')}", "DOI", d, reason)
        stats["nhm_doi_assertions"] += 1
f.close()

# ---------------- rights.ttl ----------------
fr = open(G / "rights.ttl", "w")
fr.write(PREFIX)
NONPRINT = re.compile(r"[^\x20-\x7E]")
CC_RE = re.compile(r"creativecommons\.org")
# The item table's ItemID is not unique (9,118 IDs recur, mostly with a
# different TitleID per row). One RightsAssertion per distinct ItemID;
# rows disagreeing on rights fields within an ItemID are counted.
seen_items = {}
item_title = collections.defaultdict(set)
for r in csv.DictReader(open(RAW / "bhl_item.txt", encoding="utf-8-sig"),
                        delimiter="\t", quoting=csv.QUOTE_NONE):
    stats["item_rows"] += 1
    item_title[r["ItemID"]].add(r["TitleID"])
    key = ((r.get("CopyrightStatus") or "").strip(),
           (r.get("LicenseType") or "").strip())
    if r["ItemID"] in seen_items:
        if seen_items[r["ItemID"]] != key:
            stats["item_dupe_rights_disagreements"] += 1
        continue
    seen_items[r["ItemID"]] = key
    iid = r["ItemID"]
    cs, lt = key
    actionable = bool(lt) and not NONPRINT.search(lt)
    lines = [f"biodiv:rights-item-{iid} a biodiv:RightsAssertion ;",
             "    biodiv:assertedBy biodiv:BHL ;",
             f"    biodiv:aboutResource biodiv:bhl-item-{iid} ;",
             f"    biodiv:machineActionableLicense {'true' if actionable else 'false'} ;"]
    if cs:
        lines.append(f'    biodiv:rawRightsString "{esc(cs)}" ;')
    if lt:
        lines.append(f'    biodiv:licenseIRI "{esc(lt)}" ;')
    lines[-1] = lines[-1].rstrip(" ;") + " ."
    txt = "\n".join(lines) + f"\nbiodiv:bhl-item-{iid} a biodiv:DigitisedItem .\n"
    fr.write(txt)
    stats["items_total"] += 1
    if not actionable:
        stats["items_without_machine_license"] += 1
    if lt and NONPRINT.search(lt):
        stats["items_license_invisible_chars"] += 1
        defect_nodes.append(txt)
    if lt and not lt.lower().startswith("http"):
        stats["items_license_not_iri"] += 1
stats["items_distinct"] = len(seen_items)
stats["item_surplus_rows"] = stats["item_rows"] - len(seen_items)
stats["item_ids_with_multiple_titles"] = sum(1 for v in item_title.values() if len(v) > 1)
for k, r in enumerate(nhm):
    lu = (r.get("license_url") or "").strip()
    li = (r.get("license_id") or "").strip()
    actionable = bool(lu)
    lines = [f"biodiv:rights-nhm-{k} a biodiv:RightsAssertion ;",
             "    biodiv:assertedBy biodiv:NHMDataPortal ;",
             f"    biodiv:aboutResource biodiv:nhm-{r['name'].replace('.', '-')} ;",
             f"    biodiv:machineActionableLicense {'true' if actionable else 'false'} ;"]
    if li:
        lines.append(f'    biodiv:rawRightsString "{esc(li)}" ;')
    if lu:
        lines.append(f'    biodiv:licenseIRI "{esc(lu)}" ;')
    lines[-1] = lines[-1].rstrip(" ;") + " ."
    fr.write("\n".join(lines) + "\n")
    stats["nhm_rights_assertions"] += 1
    if not actionable:
        stats["nhm_without_license_url"] += 1
fr.close()

# ---------------- registers.ttl ----------------
fg = open(G / "registers.ttl", "w")
fg.write(PREFIX)
snapshots = [
    ("snap-checklistbank-zoobank", "ZooBank", "ChecklistBank",
     datetime.date(2023, 1, 9), 399326),
    ("snap-gbif-zoobank", "ZooBank", "GBIFChecklist",
     datetime.date(2025, 3, 28), 478746),
]
for node, of, held, date, count in snapshots:
    days = (TODAY - date).days
    fg.write(f"""biodiv:{node} a biodiv:RegisterSnapshot ;
    biodiv:snapshotOf biodiv:{of} ;
    biodiv:heldBy biodiv:{held} ;
    biodiv:snapshotDate "{date.isoformat()}"^^xsd:date ;
    biodiv:recordCount {count} ;
    biodiv:stalenessDays {days} .
""")
    stats[f"staleness_{held}"] = days
obs = [json.loads(l) for l in open(OUT / "resolution_observations.jsonl")]
for m, o in enumerate(obs):
    reg = {"zoobank-act": "ZooBank", "worms": "WoRMS", "ipni": "IPNI",
           "doi-handle": "BHL"}.get(o["kind"], "BHL")
    status = o.get("http_status")
    if status is None:
        status = 200 if o.get("handle_response_code") == 1 else 404
    fg.write(f"""biodiv:obs-{m} a biodiv:ResolutionObservation ;
    biodiv:observedFor biodiv:{reg} ;
    biodiv:observedUrl "{esc(o['url'])}"^^xsd:anyURI ;
    biodiv:httpStatus {status} ;
    biodiv:observationDate "{o['date']}"^^xsd:date .
""")
    stats["observations_total"] += 1
    if o["kind"] == "zoobank-act" and status >= 400:
        stats["zoobank_dead_observations"] += 1
fg.close()

# ---------------- defects.ttl (SHACL partition) ----------------
fd = open(G / "defects.ttl", "w")
fd.write(PREFIX)
for txt in defect_nodes:
    fd.write(txt)
sample = random.sample(conformant_pool, min(5000, len(conformant_pool)))
for txt in sample:
    fd.write(txt)
fd.write(open(G / "registers.ttl").read().replace(PREFIX, ""))
fd.close()
stats["defect_partition_nodes"] = len(defect_nodes)
stats["control_sample_nodes"] = len(sample)

with open(OUT / "graph_stats.json", "w") as fh:
    json.dump(dict(stats), fh, indent=2, sort_keys=True)
print(json.dumps(dict(stats), indent=2, sort_keys=True))
