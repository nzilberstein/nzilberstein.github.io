#!/usr/bin/env python3
"""Convert publications.bib into data/publications.json for Hugo.

Hugo can read data files but has no BibTeX parser, so this runs before the
build. Standard library only -- no pip install, in CI or locally.

Entries are grouped by year, newest first. Tag an entry with
`keywords = {highlighted}` to have it appear on the home page.
"""

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIB = os.path.join(ROOT, "publications.bib")
OUT = os.path.join(ROOT, "data", "publications.json")

# The handful of LaTeX escapes that actually show up in Scholar exports.
ACCENTS = {
    r"\'a": "á", r"\'e": "é", r"\'i": "í", r"\'o": "ó", r"\'u": "ú",
    r"\`a": "à", r"\`e": "è", r"\"a": "ä", r"\"o": "ö", r"\"u": "ü",
    r"\~n": "ñ", r"\^a": "â", r"\^e": "ê", r"\^o": "ô", r"\c c": "ç",
    r"\ss": "ß", r"\&": "&", r"\%": "%", r"\_": "_", r"\$": "$",
    "--": "–", "~": " ",
}


def clean(value):
    """Strip BibTeX braces and LaTeX escapes from a field value."""
    for tex, char in ACCENTS.items():
        value = value.replace(tex, char)
    value = re.sub(r"\\[a-zA-Z]+", "", value)   # leftover commands
    value = value.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", value).strip()


def read_part(text, i):
    """Read one value token at position i: a {braced} or "quoted" string,
    or a bare word. Returns (value, next_index, kind)."""
    while i < len(text) and text[i].isspace():
        i += 1
    if i >= len(text):
        return "", i, "bare"
    if text[i] == "{":
        depth, start = 0, i
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return text[start + 1:i], i + 1, "brace"
            i += 1
        return text[start + 1:], i, "brace"
    if text[i] == '"':
        start = i + 1
        i += 1
        while i < len(text) and text[i] != '"':
            i += 1
        return text[start:i], i + 1, "quote"
    start = i
    while i < len(text) and text[i] not in ",}#" and not text[i].isspace():
        i += 1
    return text[start:i], i, "bare"


def read_value(text, i, macros):
    """Read a full field value. A bare word is an @string macro (or a
    number) and is expanded; parts joined with `#` are concatenated,
    e.g.  booktitle = ICASSP # " Workshop"  ->  "...(ICASSP) Workshop"."""
    parts = []
    while True:
        val, i, kind = read_part(text, i)
        if kind == "bare":
            val = macros.get(val.lower(), val)   # numbers fall through as-is
        parts.append(val)
        j = i
        while j < len(text) and text[j].isspace():
            j += 1
        if j < len(text) and text[j] == "#":
            i = j + 1
            continue
        return "".join(parts), i


def collect_macros(text):
    """Build {name: value} from every @string{NAME = "..."} block. Names
    are case-insensitive in BibTeX. Later macros may reference earlier ones."""
    macros = {}
    for m in re.finditer(r"@string\s*\{", text, re.I):
        i = m.end()
        nm = re.compile(r"\s*([^\s=]+)\s*=").match(text, i)
        if not nm:
            continue
        value, i = read_value(text, nm.end(), macros)
        macros[nm.group(1).lower()] = value.strip()
    return macros


def parse(text):
    """Yield (entry_type, key, {field: value}) for each BibTeX entry."""
    macros = collect_macros(text)
    for m in re.finditer(r"@(\w+)\s*\{", text):
        etype = m.group(1).lower()
        if etype in ("comment", "string", "preamble"):
            continue
        i = m.end()
        key_end = text.find(",", i)
        if key_end == -1:
            continue
        key = text[i:key_end].strip()
        i = key_end + 1
        fields, depth = {}, 1
        while i < len(text):
            fm = re.compile(r"\s*(\w+)\s*=").match(text, i)
            if not fm:
                break
            value, i = read_value(text, fm.end(), macros)
            fields[fm.group(1).lower()] = clean(value)
            while i < len(text) and text[i] in " \n\r\t,":
                i += 1
            if i < len(text) and text[i] == "}":
                break
        yield etype, key, fields


