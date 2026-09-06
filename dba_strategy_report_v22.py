from __future__ import annotations

import json
from pathlib import Path

STRATEGY=Path('results/wow_strategy_latest.json')
PLAN=Path('results/procurement_plan_v22.json')
OFFERS=Path('results/retail_offers_v22.json')
BASE=Path('results/wow_self_build_report_v21.md')
OUT=Path('results/wow_self_build_report_v22.md')
CANONICAL=Path('results/wow_self_build_report.md')
LEGACY=Path('results/wow_platform_first_report.md')
ALIAS=Path('results/wow_a3_report.md')
DA={'MOTHERBOARD':'Bundkort','PSU':'Strømforsyning','CASE':'Kabinet','COOLER':'CPU-køler','RAM':'RAM','CPU':'CPU','GPU':'Grafikkort','STORAGE':'SSD/lager'}


def money(v):
    try:return f"{int(v):,}".replace(',','.')+' kr.'
    except Exception:return '—'


def link(name,url):return f'[{name}]({url})' if url else str(name or '—')


def reference(row:dict)->tuple[int|None,str]:
    delivered=int(row.get('delivered_price_dkk') or 0)
    normal=row.get('normal_price_dkk')
    if normal is not None and int(normal)>delivered:return int(normal),'før/normalpris'
    market=row.get('market_reference_delivered_dkk')
    if market is not None and int(market)>delivered:return int(market),'median leveret butikspris'
    return None,'—'


def saving(row:dict)->tuple[int|None,float|None,str]:
    ref,label=reference(row);price=int(row.get('delivered_price_dkk') or 0)
    if not ref or not price:return None,None,label
    return ref-price,round((ref-price)/ref*100,1),label


def eligible_skus(strategy:dict)->set[str]:
    out=set();rec=strategy.get('recommended_self_build') or {};dec=rec.get('component_choice_v19') or {}
    for d in dec.values():
        for x in (d or {}).get('evaluated') or []:
            if x.get('eligible') is True and x.get('sku'):out.add(str(x['sku']))
    return out


