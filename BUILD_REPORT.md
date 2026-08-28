# BDRO build report

Built 28 August 2026 in one session. This report records exactly what was fetched, what was computed, what could not be obtained, and where the sampling caveats are. Every headline number is computed two ways (set-based in Python and via SPARQL over the emitted graph) by `pipeline/05_verify.py`, which exits non-zero on any disagreement.

## Sources, verified hands-on before any pipeline code

| Source | Access | Licence | Result |
|---|---|---|---|
| BHL bulk TSV export (`biodiversitylibrary.org/data/TSV/`) | open, keyless | BHL data exports are published for reuse; the corpus itself carries per-item rights | HARVESTED in full, export stamped 1 Aug 2026 |
| BHL `doi.txt` | open | as above | 306,173 rows |
| NHM Data Portal CKAN API (`data.nhm.ac.uk`) | open, keyless; blocks the default Python urllib user agent (HTTP 403) but accepts curl's | per-dataset licences, many CC0/CC BY | all 294 public datasets harvested |
| ZooBank (`zoobank.org`) | BROKEN. Every route except the homepage returned HTTP 404 on 28 Aug 2026 at two observation times (13:48 and 14:09 UTC): `/About`, `/Api`, `/Search`, the documented JSON API, `urn:lsid:` URNs, and all 50 sampled canonical act URLs | n/a | register content obtained via mirrors instead |
| ZooBank via ChecklistBank (dataset 2037, ColDP export) | open, keyless | CC0 | 399,326 records, snapshot dated 2023-01-09 |
| ZooBank via GBIF (dataset c8227bb4) | open, keyless | (GBIF terms) | 478,746 records, pubDate 2025-03-28; GBIF's crawl of 23 Aug 2026 ended in ABORT |
| Bishop Museum IPT (`ipt.bishopmuseum.org:8080`), ZooBank's declared publication endpoint | HTTP 404 | n/a | BLOCKED; this is why the mirrors are stale |
| WoRMS REST API | open, keyless | CC BY | control register, 10/10 sampled AphiaIDs resolve |
| IPNI API | open, keyless | CC BY | control register, 5/5 sampled name IDs resolve |
| doi.org handle API | open, keyless | n/a | registry-of-record check for every sampled DOI |

Not fetched: the 2.4 GB `data.zip` (the individual TSVs cover every table used); BHL OCR text (out of scope); ZooBank's own API (broken, see above). The Wayback CDX API timed out twice when we tried to date the start of the ZooBank outage; the outage duration is therefore UNKNOWN and we claim only the two dated observations. No announcement of the outage was found on iczn.org or in web search as of 28 Aug 2026; we looked.

## Findings

### F1. ZooBank, the Official Register of Zoological Nomenclature, has no working machine interface
- 50 of 50 sampled register UUIDs return HTTP 404 at `https://zoobank.org/{uuid}`, the exact URL form GBIF's copy of the register publishes in `references`.
- The register's own homepage links `/About` and `/Api` return 404. The LSID URN form also returns 404.
- The register's declared IPT publication endpoint returns 404, GBIF's last crawl attempt (23 Aug 2026) ended in ABORT, and the freshest public mirrors are 518 days (GBIF, 2025-03-28) and 1,327 days (ChecklistBank, 2023-01-09) stale.
- The two mirrors disagree on record count: 478,746 (GBIF) vs 399,326 (ChecklistBank). Both figures are snapshot artifacts, not register truth; we cite them only as mirror counts.
- The ChecklistBank snapshot contains 50 identifiers that do not match the register's own UUID pattern (values such as `x5C`, `~4Q`).
- Controls: WoRMS resolved 10/10 and IPNI 5/5 on the same day, so this is register-specific, not infrastructure-wide.
- CAVEAT stated plainly: our observations are two timestamps on one day. If the outage is transient the resolution finding shrinks to "the register was unreachable on the day of census and its mirrors are years stale"; the staleness and mirror-disagreement findings survive any recovery.

