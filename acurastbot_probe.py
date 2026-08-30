from __future__ import annotations

import json
import re
from urllib.parse import urljoin

import requests

BASE='https://acurastbot.com'
API_BASE='https://api.acurastbot.com'
HEADERS={'User-Agent':'Mozilla/5.0','Accept':'text/html,application/javascript,application/json,*/*'}


def get(url:str)->requests.Response:
    r=requests.get(url,headers=HEADERS,timeout=20)
    r.raise_for_status()
    return r


def clean(s:str)->str:
    return re.sub(r'\s+',' ',s).strip()


def main():
    page=get(BASE+'/devices').text
    scripts=[]
    for src in re.findall(r'<script[^>]+src=["\']([^"\']+)',page,re.I):
        u=urljoin(BASE,src)
        if u not in scripts:scripts.append(u)

    route_strings=set(); contexts=[]; fetched=[]
    needles=('api.acurastbot.com','/devices','devices?','benchmark','reward','processor','device-types','deviceTypes')
    for u in scripts:
        try:
            text=get(u).text
            fetched.append({'url':u,'bytes':len(text)})
            if 'acurastbot.com/assets/' not in u: continue

            # Collect quoted strings that look like relative or absolute API routes.
            for q in re.findall(r'["\'`]([^"\'`]{1,240})["\'`]',text):
                low=q.lower()
                if any(k in low for k in ('device','benchmark','reward','processor')) and ('/' in q or 'api.' in low):
                    route_strings.add(q)

            # Keep compact context around high-value route/API occurrences.
            low=text.lower()
            for needle in needles:
                start=0
                while len(contexts)<120:
                    idx=low.find(needle.lower(),start)
                    if idx<0: break
                    contexts.append({'needle':needle,'context':clean(text[max(0,idx-450):min(len(text),idx+650)])})
                    start=idx+len(needle)
        except Exception as e:
            fetched.append({'url':u,'error':repr(e)})

    # Build only concrete-looking GET candidates; do not invent routes.
    concrete=[]
    for s in sorted(route_strings):
        val=s.replace('\\/','/')
        if val.startswith(API_BASE): concrete.append(val)
        elif val.startswith('/') and any(x in val.lower() for x in ('device','benchmark','reward','processor')):
            concrete.append(API_BASE+val)

    # De-duplicate while preserving order and lightly test only literal routes without placeholders.
    seen=set(); tested=[]
    for url in concrete:
        if url in seen or any(c in url for c in ('${','{','}','`')): continue
        seen.add(url)
        if len(tested)>=30: break
        try:
            r=requests.get(url,headers=HEADERS,timeout=12)
            tested.append({'url':url,'status':r.status_code,'content_type':r.headers.get('content-type'),'bytes':len(r.content),'preview':clean(r.text[:500])})
        except Exception as e:
            tested.append({'url':url,'error':repr(e)})

    out={
        'page_bytes':len(page),
        'scripts':fetched,
        'api_base':API_BASE,
        'route_strings':sorted(route_strings)[:300],
        'tested_literal_routes':tested,
        'contexts':contexts[:120],
    }
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
