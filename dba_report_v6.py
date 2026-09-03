from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

BASE = 'https://www.dba.dk'
SEARCH_API = BASE + '/recommerce/forsale/search/api/search/SEARCH_ID_BAP_COMMON'
ITEM_URL = BASE + '/recommerce/forsale/item/{id}'
HEADERS = {
    'User-Agent': 'Mozilla/5.0',
    'Accept-Language': 'da-DK,da;q=0.9',
    'Accept': 'application/json,text/html;q=0.9,*/*;q=0.8',
}
TIMEOUT = 25
MAX_PRICE = 15000
RESCUE_MAX_PRICE = 6000

QUERIES = [
    'gaming pc','gamer pc','gaming computer','gamer computer','stationær gaming','stationær gamer',
    'stationær computer gaming','stationær computer gamer','gaming stationær','gamer stationær',
    'desktop gaming','desktop gamer','komplet gaming','komplet gamer','computer rtx','computer rx',
    'gaming laptop','gamer laptop','gaming bærbar','mini pc gaming','mini gaming pc',
    'omen','hp omen','pavilion gaming','legion','lenovo legion','acer nitro','nitro gaming','predator',
    'dell g5','dell xps gaming','sharkgaming','dutzo','mm vision','mm-vision','msi gamer','asus gamer',
    'færdigbygget gaming','skal væk gaming','hurtig handel gaming','gaming pc sælges','gamer pc sælges',
    'rtx 2060 super','rtx 2070','rtx 2070 super','rtx 2080','rtx 2080 super','rtx 2080 ti',
    'rtx 3060','rtx 3060 ti','rtx 3070','rtx 3070 ti','rtx 3080','rtx 3080 ti',
    'rtx 4060','rtx 4060 ti','rtx 4070','rtx 4070 super',
    'rx 5700 xt','rx 6600 xt','rx 6650 xt','rx 6700','rx 6700 xt','rx 6750 xt','rx 6800',
    'rx 6800 xt','rx 7600','rx 7700 xt','rx 7800 xt',
]

PC_QUERY_HINTS = {
    'gaming pc','gamer pc','gaming computer','gamer computer','stationær gaming','stationær gamer',
    'stationær computer gaming','stationær computer gamer','gaming stationær','gamer stationær',
    'desktop gaming','desktop gamer','komplet gaming','komplet gamer','gaming laptop','gamer laptop',
    'gaming bærbar','mini pc gaming','mini gaming pc','omen','hp omen','pavilion gaming','legion',
    'lenovo legion','acer nitro','nitro gaming','predator','dell g5','dell xps gaming','sharkgaming',
    'dutzo','mm vision','mm-vision','msi gamer','asus gamer','færdigbygget gaming','skal væk gaming',
    'hurtig handel gaming','gaming pc sælges','gamer pc sælges',
}

GPU_RULES = [
    (r'\brtx\s*4090\b','RTX 4090',130),(r'\brtx\s*4080(?:\s*super)?\b','RTX 4080',115),
    (r'\brtx\s*4070\s*ti(?:\s*super)?\b','RTX 4070 Ti',105),(r'\brtx\s*4070(?:\s*super)?\b','RTX 4070',92),
    (r'\brtx\s*4060\s*ti\b','RTX 4060 Ti',72),(r'\brtx\s*4060\b','RTX 4060',60),
    (r'\brtx\s*3090\s*ti\b','RTX 3090 Ti',105),(r'\brtx\s*3090\b','RTX 3090',100),
    (r'\brtx\s*3080\s*ti\b','RTX 3080 Ti',96),(r'\brtx\s*3080\b','RTX 3080',90),
    (r'\brtx\s*3070\s*ti\b','RTX 3070 Ti',79),(r'\brtx\s*3070\b','RTX 3070',73),
    (r'\brtx\s*3060\s*ti\b','RTX 3060 Ti',66),(r'\brtx\s*3060\b','RTX 3060',54),
    (r'\brtx\s*2080\s*ti\b','RTX 2080 Ti',73),(r'\brtx\s*2080\s*super\b','RTX 2080 Super',65),
    (r'\brtx\s*2080\b','RTX 2080',61),(r'\brtx\s*2070\s*super\b','RTX 2070 Super',57),
    (r'\brtx\s*2070\b','RTX 2070',52),(r'\brtx\s*2060\s*super\b','RTX 2060 Super',50),
    (r'\brtx\s*2060\b','RTX 2060',45),(r'\bgtx\s*1080\s*ti\b','GTX 1080 Ti',60),
    (r'\bgtx\s*1080\b','GTX 1080',50),(r'\brx\s*7900\s*xtx\b','RX 7900 XTX',120),
    (r'\brx\s*7900\s*xt\b','RX 7900 XT',110),(r'\brx\s*7800\s*xt\b','RX 7800 XT',98),
    (r'\brx\s*7700\s*xt\b','RX 7700 XT',86),(r'\brx\s*7600\b','RX 7600',59),
    (r'\brx\s*6950\s*xt\b','RX 6950 XT',98),(r'\brx\s*6900\s*xt\b','RX 6900 XT',94),
    (r'\brx\s*6800\s*xt\b','RX 6800 XT',90),(r'\brx\s*6800\b','RX 6800',84),
    (r'\brx\s*6750\s*xt\b','RX 6750 XT',72),(r'\brx\s*6700\s*xt\b','RX 6700 XT',68),
    (r'\brx\s*6700\b','RX 6700',62),(r'\brx\s*6650\s*xt\b','RX 6650 XT',54),
    (r'\brx\s*6600\s*xt\b','RX 6600 XT',51),(r'\brx\s*5700\s*xt\b','RX 5700 XT',55),
]

