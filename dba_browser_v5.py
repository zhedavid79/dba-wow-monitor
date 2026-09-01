from __future__ import annotations

import asyncio
import re

import dba_browser_v2 as v2
import dba_browser_v4 as v4


# Format classification hardening:
# 1) DBA's own Product category is primary truth for laptop vs desktop.
# 2) Title markers are fallback only when category is not decisive.
# 3) Description-only words can never turn a desktop into a laptop.
# 4) Existing mATX/ITX/ATX/PSU logic remains authoritative for desktop A3 status.
CATEGORY_LAPTOP_MARKER = "__DBA_CATEGORY_LAPTOP__"
CATEGORY_DESKTOP_MARKER = "__DBA_CATEGORY_DESKTOP__"

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
_original_fetch_item = v4.fetch_jsonld_item_all_scripts


async def fetch_item_with_category_marker(page, listing_id: str) -> dict | None:
    item = await _original_fetch_item(page, listing_id)
    if not item:
        return item

    category = str(item.get("category") or "").lower()
    description = str(item.get("description") or "")

    if any(token in category for token in ("bærbare computere", "baerbare computere", "laptop", "notebook")):
        item["description"] = f"{CATEGORY_LAPTOP_MARKER}\n{description}"
    elif any(token in category for token in ("stationære computere", "stationaere computere", "desktop")):
        item["description"] = f"{CATEGORY_DESKTOP_MARKER}\n{description}"

    return item


def classify_format_hardened(text: str) -> tuple[str, str]:
    raw = text or ""
    title = raw.splitlines()[0].strip()

    if CATEGORY_LAPTOP_MARKER in raw:
        return "LAPTOP", "Laptop form factor verified from DBA's live Product category."

    if CATEGORY_DESKTOP_MARKER in raw:
        cleaned = raw.replace(CATEGORY_DESKTOP_MARKER, " ")
        cleaned = v2.LAPTOP_RE.sub(" ", cleaned)
        return _original_classify_format(cleaned)

    if TITLE_DESKTOP_RE.search(title):
        cleaned = v2.LAPTOP_RE.sub(" ", raw)
        return _original_classify_format(cleaned)

    if TITLE_LAPTOP_RE.search(title) or v2.LAPTOP_RE.search(title):
        return "LAPTOP", "Laptop form factor verified from the live listing title."

    cleaned = v2.LAPTOP_RE.sub(" ", raw)
    return _original_classify_format(cleaned)


v4.fetch_jsonld_item_all_scripts = fetch_item_with_category_marker
v2.classify_format = classify_format_hardened


if __name__ == "__main__":
    asyncio.run(v4.main())
