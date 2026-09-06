from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import dba_retail_prices_v19 as retail19

MONEY_RE = re.compile(
    r'(?<!\d)(\d{1,3}(?:[. ]\d{3})*|\d{1,5})(?:[,.](\d{1,2}))?\s*(?:kr\.?|DKK)',
    re.I,
)
EXACT_SHIP_RE = re.compile(
    r'\b(?:fragt|levering|shipping)(?:\s*\([^\)\n]{1,40}\))?\s*(?!fra\b)(?:kun\s*)?'
    r'(\d{1,3}(?:[. ]\d{3})*|\d{1,4})(?:[,.](\d{1,2}))?\s*(?:kr\.?|DKK)',
    re.I,
)
FREE_SHIP_RE = re.compile(r'\b(?:fri fragt|gratis fragt|gratis levering|free shipping)\b', re.I)
THRESHOLD_RE = re.compile(
    r'\b(?:over|fra|ved køb for|min(?:imum)?\.?)\s*'
    r'(\d{1,4})(?:[,.](\d{1,2}))?\s*(?:kr\.?|DKK)',
    re.I,
)
FINANCE_RE = re.compile(
    r'\b(?:pr\.?\s*(?:md|måned)|/\s*(?:md|måned)|måned(?:lig|en|er)?|'
    r'afbetaling|delbetaling|finansiering|ratebetaling|kredit|per\s+month)\b',
    re.I,
)
OUT_OF_STOCK_RE = re.compile(
    r'\b(?:ikke på lager|udsolgt|out of stock|sold out|på lager igen|forventet på lager|preorder|forudbestil)\b',
    re.I,
)
IN_STOCK_RE = re.compile(
    r'\b(?:på lager|in stock|lagerført|lagerfør|klar til levering|sendes i dag|afsendes)\b',
    re.I,
)



def _identity_tokens(value: str) -> list[str]:
    return re.findall(r'[a-z0-9]+(?:-[a-z0-9]+)*', str(value or '').lower())


def _brand_token(value: str) -> str | None:
    ignored = {'amd', 'intel', 'pcie', 'ddr', 'wifi', 'black', 'white', 'sort', 'hvid'}
    for token in _identity_tokens(value):
        if token.isalpha() and len(token) >= 3 and token not in ignored:
            return token
    return None


def _model_tokens(value: str) -> set[str]:
    """Return discriminative model tokens, not generic capacity/spec tokens."""
    out: set[str] = set()
    for token in _identity_tokens(value):
        if not (re.search(r'[a-z]', token) and re.search(r'\d', token)):
            continue
        compact = token.replace('-', '')
        if re.fullmatch(r'\d+(?:gb|tb|w|mhz|ghz|mm)', compact):
            continue
        if re.fullmatch(r'(?:ddr|pcie|wifi|atx|gen)\d+[a-z0-9]*', compact):
            continue
        # Chipset-only tokens cannot prove the board model. Suffix-bearing
        # tokens such as B850M-PLUS remain discriminative and are retained.
        if re.fullmatch(r'[abxhqz]\d{3,4}(?:m|e)?', compact):
            continue
        if len(compact) >= 3:
            out.add(token)
    return out


def _same_product_identity(expected: str, actual: str) -> bool:
    """Prove same product without accepting brand/chipset overlap alone."""
    expected_brand = _brand_token(expected)
    actual_tokens = set(_identity_tokens(actual))
    if not expected_brand or expected_brand not in actual_tokens:
        return False

    expected_models = _model_tokens(expected)
    actual_models = _model_tokens(actual)
    if expected_models:
        # If the expected name supplies a discriminative model token, at least
        # one must match. This prevents TUF B850M-PLUS from matching PRIME
        # B850M-A merely because both say ASUS/B850M/WIFI.
        return bool(expected_models & actual_models)

    # For names without a discriminative alphanumeric model token, retain the
    # established overlap check after brand identity has already been proven.
    return retail19.identity_ok(expected, actual)