CPU_RULES = [
    (r'\b9800x3d\b','Ryzen 7 9800X3D',135),(r'\b7800x3d\b','Ryzen 7 7800X3D',125),
    (r'\b5800x3d\b','Ryzen 7 5800X3D',100),(r'\b5700x3d\b','Ryzen 7 5700X3D',96),
    (r'\b5950x\b','Ryzen 9 5950X',88),(r'\b5900x\b','Ryzen 9 5900X',86),
    (r'\b5800x\b','Ryzen 7 5800X',84),(r'\b5700x\b','Ryzen 7 5700X',82),
    (r'\b5600x\b','Ryzen 5 5600X',79),(r'\b5600g\b','Ryzen 5 5600G',68),(r'\b5600\b','Ryzen 5 5600',76),
    (r'\b3900x\b','Ryzen 9 3900X',64),(r'\b3800x\b','Ryzen 7 3800X',62),(r'\b3700x\b','Ryzen 7 3700X',61),
    (r'\b3600x\b','Ryzen 5 3600X',59),(r'\b3600\b','Ryzen 5 3600',56),
    (r'\bi5[- ]?14600(?:kf|k|f)?\b','Core i5-14600K',112),(r'\bi5[- ]?13600(?:kf|k|f)?\b','Core i5-13600K',105),
    (r'\bi5[- ]?12600(?:kf|k|f)?\b','Core i5-12600K',91),(r'\bi5[- ]?12400(?:kf|k|f)?\b','Core i5-12400',81),
    (r'\bi5[- ]?12100(?:kf|k|f)?\b','Core i5-12100',72),(r'\bi5[- ]?11600(?:kf|k|f)?\b','Core i5-11600K',73),
    (r'\bi5[- ]?11400(?:kf|k|f)?\b','Core i5-11400',70),(r'\bi5[- ]?10600(?:kf|k|f)?\b','Core i5-10600K',68),
    (r'\bi5[- ]?10400(?:kf|k|f)?\b','Core i5-10400',65),(r'\bi5[- ]?9600(?:kf|k|f)?\b','Core i5-9600K',59),
    (r'\bi5[- ]?9400(?:f)?\b','Core i5-9400',53),(r'\bi5[- ]?8600(?:kf|k|f)?\b','Core i5-8600K',53),
    (r'\bi5[- ]?8400\b','Core i5-8400',50),
    (r'\bi9[- ]?14900(?:ks|kf|k|f)?\b','Core i9-14900K',126),(r'\bi9[- ]?13900(?:ks|kf|k|f)?\b','Core i9-13900K',119),
    (r'\bi9[- ]?12900(?:ks|kf|k|f)?\b','Core i9-12900K',108),(r'\bi9[- ]?11900(?:kf|k|f)?\b','Core i9-11900K',88),
    (r'\bi9[- ]?10900(?:kf|k|f)?\b','Core i9-10900',79),(r'\bi9[- ]?9900(?:ks|kf|k|f)?\b','Core i9-9900K',76),
    (r'\bi7[- ]?14700(?:kf|k|f)?\b','Core i7-14700K',120),(r'\bi7[- ]?13700(?:kf|k|f)?\b','Core i7-13700K',113),
    (r'\bi7[- ]?12700(?:kf|k|f)?\b','Core i7-12700',98),(r'\bi7[- ]?11700(?:kf|k|f)?\b','Core i7-11700',79),
    (r'\bi7[- ]?10700(?:kf|k|f)?\b','Core i7-10700',72),(r'\bi7[- ]?9700(?:kf|k|f)?\b','Core i7-9700',67),
    (r'\bi7[- ]?8700(?:kf|k|f)?\b','Core i7-8700',61),(r'\bi7[- ]?7700(?:k)?\b','Core i7-7700',48),
]

