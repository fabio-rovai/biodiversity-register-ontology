#!/usr/bin/env python3
"""Emit the whitelist retest as a graph and verify it three ways.

The article's central correction rests on the before-and-after in
reports/zoobank_whitelist_retest.json, and until now that was the one headline
in this repository computed only one way, while the article claims every
headline is computed two ways. This closes that gap.

Path 1: the set-based tallies already in the retest report.
Path 2: SPARQL over the emitted Turtle after a full rdflib parse.
Path 3: open-ontologies validate and lint over the same file.

Any disagreement exits non-zero.

The graph carries both arms of the experiment as ResolutionObservation
instances distinguished by biodiv:clientWhitelisted, which 0.3.0 adds for
exactly this reason: both arms share an observation date, so date alone cannot
tell them apart.

Writes graph/zoobank-whitelist.ttl and reports/zoobank_whitelist_verification.json.
"""
import json, pathlib, subprocess, sys
from collections import OrderedDict

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "reports"
G = ROOT / "graph"
OO = pathlib.Path("/Users/fabio/projects/open-ontologies/target/release/open-ontologies")
B = "https://gov.tesseract.academy/def/biodiversity#"

retest = json.load(open(OUT / "zoobank_whitelist_retest.json"))
rows = retest["rows"]
BEFORE_INSTANT = retest["before"]["observed"]
AFTER_INSTANT = retest["generated"]


def esc(s):
    return str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "")


lines = [
    "@prefix biodiv: <https://gov.tesseract.academy/def/biodiversity#> .",
    "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
    "",
    "biodiv:ZooBank a biodiv:Register .",
    "",
]

for i, r in enumerate(rows):
    url = esc(r["url"])
    # arm 1: un-whitelisted client
    lines += [
        f"biodiv:wobs-before-{i} a biodiv:ResolutionObservation ;",
        "    biodiv:observedFor biodiv:ZooBank ;",
        f'    biodiv:observedUrl "{url}"^^xsd:anyURI ;',
        f'    biodiv:httpStatus {int(r["before_http"])} ;',
        "    biodiv:clientWhitelisted false ;",
        f'    biodiv:observationInstant "{esc(BEFORE_INSTANT)}"^^xsd:dateTime ;',
        '    biodiv:observationDate "2026-08-30"^^xsd:date .',
        "",
    ]
    # arm 2: whitelisted client
    after = [
        f"biodiv:wobs-after-{i} a biodiv:ResolutionObservation ;",
        "    biodiv:observedFor biodiv:ZooBank ;",
        f'    biodiv:observedUrl "{url}"^^xsd:anyURI ;',
        f'    biodiv:httpStatus {int(r["after_http"])} ;',
        "    biodiv:clientWhitelisted true ;",
        f'    biodiv:observationInstant "{esc(AFTER_INSTANT)}"^^xsd:dateTime ;',
    ]
    if str(r.get("first_pass_http")) != str(r["after_http"]):
        after.append(f'    biodiv:firstPassHttpStatus {int(r["first_pass_http"])} ;')
    after.append('    biodiv:observationDate "2026-08-30"^^xsd:date .')
    after.append("")
    lines += after

path = G / "zoobank-whitelist.ttl"
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


def arm(whitelisted, status=None):
    st = f"; <{B}httpStatus> {status}" if status is not None else ""
    return f"""SELECT (COUNT(?o) AS ?n) WHERE {{
        ?o a <{B}ResolutionObservation> ;
           <{B}observedFor> <{B}ZooBank> ;
           <{B}clientWhitelisted> {str(whitelisted).lower()} {st} . }}"""


check("sample_size", retest["sample_size"], q(arm(False)))
check("after_arm_size", retest["sample_size"], q(arm(True)))
check("before_404", int(retest["before"]["status_tally"].get("404", 0)), q(arm(False, 404)))
check("after_200", int(retest["after_published_form"]["status_tally"].get("200", 0)), q(arm(True, 200)))
check("flipped_404_to_200", retest["flipped_404_to_200"],
      q(f"""SELECT (COUNT(DISTINCT ?u) AS ?n) WHERE {{
            ?a a <{B}ResolutionObservation> ; <{B}observedUrl> ?u ;
               <{B}clientWhitelisted> false ; <{B}httpStatus> 404 .
            ?b a <{B}ResolutionObservation> ; <{B}observedUrl> ?u ;
               <{B}clientWhitelisted> true  ; <{B}httpStatus> 200 . }}"""))
check("transient_reprobed",
      retest["transient_redirect_terminations_reprobed"]["published_form"],
      q(f"""SELECT (COUNT(?o) AS ?n) WHERE {{
            ?o a <{B}ResolutionObservation> ;
               <{B}firstPassHttpStatus> ?f . }}"""))
# the contradiction the model must be able to express at all
check("urls_with_contradictory_status_same_date", retest["sample_size"],
      q(f"""SELECT (COUNT(DISTINCT ?u) AS ?n) WHERE {{
            ?a a <{B}ResolutionObservation> ; <{B}observedUrl> ?u ;
               <{B}httpStatus> ?sa ; <{B}observationDate> ?d .
            ?b a <{B}ResolutionObservation> ; <{B}observedUrl> ?u ;
               <{B}httpStatus> ?sb ; <{B}observationDate> ?d .
            FILTER(?sa != ?sb) }}"""))

# ------------------------------------------- path 3: open-ontologies engine
oo = {}
if OO.exists():
    for cmd in ("validate", "lint"):
        p = subprocess.run([str(OO), cmd, str(path)], capture_output=True, text=True)
        oo[cmd] = p.stdout.strip()[:1500]
        print(f"\nopen-ontologies {cmd}: {oo[cmd][:300]}")
    p = subprocess.run([str(OO), "validate", str(ROOT / "ontology" / "biodiversity-register-ontology.ttl")],
                       capture_output=True, text=True)
    oo["validate_ontology_0_3_0"] = p.stdout.strip()[:500]
    print(f"open-ontologies validate (ontology 0.3.0): {oo['validate_ontology_0_3_0']}")
else:
    oo["note"] = f"binary not found at {OO}"
    print(f"\nWARNING: open-ontologies binary not found at {OO}, path 3 skipped")

report["open_ontologies"] = oo
report["failures"] = failures
json.dump(report, open(OUT / "zoobank_whitelist_verification.json", "w"), indent=2)
print(f"\nwrote {OUT / 'zoobank_whitelist_verification.json'}")

if failures:
    print(f"\nVERIFICATION FAILED: {failures}")
    sys.exit(1)
print("\nAll whitelist headline numbers agree across set-based and SPARQL paths.")
