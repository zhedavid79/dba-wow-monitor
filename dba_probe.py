from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "da-DK,da;q=0.9,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}
TIMEOUT = 25
REGRESSION_ID = "24247594"

TARGETS = [
    ("item_regression", f"https://www.dba.dk/recommerce/forsale/item/{REGRESSION_ID}"),
    ("search_html", "https://www.dba.dk/recommerce/forsale/search?q=gaming%20pc%20rtx%203070"),
    ("search_api_a", "https://www.dba.dk/recommerce/forsale/search/api/search/SEARCH_ID_BAP_COMMON?q=gaming%20pc%20rtx%203070"),
    ("search_api_b", "https://www.dba.dk/recommerce-search-page/api/search/SEARCH_ID_BAP_COMMON?q=gaming%20pc%20rtx%203070"),
]

PRICE_KEYS = {
    "price", "priceamount", "price_amount", "pricevalue", "price_value",
    "amount", "priceformatted", "price_formatted", "priceraw", "price_raw",
}
ID_KEYS = {"listingid", "listing_id", "itemid", "item_id", "id"}
TITLE_KEYS = {"title", "name", "heading"}
STATUS_KEYS = {"status", "tradetype", "trade_type", "disposed", "active", "sold"}
URL_KEYS = {"url", "canonicalurl", "canonical_url", "weburl", "web_url"}


def keynorm(k: Any) -> str:
    return re.sub(r"[^a-z0-9_]", "", str(k).lower())


def compact(value: Any, limit: int = 300) -> Any:
    if isinstance(value, str):
        return value[:limit]
    return value


def walk(obj: Any, path: str = "$", out: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if out is None:
        out = []
    if isinstance(obj, dict):
        norms = {keynorm(k): k for k in obj}
        has_id = any(k in norms for k in ID_KEYS)
        has_price = any(k in norms for k in PRICE_KEYS)
        has_title = any(k in norms for k in TITLE_KEYS)
        if (has_id and has_price) or (has_price and has_title):
            row: dict[str, Any] = {"path": path}
            for wanted, label in [
                (ID_KEYS, "id"), (TITLE_KEYS, "title"), (PRICE_KEYS, "price"),
                (STATUS_KEYS, "status"), (URL_KEYS, "url"),
            ]:
                for n, original in norms.items():
                    if n in wanted:
                        row[label] = compact(obj.get(original))
                        break
            row["keys"] = list(obj.keys())[:40]
            out.append(row)
        for k, v in obj.items():
            walk(v, f"{path}.{k}", out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:10000]):
            walk(v, f"{path}[{i}]", out)
    return out


def parse_json_scripts(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    found: list[dict[str, Any]] = []
    for i, s in enumerate(soup.find_all("script")):
        typ = (s.get("type") or "").lower()
        sid = s.get("id") or ""
        text = s.string or s.get_text() or ""
        if not text.strip():
            continue
        if "json" in typ or sid in {"__NEXT_DATA__", "__NUXT_DATA__"}:
            try:
                data = json.loads(text)
            except Exception:
                continue
            candidates = walk(data)
            if candidates:
                found.append({
                    "script_index": i,
                    "type": typ,
                    "id": sid,
                    "candidate_count": len(candidates),
                    "candidates": candidates[:100],
                })
    return found


def interesting_text(html: str, needle: str) -> list[str]:
    out = []
    low = html.lower()
    needles = [needle.lower(), '"price"', 'listingid', 'itemid', 'tradetype', 'disposed']
    for n in needles:
        start = 0
        while len(out) < 15:
            idx = low.find(n, start)
            if idx < 0:
                break
            a, b = max(0, idx - 180), min(len(html), idx + 350)
            snippet = re.sub(r"\s+", " ", html[a:b])
            out.append(snippet)
            start = idx + len(n)
    return out


def fetch_target(name: str, url: str) -> dict[str, Any]:
    result: dict[str, Any] = {"name": name, "url": url}
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        result.update({
            "status_code": r.status_code,
            "final_url": r.url,
            "content_type": r.headers.get("content-type"),
            "content_length": len(r.content),
            "server": r.headers.get("server"),
        })
        text = r.text
        result["contains_regression_id"] = REGRESSION_ID in text
        ct = (r.headers.get("content-type") or "").lower()
        if "json" in ct or text.lstrip().startswith(("{", "[")):
            try:
                data = r.json()
                cands = walk(data)
                result["json_candidate_count"] = len(cands)
                result["json_candidates"] = cands[:200]
                result["json_top_type"] = type(data).__name__
                if isinstance(data, dict):
                    result["json_top_keys"] = list(data.keys())[:80]
            except Exception as e:
                result["json_error"] = repr(e)
        else:
            scripts = parse_json_scripts(text)
            result["structured_scripts"] = scripts
            result["structured_candidate_count"] = sum(x["candidate_count"] for x in scripts)
            result["snippets"] = interesting_text(text, REGRESSION_ID)
            soup = BeautifulSoup(text, "html.parser")
            result["title_tag"] = soup.title.get_text(strip=True) if soup.title else None
            canon = soup.find("link", rel="canonical")
            result["canonical"] = canon.get("href") if canon else None
    except Exception as e:
        result["error"] = repr(e)
    return result


def main() -> int:
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "regression_id": REGRESSION_ID,
        "targets": [fetch_target(name, url) for name, url in TARGETS],
    }
    Path("results").mkdir(exist_ok=True)
    Path("results/latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
