from __future__ import annotations

import json
from pathlib import Path

SRC=Path("results/wow_strategy_latest.json")
REPORT=Path("results/wow_platform_first_report.md")
REPORT_ALIAS=Path("results/wow_a3_report.md")
EXCLUDED_LISTING_IDS={"7969913":"PURCHASE_ATTEMPTED"}

def money(n): return f"{int(n):,}".replace(",",".")+" kr."
def links(r):
    used=[c for c in (r or {}).get("components",[]) if c.get("source")=="USED ASK"]
    return "—" if not used else "; ".join(f"[{c.get('kind')}: {c.get('name')}]({c.get('url')})" for c in used)
def listing_ids(r): return {str(c.get('listing_id')) for c in (r or {}).get('components',[]) if c.get('listing_id')}
def excluded(r): return bool(listing_ids(r) & set(EXCLUDED_LISTING_IDS))
def line(r):
    if not r:return "Ingen verificeret kandidat i denne kategori."
    extra=f" — foundation {r['foundation']}" if r.get('foundation') else ""
    return f"**{r['route']} — {money(r['tcwp'])} — {r['cpu']} + {r['gpu']} — {r['performance_class']} — upgrade {r['upgradeability']} — Z20 {r['z20_fit']}{extra}**\n\n{r['rationale']}\n\nBrugte kilder: {links(r)}"
