#!/usr/bin/env python3
"""Second mining pass over the already-harvested exports.

Adds: ORCID checksum conformance (ISO 7064 MOD 11-2), VIAF and Wikidata
syntax conformance, ZooBank mirror hierarchy integrity (orphans, self-
parents, duplicate ids), BHL title-year sanity, and coverage overlaps.
Writes reports/deep_census.json. Resolution sampling lives in 07.
"""
import csv, json, re, sys, collections, pathlib

RAW = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("raw")
OUT = pathlib.Path(__file__).resolve().parent.parent / "reports"
OUT.mkdir(exist_ok=True)
csv.field_size_limit(10_000_000)

def rows(name):
    with open(RAW / name, encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE)

report = {}

# ---------- ORCID: ISO 7064 MOD 11-2 check digit ----------
def orcid_reason(v):
    s = v.strip()
    s = re.sub(r"^https?://(www\.)?orcid\.org/", "", s)
    if not re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dXx]", s):
        return "malformed-syntax", s
    digits = s.replace("-", "")
    total = 0
    for c in digits[:-1]:
        total = (total + int(c)) * 2
    check = (12 - total % 11) % 11
    expected = "X" if check == 10 else str(check)
    return (None if digits[-1].upper() == expected else "checksum-failure"), s

orcid = collections.Counter()
orcid_bad = collections.defaultdict(list)
viaf = collections.Counter()
viaf_bad = []
wd_creator = collections.Counter()
wd_bad = collections.defaultdict(list)
for r in rows("bhl_creatoridentifier.txt"):
    sch = r["IdentifierName"].strip()
    v = r["IdentifierValue"].strip()
    if sch == "ORCID":
        reason, norm = orcid_reason(v)
        orcid["total"] += 1
        if v.lower().startswith("http"):
            orcid["url-form"] += 1
        if reason:
            orcid[reason] += 1
            if len(orcid_bad[reason]) < 25:
                orcid_bad[reason].append({"CreatorID": r["CreatorID"], "value": v})
    elif sch == "VIAF":
        viaf["total"] += 1
        if not re.fullmatch(r"\d{1,22}", v):
            viaf["malformed"] += 1
            if len(viaf_bad) < 25:
                viaf_bad.append({"CreatorID": r["CreatorID"], "value": v})
    elif sch == "Wikidata":
        wd_creator["total"] += 1
        if not re.fullmatch(r"Q\d+", v):
            wd_creator["malformed"] += 1
            if len(wd_bad["creator"]) < 25:
                wd_bad["creator"].append({"CreatorID": r["CreatorID"], "value": v})
report["orcid"] = {**dict(orcid), "examples": dict(orcid_bad)}
report["viaf"] = {**dict(viaf), "examples": viaf_bad}

# Wikidata on titles and parts
for fname, idcol, key in [("bhl_titleidentifier.txt", "TitleID", "title"),
                          ("bhl_partidentifier.txt", "PartID", "part")]:
    c = collections.Counter()
    for r in rows(fname):
        if r["IdentifierName"].strip() == "Wikidata":
            c["total"] += 1
            if not re.fullmatch(r"Q\d+", r["IdentifierValue"].strip()):
                c["malformed"] += 1
                if len(wd_bad[key]) < 25:
                    wd_bad[key].append({idcol: r[idcol], "value": r["IdentifierValue"]})
    report[f"wikidata_{key}"] = dict(c)
report["wikidata_creator"] = dict(wd_creator)
report["wikidata_examples"] = dict(wd_bad)

# Duplicate identifier -> multiple creators (same ORCID on two creators)
own = collections.defaultdict(lambda: collections.defaultdict(set))
for r in rows("bhl_creatoridentifier.txt"):
    own[r["IdentifierName"].strip()][r["IdentifierValue"].strip()].add(r["CreatorID"])
dup = {}
for sch in ["ORCID", "VIAF", "Wikidata"]:
    d = {v: sorted(cs) for v, cs in own[sch].items() if len(cs) > 1}
    dup[sch] = {"values_shared_by_multiple_creators": len(d),
                "examples": dict(list(d.items())[:10])}