def format_authors(raw):
    """'Last, First and Other, A.' -> ['First Last', 'A. Other']"""
    if not raw:
        return []
    names = []
    for part in re.split(r"\s+and\s+", raw):
        part = part.strip()
        if not part:
            continue
        if "," in part:
            last, first = part.split(",", 1)
            part = f"{first.strip()} {last.strip()}".strip()
        names.append(part)
    return names


VENUE_FIELDS = ("journal", "booktitle", "school", "publisher", "howpublished",
                "series", "institution", "archiveprefix")


ML_CONFS = r"neurips|\bnips\b|iclr|icml|aistats|aaai"
JOURNAL_HINTS = r"\btrans\.|\blett\.|\bj\.|journal|\bmag\.|proc\. ieee"
CATEGORIES = ("ml", "journal", "sp", "workshop", "preprint")


def categorize(venue, keywords, override=""):
    """Bucket an entry for the publications page. Rules run in order and the
    first match wins; a `category = {...}` field in the .bib overrides them.

      preprint  keyword `preprint`, or an arXiv venue
      workshop  a workshop *of an ML conference* (NeurIPS/ICML/... workshop)
      ml        main track of NeurIPS, ICLR, ICML, AISTATS, AAAI
      journal   Trans. / Lett. / J. / Journal / Mag.
      sp        every other venue (ICASSP, EUSIPCO, Asilomar, ...)
    """
    if override in CATEGORIES:
        return override
    v = venue.lower()
    if "preprint" in keywords or "arxiv" in v:
        return "preprint"
    if re.search(ML_CONFS, v):
        return "workshop" if "workshop" in v else "ml"
    if re.search(JOURNAL_HINTS, v):
        return "journal"
    return "sp" if v else "other"


def main():
    if not os.path.exists(BIB):
        sys.stderr.write(f"No {BIB}; writing an empty publication list.\n")
        entries = []
    else:
        with open(BIB, encoding="utf-8") as fh:
            entries = list(parse(fh.read()))

    pubs = []
    for etype, key, f in entries:
        year = f.get("year", "")
        venue = next((f[k] for k in VENUE_FIELDS if f.get(k)), "")
        if etype == "phdthesis" and f.get("school"):
            venue = f"PhD thesis, {f['school']}"
        pubs.append({
            "key": key,
            "category": f.get("category", "").strip().lower(),
            "title": f.get("title", "Untitled"),
            "authors": format_authors(f.get("author", "")),
            "year": year,
            "venue": venue,
            "url": f.get("url") or f.get("howpublished_url") or "",
            "doi": f.get("doi", ""),
            "code": f.get("code", ""),
            "note": f.get("note", ""),
            # Optional short label used in the matrix instead of the
            # full title, e.g. short = {Flow Map Denoisers}
            "short": f.get("short") or f.get("shortname", ""),
            # Optional teaser image, e.g. image = {/pubs/my-paper.png}
            "image": f.get("image", ""),
            "image_alt": f.get("image_alt", ""),
            "keywords": [k.strip().lower()
                         for k in re.split(r"[;,]", f.get("keywords", "")) if k.strip()],
        })

    for p in pubs:
        p["category"] = categorize(p["venue"], p["keywords"], p["category"])

    # Newest first; undated entries sort last.
    pubs.sort(key=lambda p: (p["year"].isdigit(), p["year"]), reverse=True)

    groups, order = {}, []
    for p in pubs:
        year = p["year"] or "Preprints"
        if year not in groups:
            groups[year] = []
            order.append(year)
        groups[year].append(p)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump([{"year": y, "items": groups[y]} for y in order], fh, indent=2)

    print(f"Wrote {len(pubs)} publication(s) to {os.path.relpath(OUT, ROOT)}")
    counts = {}
    for p in pubs:
        counts[p["category"]] = counts.get(p["category"], 0) + 1
    print("  " + " · ".join(f"{c} {counts.get(c, 0)}" for c in CATEGORIES))
    for p in pubs:
        if p["category"] == "other":
            sys.stderr.write(f"  ! no venue, not shown in any section: {p['key']}\n")


if __name__ == "__main__":
    main()
