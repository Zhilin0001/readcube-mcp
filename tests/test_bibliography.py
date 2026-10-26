import csv
import io
from pathlib import Path

import bibtexparser
import pytest
import rispy

from readcube_client.authors import author_matches, normalize_author
from readcube_client.bibliography import author_statistics, export_references, normalize_names
from readcube_client.workflow import query_library


@pytest.fixture
def library(make_client, monkeypatch):
    client = make_client(lambda r: pytest.fail("Unexpected network"), verified=("list_items",))
    rows = [
        {
            "id": "a",
            "article": {
                "title": "Cognition, A & B {study}",
                "authors": ["José García", "Francisco Gonzalez-Lima"],
                "year": 2024,
                "journal": "Neuro Science",
                "pages": "10–20",
                "abstract": "First\nsecond",
            },
            "ext_ids": {"doi": "https://doi.org/10.1000/ABC"},
        },
        {
            "id": "b",
            "article": {"title": "Duplicate", "authors": ["García, José", "F. Gonzalez-Lima"]},
            "ext_ids": {"doi": "DOI:10.1000/abc"},
        },
        {"id": "c", "article": {"title": "=SUM(1,2)", "authors": ["José García"]}},
        {"id": "d", "article": {"title": "No DOI two", "authors": ["Li Wang"]}},
    ]
    calls = []
    monkeypatch.setattr(client, "list_items", lambda cid: calls.append(cid) or rows)
    return client, rows, calls


def test_author_matching_uses_shared_cache_without_identity_merging(library):
    client, _, calls = library
    result = query_library(client, "lib", query="Garcia, Jose", field="author")
    assert result["matched"] == 3
    assert query_library(client, "lib", query="F Gonzalez Lima", field="author")["matched"] == 2
    assert calls == ["lib"]
    stats = author_statistics(client, "lib", author="Jose Garcia")
    assert stats["matched_records"] == 3 and stats["unique_papers"] == 2
    assert stats["duplicate_doi_groups"] == {"10.1000/abc": ["a", "b"]}
    assert len(stats["authors"]) == 1 and stats["authors"][0]["records"] == 3
    different = author_statistics(client, "lib", author="Gonzalez Lima")
    assert len(different["authors"]) == 2  # Do not merge F. into Francisco.
    assert calls == ["lib"]


def test_normalization_preserves_names_and_nonlatin_text():
    name = normalize_author("González-Lima, Francisco")
    assert name["display"] == "Francisco González-Lima"
    assert name["canonical"] == "González-Lima, Francisco"
    assert normalize_author("张三")["display"] == "张三"
    assert not author_matches(normalize_author("Lin Wang"), "Li")
    assert not normalize_names(["F. Smith"])["remote_changes"]


@pytest.mark.parametrize("format", ["csv", "ris", "bibtex"])
def test_exports_roundtrip_with_independent_parsers_and_doi_dedup(library, format):
    client, _, calls = library
    result = export_references(client, "lib", format=format)
    assert result["selected_records"] == 4 and result["exported_records"] == 3
    text = Path(result["artifact"]["local_path"]).read_text(encoding="utf-8-sig")
    if format == "csv":
        parsed = list(csv.DictReader(io.StringIO(text)))
        assert parsed[1]["title"].startswith("'=")
        assert parsed[0]["authors"].startswith("García, José;")
    elif format == "ris":
        parsed = rispy.loads(text)
        assert parsed[0]["authors"][0] == "García, José"
        assert parsed[0]["doi"] == "10.1000/abc"
        assert parsed[0]["end_page"] == "20"
    else:
        parsed = bibtexparser.loads(text).entries
        assert parsed[0]["doi"] == "10.1000/abc"
        assert "García, José" in parsed[0]["author"]
    assert len(parsed) == 3
    assert result["artifact"]["size"] > 0 and calls == ["lib"]


def test_export_subset_and_no_doi_records_remain_distinct(library):
    client, _, _ = library
    result = export_references(client, "lib", item_ids=["c", "d"])
    assert result["exported_records"] == 2
    assert export_references(client, "lib", deduplicate_doi=False)["exported_records"] == 4
    with pytest.raises(ValueError):
        export_references(client, "lib", item_ids=["missing"])
