from __future__ import annotations

import json
import re
from pathlib import Path

import dba_browser_v2 as v2

GPU_CONTEXT = re.compile(r"\b(?:gpu|grafikkort|geforce|radeon|rtx|gtx|rx)\b", re.I)
CPU_CONTEXT = re.compile(r"\b(?:cpu|processor|ryzen|intel|core\s+i[3579]|i[3579][- ]?\d{4,5})\b", re.I)
BOARD_MODEL = re.compile(
    r"\b(?:asus|msi|gigabyte|asrock)?\s*(?:prime\s+|tuf\s+|aorus\s+|pro\s+|gaming\s+)?"
    r"(?:a320m|a520m|a620m|b350m|b365m|b450m|b460m|b550m|b560m|b650m|b660m|b760m|"
    r"h310m|h370m|h410m|h510m|h610m|z370m|z390m|z490m|z590m|z690m|z790m|"
    r"a320|a520|a620|b350|b365|b450|b460|b550|b560|b650|b660|b760|h310|h370|h410|h510|h610|z370|z390|z490|z590|z690|z790)"
    r"[a-z0-9 .+/_-]*",
    re.I,
)
MATX = re.compile(r"\b(?:micro[- ]?atx|m[- ]?atx|matx|[abhqz][1-9]\d{2}m(?:[-\s/]|\b))", re.I)
ITX = re.compile(r"\b(?:mini[- ]?itx|miniitx|m[- ]?itx|itx)\b", re.I)
FULL_ATX_BOARD = re.compile(
    r"\b(?:bundkort|motherboard|mainboard)\s*[:=-]?\s*(?:e[- ]?atx|atx)\b|"
    r"\b(?:e[- ]?atx|atx)\s+(?:bundkort|motherboard|mainboard)\b",
    re.I,
)
# Exact model-family evidence is stronger than UNKNOWN. These patterns only encode
# motherboard families whose form factor is part of the model identity/specification.
KNOWN_MATX_BOARD = re.compile(
    r"\b(?:[abhqz][1-9]\d{2}m\b|aorus\s+(?:pro|elite)\s*m\b|mortar\b|bazooka\b|"
    r"tuf\s+gaming\s+[abhqz][1-9]\d{2}m(?:[-\s]|$)|prime\s+[abhqz][1-9]\d{2}m(?:[-\s]|$))",
    re.I,
)
KNOWN_ITX_BOARD = re.compile(r"\b(?:[abhqz][1-9]\d{2}i\b|aorus\s+(?:pro|ultra)\s+(?:ax\s+)?itx\b|gaming[- ]?itx)\b", re.I)
KNOWN_ATX_BOARD = re.compile(
    r"\b(?:b450\s+aorus\s+elite(?:\s+v2)?|b450\s+aorus\s+pro(?:\s+wifi)?|"
    r"b550\s+aorus\s+elite(?:\s+(?:v2|ax\s+v2))?|b550\s+aorus\s+pro(?:\s+v2)?|"
    r"(?:b450|b550|b650|b660|b760|z390|z490|z590|z690|z790)\s+tomahawk(?:\s+max)?|"
    r"tuf\s+gaming\s+(?:b450|b550|b650|b660|b760|z690|z790)-plus|"
    r"prime\s+(?:b450|b550|b650|b660|b760|z690|z790)-plus)\b",
    re.I,
)
RAM = re.compile(r"\b(?:(\d{1,2})\s*gb\s*(?:ddr([345]))|ddr([345])\s*(\d{1,2})\s*gb|(?:2\s*x\s*(8|16|32)\s*gb))\b", re.I)
STORAGE = re.compile(r"\b(?:(\d{3,4})\s*gb|([1-8])\s*tb)\s*(nvme|m\.?2|ssd|hdd)\b", re.I)
PSU = re.compile(r"\b((?:corsair|seasonic|be\s*quiet!?|evga|cooler\s*master|nzxt|asus|msi|fsp|super\s*flower)[^\n,;]{0,55}?([5-9]\d{2}|1\d{3})\s*w)\b", re.I)
CASE = re.compile(r"\b(?:kabinet|case)\s*[:=-]?\s*([^\n,;]{3,70})", re.I)
OEM = re.compile(r"\b(?:hp\s+(?:omen|pavilion)|lenovo\s+legion|acer\s+(?:nitro|predator)|dell\s+(?:g5|xps|alienware))\b", re.I)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _lines(title: str, description: str) -> list[str]:
    raw = [title] + re.split(r"[\r\n]+", description or "")
    return [_norm(x) for x in raw if _norm(x)]