report["creator_identifier_sharing"] = dup

# ---------- ZooBank mirror hierarchy integrity ----------
zb = list(csv.DictReader(open(RAW / "zoobank" / "NameUsage.tsv"), delimiter="\t"))
ids = collections.Counter(r["col:ID"] for r in zb)
dup_ids = {k: v for k, v in ids.items() if v > 1}
id_set = set(ids)
orphans = 0
self_parent = 0
orphan_examples = []
for r in zb:
    p = r["col:parentID"].strip()
    if p and p not in id_set:
        orphans += 1
        if len(orphan_examples) < 10:
            orphan_examples.append({"id": r["col:ID"], "parentID": p,
                                    "name": r["col:scientificName"]})
    if p and p == r["col:ID"]:
        self_parent += 1
no_authorship = sum(1 for r in zb if not r["col:authorship"].strip())
no_parent = sum(1 for r in zb if not r["col:parentID"].strip())
report["zoobank_mirror"] = {
    "records": len(zb),
    "duplicate_ids": len(dup_ids),
    "duplicate_id_examples": dict(list(dup_ids.items())[:10]),
    "orphan_parent_refs": orphans,
    "orphan_examples": orphan_examples,
    "self_parenting": self_parent,
    "records_without_authorship": no_authorship,
    "roots_or_parentless": no_parent,
}

# ---------- BHL title-year sanity ----------
years = collections.Counter()
year_examples = collections.defaultdict(list)
langs = collections.Counter()
for r in rows("bhl_title.txt"):
    sy, ey = r["StartYear"].strip(), r["EndYear"].strip()
    langs[r["LanguageCode"].strip() or "(blank)"] += 1
    def num(x):
        return int(x) if re.fullmatch(r"-?\d{1,5}", x) else None
    s, e = num(sy) if sy else None, num(ey) if ey else None
    if sy and s is None:
        years["start_not_numeric"] += 1
        if len(year_examples["start_not_numeric"]) < 10:
            year_examples["start_not_numeric"].append({"TitleID": r["TitleID"], "value": sy})
    if s is not None:
        if s > 2026:
            years["start_in_future"] += 1
            if len(year_examples["start_in_future"]) < 10:
                year_examples["start_in_future"].append({"TitleID": r["TitleID"], "value": sy})
        if 0 < s < 1450:
            years["start_before_1450"] += 1
            if len(year_examples["start_before_1450"]) < 10:
                year_examples["start_before_1450"].append({"TitleID": r["TitleID"], "value": sy})
        if s <= 0:
            years["start_zero_or_negative"] += 1
            if len(year_examples["start_zero_or_negative"]) < 10:
                year_examples["start_zero_or_negative"].append({"TitleID": r["TitleID"], "value": sy})
    if s is not None and e is not None and e < s:
        years["end_before_start"] += 1
        if len(year_examples["end_before_start"]) < 10:
            year_examples["end_before_start"].append(
                {"TitleID": r["TitleID"], "start": sy, "end": ey})
report["title_years"] = {**dict(years), "examples": dict(year_examples)}
report["title_language_top"] = langs.most_common(10)
report["title_language_blank"] = langs.get("(blank)", 0)

# ---------- NHM resource URLs harvested for 07 ----------
nhm = [json.loads(l) for l in open(RAW / "nhm_packages.jsonl")]
urls = []
for p in nhm:
    for res in p.get("resources", []):
        u = (res.get("url") or "").strip()
        if u:
            urls.append({"package": p["name"], "resource": res.get("id"), "url": u})
with open(OUT / "nhm_resource_urls.json", "w") as f:
    json.dump(urls, f)
report["nhm_resource_urls_written"] = len(urls)

with open(OUT / "deep_census.json", "w") as f:
    json.dump(report, f, indent=2)

slim = {k: {kk: vv for kk, vv in v.items() if "example" not in kk} if isinstance(v, dict) else v
        for k, v in report.items()}
print(json.dumps(slim, indent=2)[:3500])
