#!/usr/bin/env python3
"""Reconcile GBIF's served usage count against the ZooBank archive, 31 Aug 2026.

After GBIF's successful crawl of 30 August 2026 it served 527,163 usages while
the source archive contains 527,127 rows and the IPT still declares 527,127
with an EML datestamp of 29 August, so the archive had not been republished.
The article first published that 36 record excess as unexplained. It is not.

GBIF's own origin facet splits its count into rows taken from the source and
usages it synthesised, and the residual is explained by rows it rejected. The
rejected rows are three of the five blank scientificName records already
reported as finding R3, which closes the loop between our defect list and
GBIF's count.

Writes reports/zoobank_gbif_reconciliation.json.
"""
import csv, json, pathlib, urllib.request, urllib.parse, zipfile, io
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "reports"
KEY = "c8227bb4-4143-443f-8cb2-51f9576aff14"


def api(url):
    with urllib.request.urlopen(url, timeout=45) as h:
        return json.load(h)


# archive row count, recomputed rather than quoted
with zipfile.ZipFile(OUT / "zoobank_dwca.zip") as z:
    with z.open("taxon.txt") as f:
        t = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
        t.readline()
        archive_rows = sum(1 for _ in t)
    meta = z.read("meta.xml").decode("utf-8", "replace")
extensions = meta.count("<extension")

# GBIF's split of its own count
facet = api(f"https://api.gbif.org/v1/species/search?datasetKey={KEY}"
            f"&facet=origin&facetLimit=20&limit=0")
origins = {c["name"]: c["count"] for f in facet.get("facets", [])
           for c in f.get("counts", [])}
gbif_total = facet["count"]
source = origins.get("SOURCE", 0)
denormed = origins.get("DENORMED_CLASSIFICATION", 0)

# which of the R3 blank-name records survived into GBIF
r3 = list(csv.DictReader(open(OUT / "zoobank_R3_blank_scientific_name.csv")))
r3_state = []
for row in r3:
    tid = row["taxonID"]
    d = api(f"https://api.gbif.org/v1/species?datasetKey={KEY}"
            f"&sourceId={urllib.parse.quote(tid)}")
    res = d.get("results", [])
    rec = {"taxonID": tid, "present_in_gbif": bool(res)}
    if res:
        r = res[0]
        rec.update({"gbif_key": r.get("key"),
                    "scientificName": r.get("scientificName"),
                    "nameType": r.get("nameType"),
                    "taxonomicStatus": r.get("taxonomicStatus"),
                    "issues": r.get("issues")})
    r3_state.append(rec)

rejected = [r for r in r3_state if not r["present_in_gbif"]]
accepted_nameless = [r for r in r3_state if r["present_in_gbif"]]

reconciles = (archive_rows - len(rejected) + denormed) == gbif_total

result = {
    "generated": datetime.now(timezone.utc).isoformat(),
    "archive_rows": archive_rows,
    "archive_extensions_declared": extensions,
    "gbif_usages_total": gbif_total,
    "gbif_origin_split": origins,
    "r3_blank_name_records": len(r3_state),
    "r3_rejected_by_gbif": len(rejected),
    "r3_accepted_by_gbif": len(accepted_nameless),
    "identity": (f"{archive_rows} archive rows - {len(rejected)} rejected "
                 f"+ {denormed} synthesised = {gbif_total}"),
    "reconciles": reconciles,
    "residual": gbif_total - (archive_rows - len(rejected) + denormed),
    "finding_gbif_accepted_nameless_records": accepted_nameless,
    "r3_detail": r3_state,
}

json.dump(result, open(OUT / "zoobank_gbif_reconciliation.json", "w"), indent=2)
print(json.dumps({k: v for k, v in result.items() if k != "r3_detail"}, indent=2))
print(f"\nwrote {OUT / 'zoobank_gbif_reconciliation.json'}")
if not reconciles:
    raise SystemExit("RECONCILIATION FAILED")
