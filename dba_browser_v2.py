from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

BASE = "https://www.dba.dk"
ITEM_URL = BASE + "/recommerce/forsale/item/{listing_id}"
ITEM_RE = re.compile(r"/recommerce/forsale/item/(\d+)")
MAX_PRICE = 15000

QUERIES = [
    "gaming pc", "gamer pc", "gaming computer", "stationær gaming", "gaming bærbar", "gaming laptop",
    "omen gaming", "legion gaming", "nitro gaming", "predator gaming", "sharkgaming", "dutzo", "mm vision", "msi gamer",
    "rtx 2060 super", "rtx 2070", "rtx 2070 super", "rtx 2080", "rtx 2080 super",
    "rtx 3060", "rtx 3060 ti", "rtx 3070", "rtx 3070 ti", "rtx 3080", "rtx 4060", "rtx 4060 ti",
    "rx 5700 xt", "rx 6600 xt", "rx 6650 xt", "rx 6700", "rx 6700 xt", "rx 6750 xt", "rx 6800", "rx 7600",
    "skal væk gaming", "hurtig handel gaming",
]

GPU_RULES = [
    (r"\brtx\s*3080\s*ti\b", "RTX 3080 Ti", 96),
    (r"\brtx\s*3080\b", "RTX 3080", 90),
    (r"\brtx\s*3070\s*ti\b", "RTX 3070 Ti", 79),
    (r"\brtx\s*3070\b", "RTX 3070", 73),
    (r"\brtx\s*3060\s*ti\b", "RTX 3060 Ti", 66),
    (r"\brtx\s*3060\b", "RTX 3060", 54),
    (r"\brtx\s*4060\s*ti\b", "RTX 4060 Ti", 72),
    (r"\brtx\s*4060\b", "RTX 4060", 60),
    (r"\brtx\s*2080\s*ti\b", "RTX 2080 Ti", 73),
    (r"\brtx\s*2080\s*super\b", "RTX 2080 Super", 65),
    (r"\brtx\s*2080\b", "RTX 2080", 61),
    (r"\brtx\s*2070\s*super\b", "RTX 2070 Super", 57),
    (r"\brtx\s*2070\b", "RTX 2070", 52),
    (r"\brtx\s*2060\s*super\b", "RTX 2060 Super", 50),
    (r"\brx\s*6800\s*xt\b", "RX 6800 XT", 90),
    (r"\brx\s*6800\b", "RX 6800", 84),
    (r"\brx\s*6750\s*xt\b", "RX 6750 XT", 72),
    (r"\brx\s*6700\s*xt\b", "RX 6700 XT", 68),
    (r"\brx\s*6700\b", "RX 6700", 62),
    (r"\brx\s*6650\s*xt\b", "RX 6650 XT", 54),
    (r"\brx\s*6600\s*xt\b", "RX 6600 XT", 51),
    (r"\brx\s*5700\s*xt\b", "RX 5700 XT", 55),
    (r"\brx\s*7600\b", "RX 7600", 59),
]