### F2. 86.0% of BHL's digitised items carry no machine-actionable licence
- 283,090 of 329,129 distinct items (86.01%) have either a blank `LicenseType` (283,006) or a licence IRI containing characters outside printable ASCII (84, all carrying U+FFA0 HALFWIDTH HANGUL FILLER appended to a CC IRI).
- 108,509 items (33.0%) carry the copyright status string "Not provided. Contact Holding Institution to verify copyright status."
- `CopyrightStatus` is uncontrolled free text: the same status appears in dozens of lexical variants (`NOT_IN_COPYRIGHT`, `NOT IN COPYRIGHT`, `Not in copyright...`, and several trailing-whitespace and double-space variants of the same sentence).
- Where a licence IRI is present it appears in http/https and trailing-slash variants of the same licence.
- 4 licence values are not IRIs at all.

### F3. Identifier hygiene in the BHL export
- 13 DOI values are not DOIs: ten titles carry the literal string `Array`, one carries `v.1:no.1 (1895)`, and two carry the `https://doi.org/` resolver prefix (a display string, not an identifier, per the DOI display guidelines).
- 171 DOI values are asserted for more than one entity (351 assertions affected); 6 of them span entity types (the same DOI on a Title and a Part), so the identifier cannot resolve to its referent.
- 912 of 5,607 title-level ISBNs (16.3%) fail ISBN validation: 896 are qualifier contamination (`0804700036 (v. 1)`, `(Br.)` and similar MARC habits stored in the value field), 8 fail their checksum, 8 are otherwise malformed.
- 6 of 2,814 ISSNs fail (4 checksum failures, 2 malformed).
- 2,652 of 170,766 OCLC numbers are malformed; the dominant pattern is a 13-14 digit value consistent with an OCLC number concatenated with a 6-digit date, which we describe but do not assert as the cause.
- Fairness, stated prominently: BHL's own DOI minting is clean. 40 of 40 sampled `10.5962` DOIs are registered at doi.org, and 24 of 25 sampled externally-minted DOIs. The defects above live in the metadata export layer, not in BHL's DOI registration practice.

### F4. NHM Data Portal: strong identifiers, weak product metadata
- Strength, stated first: all 294 datasets carry a DOI (`10.5519/...`) and 25 of 25 sampled resolve at doi.org. All 294 have descriptions. This is materially better than the eleven Nordic national catalogues we measured in the HDCO study, where `dct:identifier` coverage was 62.65%.
- 8 of 294 datasets (2.7%) satisfy all five of: licence URL, DOI, a contact email, a description of at least 100 characters, and a declared update frequency.
- 108 datasets (36.7%) have no licence URL; 51 have no usable licence at all (46 `notspecified` + 5 empty).
- The licence vocabulary is uncontrolled: `cc-by`, `CC-BY-4.0`, `CC BY-NC 4.0`, `cc-nc`, `CC-BY-NC-4.0` coexist as distinct identifiers for overlapping licences (18 distinct values).
- `author_email` is empty on all 294 datasets; `maintainer_email` is present on 35.
- `update_frequency` is absent on 207 (70.4%); `spatial` is present on exactly 1 dataset.
- Resource layer: of 1,293 resources, 243 lack a format, 634 lack a size, 460 lack a description.

### F5. The BHL item table's primary key is not unique, found by the verification gate itself
- The item export holds 338,342 rows describing 329,129 distinct ItemIDs: 9,118 ItemIDs recur (9,213 surplus rows), and every recurring ItemID appears with more than one TitleID. ItemID 7266, for example, appears under TitleID 296 and TitleID 1599 with the same barcode.
- The duplicate rows agree on their rights fields in every case (zero disagreements), so per-item rights statistics are computed over distinct items.
- Discovery is worth recording: the first build counted rows set-based while the graph merged nodes, the dual computation refused to reconcile (288,846 vs 283,090), and chasing the 5,756 gap exposed the key collision. This is the fifth vertical in a row in which the two-ways rule has caught a real defect, in this case in the source, not in our code.

## Second mining pass (same day, `pipeline/06_census_deep.py` and `07_resolution_deep.py`)

