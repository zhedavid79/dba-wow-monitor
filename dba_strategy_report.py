from __future__ import annotations

import json
from pathlib import Path

SRC=Path("results/wow_strategy_latest.json")
REPORT=Path("results/wow_a3_report.md")

# User-specific procurement state: these listings are no longer actionable candidates.
EXCLUDED_LISTING_IDS={"7969913":"PURCHASE_ATTEMPTED"}


def money(n): return f"{int(n):,}".replace(",",".")+" kr."
def links(r):
    used=[c for c in (r or {}).get("components",[]) if c.get("source")=="USED ASK"]
    return "—" if not used else "; ".join(f"[{c.get('kind')}: {c.get('name')}]({c.get('url')})" for c in used)

def listing_ids(r):
    return {str(c.get('listing_id')) for c in (r or {}).get('components',[]) if c.get('listing_id')}

def excluded(r):
    return bool(listing_ids(r) & set(EXCLUDED_LISTING_IDS))

def line(r):
    if not r:return "Ingen verificeret kandidat i denne kategori."
    extra=""
    if r.get('foundation'): extra=f" — foundation {r['foundation']}"
    return f"**{r['route']} — {money(r['tcwp'])} — {r['cpu']} + {r['gpu']} — {r['performance_class']} — upgrade {r['upgradeability']} — Z20 {r['z20_fit']}{extra}**\n\n{r['rationale']}\n\nBrugte kilder: {links(r)}"

