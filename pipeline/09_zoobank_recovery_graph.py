#!/usr/bin/env python3
"""Emit the ZooBank recovery graph and run the three-path verification gate.

Path 1: set-based counts, from 08, in reports/zoobank_recovery.json.
Path 2: SPARQL over the emitted Turtle after a full rdflib parse.
Path 3: open-ontologies validate and lint over the same file.

Any disagreement between path 1 and path 2 exits non-zero. The graph carries
every broken internal reference plus a seeded control sample of resolving
ones, so the SHACL layers have both a defect partition and a control.
"""
import csv, io, json, pathlib, random, subprocess, sys, zipfile
from collections import OrderedDict

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "reports"
G = ROOT / "graph"
OO = pathlib.Path("/Users/fabio/projects/open-ontologies/target/release/open-ontologies")

B = "https://gov.tesseract.academy/def/biodiversity#"
stats = json.load(open(OUT / "zoobank_recovery.json"))
resolution = json.load(open(OUT / "zoobank_recovery_resolution.json"))
CONTROL_N = 5000
random.seed(42)


def esc(s):
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "")


# ------------------------------------------------------------ collect refs
z = zipfile.ZipFile(OUT / "zoobank_dwca.zip")
ids = set()
recs = {}
with z.open("taxon.txt") as fh:
    t = io.TextIOWrapper(fh, encoding="utf-8", errors="replace", newline="")
    for row in csv.DictReader(t, delimiter="\t", quoting=csv.QUOTE_NONE):
        tid = (row.get("taxonID") or "").strip()
        ids.add(tid)
        p = (row.get("parentNameUsageID") or "").strip()
        o = (row.get("originalNameUsageID") or "").strip()
        if p or o:
            recs[tid] = (p, o, (row.get("parentNameUsage") or "").strip(),
                         (row.get("originalNameUsage") or "").strip(),
                         (row.get("scientificName") or "").strip())

broken, resolving = [], []
for tid, (p, o, pn, on, sn) in recs.items():
    if p:
        (broken if p not in ids else resolving).append((tid, "parentNameUsageID", p, pn, sn, p in ids))
    if o:
        (broken if o not in ids else resolving).append((tid, "originalNameUsageID", o, on, sn, o in ids))

control = random.sample(resolving, min(CONTROL_N, len(resolving)))
print(f"broken internal references: {len(broken)}; resolving: {len(resolving)}; control sample: {len(control)}")

# ------------------------------------------------------------- emit turtle
lines = [
    "@prefix biodiv: <https://gov.tesseract.academy/def/biodiversity#> .",
    "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
    "",
    "biodiv:snap-ipt-zoobank-2026-08-29 a biodiv:RegisterSnapshot ;",
    "    biodiv:snapshotOf biodiv:ZooBank ;",
    "    biodiv:heldBy biodiv:BishopMuseumIPT ;",
    f'    biodiv:snapshotDate "{stats["eml_pubDate"]}"^^xsd:date ;',
    f'    biodiv:recordCount {stats["rows"]} ;',
    "    biodiv:stalenessDays 1 .",
    "biodiv:BishopMuseumIPT a biodiv:Register .",
    "biodiv:ZooBank a biodiv:Register .",
    "",
]

for i, (tid, role, target, label, sn, ok) in enumerate(broken + control):
    n = f"biodiv:iref-rec-{i}"
    lines += [
        f"{n} a biodiv:InternalReferenceAssertion ;",
        f"    biodiv:assertedBy biodiv:ZooBank ;",
        f"    biodiv:referenceSubject biodiv:zb-{tid} ;",
        f'    biodiv:referenceRole "{esc(role)}" ;',
        f'    biodiv:referenceTarget "{esc(target)}" ;',
        f'    biodiv:referenceTargetLabel "{esc(label)}" ;',
        f'    biodiv:assertedDate "{stats["eml_pubDate"]}"^^xsd:date ;',
        f"    biodiv:referenceResolves {'true' if ok else 'false'} .",
        f"biodiv:zb-{tid} a biodiv:NomenclaturalActRecord .",
    ]

