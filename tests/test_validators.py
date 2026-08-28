"""Offline regression tests for the scheme validators.

Includes the known-answer cases the census depends on. Run: python3 -m pytest tests/ -q
"""
import importlib.util, pathlib, sys

spec = importlib.util.spec_from_file_location(
    "build_graph", pathlib.Path(__file__).resolve().parent.parent / "pipeline" / "04_build_graph.py")


def load_validators():
    # import only the pure functions without running the pipeline
    pipeline_file = pathlib.Path(__file__).resolve().parent.parent / "pipeline" / "04_build_graph.py"
    src = pipeline_file.read_text()
    old_argv = sys.argv
    sys.argv = ["04_build_graph.py"]
    try:
        ns = {"__file__": str(pipeline_file)}
        header = src.split("stats = collections.Counter()")[0]
        exec(compile(header, "validators", "exec"), ns)
    finally:
        sys.argv = old_argv
    return ns


V = load_validators()


def test_issn_valid():
    assert V["issn_reason"]("0028-0836") is None          # Nature
    assert V["issn_reason"]("2049-3630") is None          # ISSN with X handled elsewhere


def test_issn_checksum_failure():
    assert V["issn_reason"]("0438-6572") == "checksum-failure"


def test_isbn10_known_answer_qualifier():
    # TitleID 4657 in the BHL export: bare ISBN passes, stored value is contaminated
    assert V["isbn_reason"]("0804700036") is None
    assert V["isbn_reason"]("0804700036 (v. 1)") == "qualifier-contamination"


def test_isbn13_checksum():
    assert V["isbn_reason"]("9780306406157") is None
    assert V["isbn_reason"]("9780306406158") == "checksum-failure"


def test_doi_rules():
    assert V["doi_reason"]("10.5962/bhl.title.41") is None
    assert V["doi_reason"]("https://doi.org/10.3897/dez.69.83335") == "resolver-prefix"
    assert V["doi_reason"]("Array") == "not-a-doi"
    assert V["doi_reason"]("v.1:no.1 (1895)") == "not-a-doi"


def test_oclc():
    assert V["oclc_reason"]("973296137") is None
    assert V["oclc_reason"]("16723735890419") == "malformed-syntax"


def test_escape_roundtrip():
    assert V["esc"]('a"b\\c\nd') == 'a\\"b\\\\c\\nd'