def main()->None:
    s=json.loads(STRATEGY.read_text(encoding='utf-8'));p=json.loads(PLAN.read_text(encoding='utf-8'));o=json.loads(OFFERS.read_text(encoding='utf-8'))
    assert p.get('version')=='V22' and (s.get('offer_optimizer_v22') or {}).get('active') is True and BASE.exists()
    text=BASE.read_text(encoding='utf-8').replace('SELF-BUILD FIRST V21 — PROCUREMENT','SELF-BUILD FIRST V22 — PROCUREMENT + DEALS').replace('V21 bruger','V22 bruger').replace('V21 beholder','V22 beholder')

    selected=(p.get('retail_offers_v22') or {}).get('selected') or []
    lines=['## 🏷️ Nye dele — tilbud, butik og leveret pris','',
           '**Styrende pris:** leveret pris. Prisjagt-sammenligningens `Pris inkl. leveringsomkostninger` kan være den autoritative total; hvor butikken viser fragt separat, vises varepris + fragt. Ukendt levering kan ikke blive KØBSKLAR.','',
           '| Del | Produkt / direkte butik | Butik | Varepris | Fragt | **Leveret** | Reference | Besparelse | Prisstatus |',
           '|---|---|---|---:|---:|---:|---:|---:|---|']
    for r in selected:
        sav,pct,label=saving(r);item=money(r.get('item_price_dkk')) if r.get('item_price_dkk') is not None else 'inkl. i total';ship=money(r.get('shipping_dkk')) if r.get('shipping_dkk') is not None else 'inkl. i total'
        ref,_=reference(r);status=str(r.get('deal_type') or 'BEST_CURRENT_PRICE')
        lines.append(f"| {DA.get(r.get('kind'),r.get('kind'))} | {link(r.get('name'),r.get('buy_url'))} | {r.get('seller') or '—'} | {item} | {ship} | **{money(r.get('delivered_price_dkk'))}** | {money(ref)} ({label}) | {money(sav)}{(' / '+str(pct)+'%') if pct is not None else ''} | **{status}** |")
    lines += ['',f"**Leveret pris for alle valgte nye dele:** {money(sum(int(x.get('delivered_price_dkk') or 0) for x in selected))}.",'']

    eligible=eligible_skus(s);deal_rows=[]
    for r in o.get('rows') or []:
        if str(r.get('sku') or '') not in eligible or r.get('delivered_price_verified') is not True:continue
        best=r.get('best_delivered_offer') or {};x={'kind':r.get('kind'),'sku':r.get('sku'),'name':r.get('name'),'seller':r.get('seller'),'url':r.get('buy_url'),'delivered_price_dkk':r.get('delivered_price_dkk'),'item_price_dkk':r.get('item_price_dkk'),'shipping_dkk':r.get('shipping_dkk'),'normal_price_dkk':r.get('normal_price_dkk'),'market_reference_delivered_dkk':r.get('market_reference_delivered_dkk'),'deal_type':r.get('deal_type')}
        sav,pct,label=saving(x);x['saving']=sav;x['saving_pct']=pct;x['reference_label']=label;deal_rows.append(x)
    deal_rows.sort(key=lambda x:(-(x.get('saving_pct') or 0),int(x.get('delivered_price_dkk') or 10**9)))
    lines += ['## 🔎 Andre kvalificerede nye tilbud fundet','',f"Retail-univers inspiceret: **{o.get('products_total')}** produkter · leveret-pris-verificeret: **{o.get('delivered_price_verified')}** · tilbud/deal-signaler: **{o.get('deal_candidates')}**.",'',
              '| Del | Kandidat / direkte butik | Leveret | Reference | Besparelse | Deal-type |',
              '|---|---|---:|---:|---:|---|']
    for r in deal_rows[:25]:
        ref,_=reference(r);lines.append(f"| {DA.get(r.get('kind'),r.get('kind'))} | {link(r.get('name'),r.get('url'))} | **{money(r.get('delivered_price_dkk'))}** | {money(ref)} | {money(r.get('saving'))}{(' / '+str(r.get('saving_pct'))+'%') if r.get('saving_pct') is not None else ''} | {r.get('deal_type') or 'BEST_CURRENT_PRICE'} |")
    if not deal_rows:lines.append('| — | Ingen ekstra kvalificerede leveret-pris-kandidater | — | — | — | — |')
    lines += ['','**Regel:** “tilbud” er ikke et scorebonusord. V22 vælger efter hard gates → Pareto → projektrelevant feature-værdi → **leveret pris**. Dermed kan et dyrere nyt produkt vinde, men kun hvis den konkrete merfunktion er mere værd end merprisen.','']

    blockers=p.get('blockers') or [];gate=['## 🚦 KØBSKLAR-gate','',f"**Hele buildet KØBSKLAR nu: {'JA' if (p.get('headline') or {}).get('ready_to_buy_complete_build_today') else 'NEJ'}**",'',f"**Styrende Z20-fit:** {(p.get('headline') or {}).get('z20_fit','UNKNOWN')}",'']
    if blockers:
        gate.append('Aktuelle blokeringer:')
        for b in blockers:gate.append(f"- **{b.get('kind')} — {b.get('procurement_action')}:** {b.get('reason') or '—'}")
    else:gate.append('Ingen blokeringer; alle valgte dele er købsklare på de verificerede vilkår.')
    gate += ['','`UNKNOWN` fit må aldrig give KØBSKLAR. Kandidaten forbliver i rankingen, men den eksakte GPU-model/clearance skal dokumenteres før samlet købsklar-status.','']

    marker='\n## Hvorfor hver permanent del vandt\n'
    addition='\n'.join(lines+gate)
    if marker in text:text=text.replace(marker,'\n'+addition+marker,1)
    else:text+='\n\n'+addition
    text=text.replace('## V21 — GPU value, Z20-fit og budmodel','## V22 — GPU value, Z20-fit og budmodel').replace('## V21 — RAM-bud og bridge-kontrol','## V22 — RAM-bud og bridge-kontrol').replace('## V21 — CPU-bud','## V22 — CPU-bud').replace('## V21 — dynamisk retail discovery','## V22 — dynamisk retail discovery').replace('## V21 — shared same-run T1-cache','## V22 — shared same-run T1-cache').replace('## V21 — GPU discovery-pool','## V22 — GPU discovery-pool')
    assert 'Nye dele — tilbud, butik og leveret pris' in text and 'Andre kvalificerede nye tilbud fundet' in text and 'KØBSKLAR-gate' in text
    assert '7969913' not in '\n'.join(line for line in text.splitlines() if 'HARD EXCLUDE' not in line and 'Historiske hard exclusions' not in line),'Excluded listing leaked outside historical exclusion section'
    for r in selected:assert r.get('buy_url') and str(r['buy_url']) in text
    for path in (OUT,CANONICAL,LEGACY,ALIAS):path.write_text(text,encoding='utf-8')
    print(json.dumps({'V22_REPORT':True,'ask_total':(p.get('headline') or {}).get('ask_total'),'target_total':(p.get('headline') or {}).get('target_total'),'fit':(p.get('headline') or {}).get('z20_fit'),'ready_today':(p.get('headline') or {}).get('ready_to_buy_complete_build_today'),'selected_new':len(selected),'eligible_offer_rows':len(deal_rows)},ensure_ascii=False))


if __name__=='__main__':main()