### F6. Person identifiers: the creator register duplicates people and inherits impersonated ORCIDs
- Of 27,282 ORCID values, 3 fail the ORCID ISO 7064 MOD 11-2 checksum and 6 are malformed, including values typed with EN DASHES instead of hyphens (`0000–0002–0941–7203`) and one double-prefixed value (`https://orcid.org/http://orcid.org/...`). The en-dash class is the third invisible-to-the-eye character defect in this vertical.
- **782 ORCID values are shared by more than one creator record**, corroborated by 736 shared VIAF values and 807 shared Wikidata Q-ids: the creator authority file holds hundreds of duplicate person records (`Rivas, Luis Rolando` / `Rivas, Luis Rene`). At least one shared ORCID joins two clearly different people (`Lim, Burton K.` and `Eger, Judith L.`).
- **11 creators whose name string embeds a death year before 2010 carry an ORCID, including Shakespeare (d. 1616), Napoleon I (d. 1821) and Ramon y Cajal (d. 1934).** Checked against the registry: these resolve to live ORCID accounts registered under those names, so the defect is joint. The ORCID registry contains self-registered accounts in the names of historical figures, and the BHL pipeline ingested them as author identities. List in `reports/orcid_deceased.json`.
- 61 of 49,584 creator Wikidata values are malformed, several carrying U+200F RIGHT-TO-LEFT MARK appended and one a stray opening parenthesis. 12 of 46,601 VIAF values are malformed.
- All 27,282 ORCIDs are stored in URL form, which is ORCID's own display guideline and is NOT counted as a defect.

### F7. BHL title chronology
- 611 titles have an EndYear earlier than their StartYear (TitleID 948 spans 1894 to 1815). 3 titles start before 1450. 9,763 titles carry no language code.

### F8. Null result, reported as one: the ZooBank mirror's internal hierarchy is clean
- Across all 399,326 records in the ChecklistBank snapshot: zero duplicate identifiers, zero orphan parent references, zero self-parenting. 13 records lack authorship. ZooBank's problem is availability and staleness, not content integrity. Fairness demands this stated as prominently as F1.

### F9. NHM resource liveness
- See `reports/resolution_deep.json` (full census of every resource URL on the portal, observation-cached).

## Verification achieved
- `pipeline/05_verify.py`: all 11 dual computations agree (see `reports/verification.json`).
- SHACL: layer 1 clean over the defects partition plus a seeded 5,000-node conformant control sample. Layer 2 reports 3,669 violations, reconciling exactly as 3,583 non-conformant assertions (13 DOI + 912 ISBN + 6 ISSN + 2,652 OCLC) + 2 resolver-prefix + 84 invisible-character licences. Layer 3 reports 408, reconciling exactly as 351 multiply-assigned assertions + 55 dead-URL observations (50 ZooBank + 4 unregistered bad-syntax DOIs + 1 dead external DOI) + 2 stale snapshots.
- open-ontologies v1.2.0 (our own engine, third verification path): `validate` ok on all six TTL artifacts; `lint` clean except documented info-level missing-domain notes on deliberately shared properties.
- Known-answer case: TitleID 4657 (`0804700036 (v. 1)`) is hand-verified qualifier contamination whose bare ISBN passes its checksum; the ISBN validator must classify it as qualifier-contamination, and a regression test pins this.

## Sampling and scope caveats
- Resolution findings rest on seeded samples (seed 42): 50 ZooBank UUIDs, 40+25 BHL DOIs, 25 NHM DOIs, 10 WoRMS, 5 IPNI. All observations are cached with dates in `reports/resolution_observations.jsonl` and replayable.
- The SHACL gate runs over the defects partition plus a control sample, not the full 3.9M-triple graph; the full-graph numbers are covered by the dual computation instead. Stated here so nobody reads the SHACL report as a full-graph census.
- Identifier conformance is measured only for schemes whose rules are declared in the SKOS registry (DOI, ISSN, ISBN, OCLC). MARC001, NAL, Wikidata and the rest are counted but not judged.
- The ZooBank content census uses the ChecklistBank snapshot (CC0); its 2023 staleness means ZooBank-side counts describe the mirror, not today's register.
