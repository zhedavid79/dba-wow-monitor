from __future__ import annotations

import asyncio
import json
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright

import dba_component_market_v19 as market
import dba_retail_authority_v22 as authority22
import dba_retail_prices_v19 as retail19

RETAIL = Path('results/retail_prices_latest.json')
OUT = Path('results/retail_offers_v22.json')

PRICE_RE = re.compile(r'(?<!\d)(\d{1,3}(?:[. ]\d{3})*|\d{3,5})(?:[,.]\d{2})?\s*(?:kr\.?|DKK)', re.I)
STOCK_RE = re.compile(r'\b(?:på lager|in stock|lagerfør|levering\s*\d|sendes|afsendes|klar til levering)\b', re.I)
NOT_IN_STOCK_RE = re.compile(r'\b(?:på lager igen|på vej|ikke på lager|udsolgt|forventet på lager)\b', re.I)
FREE_SHIP_RE = re.compile(r'\b(?:fri fragt|gratis fragt|gratis levering|free shipping|0(?:[,.]00)?\s*kr\.?\s*(?:fragt|levering))\b', re.I)
PROMO_RE = re.compile(r'\b(?:tilbud|kampagne|rabat|spar|sale|specialpris|weekendpris|black friday|outlet|gælder\s+t\.?o\.?m\.?)\b|\b\d{1,2}\s*%\b', re.I)
NORMAL_RE = re.compile(r'\b(?:før|førpris|normalpris|normal pris|vejledende pris|vejl\.?\s*pris)\D{0,20}(\d{1,3}(?:[. ]\d{3})*|\d{3,5})(?:[,.]\d{2})?\s*(?:kr\.?|DKK)', re.I)
SHIP_A = re.compile(r'\b(?:fragt|levering|shipping)\s*(?:fra\s*)?(\d{1,3}(?:[. ]\d{3})*|\d{1,4})(?:[,.](\d{1,2}))?\s*kr\.?', re.I)
SHIP_B = re.compile(r'(\d{1,3}(?:[. ]\d{3})*|\d{1,4})(?:[,.](\d{1,2}))?\s*kr\.?.{0,20}\b(?:fragt|levering|shipping)\b', re.I)
DELIVERY_INCLUDED_RE = re.compile(r'pris\s+inkl\.?\s+(?:leveringsomkostninger|fragt|levering)', re.I)
STORE_LINK_RE = re.compile(r'/go-to-shop/(\d+)/offer/(\d+)')
FINANCE_RE = re.compile(r'\b(?:pr\.?\s*(?:md|måned)|/\s*(?:md|måned)|måned(?:lig|en|er)?|afbetaling|delbetaling|finansiering|ratebetaling|kredit|per\s+month)\b', re.I)
SHIP_CONTEXT_RE = re.compile(r'\b(?:fragt|shipping|leveringsomkostning(?:er)?)\b', re.I)
UNIT_PRICE_RE = re.compile(r'(?:/|pr\.?|per)\s*(?:GB|TB)\b|\b(?:GB|TB)\s*(?:pris|price)\b', re.I)


def _int_price(raw: str) -> int | None:
    try:
        return int(str(raw).replace('.', '').replace(' ', ''))
    except Exception:
        return None


def _line_context(text: str, start: int, end: int) -> str:
    lo = text.rfind('\n', 0, start) + 1
    hi = text.find('\n', end)
    if hi < 0:
        hi = len(text)
    return text[lo:hi].strip()


def price_hits(text: str) -> list[dict]:
    """Current-price candidates from one exact comparison-offer card only."""
    s = str(text or '')
    out = []
    for m in PRICE_RE.finditer(s):
        n = _int_price(m.group(1))
        if n is None or not 100 <= n <= 100000:
            continue
        line = _line_context(s, m.start(), m.end())
        if FINANCE_RE.search(line):
            continue
        if SHIP_CONTEXT_RE.search(line) and not DELIVERY_INCLUDED_RE.search(line):
            continue
        if UNIT_PRICE_RE.search(line):
            continue
        out.append({'value': n, 'line': line[:240], 'start': m.start()})
    return out


def prices(text: str) -> list[int]:
    return [x['value'] for x in price_hits(text)]


def normal_price(text: str) -> int | None:
    m = NORMAL_RE.search(str(text or ''))
    return _int_price(m.group(1)) if m else None


