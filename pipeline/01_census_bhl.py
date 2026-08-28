#!/usr/bin/env python3
"""Census of identifier and rights metadata in the BHL bulk export.

Reads the BHL TSV export tables and computes, per identifier scheme,
conformance against the scheme's own published rules (ISSN mod-11,
ISBN-10/13 checksums, DOI syntax), duplicate assignments, and the
rights-metadata completeness of items. Everything is written to
reports/bhl_census.json; nothing is printed that is not also saved.
"""
import csv, json, re, sys, collections, pathlib

RAW = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("raw")
OUT = pathlib.Path(__file__).resolve().parent.parent / "reports"
OUT.mkdir(exist_ok=True)
csv.field_size_limit(10_000_000)

def rows(name):
    with open(RAW / name, encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE)

# ---------- scheme validators (each register's own published rule) ----------
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")

def issn_ok(v):
    s = v.replace("-", "").replace(" ", "").upper()
    if not re.fullmatch(r"\d{7}[\dX]", s):
        return False
    total = sum(int(c) * w for c, w in zip(s[:7], range(8, 1, -1)))
    check = (11 - total % 11) % 11
    return s[7] == ("X" if check == 10 else str(check))

def isbn_ok(v):
    s = re.sub(r"[- ]", "", v).upper()
    if re.fullmatch(r"\d{9}[\dX]", s):
        total = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(s))
        return total % 11 == 0
    if re.fullmatch(r"\d{13}", s):
        total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(s))
        return total % 10 == 0
    return False

def oclc_ok(v):
    return re.fullmatch(r"(ocm|ocn|on)?\d{1,12}", v.strip().lower()) is not None

report = {}

# ---------- doi.txt ----------
doi_rows = list(rows("bhl_doi.txt"))
by_entity = collections.Counter(r["EntityType"] for r in doi_rows)
bad_syntax = [r for r in doi_rows if not DOI_RE.match(r["DOI"].strip())]
doi_map = collections.defaultdict(list)
for r in doi_rows:
    doi_map[r["DOI"].strip().lower()].append((r["EntityType"], r["EntityID"]))
dupes = {d: v for d, v in doi_map.items() if len(v) > 1}
dupes_cross_entity = {d: v for d, v in dupes.items() if len({e for e, _ in v}) > 1}
same_entity_multi = collections.defaultdict(list)
for r in doi_rows:
    same_entity_multi[(r["EntityType"], r["EntityID"])].append(r["DOI"].strip().lower())
multi_doi_entities = {f"{k[0]}:{k[1]}": v for k, v in same_entity_multi.items() if len(set(v)) > 1}
prefixes = collections.Counter(r["DOI"].split("/")[0] for r in doi_rows)
report["doi"] = {
    "total_rows": len(doi_rows),
    "by_entity_type": dict(by_entity),
    "bad_syntax_count": len(bad_syntax),
    "bad_syntax_examples": [dict(r) for r in bad_syntax[:20]],
    "distinct_dois": len(doi_map),
    "dois_assigned_to_multiple_entities": len(dupes),
    "dois_assigned_across_entity_types": len(dupes_cross_entity),
    "cross_entity_examples": dict(list(dupes_cross_entity.items())[:10]),
    "entities_with_multiple_dois": len(multi_doi_entities),
    "entities_with_multiple_dois_examples": dict(list(multi_doi_entities.items())[:10]),
    "top_prefixes": prefixes.most_common(15),
    "bhl_prefix_10_5962": prefixes.get("10.5962", 0),
}

# ---------- title/part identifiers ----------
def ident_census(fname, idcol):
    schemes = collections.Counter()
    bad = collections.defaultdict(list)
    conform = collections.Counter()
    checked = collections.Counter()
    for r in rows(fname):
        scheme = r["IdentifierName"].strip()
        val = r["IdentifierValue"].strip()
        schemes[scheme] += 1
        ok = None
        if scheme == "ISSN":
            ok = issn_ok(val)
        elif scheme == "ISBN":
            ok = isbn_ok(val)
        elif scheme == "DOI":
            ok = bool(DOI_RE.match(val))
        elif scheme == "OCLC":
            ok = oclc_ok(val)
        if ok is not None:
            checked[scheme] += 1
            if ok:
                conform[scheme] += 1
            elif len(bad[scheme]) < 25:
                bad[scheme].append({idcol: r[idcol], "value": val})
    return {
        "schemes": schemes.most_common(),
        "checked": dict(checked),
        "conformant": dict(conform),
        "nonconformant_examples": {k: v for k, v in bad.items()},
    }

report["title_identifiers"] = ident_census("bhl_titleidentifier.txt", "TitleID")
report["part_identifiers"] = ident_census("bhl_partidentifier.txt", "PartID")
report["creator_identifiers"] = {
    "schemes": collections.Counter(
        r["IdentifierName"].strip() for r in rows("bhl_creatoridentifier.txt")
    ).most_common()
}

# ---------- item rights metadata ----------
items = 0
rights = collections.Counter()
lic_types = collections.Counter()
holders = 0
statements = collections.Counter()
inst = collections.Counter()
no_rights_at_all = 0
for r in rows("bhl_item.txt"):
    items += 1
    cs = (r.get("CopyrightStatus") or "").strip()
    rs = (r.get("RightsStatement") or "").strip()
    lt = (r.get("LicenseType") or "").strip()
    rh = (r.get("RightsHolder") or "").strip()
    rights[cs or "(blank)"] += 1
    lic_types[lt or "(blank)"] += 1
    statements[rs[:80] or "(blank)"] += 1
    if rh:
        holders += 1
    if not cs and not rs and not lt:
        no_rights_at_all += 1
    inst[(r.get("InstitutionName") or "").strip()] += 1
report["item_rights"] = {
    "total_items": items,
    "copyright_status_values": rights.most_common(30),
    "license_type_values": lic_types.most_common(30),
    "rights_statement_top": statements.most_common(15),
    "items_with_rights_holder": holders,
    "items_with_no_rights_fields_at_all": no_rights_at_all,
    "top_institutions": inst.most_common(15),
}

# ---------- titles: DOI coverage ----------
title_ids = set()
for r in rows("bhl_title.txt"):
    title_ids.add(r["TitleID"])
titles_with_doi = {e for (et, e) in [(r["EntityType"], r["EntityID"]) for r in doi_rows] if et == "Title"}
part_count = sum(1 for _ in rows("bhl_part.txt"))
parts_with_doi = len({r["EntityID"] for r in doi_rows if r["EntityType"] == "Part"})
report["coverage"] = {
    "titles_total": len(title_ids),
    "titles_with_doi": len(titles_with_doi & title_ids),
    "doi_title_rows_not_in_title_table": len(titles_with_doi - title_ids),
    "parts_total": part_count,
    "parts_with_doi": parts_with_doi,
}

with open(OUT / "bhl_census.json", "w") as f:
    json.dump(report, f, indent=2, default=str)
print(json.dumps({k: {kk: vv for kk, vv in v.items() if not isinstance(vv, (list, dict)) or kk in ("by_entity_type", "checked", "conformant")} if isinstance(v, dict) else v for k, v in report.items()}, indent=2, default=str)[:4000])