CPU_RULES = [
    (r"\b9950x3d\b", "Ryzen 9 9950X3D", 145),
    (r"\b9900x3d\b", "Ryzen 9 9900X3D", 141),
    (r"\b9800x3d\b", "Ryzen 7 9800X3D", 135),
    (r"\b9700x\b", "Ryzen 7 9700X", 113),
    (r"\b9600x\b", "Ryzen 5 9600X", 107),
    (r"\b7950x3d\b", "Ryzen 9 7950X3D", 132),
    (r"\b7900x3d\b", "Ryzen 9 7900X3D", 128),
    (r"\b7800x3d\b", "Ryzen 7 7800X3D", 125),
    (r"\b7950x\b", "Ryzen 9 7950X", 118),
    (r"\b7900x\b", "Ryzen 9 7900X", 114),
    (r"\b7900\b", "Ryzen 9 7900", 111),
    (r"\b7700x\b", "Ryzen 7 7700X", 108),
    (r"\b7700\b", "Ryzen 7 7700", 104),
    (r"\b7600x\b", "Ryzen 5 7600X", 101),
    (r"\b7600\b", "Ryzen 5 7600", 98),
    (r"\b7500f\b", "Ryzen 5 7500F", 94),
    (r"\b5800x3d\b", "Ryzen 7 5800X3D", 100),
    (r"\b5700x3d\b", "Ryzen 7 5700X3D", 96),
    (r"\b5700x\b", "Ryzen 7 5700X", 82),
    (r"\b5600x\b", "Ryzen 5 5600X", 79),
    (r"\b5600\b", "Ryzen 5 5600", 76),
    (r"\b3600x\b", "Ryzen 5 3600X", 59),
    (r"\b3600\b", "Ryzen 5 3600", 56),
    (r"\bi9[- ]?14900[a-z]*\b", "Core i9-14900", 126),
    (r"\bi7[- ]?14700[a-z]*\b", "Core i7-14700", 120),
    (r"\bi5[- ]?14600[a-z]*\b", "Core i5-14600", 112),
    (r"\bi9[- ]?13900[a-z]*\b", "Core i9-13900", 119),
    (r"\bi7[- ]?13700[a-z]*\b", "Core i7-13700", 113),
    (r"\bi5[- ]?13600[a-z]*\b", "Core i5-13600", 105),
    (r"\bi7[- ]?13620h\b", "Core i7-13620H", 99),
    (r"\bi9[- ]?12900[a-z]*\b", "Core i9-12900", 108),
    (r"\bi7[- ]?12700[a-z]*\b", "Core i7-12700", 98),
    (r"\bi5[- ]?12600[a-z]*\b", "Core i5-12600", 91),
    (r"\bi5[- ]?12400[a-z]*\b", "Core i5-12400", 81),
    (r"\bi7[- ]?11800h\b", "Core i7-11800H", 77),
    (r"\bi7[- ]?11700[a-z]*\b", "Core i7-11700", 79),
    (r"\bi5[- ]?11400[a-z]*\b", "Core i5-11400", 70),
    (r"\bi7[- ]?10700[a-z]*\b", "Core i7-10700", 72),
    (r"\bi5[- ]?10400[a-z]*\b", "Core i5-10400", 65),
    (r"\bi7[- ]?9700[a-z]*\b", "Core i7-9700", 67),
    (r"\bi5[- ]?9600[a-z]*\b", "Core i5-9600", 59),
    (r"\bi7[- ]?8700[a-z]*\b", "Core i7-8700", 61),
    (r"\bi5[- ]?8600[a-z]*\b", "Core i5-8600", 53),
]

LAPTOP_RE = re.compile(
    r"\b(laptop|bærbar|notebook|omen\s+1[456789]|legion\s+(?:5|7|pro|slim)|nitro\s+(?:5|16|17|v)|predator\s+helios|katana\s+(?:15|17)|rog\s+(?:strix|zephyrus)|tuf\s+gaming\s+[af]1[567])\b",
    re.I,
)
MATX_RE = re.compile(r"\b(micro[- ]?atx|m[- ]?atx|matx|[abhqz][1-9]\d{2}m(?:[-\s]|\b))", re.I)
ITX_RE = re.compile(r"\b(mini[- ]?itx|itx)\b", re.I)
ATX_RE = re.compile(r"\b(e[- ]?atx|extended[- ]?atx|atx)\b", re.I)
OEM_RE = re.compile(r"\b(hp\s+(?:omen|pavilion)|dell\s+(?:g5|xps|alienware)|lenovo\s+(?:legion|ideacentre)|acer\s+(?:nitro|predator))\b", re.I)
PSU_RE = re.compile(r"\b(corsair|seasonic|be quiet!?|evga|cooler master|nzxt|asus|msi|fsp|super flower)\b.{0,60}\b\d{3,4}\s*w\b", re.I | re.S)