def _numeric(v) -> int | None:
    if isinstance(v, dict):
        for key in ('value', 'price', 'amount'):
            if key in v:
                n = _numeric(v.get(key))
                if n is not None:
                    return n
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return int(round(float(v))) if 0 <= float(v) <= 100000 else None
    try:
        s = str(v).strip().replace(' ', '')
        if ',' in s:
            s = s.replace('.', '').replace(',', '.')
        elif re.fullmatch(r'\d{1,3}(?:\.\d{3})+', s):
            s = s.replace('.', '')
        n = float(s)
        if 0 <= n <= 100000:
            return int(round(n))
    except Exception:
        return None
    return None


def _currency(obj: dict) -> str:
    for key in ('priceCurrency', 'currency'):
        value = obj.get(key)
        if value:
            return str(value).upper()
    spec = obj.get('priceSpecification')
    if isinstance(spec, dict):
        for key in ('priceCurrency', 'currency'):
            value = spec.get(key)
            if value:
                return str(value).upper()
    return ''


def _type_names(obj: dict) -> set[str]:
    typ = obj.get('@type')
    values = typ if isinstance(typ, list) else [typ]
    return {str(x).lower() for x in values if x}


def _offer_price(offer: dict) -> int | None:
    # Never consume lowPrice/highPrice/AggregateOffer as an authoritative
    # retailer acquisition price. A concrete current Offer.price is required.
    n = _numeric(offer.get('price'))
    if n is not None and n >= 100:
        return n
    spec = offer.get('priceSpecification')
    if isinstance(spec, dict):
        n = _numeric(spec.get('price'))
        if n is not None and n >= 100:
            return n
    return None


def _offer_in_stock(offer: dict) -> bool:
    availability = str(offer.get('availability') or '').strip().lower()
    if not availability:
        return False
    tail = availability.rstrip('/').split('/')[-1].replace('-', '').replace('_', '')
    return tail == 'instock'


def _shipping_rate(details: dict, item_price: int) -> tuple[int | None, bool, str]:
    rate = details.get('shippingRate')
    if rate is None:
        rate = details.get('shippingCost')
    if rate is None:
        return None, False, 'NO_STRUCTURED_SHIPPING_RATE'

    rate_currency = ''
    if isinstance(rate, dict):
        rate_currency = str(rate.get('currency') or rate.get('priceCurrency') or '').upper()
    if rate_currency and rate_currency != 'DKK':
        return None, False, 'STRUCTURED_SHIPPING_NON_DKK'

    value = _numeric(rate)
    if value is None:
        return None, False, 'STRUCTURED_SHIPPING_RATE_UNPARSEABLE'

    threshold = details.get('eligibleTransactionVolume')
    if isinstance(threshold, dict):
        threshold_value = _numeric(threshold.get('minValue') or threshold.get('value'))
        threshold_currency = str(
            threshold.get('priceCurrency') or threshold.get('currency') or ''
        ).upper()
        if threshold_currency and threshold_currency != 'DKK':
            return None, False, 'STRUCTURED_SHIPPING_THRESHOLD_NON_DKK'
        if threshold_value is not None and item_price < threshold_value:
            return None, False, 'STRUCTURED_SHIPPING_THRESHOLD_NOT_MET'

    return int(value), True, 'JSON_LD_OFFER_SHIPPING_DETAILS'


def _shipping_from_offer(offer: dict, item_price: int) -> tuple[int | None, bool, str]:
    details = offer.get('shippingDetails')
    rows = details if isinstance(details, list) else [details] if isinstance(details, dict) else []
    exact: list[tuple[int, str]] = []
    for row in rows:
        rate, ok, method = _shipping_rate(row, item_price)
        if ok and rate is not None:
            exact.append((int(rate), method))
    if not exact:
        return None, False, 'NO_EXACT_STRUCTURED_SHIPPING'
    unique = sorted({x[0] for x in exact})
    if len(unique) != 1:
        return None, False, 'AMBIGUOUS_STRUCTURED_SHIPPING_RATES'
    return unique[0], True, exact[0][1]


def _money_from_match(m: re.Match) -> int | None:
    whole = str(m.group(1) or '').replace('.', '').replace(' ', '')
    cents = str(m.group(2) or '')
    try:
        value = float(whole + ('.' + cents if cents else ''))
        return int(round(value))
    except Exception:
        return None


