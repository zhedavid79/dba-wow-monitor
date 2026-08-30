from __future__ import annotations
import json
from pathlib import Path
import requests
import dba_report_v2 as base

IDS = ['7969913','22950485','22894303','24247594','24400646','19011254']

def compact_item(item):
    keep = {
        'title': item.get('title'),
        'price': item.get('price'),
        'disposed': item.get('disposed'),
        'adViewTypeLabel': item.get('adViewTypeLabel'),
        'description': item.get('description'),
        'meta': item.get('meta'),
        'category': item.get('category'),
    }
    return keep

s=requests.Session()
out={}
for lid in IDS:
    try:
        data=base.getj(s, base.ITEM_URL.format(id=lid))
        out[lid]=compact_item(data.get('itemData') or {})
    except Exception as e:
        out[lid]={'error':str(e)}
Path('results').mkdir(exist_ok=True)
Path('results/item_inspection.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out,ensure_ascii=False,indent=2))