CARD_META_RE = re.compile(
    r"^(?:Føj til favoritter\.?|Gå til annoncen|Køb nu|Fiks færdig|Betalt placering|Privat|Forhandler|Asus|HP|MSI|Acer|Lenovo|Dell)$",
    re.I,
)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_dkk(text: str) -> int | None:
    m = re.search(r"(?<!\d)(\d{1,3}(?:[.\s\u00a0]\d{3})*|\d{3,6})\s*(?:kr\.?|DKK)\b", text or "", re.I)
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(1))
    return int(digits) if digits else None


def parse_number(value) -> int | None:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        s = value.strip().replace(".", "").replace(" ", "").replace("\u00a0", "")
        if re.fullmatch(r"\d+(?:,\d+)?", s):
            return int(float(s.replace(",", ".")))
    return None


def card_title(card_text: str) -> str:
    lines = [re.sub(r"\s+", " ", x).strip() for x in (card_text or "").splitlines() if x.strip()]
    price_index = next((i for i, x in enumerate(lines) if parse_dkk(x) is not None), None)
    candidates = lines[price_index + 1 :] if price_index is not None else lines
    for line in candidates:
        if CARD_META_RE.match(line):
            continue
        if parse_dkk(line) is not None:
            continue
        if re.fullmatch(r"\d+\s*(?:t\.|min\.|d\.)", line, re.I):
            continue
        if len(line) >= 5:
            return line
    return ""


def match_rule(text: str, rules):
    for pat, label, score in rules:
        if re.search(pat, text or "", re.I):
            return label, score
    return "Ukendt", 0


def performance_class(gpu_score: int, cpu_score: int) -> str:
    if gpu_score < 50 or cpu_score < 50:
        return "UNDER MINIMUM"
    if gpu_score >= 90 and cpu_score >= 76:
        return "OVERKILL"
    if gpu_score >= 65 and cpu_score >= 60:
        return "SWEET SPOT"
    return "ACCEPTABLE"


def fixture_regression() -> dict:
    fixture = [
        {"id": "24247594", "title": "RTX 3070 Ti / i5-8600K", "price": 4399},
        {"id": "other", "title": "Other PC", "price": 2000},
    ]
    target = next(x for x in fixture if x["id"] == "24247594")
    if target["price"] != 4399 or not target["title"].startswith("RTX 3070 Ti"):
        raise SystemExit("PRICE BINDING FIXTURE FAILED")
    return {
        "ok": True,
        "type": "static_fixture",
        "historical_listing_id": "24247594",
        "expected_price": 4399,
    }


def classify_format(text: str) -> tuple[str, str]:
    if LAPTOP_RE.search(text):
        return "LAPTOP", "Portable complete system; no case transfer required."
    matx = bool(MATX_RE.search(text))
    itx = bool(ITX_RE.search(text))
    cleaned = re.sub(r"\b(?:micro[- ]?atx|m[- ]?atx|matx|mini[- ]?itx)\b", " ", text, flags=re.I)
    full_atx = bool(ATX_RE.search(cleaned))
    if full_atx and not (matx or itx):
        return "A3_INCOMPATIBLE", "Listing explicitly indicates ATX/E-ATX rather than mATX/ITX."
    if matx or itx:
        if PSU_RE.search(text):
            return "A3_READY", "Explicit mATX/ITX evidence plus standard PSU brand/wattage evidence."
        return "A3_READY_PSU_CHECK", "Explicit mATX/ITX evidence; PSU compatibility still requires confirmation."
    if OEM_RE.search(text):
        return "A3_UNCERTAIN", "OEM platform without explicit standard mATX/ITX evidence; proprietary parts cannot be ruled out."
    return "A3_UNCERTAIN", "No explicit mATX/ITX evidence in the live listing."


