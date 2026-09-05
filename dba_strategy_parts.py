from __future__ import annotations

import asyncio
import re

import dba_z20_parts_recovery as recovery

parts = recovery.parts
# Platform-first discovery: keep the proven T0/T1 price gate, but search the durable
# AM5 foundation and bridge-performance market explicitly.
parts.T1_CONCURRENCY = 8
parts.T1_TOTAL_DEADLINE_SECONDS = 600

# HARD EXCLUDE must mean a functional defect, not ordinary cosmetic wear and not
# a harmless phrase such as "ingen fejl". Override the older broad component regex
# before parts.main() evaluates T1 descriptions.
FUNCTIONAL_DEFECT = re.compile(
    r"\b(?:delvist\s+defekt|defekt|virker\s+ikke|fungerer\s+ikke|ustabil|"
    r"artefakt(?:er)?|artifact(?:s)?|til\s+dele|reservedele|"
    r"fryser|crash(?:er)?|genstarter|slukker|overopheder)\b"
    r"|\bfejl(?:er)?\s+(?:under|ved|på)\b",
    re.I,
)
parts.DEFECT = FUNCTIONAL_DEFECT

EXTRA_QUERIES = [
    # Permanent/long-lived foundation opportunities.
    "ryzen 7500f", "ryzen 7600", "ryzen 7600x", "ryzen 7700", "am5 cpu",
    "b650m wifi", "b650m wi-fi", "b850m wifi", "am5 matx wifi", "am5 bundkort wifi",
    "ddr5 32gb", "ddr5 6000 32gb",
    # Opportunistic bridge GPUs: do not require a modern GPU if an older cheap card is sufficient.
    "vega 56", "vega 64", "rx 5700 xt", "rx 6600", "rx 6600 xt", "rx 6650 xt",
    "rtx 2060", "rtx 2060 super", "rtx 2070", "rtx 2070 super", "rtx 2080", "rtx 2080 super",
    # New-first categories are still discovered for exceptional used offers / donor reuse.
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
BOARD_ONLY = re.compile(r"\b(?:b650m|b850m|a620m|x670e?m?|bundkort|motherboard)\b", re.I)
AM5_BOARD = re.compile(r"\b(?:b650m|b850m|a620m|am5)\b", re.I)
BOARD_WIFI = re.compile(r"\b(?:wi-?fi|wifi|wireless|ax)\b", re.I)

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
    base_kind, base_reason = _original_classify(title)
    if base_kind:
        return base_kind, base_reason
    # Standalone boards are needed by the platform-first strategy. Keep this strict:
    # the title itself must identify a motherboard-class product, not merely mention AM5.
    if BOARD_ONLY.search(title) and not re.search(r"\b(?:pc|computer|stationær|desktop|bundle|pakke|cpu\s*\+|ryzen\s+[3579])\b", title, re.I):
        return "MOTHERBOARD", "TITLE_PROVES_STANDALONE_MOTHERBOARD"
    return None, base_reason


def plausible_at_t0(row: dict) -> bool:
    title = row.get("title") or ""
    if classify(title)[0] in {"STORAGE", "CASE", "COOLER", "MOTHERBOARD"}:
        return True
    return _original_plausible(row)


def defect_regression() -> None:
    # Cosmetic wear and explicit absence of faults are not functional defects.
    assert FUNCTIONAL_DEFECT.search("ingen fejl, kun en lille ridse") is None
    assert FUNCTIONAL_DEFECT.search("kosmetiske ridser og en lille bule") is None
    # Actual operational problems remain hard excludes.
    assert FUNCTIONAL_DEFECT.search("grafikkortet fryser under høj belastning")
    assert FUNCTIONAL_DEFECT.search("delvist defekt - virker ikke stabilt")


parts.classify = classify
parts.plausible_at_t0 = plausible_at_t0

if __name__ == "__main__":
    defect_regression()
    asyncio.run(parts.main())
