from __future__ import annotations

import asyncio
import json
from playwright.async_api import async_playwright

TESTS = [
    ('Komplett', '1317727', 'ASUS TUF GAMING B850M-PLUS WIFI', [
        'https://www.komplett.dk/product/1317727',
    ]),
    ('Proshop', '3370565', 'MSI MAG A850GL PCIE5 II', [
        'https://www.proshop.dk/3370565',
        'https://www.proshop.dk/?s=3370565',
        'https://www.proshop.dk/Search?search=3370565',
        'https://www.proshop.dk/Stroemforsyning/x/3370565',
    ]),
    ('Happii', '3324875', 'ASUS TUF GAMING B850M-PLUS WIFI', [
        'https://www.happii.dk/3324875',
        'https://www.happii.dk/?s=3324875',
        'https://www.happii.dk/Search?search=3324875',
        'https://www.happii.dk/Bundkort/x/3324875',
    ]),
]


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        c = await b.new_context(locale='da-DK')
        for seller, offer_id, expected, urls in TESTS:
            for url in urls:
                page = await c.new_page()
                rec = {'seller': seller, 'offer_id': offer_id, 'test_url': url}
                try:
                    resp = await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                    await page.wait_for_timeout(500)
                    title = await page.title()
                    body = ' '.join((await page.locator('body').inner_text(timeout=3000)).split())[:3000]
                    rec.update({
                        'status': int(resp.status) if resp else None,
                        'final_url': page.url,
                        'title': title[:240],
                        'offer_id_in_page': offer_id in (page.url + ' ' + title + ' ' + body),
                        'expected_name_in_page': all(t.lower() in body.lower() for t in expected.split()[:3]),
                        'body_head': body[:600],
                    })
                except Exception as exc:
                    rec['error'] = f'{type(exc).__name__}:{str(exc)[:180]}'
                    rec['final_url'] = page.url
                finally:
                    await page.close()
                print(json.dumps(rec, ensure_ascii=False), flush=True)
        await c.close(); await b.close()

if __name__ == '__main__':
    asyncio.run(main())