def choose_card_price(hits: list[dict], card_text: str, product_floor: int | None = None) -> tuple[int | None, str, str]:
    """Choose a current amount only from one exact live offer card.

    `product_floor` is accepted only for backward call compatibility and is
    deliberately ignored: a page-wide or previously inferred floor must never
    decide which monetary amount inside a card is current.
    """
    if not hits:
        return None, '', 'NO_CARD_PRICE'
    if len(hits) == 1:
        h = hits[0]
        old = normal_price(card_text)
        if old is not None and int(old) == int(h['value']):
            return None, '', 'ONLY_EXPLICIT_NORMAL_OR_BEFORE_PRICE'
        return int(h['value']), str(h.get('line') or ''), 'SINGLE_PRICE_EXACT_LIVE_OFFER_CARD'

    old = normal_price(card_text)
    if PROMO_RE.search(card_text) and old:
        current = [h for h in hits if int(h['value']) != int(old)]
        values = {int(h['value']) for h in current}
        if len(values) == 1 and current:
            h = current[-1]
            return int(h['value']), str(h.get('line') or ''), 'PROMO_CURRENT_EXCLUDING_EXPLICIT_NORMAL_PRICE'

    return None, '', 'AMBIGUOUS_MULTI_PRICE_LIVE_OFFER_CARD'


def page_floor_price(live_offer_rows, fallback: int | None = None) -> tuple[int | None, str]:
    """Current same-product sanity floor from the live offer list only.

    Whole product-page text and fallback/history/reference prices are
    intentionally forbidden. The optional fallback parameter is accepted only
    for backward signature compatibility and is never consumed.
    """
    rows = live_offer_rows if isinstance(live_offer_rows, list) else []
    values = [
        int(r['displayed_price_dkk'])
        for r in rows
        if r.get('displayed_price_dkk') is not None
        and r.get('card_current') is True
    ]
    if values:
        return min(values), 'LIVE_OFFER_LIST_CURRENT_CARD_MIN'
    return None, 'NO_LIVE_OFFER_LIST_PRICE_FLOOR'


def shipping(text: str):
    s = str(text or '')
    if FREE_SHIP_RE.search(s):
        return 0, True, 'COMPARISON_CARD_EXPLICIT_FREE_SHIPPING'
    for rx in (SHIP_A, SHIP_B):
        m = rx.search(s)
        if not m:
            continue
        n = _int_price(m.group(1))
        if n is None:
            continue
        ctx = s[max(0, m.start() - 18):m.end() + 8].lower()
        exact = 'fra' not in ctx
        return n, exact, 'COMPARISON_CARD_EXACT_SHIPPING' if exact else 'COMPARISON_CARD_SHIPPING_FROM'
    return None, False, 'COMPARISON_CARD_SHIPPING_UNPROVEN'


def kinds() -> dict[str, str]:
    out = {}
    for kind, rows in market.RETAIL_CANDIDATES.items():
        for row in rows:
            out[str(row.get('sku') or '')] = kind
    return out


async def exact_offer_card(anchor) -> tuple[str, str | None]:
    """The go-to-shop anchor itself is the comparison offer card.

    Never climb to a parent: parents can contain neighbouring shops, price
    history and aggregate Lavest/Højest values.
    """
    try:
        text = (await anchor.inner_text(timeout=900)).strip()
    except Exception:
        return '', None
    seller = None
    try:
        imgs = anchor.locator('img')
        for i in range(min(await imgs.count(), 6)):
            alt = (await imgs.nth(i).get_attribute('alt') or '').strip()
            if alt:
                seller = alt
                break
    except Exception:
        pass
    return text[:1600], seller


