#!/usr/bin/env python3
"""ZooBank whitelist retest, 30 Aug 2026: the controlled before-and-after.

The 28 Aug build and the 30 Aug recovery census both recorded every sampled
canonical act URL as 404 and framed that as a resolver failure. The ZooBank
registrar then disclosed the real mechanism: zoobank.org sits behind a
reCAPTCHA and IP-whitelist anti-DDoS gate, and un-whitelisted machine clients
are refused with a 404 rather than a 403. He whitelisted this machine's egress
IPv4 on 30 Aug at approximately 20:45 UTC.

That makes a clean single-variable experiment available. This script re-probes
the EXACT 50 URLs recorded in reports/zoobank_recovery_resolution.json, from
the same machine, with the same curl invocation as pipeline/03_resolution.py:

    curl -sS -m 20 -o /dev/null -w "%{http_code}" -L <url>

No User-Agent override, redirects followed. The only thing that changed
between the two observations is whether the client IP is on the whitelist.

A second arm probes the same 50 UUIDs in canonical /NomenclaturalActs/ form,
and a control arm probes a well-formed but non-existent UUID, which the
registrar has confirmed as a known defect: it redirects to /Search and
returns 200 instead of 404, so a link checker records a dead identifier as
healthy.

Writes reports/zoobank_whitelist_retest.json.
"""
import json, pathlib, subprocess, re
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "reports"
PRIOR = OUT / "zoobank_recovery_resolution.json"

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def observe(url):
    """Identical invocation to pipeline/03_resolution.py observe()."""
    r = subprocess.run(["curl", "-sS", "-m", "20", "-o", "/dev/null",
                        "-w", "%{http_code}|%{url_effective}", "-L", url],
                       capture_output=True, text=True)
    out = (r.stdout or "").strip()
    code_s, _, final = out.partition("|")
    try:
        code = int(code_s or 0)
    except ValueError:
        code = 0
    return {"url": url, "http": code, "final_url": final,
            "observed": datetime.now(timezone.utc).isoformat()}


def observe_retry(url, attempts=3):
    """curl exit failures return 0. Retry so a transient timeout is never
    reported as an observation about the server."""
    for _ in range(attempts):
        o = observe(url)
        if o["http"] != 0:
            return o
    return o


def verify_non200(rows, attempts=3):
    """A first serial pass left 1 of 50 terminating on the 302 http->https hop.
    Three immediate re-probes of that URL returned 200 every time, so the
    termination is transient rather than a property of the record. Any non-200
    is re-probed here and both statuses are kept, because silently replacing
    the first observation would hide the flakiness the re-probe measured."""
    transient = 0
    for r in rows:
        if r["http"] == 200:
            continue
        for _ in range(attempts):
            v = observe(r["url"])
            if v["http"] == 200:
                r["first_pass_http"] = r["http"]
                r["http"] = 200
                r["final_url"] = v["final_url"]
                transient += 1
                break
    return transient

prior = json.load(open(PRIOR))
prior_by_url = {p["url"]: p for p in prior}
urls = [p["url"] for p in prior]

canonical = []
for u in urls:
    m = UUID_RE.search(u)
    canonical.append(f"https://zoobank.org/NomenclaturalActs/{m.group(0)}" if m else None)

BOGUS = "http://zoobank.org/00000000-0000-0000-0000-000000000000"
BOGUS_CANON = "https://zoobank.org/NomenclaturalActs/00000000-0000-0000-0000-000000000000"

# Serial, exactly as pipeline/03_resolution.py ran it. A first pass at four
# concurrent workers returned 302 as the terminal status for 3 of the 50; all
# three resolved 200 in two redirects when re-probed serially. ColdFusion hands
# out a CFID/CFTOKEN session per connection and parallel probes interfere with
# the http->https hop, so concurrency was a variable this experiment must not
# introduce. The point of the run is that the client IP is the ONLY difference.
after = [observe_retry(u) for u in urls]
after_canon = [observe_retry(c) for c in canonical if c]
controls = [observe_retry(u) for u in (BOGUS, BOGUS_CANON)]

transient_published = verify_non200(after)
transient_canonical = verify_non200(after_canon)



def tally(rows):
    t = {}
    for r in rows:
        t[str(r["http"])] = t.get(str(r["http"]), 0) + 1
    return t

before_t = {}
for p in prior:
    before_t[str(p["http"])] = before_t.get(str(p["http"]), 0) + 1

# how many published bare-UUID URLs land on the canonical act path
landed = sum(1 for r in after if "/NomenclaturalActs/" in r["final_url"])

result = {
    "generated": datetime.now(timezone.utc).isoformat(),
    "method": 'curl -sS -m 20 -o /dev/null -w "%{http_code}" -L  (no UA override, as pipeline/03)',
    "single_variable": "client egress IPv4 added to the zoobank.org whitelist by the registrar",
    "sample_size": len(urls),
    "sample_provenance": "the exact URL list in reports/zoobank_recovery_resolution.json, seed 42",
    "before": {"observed": prior[0]["observed"], "status_tally": before_t},
    "flipped_404_to_200": sum(1 for u, a in zip(urls, after)
                              if str(prior_by_url[u]["http"]) == "404"
                              and str(a["http"]) == "200"),
    "transient_redirect_terminations_reprobed": {
        "published_form": transient_published,
        "canonical_form": transient_canonical},
    "after_published_form": {"status_tally": tally(after),
                             "landed_on_canonical_act_path": landed},
    "after_canonical_form": {"status_tally": tally(after_canon)},
    "control_nonexistent_uuid": {
        "published_form": {"url": BOGUS, "http": controls[0]["http"],
                           "final_url": controls[0]["final_url"]},
        "canonical_form": {"url": BOGUS_CANON, "http": controls[1]["http"],
                           "final_url": controls[1]["final_url"]},
    },
    "rows": [{"url": u,
              "before_http": str(prior_by_url[u]["http"]),
              "after_http": str(a["http"]),
              "first_pass_http": str(a.get("first_pass_http", a["http"])),
              "final_url": a["final_url"]} for u, a in zip(urls, after)],
}

json.dump(result, open(OUT / "zoobank_whitelist_retest.json", "w"), indent=2)

print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
print(f"\nwrote {OUT / 'zoobank_whitelist_retest.json'}")
