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
BRAND_CANON={'pixel':'google','iphone':'apple'}
PRICE_MENTION = re.compile(r'(?<!\d)(\d{2,5})\s*(?:kr\.?|kroner)\b', re.I)
BUNDLE_WORDS = re.compile(r'\b(begge|2\s*(?:telefoner|mobiler)|to\s*(?:telefoner|mobiler)|samlet|pakke|bundle|styk(?:ker)?|stk\.? )\b', re.I)
OTHER_DEVICE = re.compile(r'\b(galaxy\s+watch|smartwatch|watch\s*\d*|galaxy\s+tab|tablet|ipad|macbook|laptop|bærbar)\b', re.I)

# Variant words are part of product identity, not cosmetic descriptors. If a seller says
# S21 Ultra / CE2 Lite / Edge 40 Neo, a base-model match must never inherit that ASK.
VARIANT_TOKENS = {
    'ultra', 'pro', 'plus', 'lite', 'fe', 'neo', 'fusion', 'ce', 'gt',
    'master', 'max', 'mini', 'fold', 'flip', 'note'
}


def norm_tokens(text: str) -> set[str]:
    text = (text or '').lower().replace('+', ' plus ')
    text = re.sub(r'([a-z]+)(\d)', r'\1 \2', text)
    text = re.sub(r'(\d)([a-z]+)', r'\1 \2', text)
    return set(re.findall(r'[a-z0-9]+', text))


def variant_conflict(title: str, model: str) -> tuple[bool, str]:
    title_variants = norm_tokens(title) & VARIANT_TOKENS
    model_variants = norm_tokens(model) & VARIANT_TOKENS
    missing = sorted(title_variants - model_variants)
    if missing:
        return True, f'live title variant(s) {missing} absent from resolved model {model!r}'
    return False, 'variant identity passed'


def canonical_brands(title:str)->set[str]:
    return {BRAND_CANON.get(m.group(1).lower(),m.group(1).lower()) for m in BRANDS.finditer(title or '')}


def ambiguity(row: dict) -> tuple[bool, str]:
    title = str(row.get('title') or '')
    desc = str(row.get('description') or '')
    model = str(row.get('model') or '')
    brands = canonical_brands(title)
    prices = {int(m.group(1)) for m in PRICE_MENTION.finditer(desc)}
    ask = int(row.get('ask_t2') or row.get('ask_t1') or 0)
    combined=title+' '+desc

    conflict, reason = variant_conflict(title, model)
    if conflict:
        return True, 'variant/model conflict: ' + reason
    if len(brands) > 1:
        return True, f'multiple phone brands in live title: {sorted(brands)}'
    if OTHER_DEVICE.search(title):
        return True, 'live title contains another distinct device type'

    # Multiple prices alone are not evidence that DBA's structured ASK belongs to
    # another item: sellers often mention original price, repair cost or previous ASK.
    # Reject only when price plurality is accompanied by explicit multi-item evidence.
    if len(prices) > 1 and (BUNDLE_WORDS.search(combined) or OTHER_DEVICE.search(combined)):
        return True, f'multiple explicit item prices with multi-item evidence: {sorted(prices)}'
    if BUNDLE_WORDS.search(combined) and prices and (ask not in prices or len(prices) != 1):
        return True, 'bundle/multi-device language with ambiguous price binding'
    return False, 'single-device price + variant identity passed'


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
        f"T0: {src.get('counts',{}).get('t0_unique')} | Product rejects: {src.get('counts',{}).get('product_identity_excluded')} | Bundle/variant/price rejects: {len(rejected)} | Final: {len(kept)}", '',
        '## Lowest verified single-device listings', '',
        '| Rank | Model | ASK | Listing |', '|---:|---|---:|---|'
    ]
    for i, row in enumerate(sorted(kept, key=lambda r: int(r.get('ask_t2') or r.get('ask_t1'))), 1):
        ask = int(row.get('ask_t2') or row.get('ask_t1'))
        lines.append(f"| {i} | {row.get('model')} | {ask} kr. | [{row.get('title')}]({row.get('url')}) |")
    if rejected:
        lines += ['', '## Manual review — ambiguous variant/multi-device/price listings', '']
        for row in rejected:
            lines.append(f"- {row['listing_id']}: {row['title']} — {row['ask']} kr. — {row['reason']}")
    REPORT.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    print(json.dumps({'gate': True, 'kept': len(kept), 'bundle_variant_price_rejects': len(rejected), 'rejected': rejected[:10]}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