async def resolve(context, href: str, seller_hint: str | None = None) -> dict:
    """Resolve a live comparison offer to an external retailer route.

    Prisjagt redirect navigation is attempted first.  If Prisjagt blocks the
    automated redirect (currently HTTP 403 on GitHub-hosted runners), a
    retailer adapter may translate the seller name plus the numeric offer ID
    into a candidate retailer URL.  The adapter is discovery-only: this
    function never grants BUY_NOW authority.  The external retailer page must
    still pass dba_retail_authority_v22.verify_external_retailer().
    """
    import dba_retail_routes_v22 as routes22

    m = STORE_LINK_RE.search(href)
    sid = m.group(1) if m else None
    oid = m.group(2) if m else None
    out = {
        'redirect_url': href,
        'store_id': sid,
        'offer_id': oid,
        'store_offer_link_verified': bool(sid and oid),
        'direct_url': None,
        'external_route_resolved': False,
        'external_resolved': False,
        'seller': seller_hint or None,
        'buy_url': None,
        'retailer_authority': 'RETAIL_LEAD',
        'route_resolution_method': None,
        'route_candidates': [],
    }

    try:
        resp = await context.request.get(href, timeout=12000, max_redirects=10, fail_on_status_code=False)
        out['redirect_http_status'] = int(resp.status)
        final_url = str(resp.url)
        if routes22.external_http_url(final_url):
            out.update({
                'direct_url': final_url,
                'route_host': urlparse(final_url).netloc.lower().removeprefix('www.'),
                'external_route_resolved': True,
                'route_resolution_method': 'PRISJAGT_REDIRECT',
            })
    except Exception as exc:
        out['resolve_error'] = f'{type(exc).__name__}: {str(exc)[:160]}'

    if not out.get('external_route_resolved'):
        candidates = routes22.candidate_urls(seller_hint, oid)
        out['route_candidates'] = candidates
        for candidate in candidates:
            page = await context.new_page()
            try:
                response = await page.goto(candidate, wait_until='domcontentloaded', timeout=30000)
                status = int(response.status) if response else None
                final_url = str(page.url)
                out['adapter_http_status'] = status
                if status is not None and status >= 400:
                    continue
                if not routes22.external_http_url(final_url):
                    continue
                out.update({
                    'direct_url': final_url,
                    'route_host': urlparse(final_url).netloc.lower().removeprefix('www.'),
                    'external_route_resolved': True,
                    'route_resolution_method': 'SELLER_OFFER_ID_RETAILER_ROUTE',
                })
                break
            except Exception as exc:
                out['adapter_error'] = f'{type(exc).__name__}: {str(exc)[:160]}'
            finally:
                await page.close()

    if not out.get('seller') and sid:
        out['seller'] = f'Prisjagt butik #{sid}'
    return out

def sane_offer(row: dict, product_floor: int | None) -> tuple[bool, str]:
    delivered = row.get('retailer_delivered_price_dkk')
    if delivered is None:
        return False, 'NO_DIRECT_RETAILER_DELIVERED_PRICE'
    if not product_floor:
        return False, 'NO_LIVE_OFFER_LIST_PRICE_FLOOR'
    d = int(delivered)
    floor = int(product_floor)
    tolerance = max(5, int(round(floor * 0.01)))
    if d + tolerance < floor:
        return False, f'BELOW_LIVE_OFFER_LIST_PRICE_FLOOR:{d}/{floor}'
    return True, f'AT_OR_ABOVE_LIVE_OFFER_LIST_PRICE_FLOOR:{d}/{floor}'


def is_in_stock(card_text: str) -> bool:
    s = str(card_text or '')
    if NOT_IN_STOCK_RE.search(s):
        return False
    return bool(STOCK_RE.search(s))


