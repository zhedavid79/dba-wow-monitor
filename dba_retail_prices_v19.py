from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

import dba_component_optimizer_v19 as v19

OUT = Path('results/retail_prices_latest.json')
PRICE_RE = re.compile(r'(?<!\d)(\d{1,3}(?:[. ]\d{3})*|\d{3,5})(?:[,.]\d{2})?\s*(?:kr\.?|DKK)', re.I)


def norm(s: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', (s or '').lower()).strip()


def identity_ok(expected: str, actual: str) -> bool:
    e = set(norm(expected).split())
    a = set(norm(actual).split())
    if not e or not a:
        return False
    strong = {x for x in e if any(ch.isdigit() for ch in x) or len(x) >= 6}
    if strong and len(strong & a) < max(1, len(strong) // 2):
        return False
    return len(e & a) / max(1, len(e)) >= 0.45


def walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def numeric_price(v):
    try:
        n = float(str(v).replace(' ', '').replace(',', '.'))
        if 100 <= n <= 100000:
            return int(round(n))
    except Exception:
        pass
    return None


def product_offer_from_ld(blobs: list, expected: str):
    candidates = []
    for blob in blobs:
        for d in walk(blob):
            typ = d.get('@type')
            types = typ if isinstance(typ, list) else [typ]
            if not any(str(x).lower() == 'product' for x in types if x):
                continue
            name = str(d.get('name') or '')
            if not identity_ok(expected, name):
                continue
            offers = d.get('offers')
            offer_objs = offers if isinstance(offers, list) else [offers] if isinstance(offers, dict) else []
            for o in offer_objs:
                price = numeric_price(o.get('price')) or numeric_price(o.get('lowPrice'))
                if not price:
                    continue
                availability = str(o.get('availability') or '')
                count = o.get('offerCount')
                candidates.append((price, name, availability, count, 'JSON_LD_PRODUCT'))
    return sorted(candidates, key=lambda x: x[0])


async def verify_one(context, product: dict, sem: asyncio.Semaphore) -> dict:
    async with sem:
        page = await context.new_page()
        expected = str(product['name'])
        url = str(product['url'])
        result = {
            'sku': product['sku'], 'name': expected, 'url': url, 'verified': False,
            'price': None, 'availability': None, 'verified_at': datetime.now(timezone.utc).isoformat(),
            'method': None, 'host': urlparse(url).netloc,
        }
        try:
            response = await page.goto(url, wait_until='domcontentloaded', timeout=45000)
            result['http_status'] = int(response.status) if response else None
            title = await page.title()
            h1 = ''
            try:
                h1 = (await page.locator('h1').first.inner_text(timeout=3000)).strip()
            except Exception:
                pass
            identity_text = ' '.join([title, h1])
            result['rendered_title'] = title
            result['rendered_h1'] = h1
            if not identity_ok(expected, identity_text):
                result['error'] = 'PRODUCT_IDENTITY_MISMATCH'
                return result

            scripts = await page.locator('script[type="application/ld+json"]').all_text_contents()
            blobs = []
            for text in scripts:
                try:
                    blobs.append(json.loads(text))
                except Exception:
                    continue
            offers = product_offer_from_ld(blobs, expected)
            if offers:
                price, _, availability, offer_count, method = offers[0]
                result.update({'verified': True, 'price': price, 'availability': availability or ('AVAILABLE_COMPARISON' if offer_count else 'UNKNOWN'), 'method': method})
                return result

            selectors = [
                'meta[property="product:price:amount"]', 'meta[itemprop="price"]',
                '[itemprop="price"]', '[data-price]',
            ]
            for sel in selectors:
                loc = page.locator(sel).first
                try:
                    if await loc.count() == 0:
                        continue
                    raw = await loc.get_attribute('content') or await loc.get_attribute('data-price') or await loc.get_attribute('value') or await loc.inner_text(timeout=1500)
                    price = numeric_price(raw)
                    if price:
                        body = (await page.locator('body').inner_text(timeout=5000))[:12000]
                        available = bool(re.search(r'\b(?:på lager|køb|til butik|in stock)\b', body, re.I))
                        result.update({'verified': True, 'price': price, 'availability': 'AVAILABLE' if available else 'UNKNOWN', 'method': f'DOM:{sel}'})
                        return result
                except Exception:
                    continue

            body = (await page.locator('body').inner_text(timeout=5000))[:20000]
            matches = []
            for m in PRICE_RE.finditer(body):
                raw = m.group(1).replace('.', '').replace(' ', '')
                try:
                    n = int(raw)
                except Exception:
                    continue
                if 100 <= n <= 100000:
                    matches.append(n)
            if matches:
                result.update({'verified': True, 'price': min(matches), 'availability': 'PAGE_PRICE', 'method': 'PAGE_TEXT_PRICE'})
                return result

            result['error'] = 'NO_PRICE_OBJECT'
            return result
        except Exception as exc:
            result['error'] = f'{type(exc).__name__}: {str(exc)[:240]}'
            return result
        finally:
            await page.close()


async def main() -> None:
    products = []
    for kind, rows in v19.RETAIL_CANDIDATES.items():
        for row in rows:
            x = dict(row)
            x['kind'] = kind
            products.append(x)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(locale='da-DK')
        sem = asyncio.Semaphore(4)
        rows = await asyncio.gather(*(verify_one(context, x, sem) for x in products))
        await context.close()
        await browser.close()

    for r in rows:
        print(json.dumps({
            'stage': 'RETAIL_VERIFY', 'sku': r.get('sku'), 'verified': r.get('verified'),
            'price': r.get('price'), 'method': r.get('method'), 'http_status': r.get('http_status'),
            'error': r.get('error'), 'rendered_title': r.get('rendered_title'), 'rendered_h1': r.get('rendered_h1'),
        }, ensure_ascii=False), flush=True)

    by_sku = {r['sku']: r for r in rows}
    required = {'ASROCK_B850M_PRO_A_WIFI','MSI_B850M_GAMING_PLUS_WIFI6E','GIGABYTE_B650M_GAMING_PLUS_WIFI'}
    required_ok = all(by_sku.get(s, {}).get('verified') is True for s in required)
    doc = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'model': 'V19_RETAIL_SAME_PRODUCT_PRICE_GATE',
        'required_motherboard_gate_passed': required_ok,
        'products': rows,
        'counts': {'total': len(rows), 'verified': sum(1 for r in rows if r.get('verified')), 'failed': sum(1 for r in rows if not r.get('verified'))},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(doc['counts'] | {'required_motherboard_gate_passed': required_ok}, ensure_ascii=False))
    if not required_ok:
        raise SystemExit('V19 RETAIL GATE FAILED: motherboard candidates not all same-product price verified')


if __name__ == '__main__':
    asyncio.run(main())
