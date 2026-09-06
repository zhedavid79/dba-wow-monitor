from __future__ import annotations

import asyncio
import json
from pathlib import Path

import dba_retail_prices_v20 as base

OUT = Path('results/retail_prices_latest.json')

# V20 deliberately sampled only eight products per discovery seed. V22 searches
# deeper in every proven category page so sale/outlet-priced substitutes have a
# realistic chance to enter the compatible candidate universe before scoring.
MAX_LINKS_PER_SEED_V22 = 20


async def main() -> None:
    base.MAX_LINKS_PER_SEED = MAX_LINKS_PER_SEED_V22
    await base.main()
    doc = json.loads(OUT.read_text(encoding='utf-8'))
    doc['deal_discovery_v22'] = {
        'active': True,
        'max_product_links_per_seed': MAX_LINKS_PER_SEED_V22,
        'seed_count': sum(len(v) for v in base.DISCOVERY_SEEDS.values()),
        'policy': 'Actively inspect a deeper live retail universe before store-level offer comparison. Compatibility evidence remains fail-closed; a cheap product cannot win without the category hard gates.',
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({
        'V22_RETAIL_DISCOVERY': True,
        'dynamic_inspected': (doc.get('counts') or {}).get('dynamic_inspected'),
        'dynamic_admitted': (doc.get('counts') or {}).get('dynamic_admitted'),
        'max_links_per_seed': MAX_LINKS_PER_SEED_V22,
    }, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