def _shipping_from_text(body: str, item_price: int) -> tuple[int | None, bool, str]:
    """Conservative retailer-page fallback for mandatory delivery cost."""
    text = str(body or '')
    free_hits = []
    for m in FREE_SHIP_RE.finditer(text):
        ctx = text[max(0, m.start() - 100):m.end() + 140]
        threshold = THRESHOLD_RE.search(ctx)
        if threshold:
            t = _money_from_match(threshold)
            if t is None or item_price < t:
                continue
        free_hits.append(ctx)
    if free_hits:
        return 0, True, 'RETAILER_TEXT_FREE_SHIPPING_EXACT'

    values = []
    for m in EXACT_SHIP_RE.finditer(text):
        ctx = text[max(0, m.start() - 50):m.end() + 50]
        if FINANCE_RE.search(ctx):
            continue
        if re.search(r'\bfra\s*$', text[max(0, m.start() - 14):m.start()], re.I):
            continue
        value = _money_from_match(m)
        if value is not None and 0 <= value <= 5000:
            values.append(value)
    unique = sorted(set(values))
    if len(unique) == 1:
        return unique[0], True, 'RETAILER_TEXT_SINGLE_EXACT_SHIPPING'
    if len(unique) > 1:
        return None, False, 'AMBIGUOUS_RETAILER_TEXT_SHIPPING'
    return None, False, 'RETAILER_SHIPPING_UNPROVEN'


def _product_objects(blobs: list) -> list[dict]:
    out = []
    for blob in blobs:
        for obj in retail19.walk(blob):
            if not isinstance(obj, dict):
                continue
            if 'product' in _type_names(obj):
                out.append(obj)
    return out


def _offers(product: dict) -> list[dict]:
    raw = product.get('offers')
    rows = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if 'aggregateoffer' in _type_names(row):
            continue
        if _offer_price(row) is None:
            continue
        out.append(row)
    return out


