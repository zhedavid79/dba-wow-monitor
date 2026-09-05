from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import dba_component_market_v19 as v19

OUT = Path('results/wow_strategy_latest.json')
RETAIL = Path('results/retail_prices_latest.json')
MAX_RETAIL_AGE_SECONDS = 20 * 60


def parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def main() -> None:
    assert OUT.exists(), 'Missing strategy snapshot'
    assert RETAIL.exists(), 'Missing live retail snapshot'

    retail = json.loads(RETAIL.read_text(encoding='utf-8'))
    assert retail.get('model') == 'V19_RETAIL_SAME_PRODUCT_PRICE_GATE'
    assert retail.get('required_motherboard_gate_passed') is True
    assert retail.get('all_catalog_products_verified') is True
    counts = retail.get('counts') or {}
    assert int(counts.get('failed') or 0) == 0
    assert int(counts.get('verified') or 0) == int(counts.get('total') or 0) >= 25
    age = (datetime.now(timezone.utc) - parse_iso(retail['generated_at'])).total_seconds()
    assert 0 <= age <= MAX_RETAIL_AGE_SECONDS, f'Retail snapshot stale: {age:.0f}s'

    data = json.loads(OUT.read_text(encoding='utf-8'))
    assert data.get('gate_passed') is True
    data = v19.finalize(data)
    assert data.get('model_version') == 'DBA-WOW-SELF-BUILD-FIRST-V19'
    assert data.get('strategy_mode') == 'EXPLAINABLE_MULTI_CRITERIA_SELF_BUILD'
    assert (data.get('component_market_coverage_v19') or {}).get('passed') is True

    rec = data.get('recommended_self_build') or {}
    assert rec and rec.get('foundation') == 'AM5_B650_B850_MATX_WIFI_4DIMM'
    assert rec.get('upgradeability') == 'A'
    assert rec.get('z20_fit') in {'VERIFIED', 'LIKELY'}
    assert sum(int(x.get('price') or 0) for x in rec.get('components') or []) == int(rec.get('tcwp') or 0)

    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    mb = (((rec.get('component_choice_v19') or {}).get('MOTHERBOARD') or {}).get('winner') or {})
    print(json.dumps({
        'model': data.get('model_version'),
        'recommended_tcwp': rec.get('tcwp'),
        'cpu': rec.get('cpu'),
        'gpu': rec.get('gpu'),
        'motherboard': mb.get('name'),
        'motherboard_price': mb.get('price'),
        'retail_age_seconds': round(age, 1),
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