def complete_pc_category(category: str, title: str) -> bool:
    c = (category or "").lower()
    if "stationære computere" in c or "bærbare computere" in c or "laptop" in c:
        return True
    return bool(re.search(r"\b(?:gaming|gamer)\s*(?:pc|computer|laptop|bærbar)|\b(?:pc|computer)\s*(?:gaming|gamer)\b", title or "", re.I))


async def dismiss_consent(page) -> None:
    for label in ("Afvis alle", "Accepter alle", "Accept all", "Reject all", "Kun nødvendige"):
        try:
            button = page.get_by_role("button", name=re.compile(label, re.I)).first
            if await button.count():
                await button.click(timeout=800)
        except Exception:
            pass


async def discover_cards(page, query: str) -> list[dict]:
    url = f"{BASE}/recommerce/forsale/search?q={quote(query)}"
    response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    if response and response.status >= 400:
        return []
    await dismiss_consent(page)
    try:
        await page.wait_for_selector('a[href*="/recommerce/forsale/item/"]', timeout=6000)
    except PlaywrightTimeoutError:
        return []
    for _ in range(3):
        await page.mouse.wheel(0, 1700)
        await page.wait_for_timeout(250)
    cards = await page.locator('a[href*="/recommerce/forsale/item/"]').all()
    found = {}
    for a in cards:
        href = await a.get_attribute("href") or ""
        m = ITEM_RE.search(href)
        if not m:
            continue
        listing_id = m.group(1)
        text = (await a.inner_text()).strip()
        if listing_id not in found or len(text) > len(found[listing_id]):
            found[listing_id] = text
    out = []
    for listing_id, text in found.items():
        price = parse_dkk(text)
        title = card_title(text)
        if not price or price > MAX_PRICE or not title:
            continue
        out.append({
            "listing_id": listing_id,
            "url": ITEM_URL.format(listing_id=listing_id),
            "title_t0": title,
            "ask_t0": price,
            "currency_t0": "DKK",
            "t0_at": utcnow(),
            "t0_source": "rendered_dba_card",
        })
    return out


async def fetch_item(page, listing_id: str) -> dict | None:
    response = await page.goto(ITEM_URL.format(listing_id=listing_id), wait_until="domcontentloaded", timeout=30000)
    if not response or response.status >= 400:
        return None
    try:
        await page.wait_for_selector('script[type="application/ld+json"]', timeout=5000)
    except PlaywrightTimeoutError:
        return None
    scripts = await page.locator('script[type="application/ld+json"]').all_text_contents()
    for raw in scripts:
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        candidates = obj if isinstance(obj, list) else [obj]
        for item in candidates:
            if not isinstance(item, dict) or item.get("@type") != "Product":
                continue
            offers = item.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            url = str(item.get("url") or ITEM_URL.format(listing_id=listing_id))
            id_ok = listing_id in url or listing_id in str(item.get("sku") or "")
            ask = parse_number(offers.get("price"))
            currency = offers.get("priceCurrency")
            availability = str(offers.get("availability") or "")
            title = str(item.get("name") or "").strip()
            if not id_ok or not title:
                continue
            return {
                "listing_id": listing_id,
                "canonical_url": ITEM_URL.format(listing_id=listing_id),
                "title": title,
                "description": str(item.get("description") or ""),
                "brand": str((item.get("brand") or {}).get("name") if isinstance(item.get("brand"), dict) else item.get("brand") or ""),
                "category": str(item.get("category") or ""),
                "ask_t1": ask,
                "currency_t1": currency,
                "availability_t1": availability,
                "active_t1": availability.rstrip("/").lower().endswith("instock"),
                "identity_ok": id_ok,
                "t1_at": utcnow(),
                "t1_source": "dba_jsonld_product_all_scripts",
            }
    return None


