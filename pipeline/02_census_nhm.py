#!/usr/bin/env python3
"""Metadata-readiness census of the NHM Data Portal (CKAN).

Measures, over every public dataset on data.nhm.ac.uk, the completeness
of the fields a licensing or data-product platform needs: licence,
persistent identifier (DOI), contact, update cadence, temporal and
spatial coverage, and resource-level format/size metadata. Writes
reports/nhm_census.json.
"""
import json, sys, collections, pathlib, re

RAW = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("raw")
OUT = pathlib.Path(__file__).resolve().parent.parent / "reports"
OUT.mkdir(exist_ok=True)

recs = [json.loads(l) for l in open(RAW / "nhm_packages.jsonl")]
n = len(recs)

def filled(v):
    return v is not None and str(v).strip() != ""

report = {"total_datasets": n}

lic = collections.Counter((r.get("license_id") or "(none)") for r in recs)
report["license_ids"] = lic.most_common()
report["datasets_without_license_url"] = sum(1 for r in recs if not filled(r.get("license_url")))
report["open_datasets"] = sum(1 for r in recs if r.get("isopen"))

doi_status = collections.Counter(str(r.get("doi_status")) for r in recs)
report["doi_status_values"] = dict(doi_status)
report["datasets_with_doi"] = sum(1 for r in recs if filled(r.get("doi")))
report["dois"] = sorted({r["doi"] for r in recs if filled(r.get("doi"))})[:5]

for field in ["author", "author_email", "maintainer", "maintainer_email",
              "update_frequency", "temporal_extent", "spatial", "version", "url"]:
    report[f"filled_{field}"] = sum(1 for r in recs if filled(r.get(field)))

freq = collections.Counter((r.get("update_frequency") or "(none)") for r in recs)
report["update_frequency_values"] = freq.most_common()

notes_len = [len((r.get("notes") or "").strip()) for r in recs]
report["datasets_without_description"] = sum(1 for L in notes_len if L == 0)
report["datasets_description_under_100_chars"] = sum(1 for L in notes_len if L < 100)

cat = collections.Counter()
for r in recs:
    cs = r.get("dataset_category") or []
    if not cs:
        cat["(none)"] += 1
    for c in cs:
        cat[c] += 1
report["dataset_categories"] = cat.most_common()

# resource layer
res_total = 0
res_no_format = 0
res_no_size = 0
res_no_desc = 0
fmt = collections.Counter()
dead_url_schemes = collections.Counter()
for r in recs:
    for res in r.get("resources", []):
        res_total += 1
        f = (res.get("format") or "").strip()
        fmt[f or "(blank)"] += 1
        if not f:
            res_no_format += 1
        if not res.get("size"):
            res_no_size += 1
        if not filled(res.get("description")):
            res_no_desc += 1
        u = res.get("url") or ""
        m = re.match(r"^(https?)://", u)
        dead_url_schemes[m.group(1) if m else "(other)"] += 1
report["resources"] = {
    "total": res_total,
    "no_format": res_no_format,
    "no_size": res_no_size,
    "no_description": res_no_desc,
    "formats": fmt.most_common(20),
    "url_schemes": dict(dead_url_schemes),
}

# the CCE-readiness roll-up: all of licence + doi + contact + description + update cadence
def ready(r):
    return (filled(r.get("license_url"))
            and filled(r.get("doi"))
            and (filled(r.get("author_email")) or filled(r.get("maintainer_email")))
            and len((r.get("notes") or "").strip()) >= 100
            and filled(r.get("update_frequency")))
report["fully_ready"] = sum(1 for r in recs if ready(r))
report["readiness_criteria"] = ("license_url AND doi AND a contact email AND "
                                "description >= 100 chars AND update_frequency")

with open(OUT / "nhm_census.json", "w") as f:
    json.dump(report, f, indent=2)
print(json.dumps(report, indent=2)[:3500])
