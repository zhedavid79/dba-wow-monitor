from __future__ import annotations

import json
import re
from urllib.parse import urljoin

import requests

BASE='https://acurastbot.com'
API_BASE='https://api.acurastbot.com'
METRICS_BASE='https://metrics.acurastbot.com'
HEADERS={'User-Agent':'Mozilla/5.0','Accept':'text/html,application/javascript,application/json,*/*'}


def get(url:str)->requests.Response:
    r=requests.get(url,headers=HEADERS,timeout=20)
    r.raise_for_status()
    return r


def compact_response(url:str)->dict:
    try:
        r=requests.get(url,headers=HEADERS,timeout=20)
        preview=re.sub(r'\s+',' ',r.text[:1200]).strip()
        return {'url':url,'status':r.status_code,'content_type':r.headers.get('content-type'),'bytes':len(r.content),'preview':preview}
    except Exception as e:
        return {'url':url,'error':repr(e)}


def main():
    page=get(BASE+'/devices').text
    scripts=[]
    for src in re.findall(r'<script[^>]+src=["\']([^"\']+)',page,re.I):
        u=urljoin(BASE,src)
        if u not in scripts:scripts.append(u)
    routes=set(); contexts=[]; fetched=[]
    for u in scripts:
        try:
            text=get(u).text; fetched.append({'url':u,'bytes':len(text)})
            if 'acurastbot.com/assets/' not in u: continue
            for q in re.findall(r'["\'`]([^"\'`]{1,240})["\'`]',text):
                if any(k in q.lower() for k in ('device','benchmark','reward','processor')) and '/' in q: routes.add(q)
            for needle in ('VITE_WEBSITE_BACKEND_URL','VITE_METRICS_API_URL','getAllDevices','getAllDevicesWithCounts','getPoolStatistics','getCurrentEpoch','getPools','getStats'):
                start=0
                while len(contexts)<80:
                    idx=text.find(needle,start)
                    if idx<0: break
                    contexts.append({'needle':needle,'context':re.sub(r'\s+',' ',text[max(0,idx-350):min(len(text),idx+700)]).strip()})
                    start=idx+len(needle)
        except Exception as e: fetched.append({'url':u,'error':repr(e)})

    tests=[
        API_BASE+'/devices',
        API_BASE+'/devices/with-counts',
        API_BASE+'/devices/pool-statistics',
        METRICS_BASE+'/benchmark/acurast-compute/epoch/current',
        METRICS_BASE+'/benchmark/acurast-compute/pools',
        METRICS_BASE+'/benchmark/acurast-compute/stats',
        METRICS_BASE+'/benchmark/acurast-compute/reward-distribution-settings',
    ]
    out={'page_bytes':len(page),'scripts':fetched,'api_base':API_BASE,'metrics_base':METRICS_BASE,'tests':[compact_response(x) for x in tests],'route_strings':sorted(routes)[:220],'contexts':contexts}
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