def round100(n):
    return max(0,(int(n)//100)*100)

def add_complete_pc_price_targets(routes):
    """Add market-relative negotiation thresholds to complete PCs.

    Hard max is the ASK at which the PC's strategic effective cost reaches parity with
    today's best other actionable finished solution. Sweet-spot price requires a 10%
    value margin below that parity point. This deliberately uses cross-route value,
    performance/platform adjustments and current alternatives instead of a percentage
    discount from the seller's ASK.
    """
    actionable=[r for r in routes if not excluded(r)]
    for r in actionable:
        if r.get('route')!='COMPLETE_USED_PC':
            continue
        others=[x for x in actionable if x is not r]
        if not others:
            continue
        benchmark=min(int(x.get('strategic_effective_cost',x['tcwp'])) for x in others)
        fixed_adjustment=int(r.get('strategic_effective_cost',r['tcwp']))-int(r['tcwp'])
        parity=max(0,benchmark-fixed_adjustment)
        hard_max=round100(parity)
        sweet=round100(parity*0.90)
        ask=int(r['tcwp'])
        r['sweet_spot_price']=sweet
        r['hard_max_price']=hard_max
        r['price_to_sweet_spot']=ask-sweet
        r['deal_action']='BUY' if ask<=sweet else 'CONSIDER' if ask<=hard_max else 'BID_LOWER'
        r['price_target_basis']='Cross-route strategic parity; sweet spot = 10% value margin below parity.'
    return actionable

def best(routes,pred,key=lambda r:int(r.get('strategic_effective_cost',r['tcwp']))):
    xs=[r for r in routes if pred(r)]
    return min(xs,key=key,default=None)


def main():
    d=json.loads(SRC.read_text(encoding='utf-8'))
    assert d.get('gate_passed') is True
    assert d.get('model_version')=='DBA-WOW-PLATFORM-FIRST-V16'
    ranked=add_complete_pc_price_targets(list(d.get('ranked') or []))
    ranked.sort(key=lambda r:(int(r.get('strategic_effective_cost',r['tcwp'])),int(r['tcwp'])))
    buy_now=ranked[0] if ranked else None
    foundation=best(ranked,lambda r:r.get('foundation')=='AM5_B650_B850_MATX_WIFI_4DIMM')
    cheapest=min(ranked,key=lambda r:int(r['tcwp']),default=None)
    opportunistic=best(ranked,lambda r:any(c.get('kind')=='GPU' and c.get('source')=='USED ASK' for c in r.get('components') or []))
    complete=best(ranked,lambda r:r.get('route')=='COMPLETE_USED_PC')
    donor=best(ranked,lambda r:r.get('route')=='USED_PC_PLUS_FUTURE_UPGRADE')
    hybrid=best(ranked,lambda r:r.get('route') in {'HYBRID_USED_NEW','PLATFORM_FIRST_AM5'})
    lines=[
      '# FULDT PÅLIDELIG DBA-PRISRAPPORT — WoW PLATFORM-FIRST V16','',
      f"Generated: {d.get('generated_at')}",
      'Mål: WoW Classic/Cataclysm, 3840×1600/75 Hz. Jonsbo Z20 er ønsket slutkabinet.',
      'Strategi: platform først, performance opportunistisk. AM5/B650-B850 mATX/Wi-Fi/4-DIMM/DDR5 er foretrukket permanent fundament; en billig ACCEPTABLE GPU må bruges som bridge.',
      'Indkøb: brugt først GPU→CPU→RAM→luftkøler; motherboard/kabinet brugt kun ved reel besparelse; PSU/SSD/blæsere nyt først.',
      'Prisgrænser for komplette PC’er: HARD MAX = strategisk prisparitet med dagens bedste alternative færdige løsning; SWEET-SPOT PRIS = 10% margin under denne paritet. Målet beregnes ikke som rabat fra sælgers ASK.',
      f"Ekskluderet fra ranking: {', '.join(sorted(EXCLUDED_LISTING_IDS))} ({', '.join(EXCLUDED_LISTING_IDS.values())}).",'',
      f"WAIT / BUY: **{'BUY' if buy_now and buy_now.get('foundation_score',0)>=100 else 'WAIT_FOR_FOUNDATION_OR_EXCEPTIONAL_COMPLETE_PC'}**",'',
      '## 🏆 BUY NOW','',line(buy_now),'',
      '## 🧱 BEST FOUNDATION','',line(foundation),'',
      '## 💰 CHEAPEST VIABLE','',line(cheapest),'',
      '## 🎯 BEST OPPORTUNISTIC BUY','',line(opportunistic),'',
      '## 🖥️ BEST COMPLETE PC','',line(complete),'',
      '## 🔧 BEST DONOR/UPGRADE ROUTE','',line(donor),'',
      '## ⚡ BEST HYBRID BUILD','',line(hybrid),'',
      '## Komplette PC’er — hvad bør de koste?','',
      '| PC | T1 ASK | Sweet-spot pris | Hard max | Til sweet spot | Handling | WoW | Upgrade | Z20 |',
      '|---|---:|---:|---:|---:|---|---|---|---|',
    ]
    complete_by_ask=sorted([r for r in ranked if r.get('route')=='COMPLETE_USED_PC' and r.get('sweet_spot_price') is not None],key=lambda r:int(r['tcwp']))
    for r in complete_by_ask[:30]:
        name=f"{r.get('cpu')} + {r.get('gpu')}"
        used=[c for c in r.get('components',[]) if c.get('source')=='USED ASK']
        if used and used[0].get('url'): name=f"[{name}]({used[0]['url']})"
        gap=int(r.get('price_to_sweet_spot') or 0)
        gap_txt=("+" if gap>0 else "")+money(gap)
        lines.append(f"| {name} | {money(r['tcwp'])} | **{money(r['sweet_spot_price'])}** | {money(r['hard_max_price'])} | {gap_txt} | **{r['deal_action']}** | {r['performance_class']} | {r['upgradeability']} | {r['z20_fit']} |")
    lines += ['', '## Samlet ranking — færdige løsninger','',
      '| # | TCWP | Strategic cost | Route | CPU | GPU | WoW | Upgrade | Z20 | Foundation | Brugte live-kilder |',
      '|---:|---:|---:|---|---|---|---|---|---|---|---|']
    for i,r in enumerate(ranked[:50],1):
        lines.append(f"| {i} | {money(r['tcwp'])} | {money(r.get('strategic_effective_cost',r['tcwp']))} | {r['route']} | {r['cpu']} | {r['gpu']} | {r['performance_class']} | {r['upgradeability']} | {r['z20_fit']} | {r.get('foundation','—')} | {links(r)} |")
    lines += ['', '## Pris- og evidensregel','', 'Alle USED ASK-komponenter i ranking kommer fra live T0→T1-verificerede DBA listing-objects. Funktionelt defekte dele er hard-excluded. NEW RETAIL er separat mærket. Search snippets/cached priser er aldrig prisbevis. UNKNOWN kompatibilitet må ikke fremstilles som VERIFIED. Sweet-spot/hard-max er beslutningsestimater og ændrer aldrig den verificerede T1 ASK.','']
    REPORT.write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'report':True,'model':d['model_version'],'ranked':len(ranked),'excluded_listing_ids':sorted(EXCLUDED_LISTING_IDS),'complete_price_targets':len(complete_by_ask)},ensure_ascii=False))

if __name__=='__main__':main()
