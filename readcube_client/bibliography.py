"""Cached author analysis, DOI grouping, and reference-manager exports."""

import collections
import csv
import hashlib
import io
import re

from .authors import author_matches, author_names, normalize_author
from .client import normalize_doi
from .workflow import cached_library_items


def doi_key(item):
    value = (item.get("ext_ids") or {}).get("doi")
    try:
        return normalize_doi(str(value)) if value else None
    except ValueError:
        return None


def deduplicate(items):
    kept, groups, seen = [], collections.defaultdict(list), set()
    for item in items:
        key = doi_key(item)
        if key:
            groups[key].append(item["id"])
        if key is None or key not in seen:
            kept.append(item)
        if key:
            seen.add(key)
    return kept, {k: v for k, v in groups.items() if len(v) > 1}


def select_items(
    client, collection_id, *, item_ids=None, author=None, match="contains", refresh=False
):
    if item_ids is not None and (not item_ids or len(item_ids) != len(set(item_ids))):
        raise ValueError("Provide unique nonempty item IDs")
    rows, meta = cached_library_items(client, collection_id, refresh=refresh)
    if item_ids is not None:
        by_id = {x["id"]: x for x in rows}
        if any(i not in by_id for i in item_ids):
            raise ValueError("Some item IDs are not in the selected library")
        rows = [by_id[i] for i in item_ids]
    if author:
        rows = [
            x
            for x in rows
            if any(
                author_matches(a, author, match=match) for a in author_names(x.get("article") or {})
            )
        ]
    return rows, meta


def author_statistics(
    client, collection_id, *, author=None, match="contains", limit=50, refresh=False
):
    if not 1 <= limit <= 500:
        raise ValueError("Invalid author limit")
    rows, meta = select_items(client, collection_id, author=author, match=match, refresh=refresh)
    unique, duplicates = deduplicate(rows)
    buckets = {}
    for row in rows:
        seen = set()
        for name in author_names(row.get("article") or {}):
            if author and not author_matches(name, author, match=match):
                continue
            if name["key"] in seen:
                continue
            seen.add(name["key"])
            bucket = buckets.setdefault(
                name["key"], {"name": name["canonical"], "variants": set(), "items": []}
            )
            bucket["variants"].add(str(name["display"]))
            bucket["items"].append(row)
    authors = []
    for bucket in buckets.values():
        own_unique, own_duplicates = deduplicate(bucket["items"])
        authors.append(
            {
                "name": bucket["name"],
                "variants": sorted(bucket["variants"]),
                "records": len(bucket["items"]),
                "unique_papers": len(own_unique),
                "duplicate_doi_groups": len(own_duplicates),
            }
        )
    authors.sort(key=lambda x: (-x["unique_papers"], x["name"]))
    return meta | {
        "matched_records": len(rows),
        "unique_papers": len(unique),
        "records_without_valid_doi": sum(doi_key(x) is None for x in rows),
        "duplicate_doi_groups": duplicates,
        "author_count": len(authors),
        "authors": authors[:limit],
        "truncated": len(authors) > limit,
        "deduplication": "Exact normalized DOI only; records without DOI stay separate.",
        "identity_warning": "Counts group normalized names, not verified person identities.",
    }


def _line(value):
    return " ".join(str(value or "").split())


def _csv_cell(value):
    value = str(value or "")
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def _bib(value):
    escapes = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "%": r"\%",
        "&": r"\&",
        "_": r"\_",
        "#": r"\#",
        "$": r"\$",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(escapes.get(c, c) for c in _line(value))


def export_references(
    client,
    collection_id,
    *,
    format="csv",
    item_ids=None,
    author=None,
    deduplicate_doi=True,
    refresh=False,
):
    if format not in {"csv", "ris", "bibtex"}:
        raise ValueError("Format must be csv, ris or bibtex")
    rows, meta = select_items(
        client, collection_id, item_ids=item_ids, author=author, refresh=refresh
    )
    unique, duplicates = deduplicate(rows)
    selected = unique if deduplicate_doi else rows
    stream = io.StringIO(newline="")
    if format == "csv":
        writer = csv.writer(stream)
        writer.writerow(
            [
                "id",
                "title",
                "authors",
                "year",
                "journal",
                "volume",
                "issue",
                "pages",
                "doi",
                "pmid",
                "url",
                "abstract",
            ]
        )
        for item in selected:
            a, ext = item.get("article") or {}, item.get("ext_ids") or {}
            values = [
                item["id"],
                a.get("title"),
                "; ".join(n["canonical"] for n in author_names(a)),
                a.get("year"),
                a.get("journal"),
                a.get("volume"),
                a.get("issue"),
                a.get("pages"),
                doi_key(item) or ext.get("doi"),
                ext.get("pmid"),
                a.get("url"),
                a.get("abstract"),
            ]
            writer.writerow([_csv_cell(v) for v in values])
    elif format == "ris":
        for item in selected:
            a = item.get("article") or {}
            fields = [("TY", "JOUR"), ("ID", item["id"]), ("TI", a.get("title"))]
            fields += [("AU", n["canonical"]) for n in author_names(a)]
            fields += [
                ("PY", a.get("year")),
                ("JO", a.get("journal")),
                ("VL", a.get("volume")),
                ("IS", a.get("issue")),
                ("DO", doi_key(item)),
                ("UR", a.get("url")),
                ("AB", a.get("abstract")),
            ]
            pages = str(a.get("pages") or "")
            if pages:
                parts = re.split(r"[-–—]", pages, maxsplit=1)
                fields += [("SP", parts[0])]
                if len(parts) > 1:
                    fields += [("EP", parts[1])]
            stream.write(
                "".join(f"{k}  - {_line(v)}\n" for k, v in fields if v is not None and v != "")
            )
            stream.write("ER  - \n\n")
    else:
        for item in selected:
            a = item.get("article") or {}
            key = "rc" + hashlib.sha256(item["id"].encode()).hexdigest()[:16]
            fields = {
                "title": a.get("title"),
                "author": " and ".join(_bib(n["canonical"]) for n in author_names(a)),
                "year": a.get("year"),
                "journal": a.get("journal"),
                "volume": a.get("volume"),
                "number": a.get("issue"),
                "pages": str(a.get("pages") or "").replace("–", "--"),
                "doi": doi_key(item),
                "url": a.get("url"),
                "abstract": a.get("abstract"),
            }
            stream.write("@article{" + key + ",\n")
            for k, v in fields.items():
                if v is not None and v != "":
                    stream.write(f"  {k} = {{{v if k == 'author' else _bib(v)}}},\n")
            stream.write("}\n\n")
    from .artifacts import store_bytes

    extension = {"csv": "csv", "ris": "ris", "bibtex": "bib"}[format]
    mime = {
        "csv": "text/csv",
        "ris": "application/x-research-info-systems",
        "bibtex": "application/x-bibtex",
    }[format]
    content = stream.getvalue().encode("utf-8-sig" if format == "csv" else "utf-8")
    artifact = store_bytes(client, content, f"readcube-references.{extension}", mime)
    return meta | {
        "format": format,
        "selected_records": len(rows),
        "exported_records": len(selected),
        "duplicate_doi_groups": duplicates,
        "artifact": artifact,
    }


def normalize_names(names):
    if not 1 <= len(names) <= 500:
        raise ValueError("Provide between 1 and 500 author names")
    return {
        "authors": [normalize_author(name) for name in names],
        "remote_changes": False,
        "note": "Formatting only. No initials expansion or identity merging.",
    }
