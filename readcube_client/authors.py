"""Conservative author matching; formatting does not assert that names share an identity."""

import re
import unicodedata


def normalize_author(author):
    if isinstance(author, dict):
        family = author.get("family") or author.get("last_name") or author.get("lastname") or ""
        given = author.get("given") or author.get("first_name") or author.get("firstname") or ""
        raw = str(author.get("name") or author.get("literal") or "").strip()
        if not (family or given):
            return normalize_author(raw)
    elif isinstance(author, str):
        raw = " ".join(unicodedata.normalize("NFKC", author).split())
        if "," in raw:
            family, given = (s.strip() for s in raw.split(",", 1))
        else:
            parts = raw.split()
            family, given = (parts[-1], " ".join(parts[:-1])) if parts else ("", "")
            # Keep surname particles with the family name without changing case.
            words = given.split()
            while words and words[-1].casefold() in {
                "de",
                "del",
                "van",
                "von",
                "der",
                "da",
                "di",
                "la",
            }:
                family = words.pop() + " " + family
            given = " ".join(words)
    else:
        raise TypeError("Authors must be strings or name objects")
    given, family = " ".join(str(given).split()), " ".join(str(family).split())
    display = " ".join(s for s in (given, family) if s)
    canonical = ", ".join(s for s in (family, given) if s)
    return {
        "original": author,
        "display": display,
        "family": family,
        "given": given,
        "canonical": canonical,
        "key": name_key(display),
        "identity_warning": "Name matching cannot disambiguate people; initials are not expanded.",
    }


def name_key(value):
    value = unicodedata.normalize("NFKD", str(value)).casefold()
    value = "".join(c for c in value if not unicodedata.combining(c))
    return " ".join(re.findall(r"[^\W_]+", value, flags=re.UNICODE))


def author_names(article):
    authors = article.get("authors") or []
    if isinstance(authors, str):
        authors = [authors]  # Do not split a surname, given-name string at the comma.
    return [normalize_author(x) for x in authors if x]


def author_matches(author, query, *, match="contains"):
    query_name = normalize_author(query)
    return author_key_matches(author["key"], query_name["key"], match=match)


def author_key_matches(author_key, key, *, match="contains"):
    if not key:
        return False
    if match == "exact":
        return author_key == key
    if match != "contains":
        raise ValueError("Author match must be contains or exact")
    # Word prefixes support "F Gonzalez Lima" without matching arbitrary middle substrings.
    terms, names = key.split(), author_key.split()
    return all(any(n.startswith(t) if len(t) == 1 else n == t for n in names) for t in terms)