def round100(n): return max(0,(int(n)//100)*100)

def add_complete_pc_price_targets(routes):
    """Platform/performance-aware negotiation targets, cross-checked against today's alternatives."""
    actionable=[r for r in routes if not excluded(r)]
    completes=[r for r in actionable if r.get('route')=='COMPLETE_USED_PC']
    if not completes:return actionable
    base=min(int(r['tcwp']) for r in completes)
    for r in completes:
        cpu=int(r.get('cpu_score') or 0); gpu=int(r.get('gpu_score') or 0); grade={'A':4,'B':3,'C':2,'D':1}.get(r.get('upgradeability'),1)
        perf={'UNDER MINIMUM':-400,'ACCEPTABLE':0,'SWEET SPOT':350,'OVERKILL':200}.get(r.get('performance_class'),0)
        cpu_premium=max(-300,min(1400,(cpu-70)*28))
        gpu_premium=max(-300,min(1400,(gpu-50)*24))
        platform_premium={1:0,2:250,3:500,4:900}[grade]
        intrinsic=base+cpu_premium+gpu_premium+platform_premium+perf
        hard_max=round100(min(int(r['tcwp']),intrinsic))
        sweet=round100(hard_max*0.90)
        ask=int(r['tcwp']); r['sweet_spot_price']=sweet; r['hard_max_price']=hard_max; r['price_to_sweet_spot']=ask-sweet
        r['deal_action']='BUY' if ask<=sweet else 'CONSIDER' if ask<=hard_max else 'BID_LOWER'
        r['price_target_basis']='Hardware/platform-aware value anchored to current complete-PC market; sweet spot = 10% margin below hard max.'
    return actionable

def best(routes,pred,key=lambda r:int(r.get('strategic_effective_cost',r['tcwp']))):
    return min([r for r in routes if pred(r)],key=key,default=None)

def bom_cell(r,kind):
    xs=[c for c in r.get('components',[]) if c.get('kind')==kind]
    if not xs:return '—'
    c=xs[0]; src='USED' if c.get('source') in {'USED ASK','DBA_USED_LIVE'} else 'NEW'
    name=str(c.get('name') or kind).replace('|','/')
    if c.get('url'): name=f"[{name}]({c['url']})"
    return f"{src}: {name} ({money(c.get('price',0))})"

def route_mix(r):
    used=sum(1 for c in r.get('components',[]) if c.get('source') in {'USED ASK','DBA_USED_LIVE'})
    new=sum(1 for c in r.get('components',[]) if c.get('source') in {'NEW RETAIL','NEW_RETAIL'})
    return f"{used}U/{new}N"

def main():
    d=json.loads(SRC.read_text(encoding='utf-8'))
    assert d.get('gate_passed') is True and d.get('model_version')=='DBA-WOW-PLATFORM-FIRST-V16'
    ranked=add_complete_pc_price_targets(list(d.get('ranked') or [])); ranked.sort(key=lambda r:(int(r.get('strategic_effective_cost',r['tcwp'])),int(r['tcwp'])))
    buy_now=ranked[0] if ranked else None; foundation=best(ranked,lambda r:r.get('foundation')=='AM5_B650_B850_MATX_WIFI_4DIMM'); cheapest=min(ranked,key=lambda r:int(r['tcwp']),default=None); opportunistic=best(ranked,lambda r:any(c.get('kind')=='GPU' and c.get('source')=='USED ASK' for c in r.get('components') or [])); complete=best(ranked,lambda r:r.get('route')=='COMPLETE_USED_PC'); donor=best(ranked,lambda r:r.get('route')=='USED_PC_PLUS_FUTURE_UPGRADE'); hybrid=best(ranked,lambda r:r.get('route') in {'HYBRID_USED_NEW','PLATFORM_FIRST_AM5'})
    lines=['# FULDT PÅLIDELIG DBA-PRISRAPPORT — WoW PLATFORM-FIRST V16','',f"Generated: {d.get('generated_at')}",'Mål: WoW Classic/Cataclysm, 3840×1600/75 Hz. Jonsbo Z20 er ønsket slutkabinet.','Strategi: platform først, performance opportunistisk.','Hver build-række nedenfor er en komplet Working-PC BOM. USED ASK og NEW RETAIL vises komponent for komponent.',f"Ekskluderet fra ranking: {', '.join(sorted(EXCLUDED_LISTING_IDS))} ({', '.join(EXCLUDED_LISTING_IDS.values())}).",'',f"WAIT / BUY: **{'BUY' if buy_now and buy_now.get('foundation_score',0)>=100 else 'WAIT_FOR_FOUNDATION_OR_EXCEPTIONAL_COMPLETE_PC'}**",'','## 🏆 BUY NOW','',line(buy_now),'','## 🧱 BEST FOUNDATION','',line(foundation),'','## 💰 CHEAPEST VIABLE','',line(cheapest),'','## 🎯 BEST OPPORTUNISTIC BUY','',line(opportunistic),'','## 🖥️ BEST COMPLETE PC','',line(complete),'','## 🔧 BEST DONOR/UPGRADE ROUTE','',line(donor),'','## ⚡ BEST HYBRID BUILD','',line(hybrid),'']
    lines += ['## Komplet løsningsmatrix — nye + brugte dele','','| # | TCWP | Route | CPU | GPU | Bundkort/platform | RAM | PSU | SSD | Kabinet | Køler | WoW | Upgrade | Z20 | Mix |','|---:|---:|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    selected=[]; per_route={}
    for r in ranked:
        rt=r.get('route'); n=per_route.get(rt,0)
        if n>=15: continue
        selected.append(r); per_route[rt]=n+1
        if len(selected)>=60: break
    for i,r in enumerate(selected,1):
        if r.get('route')=='COMPLETE_USED_PC':
            cpu=f"USED: {r.get('cpu')}"; gpu=f"USED: {r.get('gpu')}"; board=ram=psu=ssd=case=cooler='inkl. i PC / ikke særskilt verificeret'
        else:
            cpu=bom_cell(r,'CPU') if bom_cell(r,'CPU')!='—' else bom_cell(r,'PLATFORM_BUNDLE'); gpu=bom_cell(r,'GPU'); board=bom_cell(r,'MOTHERBOARD') if bom_cell(r,'MOTHERBOARD')!='—' else bom_cell(r,'PLATFORM_BUNDLE'); ram=bom_cell(r,'RAM'); psu=bom_cell(r,'PSU'); ssd=bom_cell(r,'STORAGE'); case=bom_cell(r,'CASE'); cooler=bom_cell(r,'COOLER')
        lines.append(f"| {i} | **{money(r['tcwp'])}** | {r.get('route')} | {cpu} | {gpu} | {board} | {ram} | {psu} | {ssd} | {case} | {cooler} | {r.get('performance_class')} | {r.get('upgradeability')} | {r.get('z20_fit')} | {route_mix(r)} |")
    lines += ['','## Komplette PC’er — hvad bør de koste?','','| PC | T1 ASK | Sweet-spot pris | Hard max | Til sweet spot | Handling | WoW | Upgrade | Z20 |','|---|---:|---:|---:|---:|---|---|---|---|']
    complete_by_ask=sorted([r for r in ranked if r.get('route')=='COMPLETE_USED_PC' and r.get('sweet_spot_price') is not None],key=lambda r:int(r['tcwp']))
    for r in complete_by_ask[:40]:
        name=f"{r.get('cpu')} + {r.get('gpu')}"; used=[c for c in r.get('components',[]) if c.get('source')=='USED ASK']
        if used and used[0].get('url'): name=f"[{name}]({used[0]['url']})"
        gap=int(r.get('price_to_sweet_spot') or 0); gap_txt=("+" if gap>0 else "")+money(gap)
        lines.append(f"| {name} | {money(r['tcwp'])} | **{money(r['sweet_spot_price'])}** | {money(r['hard_max_price'])} | {gap_txt} | **{r['deal_action']}** | {r['performance_class']} | {r['upgradeability']} | {r['z20_fit']} |")
    lines += ['','## Samlet ranking — færdige løsninger','','| # | TCWP | Strategic cost | Route | CPU | GPU | WoW | Upgrade | Z20 | Foundation | Brugte live-kilder |','|---:|---:|---:|---|---|---|---|---|---|---|---|']
    for i,r in enumerate(ranked[:60],1): lines.append(f"| {i} | {money(r['tcwp'])} | {money(r.get('strategic_effective_cost',r['tcwp']))} | {r['route']} | {r['cpu']} | {r['gpu']} | {r['performance_class']} | {r['upgradeability']} | {r['z20_fit']} | {r.get('foundation','—')} | {links(r)} |")
    lines += ['','## Pris- og evidensregel','','Alle USED ASK-komponenter i ranking kommer fra live T0→T1-verificerede DBA listing-objects. Funktionelt defekte dele og accessory-listings forklædt som CPU/GPU er hard-excluded. NEW RETAIL er separat mærket. Search snippets/cached priser er aldrig prisbevis. Sweet-spot/hard-max er beslutningsestimater og ændrer aldrig T1 ASK.','']
    text='\n'.join(lines)
    REPORT.write_text(text,encoding='utf-8')
    REPORT_ALIAS.write_text(text,encoding='utf-8')
    print(json.dumps({'report':True,'canonical_report':str(REPORT),'alias_report':str(REPORT_ALIAS),'model':d['model_version'],'ranked':len(ranked),'matrix_rows':len(selected),'complete_price_targets':len(complete_by_ask)},ensure_ascii=False))

if __name__=='__main__':main()