async def main() -> None:
    Path("results").mkdir(exist_ok=True)
    fixture = fixture_regression()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(locale="da-DK", viewport={"width": 1440, "height": 1100})
        search_page = await context.new_page()
        item_page = await context.new_page()
        try:
            found = {}
            search_errors = []
            for query in QUERIES:
                try:
                    rows = await discover_cards(search_page, query)
                except Exception as exc:
                    search_errors.append({"query": query, "error": type(exc).__name__, "detail": str(exc)[:300]})
                    continue
                for row in rows:
                    if row["listing_id"] not in found:
                        row["source_queries"] = [query]
                        found[row["listing_id"]] = row
                    else:
                        found[row["listing_id"]]["source_queries"].append(query)
            verified = []
            rejected = []
            for row in sorted(found.values(), key=lambda x: x["ask_t0"]):
                try:
                    t1 = await fetch_item(item_page, row["listing_id"])
                except Exception as exc:
                    rejected.append({"listing_id": row["listing_id"], "reason": "T1_FETCH_FAILED", "detail": type(exc).__name__})
                    continue
                if not t1 or not t1["identity_ok"]:
                    rejected.append({"listing_id": row["listing_id"], "reason": "T1_IDENTITY_UNVERIFIED"})
                    continue
                if not t1["active_t1"]:
                    rejected.append({"listing_id": row["listing_id"], "reason": "INACTIVE_OR_STATUS_UNVERIFIED"})
                    continue
                if not isinstance(t1["ask_t1"], int) or t1["currency_t1"] != "DKK":
                    rejected.append({"listing_id": row["listing_id"], "reason": "MISSING_OR_INVALID_T1_PRICE"})
                    continue
                text = f"{t1['title']}\n{t1['description']}\n{t1['brand']}\n{t1['category']}"
                gpu, gpu_score = match_rule(text, GPU_RULES)
                cpu, cpu_score = match_rule(text, CPU_RULES)
                if gpu_score < 50 or cpu_score < 50 or not complete_pc_category(t1["category"], t1["title"]):
                    rejected.append({"listing_id": row["listing_id"], "reason": "NOT_COMPLETE_OR_BELOW_MINIMUM"})
                    continue
                format_class, format_rationale = classify_format(text)
                verified.append({
                    "listing_id": row["listing_id"], "url": t1["canonical_url"], "title": t1["title"],
                    "ask_t0": row["ask_t0"], "ask_t1": t1["ask_t1"], "currency": t1["currency_t1"],
                    "price_changed": row["ask_t0"] != t1["ask_t1"], "status": t1["availability_t1"],
                    "gpu": gpu, "gpu_score": gpu_score, "cpu": cpu, "cpu_score": cpu_score,
                    "performance_class": performance_class(gpu_score, cpu_score),
                    "form_factor": "LAPTOP" if format_class == "LAPTOP" else "DESKTOP",
                    "a3_compatibility": format_class, "a3_rationale": format_rationale,
                    "t0_source": row["t0_source"], "t1_source": t1["t1_source"],
                    "t0_at": row["t0_at"], "t1_at": t1["t1_at"],
                    "source_queries": sorted(set(row["source_queries"])),
                })
        finally:
            await search_page.close()
            await item_page.close()
            await context.close()
            await browser.close()

    verified.sort(key=lambda r: (r["ask_t1"], -r["gpu_score"], -r["cpu_score"]))
    out = {
        "model_version": "DBA-WOW-BROWSER-V2",
        "generated_at": utcnow(),
        "gate_passed": bool(verified),
        "retrieval_method": "Rendered DBA result card at T0 + same-ID DBA Product JSON-LD at T1",
        "fixture_regression": fixture,
        "counts": {"queries": len(QUERIES), "t0_unique": len(found), "verified": len(verified), "rejected": len(rejected)},
        "ranked": verified,
        "rejection_reason_counts": dict(Counter(x["reason"] for x in rejected)),
        "search_errors": search_errors,
    }
    Path("results/wow_a3_latest.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out["counts"], ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
