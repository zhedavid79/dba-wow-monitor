from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

BASE = "https://www.dba.dk"
SEARCH_API = BASE + "/recommerce/forsale/search/api/search/SEARCH_ID_BAP_COMMON"
ITEM_URL = BASE + "/recommerce/forsale/item/{id}"
REGRESSION_ID = "24247594"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept-Language": "da-DK,da;q=0.9,en;q=0.7", "Accept": "application/json,text/html;q=0.9,*/*;q=0.8"}
TIMEOUT = 25

QUERIES = [
    "gaming pc", "gamer pc", "gaming computer", "stationær gaming",
    "rtx 3060 ti pc", "rtx 3070 pc", "rtx 3070 ti pc", "rtx 3080 pc",
    "rtx 2080 ti pc", "rtx 4060 pc", "rtx 4060 ti pc",
    "rx 6700 xt pc", "rx 6750 xt pc", "rx 6800 pc",
    "omen gaming", "legion gaming pc", "acer nitro pc", "predator gaming pc",
    "sharkgaming", "dutzo gaming", "mm vision gamer", "skal væk gaming pc",
]

GPU_RULES = [
    (r"\brtx\s*4090\b", "RTX 4090", 130), (r"\brtx\s*4080(?:\s*super)?\b", "RTX 4080", 115),
    (r"\brtx\s*4070\s*ti(?:\s*super)?\b", "RTX 4070 Ti", 105), (r"\brtx\s*4070(?:\s*super)?\b", "RTX 4070", 92),
    (r"\brtx\s*4060\s*ti\b", "RTX 4060 Ti", 72), (r"\brtx\s*4060\b", "RTX 4060", 60),
    (r"\brtx\s*3090\s*ti\b", "RTX 3090 Ti", 105), (r"\brtx\s*3090\b", "RTX 3090", 100),
    (r"\brtx\s*3080\s*ti\b", "RTX 3080 Ti", 96), (r"\brtx\s*3080\b", "RTX 3080", 90),
    (r"\brtx\s*3070\s*ti\b", "RTX 3070 Ti", 79), (r"\brtx\s*3070\b", "RTX 3070", 73),
    (r"\brtx\s*3060\s*ti\b", "RTX 3060 Ti", 66), (r"\brtx\s*3060\b", "RTX 3060", 54),
    (r"\brtx\s*2080\s*ti\b", "RTX 2080 Ti", 73), (r"\brtx\s*2080\s*super\b", "RTX 2080 Super", 65),
    (r"\brtx\s*2080\b", "RTX 2080", 61), (r"\brtx\s*2070\s*super\b", "RTX 2070 Super", 57),
    (r"\brtx\s*2070\b", "RTX 2070", 52), (r"\brtx\s*2060\s*super\b", "RTX 2060 Super", 50),
    (r"\brtx\s*2060\b", "RTX 2060", 45), (r"\bgtx\s*1080\s*ti\b", "GTX 1080 Ti", 60),
    (r"\bgtx\s*1080\b", "GTX 1080", 50),
    (r"\brx\s*7900\s*xtx\b", "RX 7900 XTX", 120), (r"\brx\s*7900\s*xt\b", "RX 7900 XT", 110),
    (r"\brx\s*7800\s*xt\b", "RX 7800 XT", 98), (r"\brx\s*7700\s*xt\b", "RX 7700 XT", 86),
    (r"\brx\s*7600\b", "RX 7600", 59), (r"\brx\s*6950\s*xt\b", "RX 6950 XT", 98),
    (r"\brx\s*6900\s*xt\b", "RX 6900 XT", 94), (r"\brx\s*6800\s*xt\b", "RX 6800 XT", 90),
    (r"\brx\s*6800\b", "RX 6800", 84), (r"\brx\s*6750\s*xt\b", "RX 6750 XT", 72),
    (r"\brx\s*6700\s*xt\b", "RX 6700 XT", 68), (r"\brx\s*6700\b", "RX 6700", 62),
    (r"\brx\s*6650\s*xt\b", "RX 6650 XT", 54), (r"\brx\s*6600\s*xt\b", "RX 6600 XT", 51),
    (r"\brx\s*5700\s*xt\b", "RX 5700 XT", 55),
]

CPU_RULES = [
    (r"\b5800x3d\b", "Ryzen 7 5800X3D", 100), (r"\b5700x3d\b", "Ryzen 7 5700X3D", 96),
    (r"\b7800x3d\b", "Ryzen 7 7800X3D", 125), (r"\b9800x3d\b", "Ryzen 7 9800X3D", 135),
    (r"\b5700x\b", "Ryzen 7 5700X", 82), (r"\b5600x\b", "Ryzen 5 5600X", 79),
    (r"\b5600g\b", "Ryzen 5 5600G", 68), (r"\b5600\b", "Ryzen 5 5600", 76),
    (r"\b3600x\b", "Ryzen 5 3600X", 59), (r"\b3600\b", "Ryzen 5 3600", 56),
    (r"\bi5[- ]?14600k[f]?\b", "Core i5-14600K", 112), (r"\bi5[- ]?13600k[f]?\b", "Core i5-13600K", 105),
    (r"\bi5[- ]?12600k[f]?\b", "Core i5-12600K", 91), (r"\bi5[- ]?12400f?\b", "Core i5-12400", 81),
    (r"\bi5[- ]?12100f?\b", "Core i5-12100", 72), (r"\bi5[- ]?11400f?\b", "Core i5-11400", 70),
    (r"\bi5[- ]?10400f?\b", "Core i5-10400", 65), (r"\bi5[- ]?9600k[f]?\b", "Core i5-9600K", 59),
    (r"\bi5[- ]?8600k\b", "Core i5-8600K", 53), (r"\bi9[- ]?10900k?\b", "Core i9-10900", 79),
    (r"\bi9[- ]?9900k[f]?\b", "Core i9-9900K", 76), (r"\bi7[- ]?12700k?\b", "Core i7-12700", 98),
    (r"\bi7[- ]?11700k?\b", "Core i7-11700", 79), (r"\bi7[- ]?10700k?\b", "Core i7-10700", 72),
    (r"\bi7[- ]?9700k?\b", "Core i7-9700", 67), (r"\bi7[- ]?8700k?\b", "Core i7-8700", 61),
]

@dataclass
class Candidate:
    listing_id: str
    url: str
    title: str
    ask_t0: int
    ask_t1: int
    disposed: bool
    trade_type: str | None
    gpu: str
    gpu_score: int
    cpu: str
    cpu_score: int
    performance_class: str
    source_queries: list[str]
    location: str | None = None


def amount(price: Any) -> int | None:
    if isinstance(price, (int, float)):
        return int(price)
    if isinstance(price, dict):
        for k in ("amount", "value", "price"):
            v = price.get(k)
            if isinstance(v, (int, float)):
                return int(v)
    if isinstance(price, str):
        nums = re.sub(r"[^0-9]", "", price)
        return int(nums) if nums else None
    return None


def first_match(text: str, rules: list[tuple[str, str, int]]) -> tuple[str, int]:
    low = text.lower()
    for pat, label, score in rules:
        if re.search(pat, low, flags=re.I):
            return label, score
    return "Ukendt", 0


def perf_class(gpu_score: int, cpu_score: int) -> str:
    if gpu_score < 50 or cpu_score < 50:
        return "UNDER MINIMUM"
    if gpu_score >= 90 and cpu_score >= 76:
        return "OVERKILL"
    if gpu_score >= 65 and cpu_score >= 60:
        return "SWEET SPOT"
    return "ACCEPTABLE"


def get_json(session: requests.Session, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    r = session.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def regression_gate(session: requests.Session) -> dict[str, Any]:
    data = get_json(session, ITEM_URL.format(id=REGRESSION_ID))
    item = data.get("itemData") or {}
    price = amount(item.get("price"))
    title = item.get("title")
    disposed = bool(item.get("disposed"))
    ok = bool(title and price is not None and price != 2000 and str(REGRESSION_ID) in ITEM_URL.format(id=REGRESSION_ID))
    return {"ok": ok, "listing_id": REGRESSION_ID, "title": title, "price": price, "disposed": disposed, "keys": list(item.keys())}


def collect_t0(session: requests.Session) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for q in QUERIES:
        try:
            data = get_json(session, SEARCH_API, {"q": q, "sort": "PRICE_ASC"})
        except Exception as e:
            print(f"search failed {q}: {e}")
            continue
        docs = data.get("docs") or []
        for d in docs:
            lid = str(d.get("id") or d.get("listingId") or d.get("itemId") or "")
            title = str(d.get("heading") or d.get("title") or "")
            p = amount(d.get("price"))
            if not lid or not title or p is None:
                continue
            row = found.setdefault(lid, {"id": lid, "title": title, "price": p, "url": d.get("url") or ITEM_URL.format(id=lid), "queries": []})
            row["queries"].append(q)
            if p < row["price"]:
                row["price"] = p
        time.sleep(0.08)
    return found


def promising_t0(rows: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows.values():
        gpu, gs = first_match(r["title"], GPU_RULES)
        # Unknown CPU is allowed at discovery; detail text may reveal it.
        if gs >= 50 and 500 <= r["price"] <= 15000:
            r = dict(r)
            r["gpu_t0"] = gpu
            r["gpu_score_t0"] = gs
            out.append(r)
    out.sort(key=lambda x: (x["price"], -x["gpu_score_t0"]))
    return out[:80]


def verify_t1(session: requests.Session, rows: list[dict[str, Any]]) -> tuple[list[Candidate], list[dict[str, Any]]]:
    good: list[Candidate] = []
    rejected: list[dict[str, Any]] = []
    for r in rows:
        lid = r["id"]
        try:
            data = get_json(session, ITEM_URL.format(id=lid))
            item = data.get("itemData") or {}
            title = str(item.get("title") or r["title"])
            desc = str(item.get("description") or "")
            text = title + "\n" + desc
            p1 = amount(item.get("price"))
            disposed = bool(item.get("disposed"))
            if p1 is None or disposed:
                rejected.append({"id": lid, "reason": "missing T1 price or disposed", "t0": r["price"], "t1": p1, "disposed": disposed})
                continue
            gpu, gs = first_match(text, GPU_RULES)
            cpu, cs = first_match(text, CPU_RULES)
            pc = perf_class(gs, cs)
            if gs == 0 or cs == 0:
                rejected.append({"id": lid, "reason": "CPU/GPU not confidently parsed", "title": title, "t1": p1, "gpu": gpu, "cpu": cpu})
                continue
            trade = item.get("tradeType") or item.get("trade_type") or item.get("adViewTypeLabel")
            loc = item.get("location")
            if isinstance(loc, dict):
                loc = loc.get("name") or loc.get("city") or json.dumps(loc, ensure_ascii=False)[:160]
            good.append(Candidate(
                listing_id=lid, url=ITEM_URL.format(id=lid), title=title,
                ask_t0=int(r["price"]), ask_t1=int(p1), disposed=disposed,
                trade_type=str(trade) if trade is not None else None,
                gpu=gpu, gpu_score=gs, cpu=cpu, cpu_score=cs,
                performance_class=pc, source_queries=sorted(set(r["queries"])),
                location=str(loc) if loc is not None else None,
            ))
        except Exception as e:
            rejected.append({"id": lid, "reason": f"T1 fetch failed: {e}"})
        time.sleep(0.08)
    return good, rejected


def markdown(report: dict[str, Any]) -> str:
    lines = ["# DBA WoW-PC verified price report", "", f"Generated: {report['generated_at']}", ""]
    rg = report["regression_gate"]
    lines += [f"Regression 24247594: **{'PASS' if rg['ok'] else 'FAIL'}** — {rg.get('price')} DKK — disposed={rg.get('disposed')}", ""]
    if not report["gate_passed"]:
        lines += ["## PRICE DATA GATE FAILED — INGEN VERIFICERET PRISRANGERING", ""]
        return "\n".join(lines)
    lines += [f"Structured T0 records: {report['counts']['t0_unique']}", f"T1 verified ranked records: {report['counts']['ranked']}", ""]
    lines += ["| Rank | ASK | Class | GPU | CPU | Listing |", "|---:|---:|---|---|---|---|"]
    for i, c in enumerate(report["ranked"][:20], 1):
        title = c["title"].replace("|", "/")
        lines.append(f"| {i} | {c['ask_t1']} kr. | {c['performance_class']} | {c['gpu']} | {c['cpu']} | [{title}]({c['url']}) |")
    return "\n".join(lines) + "\n"


def main() -> None:
    session = requests.Session()
    generated = datetime.now(timezone.utc).isoformat()
    try:
        rg = regression_gate(session)
    except Exception as e:
        rg = {"ok": False, "error": repr(e), "listing_id": REGRESSION_ID}

    if not rg.get("ok"):
        report = {"generated_at": generated, "gate_passed": False, "regression_gate": rg, "counts": {"t0_unique": 0, "ranked": 0}, "ranked": []}
    else:
        rows = collect_t0(session)
        shortlist = promising_t0(rows)
        verified, rejected = verify_t1(session, shortlist)
        rankable = [c for c in verified if c.performance_class != "UNDER MINIMUM"]
        rankable.sort(key=lambda c: (c.ask_t1, {"SWEET SPOT": 0, "ACCEPTABLE": 1, "OVERKILL": 2}.get(c.performance_class, 9), -c.gpu_score, -c.cpu_score))
        report = {
            "generated_at": generated,
            "gate_passed": True,
            "regression_gate": rg,
            "counts": {"t0_unique": len(rows), "t0_promising": len(shortlist), "t1_verified_specs": len(verified), "ranked": len(rankable), "rejected": len(rejected)},
            "ranked": [asdict(c) for c in rankable],
            "rejected": rejected,
        }

    Path("results").mkdir(exist_ok=True)
    Path("results/report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    Path("results/report.md").write_text(markdown(report), encoding="utf-8")
    print(markdown(report))


if __name__ == "__main__":
    main()