for i, obs in enumerate(resolution):
    lines += [
        f"biodiv:robs-{i} a biodiv:ResolutionObservation ;",
        "    biodiv:observedFor biodiv:ZooBank ;",
        f'    biodiv:observedUrl "{esc(obs["url"])}"^^xsd:anyURI ;',
        f"    biodiv:httpStatus {int(obs['http']) if obs['http'].isdigit() else 0} ;",
        '    biodiv:observationDate "2026-08-30"^^xsd:date .',
    ]

path = G / "zoobank-recovery.ttl"
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"wrote {path} ({path.stat().st_size:,} bytes)")

# ------------------------------------------------------- path 2: SPARQL
import rdflib

g = rdflib.Graph()
g.parse(path, format="turtle")
print(f"parsed: {len(g)} triples")

q = lambda s: int(next(iter(g.query(s)))[0])
failures, report = [], OrderedDict()


def check(name, set_based, sparql_based):
    ok = set_based == sparql_based
    report[name] = {"set_based": set_based, "sparql": sparql_based, "agree": ok}
    print(f"{'OK  ' if ok else 'FAIL'} {name}: set={set_based} sparql={sparql_based}")
    if not ok:
        failures.append(name)


check("record_count", stats["rows"],
      q(f"""SELECT ?n WHERE {{
            ?s a <{B}RegisterSnapshot> ;
               <{B}heldBy> <{B}BishopMuseumIPT> ;
               <{B}recordCount> ?n . }}"""))

check("orphan_parentNameUsageID", stats["orphan_parentNameUsageID"],
      q(f"""SELECT (COUNT(?a) AS ?n) WHERE {{
            ?a a <{B}InternalReferenceAssertion> ;
               <{B}referenceRole> "parentNameUsageID" ;
               <{B}referenceResolves> false . }}"""))

check("orphan_originalNameUsageID", stats["orphan_originalNameUsageID"],
      q(f"""SELECT (COUNT(?a) AS ?n) WHERE {{
            ?a a <{B}InternalReferenceAssertion> ;
               <{B}referenceRole> "originalNameUsageID" ;
               <{B}referenceResolves> false . }}"""))

check("broken_references_total",
      stats["orphan_parentNameUsageID"] + stats["orphan_originalNameUsageID"],
      q(f"""SELECT (COUNT(?a) AS ?n) WHERE {{
            ?a a <{B}InternalReferenceAssertion> ;
               <{B}referenceResolves> false . }}"""))

check("control_sample_all_resolve", len(control),
      q(f"""SELECT (COUNT(?a) AS ?n) WHERE {{
            ?a a <{B}InternalReferenceAssertion> ;
               <{B}referenceResolves> true . }}"""))

check("dead_act_urls", sum(1 for o in resolution if o["http"] == "404"),
      q(f"""SELECT (COUNT(?o) AS ?n) WHERE {{
            ?o a <{B}ResolutionObservation> ;
               <{B}observedFor> <{B}ZooBank> ;
               <{B}httpStatus> 404 . }}"""))

check("resolution_sample_size", len(resolution),
      q(f"""SELECT (COUNT(?o) AS ?n) WHERE {{
            ?o a <{B}ResolutionObservation> ;
               <{B}observedFor> <{B}ZooBank> . }}"""))

# ------------------------------------------- path 3: open-ontologies engine
oo = {}
for cmd in ("validate", "lint"):
    p = subprocess.run([str(OO), cmd, str(path)], capture_output=True, text=True)
    oo[cmd] = p.stdout.strip()[:2000]
    print(f"\nopen-ontologies {cmd}: {oo[cmd][:400]}")

p = subprocess.run([str(OO), "validate", str(ROOT / "ontology" / "biodiversity-register-ontology.ttl")],
                   capture_output=True, text=True)
oo["validate_ontology"] = p.stdout.strip()[:500]
print(f"open-ontologies validate (ontology): {oo['validate_ontology']}")

report["open_ontologies"] = oo
report["failures"] = failures
json.dump(report, open(OUT / "zoobank_recovery_verification.json", "w"), indent=2)
print(f"\nwrote {OUT / 'zoobank_recovery_verification.json'}")

if failures:
    print(f"\nVERIFICATION FAILED: {failures}")
    sys.exit(1)
print("\nAll headline numbers agree across set-based and SPARQL paths.")