async def inspect(context, p: dict, sem, kmap: dict) -> dict:
    async with sem:
        page = await context.new_page()
        sku = str(p.get('sku') or '')
        name = str(p.get('name') or '')
        url = str(p.get('url') or '')
        anchor_price = int(p.get('price') or 0) or None
        out = {
            'sku': sku,
            'kind': p.get('kind') or kmap.get(sku),
            'name': name,
            'product_url': url,
            'product_reference_price_dkk': anchor_price,
            'verified_at': datetime.now(timezone.utc).isoformat(),
            'identity_verified': False,
            'offers': [],
            'delivered_price_verified': False,
            'retailer_authority': 'RETAIL_LEAD',
        }
        try:
            resp = await page.goto(url, wait_until='domcontentloaded', timeout=45000)
            out['http_status'] = int(resp.status) if resp else None
            title = await page.title()
            try:
                h1 = (await page.locator('h1').first.inner_text(timeout=2500)).strip()
            except Exception:
                h1 = ''
            if not retail19.identity_ok(name, ' '.join([title, h1])):
                out['error'] = 'PRODUCT_IDENTITY_MISMATCH'
                return out
            out['identity_verified'] = True

            anchors = page.locator('a[href*="go-to-shop"]')
            n = min(await anchors.count(), 80)
            raw = []
            seen = set()
            for i in range(n):
                a = anchors.nth(i)
                try:
                    href = await a.get_attribute('href') or ''
                except Exception:
                    continue
                if not href:
                    continue
                href = urljoin(url, href)
                card_text, seller_hint = await exact_offer_card(a)
                hits = price_hits(card_text)
                displayed, line, price_method = choose_card_price(hits, card_text)
                if displayed is None:
                    continue
                key = (href, displayed, seller_hint)
                if key in seen:
                    continue
                seen.add(key)
                ship, ship_exact, ship_method = shipping(card_text)
                raw.append({
                    'displayed_price_dkk': displayed,
                    'displayed_price_line': line,
                    'card_price_method': price_method,
                    'price_candidates_dkk': [x['value'] for x in hits],
                    'shipping_dkk_lead': ship,
                    'shipping_exact_lead': ship_exact,
                    'shipping_method_lead': ship_method,
                    'in_stock_card': is_in_stock(card_text),
                    'card_current': not bool(NOT_IN_STOCK_RE.search(card_text)),
                    'promo_evidence': bool(PROMO_RE.search(card_text)),
                    'normal_price_dkk': normal_price(card_text),
                    'comparison_delivery_included_card': bool(DELIVERY_INCLUDED_RE.search(card_text)),
                    'redirect_url': href,
                    'seller_hint': seller_hint,
                    'evidence_text': card_text[:800],
                })

            product_floor, floor_method = page_floor_price(raw)
            out['same_page_lowest_price_dkk'] = product_floor
            out['same_page_price_floor_method'] = floor_method
            out['retail_lead_price_dkk'] = product_floor

            raw.sort(key=lambda x: (x['displayed_price_dkk'], 0 if x['card_current'] else 1))
            resolved = []
            direct_attempts = 0
            for row in raw[:12]:
                r = dict(row)
                r.update(await resolve(context, row['redirect_url'], row.get('seller_hint')))

                if r.get('comparison_delivery_included_card'):
                    r['lead_delivered_price_dkk'] = int(r['displayed_price_dkk'])
                    r['lead_delivered_method'] = 'COMPARISON_CARD_PRICE_INCL_DELIVERY'
                elif r.get('shipping_exact_lead') and r.get('shipping_dkk_lead') is not None:
                    r['lead_delivered_price_dkk'] = int(r['displayed_price_dkk']) + int(r['shipping_dkk_lead'])
                    r['lead_delivered_method'] = 'COMPARISON_CARD_ITEM_PLUS_SHIPPING'
                else:
                    r['lead_delivered_price_dkk'] = None
                    r['lead_delivered_method'] = 'COMPARISON_LEAD_ONLY'

                can_try_direct = (
                    direct_attempts < 3
                    and r.get('external_route_resolved') is True
                    and r.get('direct_url')
                    and product_floor is not None
                    and r.get('card_current') is True
                )
                if can_try_direct:
                    direct_attempts += 1
                    retailer = await authority22.verify_external_retailer(
                        context,
                        str(r['direct_url']),
                        name,
                        lead_price_dkk=product_floor,
                    )
                    r.update(retailer)

                strict = bool(
                    r.get('external_resolved') is True
                    and r.get('retailer_page_verified') is True
                    and r.get('retailer_identity_verified') is True
                    and r.get('retailer_price_verified') is True
                    and r.get('retailer_stock_verified') is True
                    and r.get('retailer_shipping_verified') is True
                    and r.get('retailer_url')
                    and 'prisjagt.dk' not in urlparse(str(r.get('retailer_url'))).netloc.lower()
                )
                sane, sanity = sane_offer(r, product_floor)
                r['price_sanity_ok'] = bool(sane)
                r['price_sanity_method'] = sanity

                if strict and sane:
                    item = int(r['retailer_item_price_dkk'])
                    ship = int(r['retailer_shipping_dkk'])
                    delivered = int(r['retailer_delivered_price_dkk'])
                    if delivered != item + ship:
                        strict = False
                        r['retailer_error'] = 'RETAILER_DELIVERED_TOTAL_ARITHMETIC_MISMATCH'

                if strict and sane:
                    r.update({
                        'item_price_dkk': int(r['retailer_item_price_dkk']),
                        'shipping_dkk': int(r['retailer_shipping_dkk']),
                        'shipping_exact': True,
                        'shipping_method': r.get('retailer_shipping_method'),
                        'delivered_price_dkk': int(r['retailer_delivered_price_dkk']),
                        'delivered_price_method': 'DIRECT_RETAILER_ITEM_PLUS_MANDATORY_SHIPPING',
                        'in_stock_verified': True,
                        'buy_url': r.get('retailer_url'),
                        'seller': r.get('seller_hint') or r.get('retailer_host'),
                        'retailer_authority': 'DIRECT_RETAILER_T1',
                        'buy_ready_offer': True,
                    })
                else:
                    r.update({
                        'item_price_dkk': None,
                        'shipping_dkk': None,
                        'shipping_exact': False,
                        'delivered_price_dkk': None,
                        'delivered_price_method': 'RETAIL_LEAD_ONLY',
                        'in_stock_verified': False,
                        'buy_url': None,
                        'external_resolved': False,
                        'retailer_authority': 'RETAIL_LEAD',
                        'buy_ready_offer': False,
                    })
                r['same_page_lowest_price_dkk'] = product_floor
                r['same_page_price_floor_method'] = floor_method
                resolved.append(r)

            verified = [r for r in resolved if r.get('buy_ready_offer')]
            delivered_values = [int(r['delivered_price_dkk']) for r in verified]
            median = int(round(statistics.median(delivered_values))) if delivered_values else None
            for r in resolved:
                r['market_reference_delivered_dkk'] = median
                dp = r.get('delivered_price_dkk')
                r['deal_type'] = (
                    'DIRECT_RETAILER_MARKET_DEAL' if dp and median and dp <= median * .90
                    else 'DIRECT_RETAILER_CURRENT_PRICE' if r.get('buy_ready_offer')
                    else 'RETAIL_LEAD'
                )

            verified.sort(key=lambda r: int(r['delivered_price_dkk']))
            out['offers'] = resolved
            out['external_routes_resolved'] = sum(1 for r in resolved if r.get('external_route_resolved'))
            out['retailer_pages_verified'] = sum(1 for r in resolved if r.get('buy_ready_offer'))
            if verified:
                b = verified[0]
                out.update({
                    'best_delivered_offer': b,
                    'delivered_price_verified': True,
                    'delivered_price_dkk': int(b['delivered_price_dkk']),
                    'item_price_dkk': int(b['item_price_dkk']),
                    'shipping_dkk': int(b['shipping_dkk']),
                    'delivered_price_method': b.get('delivered_price_method'),
                    'buy_url': b.get('buy_url'),
                    'seller': b.get('seller'),
                    'store_id': b.get('store_id'),
                    'offer_id': b.get('offer_id'),
                    'external_url_resolved': True,
                    'external_route_resolved': True,
                    'retailer_page_verified': True,
                    'retailer_identity_verified': True,
                    'retailer_price_verified': True,
                    'retailer_stock_verified': True,
                    'retailer_shipping_verified': True,
                    'retailer_authority': 'DIRECT_RETAILER_T1',
                    'deal_type': b.get('deal_type'),
                    'normal_price_dkk': b.get('normal_price_dkk'),
                    'market_reference_delivered_dkk': median,
                    'price_sanity_ok': True,
                    'price_sanity_method': b.get('price_sanity_method'),
                    'card_price_method': b.get('card_price_method'),
                    'same_page_lowest_price_dkk': product_floor,
                    'same_page_price_floor_method': floor_method,
                })
            else:
                out.update({
                    'external_url_resolved': False,
                    'retailer_page_verified': False,
                    'retailer_identity_verified': False,
                    'retailer_price_verified': False,
                    'retailer_stock_verified': False,
                    'retailer_shipping_verified': False,
                })
            return out
        except Exception as exc:
            out['error'] = f'{type(exc).__name__}: {str(exc)[:220]}'
            return out
        finally:
            await page.close()


