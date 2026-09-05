from __future__ import annotations

import json
import re
from pathlib import Path

import dba_strategy_report as strategy_report

STRATEGY = Path('results/wow_strategy_latest.json')
PARTS = Path('results/z20_parts_latest.json')
REPORT = Path('results/wow_platform_first_report.md')
ALIAS = Path('results/wow_a3_report.md')

# Verified current retail choices. Storage capacity is deliberately NOT fixed at 1 TB.
RETAIL_ALTS = {
    'STORAGE': [
        {'name':'Intenso Premium M.2 SSD 250GB NVMe','price':426,'url':'https://www.proshop.dk/SSD/Intenso-Premium-M2-SSD-250GB-PCIe-30-M2-2280/','source':'NEW RETAIL','capacity_gb':250,'tier':'MINIMUM','pros':'Lowest TCWP; NVMe; sufficient as a Windows + WoW bridge drive.','cons':'Little spare capacity; likely future storage upgrade.'},
        {'name':'PNY CS1030 M.2 NVMe 500GB','price':689,'url':'https://www.proshop.dk/SSD','source':'NEW RETAIL','capacity_gb':500,'tier':'VALUE','pros':'More comfortable capacity while keeping storage spend modest.','cons':'Costs more without meaningful WoW FPS gain.'},
        {'name':'Kingston NV3 1TB M.2 NVMe','price':1212,'url':'https://www.proshop.dk/SSD/Kingston-NV3-SSD-1TB-PCIe-40-M2-2280/3284682','source':'NEW RETAIL','capacity_gb':1000,'tier':'COMFORT','pros':'Plenty of space and no near-term storage upgrade.','cons':'Large premium that does not improve WoW FPS.'},
    ],
}

# Regression fixture: listing was inspected and sells the cooler, not the named CPU.
KNOWN_ACCESSORY_FALSE_POSITIVES = {'11596289'}
CPU_ACCESSORY = re.compile(r'\b(?:k(?:ø|oe)ler|cooler|heatsink|vandblok|waterblock|aio|radiator|mount(?:ing)?\s*(?:kit|bracket)|beslag|backplate|tom\s*(?:kasse|emballage)|empty\s*box)\b', re.I)

def money(n): return f"{int(n):,}".replace(',','.')+' kr.'
def cap(title):
    t=title or ''
    m=re.search(r'\b(2|4)\s*x\s*(8|16|32)\s*gb\b',t,re.I)
    if m:return int(m.group(1))*int(m.group(2))
    vals=[int(x) for x in re.findall(r'\b(8|16|32|64)\s*gb\b',t,re.I)]
    return max(vals) if vals else 0

def live_ram_alternatives(parts):
    out=[]
    for r in parts:
        if r.get('kind')!='RAM' or r.get('ram_compatibility')!='DESKTOP_COMPATIBLE':continue
        title=str(r.get('title') or '')
        if 'ddr5' not in title.lower():continue
        capacity=cap(title)
        if capacity < 16:continue
        price=int(r.get('ask_t1') or 0)
        if price<=0 or not r.get('url'):continue
        out.append({'name':title,'price':price,'url':r['url'],'source':'USED ASK','listing_id':str(r.get('listing_id') or ''),'capacity_gb':capacity,'tier':'BRIDGE' if capacity<32 else 'VALUE','pros':('Lowest-cost functional bridge; preserves upgrade budget.' if capacity<32 else '32 GB capacity suitable for long-term use.'),'cons':('16 GB is adequate rather than luxurious; 32 GB may be desirable later.' if capacity<32 else 'Used RAM must be memory-tested; speed/timings may not be optimal.')})
    return sorted(out,key=lambda x:(x['price'], -x['capacity_gb']))[:8]

def component_alts(route, ram_alts):
    result={}
    for kind in ('CPU','GPU','MOTHERBOARD','RAM','PSU','STORAGE','CASE','COOLER'):
        cur=next((c for c in route.get('components',[]) if c.get('kind')==kind),None)
        opts=[]
        if cur:
            opts.append({'name':cur.get('name',kind),'price':int(cur.get('price') or 0),'url':cur.get('url'),'source':cur.get('source'),'tier':'CURRENT','pros':'Current selected BOM component.','cons':'Compare against alternatives before buying.'})
        if kind=='STORAGE': opts.extend(RETAIL_ALTS['STORAGE'])
        if kind=='RAM': opts.extend(ram_alts)
        result[kind]=opts
    return result

