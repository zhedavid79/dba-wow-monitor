from __future__ import annotations

import json
import re
from collections import Counter
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


def reward_diagnostics():
    devices=get(API_BASE+'/devices/with-counts').json()
    stats=get(API_BASE+'/devices/pool-statistics').json()
    by_cfg={int(x['deviceConfigurationId']):x for x in stats if x.get('deviceConfigurationId') is not None}
    chain_ids=Counter(str(x.get('chainId')) for x in stats)
    weighted_avg_total=0.0; processors_total=0; weighted_median_total=0.0
    for st in stats:
        count=int(st.get('processorCount') or 0)
        processors_total += count
        try: weighted_avg_total += float(st.get('expectedRewardAvg'))*count
        except Exception: pass
        try: weighted_median_total += float(st.get('expectedRewardMedian'))*count
        except Exception: pass
    wanted=('s20 fe','s21 ultra','galaxy s10','oneplus 8t','oneplus 8 pro','oneplus 9')
    rows=[]
    for d in devices:
        label=f"{d.get('company','')} {d.get('model','')}".strip()
        nl=re.sub(r'[^a-z0-9]+',' ',label.lower()).strip()
        if not any(w in nl for w in wanted): continue
        for c in d.get('configurations') or []:
            cid=c.get('id'); st=by_cfg.get(int(cid)) if cid is not None else None
            rows.append({'device':label,'configuration_id':cid,'ram':c.get('ram'),'storage':c.get('storage'),'cpu':c.get('cpu'),'variant':c.get('variant'),'processorCount':None if not st else st.get('processorCount'),'chainId':None if not st else st.get('chainId'),'expectedRewardMin':None if not st else st.get('expectedRewardMin'),'expectedRewardAvg':None if not st else st.get('expectedRewardAvg'),'expectedRewardMedian':None if not st else st.get('expectedRewardMedian'),'expectedRewardMax':None if not st else st.get('expectedRewardMax'),'calculatedAt':None if not st else st.get('calculatedAt')})
    return {'stats_rows':len(stats),'chain_id_counts':dict(chain_ids),'processors_total':processors_total,'weighted_expected_reward_avg_total':weighted_avg_total,'weighted_expected_reward_median_total':weighted_median_total,'selected_configurations':rows}


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
    tests=[API_BASE+'/devices',API_BASE+'/devices/with-counts',API_BASE+'/devices/pool-statistics',METRICS_BASE+'/benchmark/acurast-compute/epoch/current',METRICS_BASE+'/benchmark/acurast-compute/pools',METRICS_BASE+'/benchmark/acurast-compute/stats',METRICS_BASE+'/benchmark/acurast-compute/reward-distribution-settings']
    out={'page_bytes':len(page),'scripts':fetched,'api_base':API_BASE,'metrics_base':METRICS_BASE,'tests':[compact_response(x) for x in tests],'reward_diagnostics':reward_diagnostics(),'route_strings':sorted(routes)[:220],'contexts':contexts}
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