def _evidence(value, source: str, evidence: str, confidence: str = "VERIFIED") -> dict:
    return {"value": value, "confidence": confidence, "source": source, "evidence": _norm(evidence)[:220]}


def _extract_gpu(lines: list[str]) -> tuple[dict, int]:
    for source, line in [("TITLE", lines[0])] + [("DESCRIPTION", x) for x in lines[1:]]:
        gpu, score = v2.match_rule(line, v2.GPU_RULES)
        if score >= 50 and GPU_CONTEXT.search(line):
            return _evidence(gpu, source, line), score
    text = "\n".join(lines)
    gpu, score = v2.match_rule(text, v2.GPU_RULES)
    return (_evidence(gpu, "FULL_TEXT", gpu, "INFERRED") if score >= 50 else _evidence(None, "NONE", "", "UNKNOWN")), score


def _cpu_rule_matches(line: str):
    for pat, label, score in v2.CPU_RULES:
        for m in re.finditer(pat, line, re.I):
            yield m, label, score


def _extract_cpu(lines: list[str]) -> tuple[dict, int]:
    for source, line in [("TITLE", lines[0])] + [("DESCRIPTION", x) for x in lines[1:]]:
        for m, label, score in _cpu_rule_matches(line):
            prefix = line[max(0, m.start()-14):m.start()].lower()
            if re.search(r"(?:\brx|radeon)\s*$", prefix):
                continue
            if CPU_CONTEXT.search(line) or re.search(r"\b(?:ryzen|intel|core|cpu|processor)\b", line, re.I):
                return _evidence(label, source, line), score
    return _evidence(None, "NONE", "", "UNKNOWN"), 0


def _extract_board(lines: list[str]) -> dict:
    for source, line in [("TITLE", lines[0])] + [("DESCRIPTION", x) for x in lines[1:]]:
        m = BOARD_MODEL.search(line)
        if m:
            return _evidence(_norm(m.group(0)), source, line)
    return _evidence(None, "NONE", "", "UNKNOWN")


def _board_fit(lines: list[str], board: dict) -> dict:
    text = "\n".join(lines)
    ev = board.get("evidence") or ""
    candidate = f"{board.get('value') or ''} {ev}"
    if KNOWN_ITX_BOARD.search(candidate) or ITX.search(candidate):
        return _evidence("COMPATIBLE", board.get("source", "FULL_TEXT"), ev or candidate)
    if KNOWN_MATX_BOARD.search(candidate) or MATX.search(candidate):
        return _evidence("COMPATIBLE", board.get("source", "FULL_TEXT"), ev or candidate)
    if KNOWN_ATX_BOARD.search(candidate):
        m = KNOWN_ATX_BOARD.search(candidate)
        return _evidence("INCOMPATIBLE", board.get("source", "DESCRIPTION"), m.group(0), "VERIFIED")
    if FULL_ATX_BOARD.search(text):
        m = FULL_ATX_BOARD.search(text)
        return _evidence("INCOMPATIBLE", "FULL_TEXT", m.group(0) if m else "ATX motherboard")
    return _evidence("UNVERIFIED", "FULL_TEXT", "Motherboard model/form factor is not proven strongly enough for Z20", "UNKNOWN")


