# Biodiversity Register Ontology (BDRO)

An open OWL 2 ontology and measured census of the identifier and rights layer of biodiversity's registers: the Biodiversity Heritage Library's bulk export, the NHM Data Portal, and ZooBank with its mirrors, with WoRMS and IPNI as controls.

The design position is the one this ontology family always takes: status and identity are never properties of a thing. They are dated claims by a named register. BDRO reifies `IdentifierAssertion` (which register published which identifier for which resource, with per-scheme conformance), `RightsAssertion` (verbatim rights strings and licence IRIs, unnormalised), `ResolutionObservation` (what happened when the canonical URL was dereferenced, dated), and `RegisterSnapshot` (how stale each mirror of a register is).

## Headline findings (28 August 2026, all reproducible)

1. **ZooBank, the Official Register of Zoological Nomenclature, had no working machine interface on the day of census.** 50 of 50 sampled canonical act URLs returned HTTP 404, as did the register's own `/Api` and `/About` pages and its LSID URN form. Its declared IPT publication endpoint is dead, GBIF's latest crawl aborted, and the freshest public mirrors are 518 and 1,327 days stale and disagree with each other by 79,420 records. Controls resolved cleanly the same day (WoRMS 10/10, IPNI 5/5).
2. **86.0% of BHL's 329,129 distinct digitised items carry no machine-actionable licence**, and 33.0% carry the status "Not provided. Contact Holding Institution to verify copyright status." 84 items append an invisible Unicode character (U+FFA0) to their Creative Commons IRI.
3. **Identifier hygiene in the world's largest biodiversity library**: ten titles whose registered DOI is the literal string `Array`; 171 DOIs asserted for more than one entity; 912 of 5,607 ISBNs failing validation (mostly MARC qualifier contamination); 2,652 malformed OCLC numbers.
4. **The NHM Data Portal mints a resolving DOI for every one of its 294 datasets, which is best-in-class** among the catalogues we have measured. On product metadata it is thinner: 8 of 294 datasets satisfy licence + DOI + contact + description + update-frequency together, and the licence vocabulary is uncontrolled.
5. **The BHL item table's primary key is not unique**: 9,118 ItemIDs recur across 9,213 surplus rows, each recurrence carrying a different TitleID. Our own verification gate caught this when set-based and SPARQL counts refused to reconcile.

Full detail, caveats, and everything that could not be obtained: [BUILD_REPORT.md](BUILD_REPORT.md).

## What is in the repository

- `ontology/biodiversity-register-ontology.ttl` - OWL 2 core (reified assertions, registers, snapshots).
- `skos/identifier-schemes.ttl` - each identifier scheme (DOI, ISSN, ISBN, OCLC, ZooBank UUID, AphiaID, IPNI ID, LSID and others) declares its own syntax pattern, checksum algorithm, and resolution template as data. The pipeline validates identifiers against their declared scheme instead of hard-coding rules.
- `shacl/` - three layers: structural, scheme conformance, cross-source. One shape per defect class, so the validation report enumerates the findings.
- `pipeline/` - five scripts: BHL census, NHM census, resolution census (seeded, cached, resumable), graph emitter (direct Turtle text), and the verification gate that computes every headline twice and exits non-zero on disagreement.
- `queries/` - SPARQL queries that re-derive each finding from the graph.
- `reports/` - the computed censuses, cached resolution observations, and the verification record.
- `graph/registers.ttl` and `graph/defects.ttl` are committed; the two large instance files (273 MB) are regenerable with `pipeline/04_build_graph.py`.

## Reproducing

```
mkdir raw && cd raw
for f in doi title item part titleidentifier partidentifier creatoridentifier; do
  curl -O https://www.biodiversitylibrary.org/data/TSV/$f.txt; done
curl -L -o zoobank_coldp.zip "https://api.checklistbank.org/dataset/2037/export.zip?format=ColDP"
unzip -d zoobank zoobank_coldp.zip
cd .. && python3 pipeline/02_census_nhm.py   # harvests NHM CKAN itself
python3 pipeline/01_census_bhl.py raw
python3 pipeline/03_resolution.py raw
python3 pipeline/04_build_graph.py raw
python3 pipeline/05_verify.py
```

## Prior art, credited

TDWG's standards family (Darwin Core, TAXREF-style vocabularies, Latimer Core) defines what biodiversity data should say; the NOMEN ontology models nomenclatural acts; OpenBiodiv (Senderov and Penev) built a knowledge graph over biodiversity literature; Plazi extracts treatments at scale; GBIF and ChecklistBank operate the aggregation layer this study reads. None of that work measures whether the registers' published identifiers conform to their own schemes, resolve, or agree across mirrors, which is the only claim BDRO makes for itself.

## Licence

Code MIT. Ontology and documentation CC BY 4.0. Register content quoted here belongs to its publishers under their terms (BHL export; ChecklistBank's ZooBank copy is CC0).

## A worked example

You maintain an extraction pipeline over BHL and want every taxon mention linked to a registered name. Today the zoological register's canonical URLs return 404 and its freshest mirror predates every name registered since March 2025. The honest architecture records your link as an `IdentifierAssertion` against a named `RegisterSnapshot`, so when the register returns your provenance survives. If you want the same measurement run against your own catalogue, or the assurance layer wired into your pipeline, email fabio@thetesseractacademy.com with a pointer to the catalogue; the first pass on one register is free.
