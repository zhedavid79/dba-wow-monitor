from __future__ import annotations

import json
import re
import statistics
from pathlib import Path

PATH = Path('results/acurast_latest.json')
REPORT = Path('results/acurast_report.md')

# A structured DBA ASK can be perfectly genuine while the listing itself contains several
# devices. In that situation the ASK cannot safely be assigned to one Acurast phone model.
BRANDS = re.compile(r'\b(samsung|oneplus|xiaomi|poco|motorola|google|pixel|huawei|honor|nokia|sony|iphone|apple|oppo|realme)\b', re.I)
PRICE_MENTION = re.compile(r'(?<!\d)(\d{2,5})\s*(?:kr\.?|kroner)\b', re.I)
BUNDLE_WORDS = re.compile(r'\b(begge|2\s*(?:telefoner|mobiler)|to\s*(?:telefoner|mobiler)|samlet|pakke|bundle)\b', re.I)
OTHER_DEVICE = re.compile(r'\b(galaxy\s+watch|smartwatch|watch\s*\d*|galaxy\s+tab|tablet|ipad|macbook|laptop|bærbar)\b', re.I)


def ambiguity(row: dict) -> tuple[bool, str]:
    title = str(row.get('title') or '')
    desc = str(row.get('description') or '')
    brands = {m.group(1).lower() for m in BRANDS.finditer(title)}
    prices = {int(m.group(1)) for m in PRICE_MENTION.finditer(desc)}
    ask = int(row.get('ask_t2') or row.get('ask_t1') or 0)

    if len(brands) > 1:
        return True, f'multiple phone brands in live title: {sorted(brands)}'
    if OTHER_DEVICE.search(title):
        return True, 'live title contains another distinct device type'
    if len(prices) > 1:
        return True, f'multiple explicit item prices in live description: {sorted(prices)}'
    if BUNDLE_WORDS.search(title + ' ' + desc) and prices and (ask not in prices or len(prices) != 1):
        return True, 'bundle/multi-device language with ambiguous price binding'
    return False, 'single-device price identity passed'


def main() -> None:
    src = json.loads(PATH.read_text(encoding='utf-8'))
    if not src.get('gate_passed'):
        raise SystemExit('PRICE DATA GATE FAILED upstream')

    kept, rejected = [], []
    for row in src.get('ranked_by_verified_ask', []):
        bad, reason = ambiguity(row)
        if bad:
            rejected.append({
                'listing_id': row.get('listing_id'),
                'title': row.get('title'),
                'ask': row.get('ask_t2') or row.get('ask_t1'),
                'url': row.get('url'),
                'reason': 'BUNDLE/PRICE IDENTITY GATE: ' + reason,
            })
        else:
            row['bundle_price_identity_ok'] = True
            row['bundle_price_identity_reason'] = reason
            kept.append(row)

    by_model: dict[str, list[int]] = {}
    for row in kept:
        by_model.setdefault(str(row.get('model')), []).append(int(row.get('ask_t2') or row.get('ask_t1')))
    market = []
    for model, asks in sorted(by_model.items()):
        asks = sorted(asks)
        market.append({'model': model, 'n': len(asks), 'min_ask': min(asks), 'median_ask': statistics.median(asks), 'max_ask': max(asks)})

    src['ranked_by_verified_ask'] = kept
    src['market'] = market
    src['bundle_price_identity_gate'] = True
    src.setdefault('counts', {})['bundle_price_identity_excluded'] = len(rejected)
    src['counts']['final_refetched'] = len(kept)
    src.setdefault('excluded', []).extend(rejected)
    PATH.write_text(json.dumps(src, ensure_ascii=False, indent=2), encoding='utf-8')

    lines = [
        '# Acurast DBA verified phone report', '',
        f"Generated: {src.get('generated_at')}", '',
        'DBA data gate: **PASS** — structured discovery + same-listing live verification + final refetch', '',
        f"T0: {src.get('counts',{}).get('t0_unique')} | Product rejects: {src.get('counts',{}).get('product_identity_excluded')} | Bundle/price rejects: {len(rejected)} | Final: {len(kept)}", '',
        '## Lowest verified single-device listings', '',
        '| Rank | Model | ASK | Listing |', '|---:|---|---:|---|'
    ]
    for i, row in enumerate(sorted(kept, key=lambda r: int(r.get('ask_t2') or r.get('ask_t1'))), 1):
        ask = int(row.get('ask_t2') or row.get('ask_t1'))
        lines.append(f"| {i} | {row.get('model')} | {ask} kr. | [{row.get('title')}]({row.get('url')}) |")
    if rejected:
        lines += ['', '## Manual review — ambiguous multi-device/price listings', '']
        for row in rejected:
            lines.append(f"- {row['listing_id']}: {row['title']} — {row['ask']} kr. — {row['reason']}")
    REPORT.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    print(json.dumps({'gate': True, 'kept': len(kept), 'bundle_price_rejects': len(rejected), 'rejected': rejected[:10]}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
