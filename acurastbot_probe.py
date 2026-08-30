from __future__ import annotations

import json
import re
from urllib.parse import urljoin

import requests

BASE='https://acurastbot.com'
HEADERS={'User-Agent':'Mozilla/5.0','Accept':'text/html,application/javascript,*/*'}


def get(url:str)->requests.Response:
    r=requests.get(url,headers=HEADERS,timeout=20)
    r.raise_for_status()
    return r


def main():
    page=get(BASE+'/devices').text
    scripts=[]
    for src in re.findall(r'<script[^>]+src=["\']([^"\']+)',page,re.I):
        u=urljoin(BASE,src)
        if u not in scripts:scripts.append(u)
    candidates=set()
    patterns=[
        r'https?://[^"\'`\s]+',
        r'["\'](/api/[^"\']+)["\']',
        r'["\']([^"\']*(?:device|benchmark|reward)[^"\']*(?:api|json)[^"\']*)["\']',
        r'["\']([^"\']*(?:api|graphql)[^"\']*(?:device|benchmark|reward)[^"\']*)["\']',
    ]
    fetched=[]
    for u in scripts:
        try:
            text=get(u).text
            fetched.append({'url':u,'bytes':len(text)})
            for pat in patterns:
                for m in re.findall(pat,text,re.I):
                    val=m if isinstance(m,str) else m[0]
                    if any(x in val.lower() for x in ('device','benchmark','reward','api','graphql','supabase')):
                        candidates.add(val[:500])
        except Exception as e:
            fetched.append({'url':u,'error':repr(e)})
    out={'page_bytes':len(page),'scripts':fetched,'candidates':sorted(candidates)}
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