def enrich_cross_route_alts(routes):
    pools={k:[] for k in ('CPU','GPU','MOTHERBOARD','PSU','CASE','COOLER')}
    for r in routes:
        for c in r.get('components') or []:
            k=c.get('kind')
            if k not in pools:continue
            key=(c.get('name'),int(c.get('price') or 0),c.get('url'))
            if not any((x['name'],x['price'],x['url'])==key for x in pools[k]):
                pools[k].append({'name':c.get('name',k),'price':int(c.get('price') or 0),'url':c.get('url'),'source':c.get('source'),'tier':'ALTERNATIVE','pros':'Alternative already present in a complete verified solution.','cons':'Re-check compatibility with this exact build before substitution.'})
    for k in pools:pools[k]=sorted(pools[k],key=lambda x:x['price'])[:5]
    for r in routes:
        for k,opts in pools.items():r.setdefault('component_alternatives',{}).setdefault(k,[]).extend(opts)

def main():
    d=json.loads(STRATEGY.read_text(encoding='utf-8'))
    p=json.loads(PARTS.read_text(encoding='utf-8'))
    routes=[]
    for r in d.get('ranked') or []:
        bad=False
        for c in r.get('components') or []:
            if c.get('kind')=='CPU' and (str(c.get('listing_id')) in KNOWN_ACCESSORY_FALSE_POSITIVES or CPU_ACCESSORY.search(str(c.get('name') or ''))):bad=True
        if bad:continue
        routes.append(r)
    ram_alts=live_ram_alternatives(p.get('opportunities') or [])
    storage_default=min(RETAIL_ALTS['STORAGE'],key=lambda x:x['price'])
    for r in routes:
        if r.get('route')=='PLATFORM_FIRST_AM5':
            comps=r.get('components') or []
            old=next((c for c in comps if c.get('kind')=='STORAGE'),None)
            if old and int(old.get('price') or 0)>storage_default['price']:
                old.update({'name':storage_default['name'],'price':storage_default['price'],'url':storage_default['url'],'source':'NEW RETAIL','capacity_gb':storage_default['capacity_gb'],'storage_tier':'MINIMUM'})
                r['tcwp']=sum(int(c.get('price') or 0) for c in comps)
            r['component_alternatives']=component_alts(r,ram_alts)
    enrich_cross_route_alts(routes)
    routes.sort(key=lambda r:(int(r.get('strategic_effective_cost',r['tcwp'])),int(r['tcwp'])))
    d['ranked']=routes
    d['storage_policy']='CAPACITY_FLEXIBLE_VALUE_FIRST_250_500_1000'
    d['component_alternatives_policy']='SHOW_PRICE_LINK_PROS_CONS_PER_PART'
    STRATEGY.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')

    # Regenerate the canonical report from the FINAL filtered/enriched ranking before
    # appending alternatives. This prevents stale BUY NOW / BEST FOUNDATION sections.
    strategy_report.main()
    text=REPORT.read_text(encoding='utf-8')
    lines=['','## Build-alternativer pr. komponent','','SSD er ikke låst til 1 TB. Basis-build bruger billigste tilstrækkelige verificerede valg; 500 GB og 1 TB vises som komfort-alternativer. RAM må tilsvarende bruge en billig 16 GB bridge, når det reducerer TCWP væsentligt, mens 32 GB vises som langsigtet alternativ.','']
    builds=[r for r in routes if r.get('route') in {'PLATFORM_FIRST_AM5','HYBRID_USED_NEW','USED_BUILD'}][:12]
    for i,r in enumerate(builds,1):
        lines += [f"### Build {i}: {r.get('cpu')} + {r.get('gpu')} — {money(r['tcwp'])}",'', '| Del | Mulighed | Pris | Kilde | Fordel | Ulempe |','|---|---|---:|---|---|---|']
        alts=r.get('component_alternatives') or {}
        for kind in ('CPU','GPU','MOTHERBOARD','RAM','PSU','STORAGE','CASE','COOLER'):
            seen=set()
            for a in (alts.get(kind) or [])[:4]:
                key=(a.get('name'),a.get('price'))
                if key in seen:continue
                seen.add(key)
                name=str(a.get('name') or kind).replace('|','/')
                if a.get('url'):name=f"[{name}]({a['url']})"
                lines.append(f"| {kind} | {name} | {money(a.get('price',0))} | {a.get('source','—')} | {a.get('pros','—')} | {a.get('cons','—')} |")
        lines.append('')
    text=text+'\n'.join(lines)+'\n'
    REPORT.write_text(text,encoding='utf-8'); ALIAS.write_text(text,encoding='utf-8')
    print(json.dumps({'ok':True,'routes':len(routes),'builds_with_alternatives':len(builds),'ram_alternatives':len(ram_alts),'storage_default_gb':storage_default['capacity_gb']},ensure_ascii=False))

if __name__=='__main__':main()