def _extract_ram(lines: list[str]) -> dict:
    for source, line in [("TITLE", lines[0])] + [("DESCRIPTION", x) for x in lines[1:]]:
        m = RAM.search(line)
        if m:
            cap = next((int(x) for x in (m.group(1), m.group(4)) if x), None)
            if m.group(5): cap = int(m.group(5)) * 2
            gen = next((x for x in (m.group(2), m.group(3)) if x), None)
            value = f"{cap} GB" + (f" DDR{gen}" if gen else "") if cap else _norm(m.group(0))
            return _evidence(value, source, line)
    return _evidence(None, "NONE", "", "UNKNOWN")


def _extract_storage(lines: list[str]) -> list[dict]:
    out = []
    for source, line in [("TITLE", lines[0])] + [("DESCRIPTION", x) for x in lines[1:]]:
        for m in STORAGE.finditer(line):
            size = f"{m.group(1)} GB" if m.group(1) else f"{m.group(2)} TB"
            out.append(_evidence(f"{size} {m.group(3).upper()}", source, line))
    seen = set(); dedup = []
    for x in out:
        if x["value"].lower() in seen: continue
        seen.add(x["value"].lower()); dedup.append(x)
    return dedup[:4]


def _extract_psu(lines: list[str]) -> dict:
    for source, line in [("TITLE", lines[0])] + [("DESCRIPTION", x) for x in lines[1:]]:
        m = PSU.search(line)
        if m:
            return _evidence(_norm(m.group(1)), source, line)
    return _evidence(None, "NONE", "", "UNKNOWN")


def _extract_case(lines: list[str]) -> dict:
    for source, line in [("TITLE", lines[0])] + [("DESCRIPTION", x) for x in lines[1:]]:
        m = CASE.search(line)
        if m:
            return _evidence(_norm(m.group(1)), source, line)
    return _evidence(None, "NONE", "", "UNKNOWN")


def _upgradeability(cpu: str | None, board: str | None, text: str) -> dict:
    t = f"{board or ''} {text}".lower()
    if any(x in t for x in ("b650", "a620", "x670", "am5")) or any(x in (cpu or "") for x in ("7500F","7600","7700","7800X3D","9600X","9700X","9800X3D")):
        return {"class": "EXCELLENT", "reason": "AM5 platform has the strongest documented upgrade path."}
    if any(x in t for x in ("b450", "b550", "x570", "am4")):
        return {"class": "GOOD", "reason": "AM4 supports strong X3D end-state upgrades."}
    if any(x in t for x in ("b660", "b760", "z690", "z790", "lga1700")):
        return {"class": "GOOD", "reason": "LGA1700 offers useful CPU upgrade options."}
    if any(x in t for x in ("b560", "h510", "lga1200")) or any(x in (cpu or "") for x in ("10400","10700","11400","11700")):
        return {"class": "LIMITED", "reason": "LGA1200 is effectively end-of-line."}
    if any(x in t for x in ("b365", "z390", "h370")) or any(x in (cpu or "") for x in ("8600","8700","9600","9700")):
        return {"class": "POOR", "reason": "Legacy LGA1151 has little meaningful CPU upgrade headroom."}
    return {"class": "UNVERIFIED", "reason": "Platform/socket is not proven by the listing."}


