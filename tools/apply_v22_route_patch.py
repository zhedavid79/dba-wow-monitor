from __future__ import annotations

import re
from pathlib import Path

path = Path('dba_retail_offers_v22.py')
text = path.read_text(encoding='utf-8')

replacement = r'''async def resolve(context, href: str, seller_hint: str | None = None) -> dict:
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
'''

pattern = re.compile(r'async def resolve\(context, href: str, seller_hint: str \| None = None\) -> dict:\n.*?\n(?=def sane_offer\()', re.S)
new_text, count = pattern.subn(replacement + '\n', text, count=1)
if count != 1:
    raise SystemExit(f'expected exactly one resolve() block, replaced={count}')

path.write_text(new_text, encoding='utf-8')
print('patched dba_retail_offers_v22.py resolve()')