async def verify_external_retailer(
    context,
    direct_url: str,
    expected_name: str,
    *,
    lead_price_dkk: int | None = None,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    result = {
        'retailer_verified_at': now,
        'external_route_resolved': False,
        'external_resolved': False,
        'retailer_page_verified': False,
        'retailer_identity_verified': False,
        'retailer_price_verified': False,
        'retailer_stock_verified': False,
        'retailer_shipping_verified': False,
        'retailer_item_price_dkk': None,
        'retailer_shipping_dkk': None,
        'retailer_delivered_price_dkk': None,
        'retailer_url': None,
        'retailer_host': None,
        'retailer_sku': None,
        'retailer_mpn': None,
        'retailer_gtin': None,
        'retailer_price_method': None,
        'retailer_shipping_method': None,
        'retailer_authority': 'RETAIL_LEAD',
    }
    parsed = urlparse(str(direct_url or ''))
    if not parsed.scheme.startswith('http') or not parsed.netloc or 'prisjagt.dk' in parsed.netloc.lower():
        result['retailer_error'] = 'NO_EXTERNAL_DIRECT_URL'
        return result

    page = await context.new_page()
    try:
        response = await page.goto(direct_url, wait_until='domcontentloaded', timeout=35000)
        status = int(response.status) if response else None
        result['retailer_http_status'] = status
        final_url = str(page.url)
        host = urlparse(final_url).netloc.lower().removeprefix('www.')
        result['retailer_url'] = final_url
        result['retailer_host'] = host or None
        if not host or 'prisjagt.dk' in host or (status is not None and status >= 400):
            result['retailer_error'] = 'EXTERNAL_RETAILER_PAGE_UNREACHABLE'
            return result
        result['external_route_resolved'] = True

        title = await page.title()
        try:
            h1 = (await page.locator('h1').first.inner_text(timeout=2500)).strip()
        except Exception:
            h1 = ''
        result['retailer_title'] = title[:300]
        result['retailer_h1'] = h1[:300]

        scripts = await page.locator('script[type="application/ld+json"]').all_text_contents()
        blobs = []
        for text in scripts:
            try:
                blobs.append(json.loads(text))
            except Exception:
                continue

        matching_products = []
        for product in _product_objects(blobs):
            pname = str(product.get('name') or '')
            if not pname or not _same_product_identity(expected_name, pname):
                continue
            visible_identity = ' '.join([title, h1, pname])
            if not _same_product_identity(expected_name, visible_identity):
                continue
            matching_products.append(product)

        if not matching_products:
            result['retailer_error'] = 'RETAILER_PRODUCT_IDENTITY_UNPROVEN'
            return result

        result['retailer_identity_verified'] = True
        product = matching_products[0]
        result['retailer_product_name'] = str(product.get('name') or '')[:300]
        result['retailer_sku'] = product.get('sku')
        result['retailer_mpn'] = product.get('mpn')
        result['retailer_gtin'] = (
            product.get('gtin13') or product.get('gtin14') or product.get('gtin12') or product.get('gtin')
        )

        concrete = []
        for prod in matching_products:
            for offer in _offers(prod):
                currency = _currency(offer)
                price = _offer_price(offer)
                if currency != 'DKK' or price is None:
                    continue
                if not _offer_in_stock(offer):
                    continue
                ship, ship_ok, ship_method = _shipping_from_offer(offer, price)
                concrete.append({
                    'price': int(price),
                    'offer': offer,
                    'structured_shipping_dkk': ship if ship_ok else None,
                    'structured_shipping_ok': bool(ship_ok),
                    'structured_shipping_method': ship_method,
                })

        if not concrete:
            result['retailer_error'] = 'NO_CURRENT_IN_STOCK_DKK_OFFER'
            return result

        unique_prices = sorted({x['price'] for x in concrete})
        price_method = 'JSON_LD_PRODUCT_OFFER_PRICE_DKK'
        if len(unique_prices) == 1:
            item_price = unique_prices[0]
        else:
            # Never choose the cheapest among multiple current retailer offers.
            # A live card for this exact retailer may disambiguate only when
            # exactly one concrete in-stock retailer Offer matches it exactly.
            lead = int(lead_price_dkk or 0)
            matched = [p for p in unique_prices if lead > 0 and p == lead]
            if len(matched) != 1:
                result['retailer_error'] = 'AMBIGUOUS_CURRENT_RETAILER_PRICES'
                result['retailer_price_candidates_dkk'] = unique_prices[:12]
                return result
            item_price = matched[0]
            price_method = 'JSON_LD_PRODUCT_OFFER_PRICE_DKK_MATCHED_LIVE_RETAILER_CARD'

        result['retailer_item_price_dkk'] = item_price
        result['retailer_price_verified'] = True
        result['retailer_stock_verified'] = True
        result['retailer_price_method'] = price_method

        same_price_offers = [x for x in concrete if x['price'] == item_price]
        exact_structured = sorted({
            int(x['structured_shipping_dkk'])
            for x in same_price_offers
            if x['structured_shipping_ok'] and x['structured_shipping_dkk'] is not None
        })
        if len(exact_structured) == 1:
            shipping = exact_structured[0]
            shipping_ok = True
            shipping_method = next(
                x['structured_shipping_method']
                for x in same_price_offers
                if x['structured_shipping_ok']
                and int(x['structured_shipping_dkk']) == shipping
            )
        elif len(exact_structured) > 1:
            shipping, shipping_ok, shipping_method = None, False, 'AMBIGUOUS_STRUCTURED_SHIPPING_RATES'
        else:
            try:
                body = (await page.locator('body').inner_text(timeout=6000))[:70000]
            except Exception:
                body = ''
            shipping, shipping_ok, shipping_method = _shipping_from_text(body, item_price)

        result['retailer_shipping_dkk'] = shipping if shipping_ok else None
        result['retailer_shipping_verified'] = bool(shipping_ok)
        result['retailer_shipping_method'] = shipping_method
        if not shipping_ok or shipping is None:
            result['retailer_error'] = 'MANDATORY_SHIPPING_UNPROVEN'
            return result

        delivered = item_price + int(shipping)
        result['retailer_delivered_price_dkk'] = delivered

        if lead_price_dkk:
            tolerance = max(5, int(round(int(lead_price_dkk) * 0.01)))
            if delivered + tolerance < int(lead_price_dkk):
                result['retailer_error'] = (
                    f'RETAILER_TOTAL_BELOW_LIVE_OFFER_FLOOR:{delivered}/{int(lead_price_dkk)}'
                )
                return result

        result['retailer_page_verified'] = True
        result['external_resolved'] = True
        result['retailer_authority'] = 'DIRECT_RETAILER_T1'
        return result
    except Exception as exc:
        result['retailer_error'] = f'{type(exc).__name__}: {str(exc)[:220]}'
        return result
    finally:
        await page.close()