def analyze_t1(t1: dict) -> dict:
    title = t1.get("title") or ""
    description = t1.get("description") or ""
    lines = _lines(title, description)
    gpu, gpu_score = _extract_gpu(lines)
    cpu, cpu_score = _extract_cpu(lines)
    board = _extract_board(lines)
    board_fit = _board_fit(lines, board)
    ram = _extract_ram(lines)
    storage = _extract_storage(lines)
    psu = _extract_psu(lines)
    case = _extract_case(lines)
    full_text = "\n".join(lines)
    is_laptop = bool(v2.LAPTOP_RE.search(full_text))
    oem = _norm(OEM.search(full_text).group(0)) if OEM.search(full_text) else None
    pclass = v2.performance_class(gpu_score, cpu_score) if gpu_score and cpu_score else "UNRESOLVED"
    upg = _upgradeability(cpu.get("value"), board.get("value"), full_text)

    missing = []
    for key, obj in (("CPU", cpu), ("GPU", gpu), ("motherboard", board), ("RAM", ram), ("PSU", psu)):
        if not obj.get("value"): missing.append(key)

    routes = []
    if cpu_score >= 50 and gpu_score >= 50 and pclass != "UNDER MINIMUM":
        routes.append({"route": "BUY_AND_USE_AS_IS", "status": "READY", "rationale": "Complete system clears the WoW performance gate from listing-proven CPU/GPU."})
    if not is_laptop:
        if board_fit["value"] == "COMPATIBLE":
            routes.append({"route": "DIRECT_Z20_TRANSFER", "status": "READY" if psu.get("value") else "NEEDS_ONE_CHECK", "rationale": "Motherboard is listing-proven mATX/ITX; PSU is the remaining fit check." if not psu.get("value") else "Motherboard and standard PSU evidence support a direct transplant route."})
        elif board_fit["value"] == "INCOMPATIBLE":
            routes.append({"route": "Z20_DONOR_WITH_NEW_PLATFORM", "status": "VIABLE", "rationale": "Current motherboard is full-size ATX; reuse GPU/storage and other compatible parts, replace platform/motherboard for Z20."})
        else:
            routes.append({"route": "Z20_TRANSFER_NEEDS_BOARD_INFO", "status": "HIGH_POTENTIAL", "rationale": "Price/performance can still be attractive; motherboard form factor is the key missing fact."})
    if gpu_score >= 60:
        routes.append({"route": "GPU_DONOR_OPTION", "status": "VIABLE", "rationale": "GPU is valuable enough to remain useful even if the platform cannot transfer directly."})

    question = None
    if board_fit["value"] == "UNVERIFIED" and not is_laptop:
        question = "Hvilket bundkort sidder der i computeren (mærke og model)?"
    elif not psu.get("value") and not is_laptop:
        question = "Hvilken strømforsyning sidder der i computeren (mærke/model og watt)?"

    return {
        "source": "T1_LISTING_TITLE_DESCRIPTION_METADATA",
        "cpu": cpu, "cpu_score": cpu_score,
        "gpu": gpu, "gpu_score": gpu_score,
        "motherboard": board, "motherboard_z20_fit": board_fit,
        "ram": ram, "storage": storage, "psu": psu, "case": case,
        "oem_family": oem,
        "performance_class": pclass,
        "upgradeability": upg,
        "missing_facts": missing,
        "seller_question": question,
        "routes": routes,
        "description_available": bool(description.strip()),
    }


def enrich_result_file(path: str | Path, t1_cache: dict[str, dict]) -> dict:
    p = Path(path)
    doc = json.loads(p.read_text(encoding="utf-8"))
    enriched = 0
    for section in ("ranked", "potential_sweet_spots_unresolved"):
        for row in doc.get(section) or []:
            t1 = t1_cache.get(str(row.get("listing_id")))
            if not t1:
                continue
            intel = analyze_t1(t1)
            row["listing_intelligence"] = intel
            if intel["cpu"].get("confidence") == "VERIFIED" and intel["cpu"].get("value"):
                row["cpu"] = intel["cpu"]["value"]; row["cpu_score"] = intel["cpu_score"]
            if intel["gpu"].get("confidence") == "VERIFIED" and intel["gpu"].get("value"):
                row["gpu"] = intel["gpu"]["value"]; row["gpu_score"] = intel["gpu_score"]
            enriched += 1
    doc["listing_intelligence"] = {
        "version": "V2",
        "policy": "Description-aware hardware extraction with model-aware motherboard form-factor evidence. Never used as price evidence; ASK remains same-object T1 verified.",
        "enriched_records": enriched,
        "cached_t1_records": len(t1_cache),
    }
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc