from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected one match, got {count}')
    return text.replace(old, new, 1)


auth_path = Path('dba_retail_authority_v22.py')
auth = auth_path.read_text(encoding='utf-8')

auth = replace_once(
    auth,
    "EXACT_SHIP_RE = re.compile(\n    r'\\b(?:fragt|levering|shipping)\\s*(?!fra\\b)(?:kun\\s*)?'\n    r'(\\d{1,3}(?:[. ]\\d{3})*|\\d{1,4})(?:[,.](\\d{1,2}))?\\s*(?:kr\\.?|DKK)',\n    re.I,\n)\n",
    "EXACT_SHIP_RE = re.compile(\n    r'\\b(?:fragt|levering|shipping)(?:\\s*\\([^\\)\\n]{1,40}\\))?\\s*(?!fra\\b)(?:kun\\s*)?'\n    r'(\\d{1,3}(?:[. ]\\d{3})*|\\d{1,4})(?:[,.](\\d{1,2}))?\\s*(?:kr\\.?|DKK)',\n    re.I,\n)\n",
    'shipping regex',
)

marker = "\ndef _numeric(v) -> int | None:\n"
helpers = r'''

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
        # Chipset-only matches such as B650M/B850M cannot on their own prove
        # which motherboard model is on the retailer page.
        if re.fullmatch(r'[abxhqz]\d{3,4}[a-z]*', compact):
            continue
        if len(compact) >= 3:
            out.add(token)
    return out


def _same_product_identity(expected: str, actual: str) -> bool:
    """Strict identity with a model-token escape hatch for retailer naming drift.

    The legacy overlap check remains the first gate.  The fallback requires
    the same brand plus at least one discriminative alphanumeric model token;
    generic capacities, interface generations and chipset names cannot satisfy
    it.  This handles naming differences such as "RM750e (2025) ATX 3.1" vs
    "RMe Series RM750e PSU" without accepting a different model.
    """
    if retail19.identity_ok(expected, actual):
        return True
    expected_brand = _brand_token(expected)
    actual_tokens = set(_identity_tokens(actual))
    if not expected_brand or expected_brand not in actual_tokens:
        return False
    expected_models = _model_tokens(expected)
    actual_models = _model_tokens(actual)
    return bool(expected_models and expected_models & actual_models)
'''
auth = replace_once(auth, marker, helpers + marker, 'identity helper insertion')

auth = replace_once(
    auth,
    "            if not pname or not retail19.identity_ok(expected_name, pname):\n                continue\n            visible_identity = ' '.join([title, h1, pname])\n            if not retail19.identity_ok(expected_name, visible_identity):\n                continue\n",
    "            if not pname or not _same_product_identity(expected_name, pname):\n                continue\n            visible_identity = ' '.join([title, h1, pname])\n            if not _same_product_identity(expected_name, visible_identity):\n                continue\n",
    'identity gate',
)

auth = replace_once(
    auth,
    "        unique_prices = sorted({x['price'] for x in concrete})\n        if len(unique_prices) != 1:\n            result['retailer_error'] = 'AMBIGUOUS_CURRENT_RETAILER_PRICES'\n            result['retailer_price_candidates_dkk'] = unique_prices[:12]\n            return result\n\n        item_price = unique_prices[0]\n        result['retailer_item_price_dkk'] = item_price\n        result['retailer_price_verified'] = True\n        result['retailer_stock_verified'] = True\n        result['retailer_price_method'] = 'JSON_LD_PRODUCT_OFFER_PRICE_DKK'\n",
    "        unique_prices = sorted({x['price'] for x in concrete})\n        price_method = 'JSON_LD_PRODUCT_OFFER_PRICE_DKK'\n        if len(unique_prices) == 1:\n            item_price = unique_prices[0]\n        else:\n            # Multiple concrete in-stock Offer prices are not resolved by\n            # choosing the cheapest.  The retailer-specific live comparison\n            # card may only disambiguate when exactly one direct retailer\n            # Offer has the exact same current item price.\n            lead = int(lead_price_dkk or 0)\n            matched = [p for p in unique_prices if lead > 0 and p == lead]\n            if len(matched) != 1:\n                result['retailer_error'] = 'AMBIGUOUS_CURRENT_RETAILER_PRICES'\n                result['retailer_price_candidates_dkk'] = unique_prices[:12]\n                return result\n            item_price = matched[0]\n            price_method = 'JSON_LD_PRODUCT_OFFER_PRICE_DKK_MATCHED_LIVE_RETAILER_CARD'\n\n        result['retailer_item_price_dkk'] = item_price\n        result['retailer_price_verified'] = True\n        result['retailer_stock_verified'] = True\n        result['retailer_price_method'] = price_method\n",
    'price disambiguation',
)

auth_path.write_text(auth, encoding='utf-8')

offers_path = Path('dba_retail_offers_v22.py')
offers = offers_path.read_text(encoding='utf-8')
offers = replace_once(
    offers,
    "                    retailer = await authority22.verify_external_retailer(\n                        context,\n                        str(r['direct_url']),\n                        name,\n                        lead_price_dkk=product_floor,\n                    )\n",
    "                    retailer = await authority22.verify_external_retailer(\n                        context,\n                        str(r['direct_url']),\n                        name,\n                        lead_price_dkk=int(r['displayed_price_dkk']),\n                    )\n",
    'retailer-specific lead',
)
offers = replace_once(
    offers,
    "        context = await browser.new_context(locale='da-DK')\n",
    "        context = await browser.new_context(\n            locale='da-DK',\n            user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36',\n            extra_http_headers={'Accept-Language': 'da-DK,da;q=0.9,en;q=0.8'},\n        )\n",
    'offers normal UA',
)
offers_path.write_text(offers, encoding='utf-8')

availability_path = Path('dba_retail_availability_v22.py')
availability = availability_path.read_text(encoding='utf-8')
availability = replace_once(
    availability,
    "        context = await browser.new_context(locale='da-DK')\n",
    "        context = await browser.new_context(\n            locale='da-DK',\n            user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36',\n            extra_http_headers={'Accept-Language': 'da-DK,da;q=0.9,en;q=0.8'},\n        )\n",
    'availability normal UA',
)
availability_path.write_text(availability, encoding='utf-8')

print('patched V22 retailer identity, price disambiguation, shipping and browser headers')