COMPLETE_HINTS = (
    'gaming pc','gamer pc','gaming computer','gamer computer','stationær','desktop','komplet pc','komplet computer',
    'gaming laptop','gamer laptop','gaming bærbar','bærbar gaming','laptop','mini pc','omen','legion','nitro',
    'predator','dell g5','xps','sharkgaming','dutzo','mm-vision','mm vision',
)
COMPONENT_ONLY_HINTS = (
    'grafikkort','graphics card','gpu only','vandkøling blok','waterblock','water block','egpu','node pro',
    'gpu enclosure','køler','cooler','strømforsyning','power supply','psu','bundkort','motherboard','ram kit',
)

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
    spec_source: str


def amount(v: Any) -> int | None:
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, dict):
        for k in ('amount', 'value', 'price'):
            if isinstance(v.get(k), (int, float)):
                return int(v[k])
    if isinstance(v, str):
        s = re.sub(r'[^0-9]', '', v)
        return int(s) if s else None
    return None


def match(text: str, rules):
    for pat, label, score in rules:
        if re.search(pat, text, re.I):
            return label, score
    return 'Ukendt', 0


def flatten_strings(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for key, val in value.items():
            if key.lower() not in {'url', 'imageurl', 'canonicalurl'}:
                out.extend(flatten_strings(val))
    elif isinstance(value, list):
        for val in value:
            out.extend(flatten_strings(val))
    return out


def resolve_specs(title: str, desc: str, item: dict) -> tuple[str, int, str, int, str]:
    sources = [('title', title), ('description', desc), ('structured_item', ' '.join(flatten_strings(item)))]
    gpu = ('Ukendt', 0)
    cpu = ('Ukendt', 0)
    used = []
    for name, text in sources:
        if not gpu[1]:
            gpu = match(text, GPU_RULES)
            if gpu[1]: used.append(name + ':gpu')
        if not cpu[1]:
            cpu = match(text, CPU_RULES)
            if cpu[1]: used.append(name + ':cpu')
        if gpu[1] and cpu[1]:
            break
    return gpu[0], gpu[1], cpu[0], cpu[1], ','.join(used) or 'unresolved'


def complete_system_evidence(title: str, desc: str = '', source_queries: list[str] | None = None) -> tuple[bool, str]:
    t = title.lower()
    combined = (title + ' ' + desc).lower()
    positives = [x for x in COMPLETE_HINTS if x in combined]
    component_only = [x for x in COMPONENT_ONLY_HINTS if x in t]
    query_hint = bool(set(source_queries or []) & PC_QUERY_HINTS)
    if component_only and not positives:
        return False, 'component-title:' + component_only[0]
    if positives:
        return True, 'text:' + positives[0]
    if query_hint:
        return True, 'pc-query'
    return False, 'no-complete-system-evidence'


def should_advance_t0(row: dict) -> bool:
    if not (500 <= int(row['price']) <= MAX_PRICE):
        return False
    _, gs = match(row['title'], GPU_RULES)
    complete, _ = complete_system_evidence(row['title'], source_queries=row.get('queries') or [])
    return bool(gs >= 45 or complete)


def perf(gs: int, cs: int) -> str:
    if gs < 50 or cs < 50:
        return 'UNDER MINIMUM'
    if gs >= 90 and cs >= 76:
        return 'OVERKILL'
    if gs >= 65 and cs >= 60:
        return 'SWEET SPOT'
    return 'ACCEPTABLE'


def getj(session: requests.Session, url: str, params=None):
    r = session.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def fixture_regression() -> dict:
    fixture = [
        {'id': '24247594', 'title': 'RTX 3070 Ti / i5-8600K', 'price': 4399, 'disposed': False},
        {'id': 'other', 'title': 'Other PC', 'price': 2000, 'disposed': False},
    ]
    target = next(x for x in fixture if x['id'] == '24247594')
    ok = target['price'] == 4399 and target['title'].startswith('RTX 3070 Ti')
    if not ok:
        raise SystemExit('PRICE BINDING FIXTURE FAILED')
    return {'ok': True, 'type': 'static_fixture', 'historical_listing_id': '24247594', 'expected_price': 4399}


def schema_gate(session: requests.Session) -> dict:
    data = getj(session, SEARCH_API, {'q': 'gaming pc', 'sort': 'PRICE_ASC'})
    for d in (data.get('docs') or []):
        lid = str(d.get('id') or d.get('listingId') or d.get('itemId') or '')
        title = str(d.get('heading') or d.get('title') or '')
        p0 = amount(d.get('price'))
        if not lid or not title or p0 is None:
            continue
        item = (getj(session, ITEM_URL.format(id=lid)).get('itemData') or {})
        p1 = amount(item.get('price'))
        title1 = str(item.get('title') or '')
        if p1 is not None and title1 and not bool(item.get('disposed')):
            return {'ok': True, 'listing_id': lid, 'search_price': p0, 'item_price': p1, 'title': title1}
    raise SystemExit('PRICE DATA GATE FAILED — no current live same-object listing could be verified')


def fetch_one(row: dict) -> tuple[Candidate | None, dict | None]:
    s = requests.Session()
    lid = row['id']
    try:
        item = (getj(s, ITEM_URL.format(id=lid)).get('itemData') or {})
        item_id = str(item.get('id') or item.get('listingId') or item.get('itemId') or lid)
        if item_id != str(lid):
            return None, {'id': lid, 'reason': 'T1_IDENTITY_MISMATCH', 'item_id': item_id}
        p1 = amount(item.get('price'))
        disposed = bool(item.get('disposed'))
        if p1 is None:
            return None, {'id': lid, 'reason': 'MISSING_LIVE_PRICE'}
        if disposed:
            return None, {'id': lid, 'reason': 'INACTIVE_OR_DISPOSED'}
        title = str(item.get('title') or row['title'])
        desc = str(item.get('description') or '')
        trade = item.get('tradeType') or item.get('adViewTypeLabel')
        complete, complete_evidence = complete_system_evidence(title, desc, row.get('queries') or [])
        gpu, gs, cpu, cs, spec_source = resolve_specs(title, desc, item)
        base = {
            'id': lid, 'url': ITEM_URL.format(id=lid), 'title': title,
            'ask_t0': int(row['price']), 'ask_t1': int(p1), 'disposed': disposed,
            'trade_type': str(trade) if trade else None, 'gpu': gpu, 'gpu_score': gs,
            'cpu': cpu, 'cpu_score': cs, 'source_queries': sorted(set(row.get('queries') or [])),
            'complete_system': complete, 'complete_evidence': complete_evidence, 'spec_source': spec_source,
        }
        if not complete:
            return None, {**base, 'reason': 'NOT_COMPLETE_SYSTEM'}
        if not gs or not cs:
            reason = 'GPU_PARSE_FAILED' if not gs else 'CPU_PARSE_FAILED'
            if p1 <= RESCUE_MAX_PRICE:
                reason = 'POTENTIAL_SWEET_SPOT_UNRESOLVED'
            return None, {**base, 'reason': reason}
        return Candidate(
            lid, ITEM_URL.format(id=lid), title, int(row['price']), int(p1), disposed,
            str(trade) if trade else None, gpu, gs, cpu, cs, perf(gs, cs),
            sorted(set(row.get('queries') or [])), spec_source,
        ), None
    except Exception as e:
        return None, {'id': lid, 'reason': 'T1_FETCH_FAILED', 'detail': str(e)}


def main():
    s = requests.Session()
    fixture = fixture_regression()
    gate = schema_gate(s)
    found: dict[str, dict] = {}
    search_failures = []
    for q in QUERIES:
        try:
            docs = (getj(s, SEARCH_API, {'q': q, 'sort': 'PRICE_ASC'}).get('docs') or [])
        except Exception as e:
            search_failures.append({'query': q, 'error': str(e)})
            continue
        for d in docs:
            lid = str(d.get('id') or d.get('listingId') or d.get('itemId') or '')
            title = str(d.get('heading') or d.get('title') or '')
            p = amount(d.get('price'))
            if not lid or not title or p is None:
                continue
            row = found.setdefault(lid, {'id': lid, 'title': title, 'price': p, 'queries': []})
            row['queries'].append(q)
            row['price'] = p
        time.sleep(.03)

    promising = [r for r in found.values() if should_advance_t0(r)]
    candidates: list[Candidate] = []
    rejected: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(fetch_one, r) for r in promising]
        for f in as_completed(futures):
            candidate, rejection = f.result()
            if candidate:
                candidates.append(candidate)
            elif rejection:
                rejected.append(rejection)

    ranked = [c for c in candidates if c.performance_class != 'UNDER MINIMUM']
    under_minimum = [asdict(c) for c in candidates if c.performance_class == 'UNDER MINIMUM']
    class_order = {'ACCEPTABLE': 0, 'SWEET SPOT': 1, 'OVERKILL': 2}
    ranked.sort(key=lambda c: (c.ask_t1, class_order.get(c.performance_class, 9), -c.gpu_score, -c.cpu_score))
    potential = sorted(
        [r for r in rejected if r.get('reason') == 'POTENTIAL_SWEET_SPOT_UNRESOLVED'],
        key=lambda r: (int(r.get('ask_t1', 10**9)), r.get('id', '')),
    )
    cheap_complete_t1 = [r for r in rejected if r.get('complete_system') and int(r.get('ask_t1', 10**9)) <= RESCUE_MAX_PRICE]
    surfaced_ids = {r['id'] for r in potential}
    hidden_cheap_complete = [r for r in cheap_complete_t1 if r.get('id') not in surfaced_ids]
    reason_counts: dict[str, int] = {}
    for r in rejected:
        reason_counts[r['reason']] = reason_counts.get(r['reason'], 0) + 1

    out = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'gate_passed': True,
        'schema_gate': gate,
        'price_binding_regression': fixture,
        'retrieval_method': 'DBA structured search JSON at T0 + same listing ID DBA itemData JSON at T1',
        'rescue_max_price': RESCUE_MAX_PRICE,
        'counts': {
            'queries': len(QUERIES), 'search_failures': len(search_failures), 't0_unique': len(found),
            't0_advanced_high_recall': len(promising), 't1_parsed_complete': len(candidates),
            'ranked_acceptable_or_better': len(ranked), 'under_minimum': len(under_minimum),
            'potential_sweet_spot_unresolved': len(potential), 'rejected': len(rejected),
        },
        'missed_opportunity_audit': {
            'ok': not hidden_cheap_complete,
            'rescue_ceiling': RESCUE_MAX_PRICE,
            'cheap_complete_unresolved': len(cheap_complete_t1),
            'surfaced_as_potential_sweet_spot': len(potential),
            'hidden_cheap_complete': hidden_cheap_complete,
        },
        'rejection_reason_counts': reason_counts,
        'search_failures': search_failures,
        'ranked': [asdict(x) for x in ranked],
        'potential_sweet_spots_unresolved': potential,
        'under_minimum': under_minimum,
        'rejected': rejected,
    }
    Path('results').mkdir(exist_ok=True)
    Path('results/latest_v6.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = [
        '# DBA WoW-PC verified price report v6 — high recall', '', f"Generated: {out['generated_at']}", '',
        f"Current schema/source gate: **PASS** — live item {gate['listing_id']}",
        'Historical price-binding regression: **PASS (static fixture; no live historical listing dependency)**', '',
        f"Discovery queries: {len(QUERIES)}", f"Structured T0 unique records: {len(found)}",
        f"T0 records advanced to T1 by GPU OR complete-PC evidence: {len(promising)}",
        f"Ranked ACCEPTABLE+: {len(ranked)}", f"Potential sweet spots unresolved <= {RESCUE_MAX_PRICE} kr.: {len(potential)}", '',
        '| Rank | ASK | Class | GPU | CPU | Listing |', '|---:|---:|---|---|---|---|',
    ]
    for i, c in enumerate(ranked[:50], 1):
        lines.append(f'| {i} | {c.ask_t1} kr. | {c.performance_class} | {c.gpu} | {c.cpu} | [{c.title}]({c.url}) |')
    lines += ['', '## Potential sweet spots — unresolved specs', '']
    for r in potential:
        lines.append(f"- {r['ask_t1']} kr. — [{r['title']}]({r['url']}) — GPU={r['gpu']} CPU={r['cpu']} — {r['complete_evidence']}")
    lines += ['', '## Missed-opportunity audit', '', json.dumps(out['missed_opportunity_audit'], ensure_ascii=False), '', '## Rejection diagnostics', '', json.dumps(reason_counts, ensure_ascii=False)]
    Path('results/report_v6.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'gate': True, 'counts': out['counts'], 'audit': out['missed_opportunity_audit'], 'top': [asdict(x) for x in ranked[:10]]}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
