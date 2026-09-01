from __future__ import annotations

import asyncio
import re

import dba_browser_v2 as v2
import dba_browser_v4 as v4


# Format classification hardening:
# - LAPTOP is determined from the listing title only, never from arbitrary description text.
# - Explicit desktop/stationary wording in the title wins over laptop-like words elsewhere.
# - Known laptop product-family markers are recognized generically in titles.
# - Desktop/A3 classification still uses the full live listing text after laptop-only markers
#   are neutralized, preserving the existing mATX/ITX/ATX/PSU logic.
TITLE_DESKTOP_RE = re.compile(r"\b(station(?:æ|a)r(?:e)?|desktop|tower)\b", re.I)
TITLE_LAPTOP_RE = re.compile(
    r"\b("
    r"laptop|b(?:æ|ae)rbar|notebook|"
    r"omen\s*(?:1[4-9]|transcend)|"
    r"legion\s*(?:5|7|pro|slim)|"
    r"nitro\s*(?:5|16|17|v)|"
    r"predator\s*(?:helios|triton)|"
    r"katana(?:\s*gf\d+|\s*1[5-7])?|"
    r"raider\s*ge\d+|stealth\s*g[sx]\d+|"
    r"rog\s*(?:strix|zephyrus|flow)|"
    r"tuf\s*gaming\s*[af]\d+|"
    r"victus\s*(?:1[5-7])|"
    r"ideapad\s*gaming|loq\s*(?:1[5-7])?"
    r")\b",
    re.I,
)

_original_classify_format = v2.classify_format


def classify_format_title_hardened(text: str) -> tuple[str, str]:
    title = (text or "").splitlines()[0].strip()

    if TITLE_DESKTOP_RE.search(title):
        cleaned = v2.LAPTOP_RE.sub(" ", text or "")
        return _original_classify_format(cleaned)

    if TITLE_LAPTOP_RE.search(title) or v2.LAPTOP_RE.search(title):
        return "LAPTOP", "Laptop form factor verified from the live listing title."

    # Do not allow laptop-like wording occurring only in the description to change
    # a desktop/unknown listing into a laptop. A3 logic continues on the full text.
    cleaned = v2.LAPTOP_RE.sub(" ", text or "")
    return _original_classify_format(cleaned)


v2.classify_format = classify_format_title_hardened


if __name__ == "__main__":
    asyncio.run(v4.main())