async def main():
    doc = json.loads(RETAIL.read_text(encoding='utf-8'))
    kmap = kinds()
    products = []
    seen = set()
    for p in doc.get('products') or []:
        key = str(p.get('sku') or p.get('url') or '')
        if not p.get('url') or key in seen:
            continue
        seen.add(key)
        products.append(dict(p))

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(locale='da-DK')
        sem = asyncio.Semaphore(5)
        rows = await asyncio.gather(*(inspect(context, p, sem, kmap) for p in products))
        await context.close()
        await browser.close()

    ready = [r for r in rows if r.get('delivered_price_verified')]
    leads = [r for r in rows if r.get('retail_lead_price_dkk')]
    deals = [r for r in ready if r.get('deal_type') == 'DIRECT_RETAILER_MARKET_DEAL']
    by = {str(r.get('sku')): r for r in rows if r.get('sku')}
    external_routes = sum(int(r.get('external_routes_resolved') or 0) for r in rows)
    retailer_verified = len(ready)
    result = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'model': 'V22_STORE_LEVEL_DELIVERED_PRICE_AND_DEALS',
        'authority_model': 'V22_DIRECT_RETAILER_PAGE_T1',
        'policy': (
            'Prisjagt is discovery/RETAIL_LEAD only. Current comparison sanity prices come only from exact live '
            'go-to-shop offer cards; whole-page price history, lows, financing, shipping-only and normal/før-prices '
            'are forbidden. BUY_NOW authority requires the external retailer product page to prove same-product '
            'identity, a concrete DKK Offer.price, InStock, exact mandatory shipping, delivered arithmetic and a '
            'direct external purchase URL.'
        ),
        'products_total': len(rows),
        'retail_leads': len(leads),
        'delivered_price_verified': len(ready),
        'deal_candidates': len(deals),
        'external_routes_resolved': external_routes,
        'external_urls_resolved': retailer_verified,
        'retailer_pages_verified': retailer_verified,
        'rows': rows,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')

    for p in doc.get('products') or []:
        r = by.get(str(p.get('sku') or ''))
        if not r:
            continue
        p['retail_offer_v22'] = {k: r.get(k) for k in (
            'delivered_price_verified','delivered_price_dkk','item_price_dkk','shipping_dkk','delivered_price_method',
            'buy_url','seller','store_id','offer_id','external_url_resolved','external_route_resolved',
            'retailer_page_verified','retailer_identity_verified','retailer_price_verified',
            'retailer_stock_verified','retailer_shipping_verified','retailer_authority',
            'deal_type','normal_price_dkk','market_reference_delivered_dkk','price_sanity_ok','price_sanity_method',
            'card_price_method','retail_lead_price_dkk','same_page_lowest_price_dkk','same_page_price_floor_method'
        )}
    doc['offer_gate_v22'] = {
        'model': result['model'],
        'authority_model': result['authority_model'],
        'products_total': len(rows),
        'retail_leads': len(leads),
        'delivered_price_verified': len(ready),
        'deal_candidates': len(deals),
        'external_routes_resolved': external_routes,
        'external_urls_resolved': retailer_verified,
        'retailer_pages_verified': retailer_verified,
        'required_price_basis': 'DIRECT_RETAILER_PAGE_ONLY',
        'same_page_floor_basis': 'LIVE_OFFER_LIST_ONLY',
        'whole_page_floor_forbidden': True,
        'price_history_forbidden': True,
        'financing_shipping_filter': True,
        'same_product_price_sanity': True,
        'exact_offer_card_binding': True,
        'parent_section_prices_forbidden': True,
        'retailer_page_required_for_buy_now': True,
        'mandatory_shipping_required_for_buy_now': True,
    }
    RETAIL.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
    bykind = {k: sum(1 for r in ready if r.get('kind') == k) for k in ('MOTHERBOARD','PSU','CASE','COOLER','RAM','STORAGE')}
    print(json.dumps({
        'V22_RETAIL_OFFERS': True,
        'products': len(rows),
        'retail_leads': len(leads),
        'delivered_verified': len(ready),
        'deals': len(deals),
        'external_routes_resolved': external_routes,
        'retailer_pages_verified': retailer_verified,
        'by_kind': bykind,
        'same_page_floor_basis': 'LIVE_OFFER_LIST_ONLY',
    }, ensure_ascii=False))
    assert rows


if __name__ == '__main__':
    asyncio.run(main())
