from __future__ import annotations

import asyncio
import re

import dba_z20_parts_recovery as recovery

parts = recovery.parts

EXTRA_QUERIES = [
    "nvme 1tb", "nvme 500gb", "m2 ssd 1tb", "ssd 1tb",
    "matx kabinet", "micro atx kabinet", "jonsbo z20", "mini itx kabinet",
    "650w strømforsyning", "750w strømforsyning",
    "am4 cpu køler", "am5 cpu køler", "lga1700 cpu køler", "cpu køler",
]
for q in EXTRA_QUERIES:
    if q not in parts.QUERIES:
        parts.QUERIES.append(q)

STORAGE = re.compile(r"\b(?:nvme|m\.?2|ssd)\b", re.I)
STORAGE_SIZE = re.compile(r"\b(?:500|512|1000|1024)\s*gb\b|\b[12]\s*tb\b", re.I)
CASE = re.compile(r"\b(?:kabinet|case)\b", re.I)
CASE_FIT = re.compile(r"\b(?:micro[- ]?atx|m[- ]?atx|matx|mini[- ]?itx|itx|jonsbo\s+z20)\b", re.I)
COOLER = re.compile(r"\b(?:cpu\s*køler|cpu\s*koeler|cpu\s*cooler|processorkøler|processorkoeler)\b", re.I)
COOLER_SOCKET = re.compile(r"\b(?:am4|am5|lga1700|lga1200)\b", re.I)

_original_classify = parts.classify
_original_plausible = parts.plausible_at_t0


def classify(title: str):
    # Extra component identities are deliberately title-proven so a search result cannot
    # accidentally turn an unrelated item into a build component.
    if STORAGE.search(title) and STORAGE_SIZE.search(title):
        return "STORAGE", "TITLE_PROVES_STORAGE"
    if CASE.search(title) and CASE_FIT.search(title):
        return "CASE", "TITLE_PROVES_CASE_AND_MATX_ITX_FIT"
    if COOLER.search(title) and COOLER_SOCKET.search(title):
        return "COOLER", "TITLE_PROVES_COOLER_AND_SOCKET"
    return _original_classify(title)


def plausible_at_t0(row: dict) -> bool:
    title = row.get("title") or ""
    if classify(title)[0] in {"STORAGE", "CASE", "COOLER"}:
        return True
    return _original_plausible(row)


parts.classify = classify
parts.plausible_at_t0 = plausible_at_t0

if __name__ == "__main__":
    asyncio.run(parts.main())
