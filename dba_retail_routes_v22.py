from __future__ import annotations

import re
from urllib.parse import urlparse

# Retailer route adapters are discovery-only.  They translate a retailer name
# plus the numeric offer/product identifier already exposed by the live
# Prisjagt offer card into candidate retailer URLs.  A candidate route has no
# purchasing authority until dba_retail_authority_v22 verifies the retailer
# product page itself (identity, current DKK Offer.price, InStock, mandatory
# shipping and delivered-price arithmetic).

_ID_RE = re.compile(r'^\d{4,12}$')


def _seller_key(value: str | None) -> str:
    return re.sub(r'[^a-z0-9]+', '', str(value or '').lower())


def candidate_urls(seller: str | None, offer_id: str | None) -> list[str]:
    oid = str(offer_id or '').strip()
    if not _ID_RE.fullmatch(oid):
        return []

    key = _seller_key(seller)
    if key == 'proshop':
        return [f'https://www.proshop.dk/{oid}']
    if key == 'happii':
        return [f'https://www.happii.dk/{oid}']
    if key == 'komplett':
        return [f'https://www.komplett.dk/product/{oid}']
    return []


def external_http_url(url: str | None) -> bool:
    parsed = urlparse(str(url or ''))
    host = parsed.netloc.lower().removeprefix('www.')
    return bool(
        parsed.scheme in {'http', 'https'}
        and host
        and 'prisjagt.dk' not in host
    )


def route_method(seller: str | None, offer_id: str | None) -> str:
    return 'SELLER_OFFER_ID_RETAILER_ROUTE' if candidate_urls(seller, offer_id) else 'NO_RETAILER_ROUTE_ADAPTER'
