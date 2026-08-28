#!/usr/bin/env python3
"""Resolution leg of the second mining pass.

Checks the suspect ORCIDs against the ORCID public API (a checksum-
failing ORCID can never have been issued, so a 404 corroborates the
validator), a seeded sample of valid ORCIDs as control, and the liveness
of every resource URL on the NHM Data Portal. Observations append to the
same cache as 03 so everything stays replayable.
"""
import json, re, random, subprocess, pathlib, collections, datetime, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "reports"
RAW = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("raw")
CACHE = OUT / "resolution_observations.jsonl"
random.seed(42)
TODAY = datetime.date.today().isoformat()

seen = {}
for line in open(CACHE):
    o = json.loads(line)
    seen[o["url"]] = o
cache_f = open(CACHE, "a")

def curl_status(url, kind, headers=None):
    if url in seen:
        return seen[url]["http_status"]
    cmd = ["curl", "-sS", "-m", "20", "-o", "/dev/null", "-w", "%{http_code}", "-L", url]
    for h in headers or []:
        cmd += ["-H", h]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        code = int(r.stdout.strip() or 0)
    except ValueError:
        code = 0
    o = {"url": url, "kind": kind, "http_status": code, "date": TODAY}
    seen[url] = o
    cache_f.write(json.dumps(o) + "\n")
    cache_f.flush()
    return code

report = {"date": TODAY}
deep = json.load(open(OUT / "deep_census.json"))

# ---- suspect ORCIDs vs the ORCID registry ----
def norm_orcid(v):
    return re.sub(r"^https?://(www\.)?orcid\.org/", "", v.strip())

suspects = [norm_orcid(x["value"]) for x in deep["orcid"]["examples"].get("checksum-failure", [])]
sus_result = {}
for s in suspects:
    code = curl_status(f"https://pub.orcid.org/v3.0/{s}", "orcid-suspect",
                      ["Accept: application/json"])
    sus_result[s] = code
report["orcid_checksum_failures_registry_status"] = sus_result

# control: 20 checksum-valid ORCIDs sampled from the export
import csv
csv.field_size_limit(10_000_000)
valid = []
with open(RAW / "bhl_creatoridentifier.txt", encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
        if r["IdentifierName"].strip() == "ORCID":
            s = norm_orcid(r["IdentifierValue"])
            if re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dXx]", s):
                valid.append(s)
control = random.sample(valid, 20)
ok = sum(1 for s in control
         if curl_status(f"https://pub.orcid.org/v3.0/{s}", "orcid-control",
                        ["Accept: application/json"]) == 200)
report["orcid_control"] = f"{ok}/20 registered"

# ---- NHM resource URL liveness, full census ----
urls = json.load(open(OUT / "nhm_resource_urls.json"))
statuses = collections.Counter()
dead = []
for u in urls:
    code = curl_status(u["url"], "nhm-resource")
    statuses[code] += 1
    if code >= 400 or code == 0:
        dead.append({**u, "status": code})
report["nhm_resources"] = {
    "total": len(urls),
    "status_histogram": {str(k): v for k, v in sorted(statuses.items())},
    "dead": len(dead),
}
with open(OUT / "nhm_dead_resources.json", "w") as f:
    json.dump(dead, f, indent=2)

with open(OUT / "resolution_deep.json", "w") as f:
    json.dump(report, f, indent=2)
print(json.dumps(report, indent=2))
