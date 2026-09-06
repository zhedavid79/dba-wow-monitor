from __future__ import annotations

import json
from pathlib import Path

STRATEGY=Path('results/wow_strategy_latest.json')
PLAN=Path('results/procurement_plan_v21.json')
BASE_REPORT=Path('results/wow_self_build_report_v20.md')
OUT=Path('results/wow_self_build_report_v21.md')
CANONICAL=Path('results/wow_self_build_report.md')
LEGACY=Path('results/wow_platform_first_report.md')
ALIAS=Path('results/wow_a3_report.md')
DA={'MOTHERBOARD':'Bundkort','PSU':'Strømforsyning','CASE':'Kabinet','COOLER':'CPU-køler','RAM':'RAM','CPU':'CPU','GPU':'Grafikkort','STORAGE':'SSD/lager'}
ORDER=('MOTHERBOARD','PSU','CASE','COOLER','RAM','CPU','GPU','STORAGE')


def money(v):
    try:return f"{int(v):,}".replace(',','.')+' kr.'
    except Exception:return '—'


def link(name,url):return f'[{name}]({url})' if url else str(name or '—')

def selected(route,kind):return next((c for c in route.get('components') or [] if c.get('kind')==kind),{})

def replace_section(text:str,start:str,end:str,new:str)->str:
    a=text.find('\n'+start)
    if a<0:a=text.find(start)
    if a<0:return text+'\n\n'+new
    b=text.find('\n'+end,a+len(start))
    if b<0:return text[:a]+'\n'+new+'\n'
    return text[:a]+'\n'+new+'\n'+text[b:]


def action_word(a:str)->str:
    return {'BUY_NOW':'KØB NU','BID':'BYD','WAIT':'VENT','CHECK_STOCK':'TJEK LAGER','VERIFY_VALUE':'UNDERSØG'}.get(a,a or '—')


def main()->None:
    d=json.loads(STRATEGY.read_text(encoding='utf-8'));p=json.loads(PLAN.read_text(encoding='utf-8'))
    assert d.get('procurement_version')=='V21'
    assert p.get('version')=='V21'
    assert BASE_REPORT.exists()
    text=BASE_REPORT.read_text(encoding='utf-8').replace('WoW SELF-BUILD FIRST V20','WoW SELF-BUILD FIRST V21 — PROCUREMENT')
    rec=d.get('recommended_self_build') or {};h=p.get('headline') or {};fit=p.get('z20_fit_authoritative') or {}

    intro='\n'.join([
        '## 🧭 ANBEFALET SELVBYG — STYRENDE V21-STATUS','',
        f"**{money(h.get('ask_total'))} ASK — {rec.get('cpu')} + {rec.get('gpu')} — {rec.get('performance_class_v20')} — Z20 {h.get('z20_fit')}**",'',
        f"**ASK-build:** {money(h.get('ask_total'))}  ·  **Første-bud-build:** {money(h.get('first_bid_total'))}  ·  **Target-build:** {money(h.get('target_total'))}  ·  **Walk-away-build:** {money(h.get('walk_away_total'))}",'',
        f"**Kan hele buildet købes rationelt i dag? {'JA' if h.get('ready_to_buy_complete_build_today') else 'NEJ'}**",'',
        f"**Styrende Z20-fit:** {fit.get('status','UNKNOWN')} — {fit.get('gpu_reason') or 'Eksakt GPU-fit er ikke bevist.'}",'',
        '> V21 bruger kun denne fit-status som styrende status for hovedbuildet. Ældre `LIKELY`-labels fra route-kernen er diagnostiske og må ikke overstyre V21.',
    ])
    text=replace_section(text,'## 🧭 ANBEFALET SELVBYG','## Aktuelt anbefalet BOM — direkte links',intro)

    actions=['## ✅ Hvad skal jeg gøre i dag?','',
             '| Del | Handling | ASK | Første bud | Target | Walk-away | Konkret købskilde / note |',
             '|---|---|---:|---:|---:|---:|---|']
    for a in p.get('actions') or []:
        store=a.get('store_offer') or {};store_txt=''
        if store:
            store_txt=link(store.get('seller') or 'Butik',store.get('url'))+f" @ {money(store.get('price'))}"
        if not store_txt:store_txt=str(a.get('reason') or '—')
        actions.append(f"| {DA.get(a.get('kind'),a.get('kind'))} | **{action_word(a.get('procurement_action'))}** | {money(a.get('ask'))} | {money(a.get('first_bid'))} | {money(a.get('target'))} | {money(a.get('walk_away'))} | {store_txt.replace('|','/')} |")
        fb=a.get('fallback') or {}
        if fb:
            actions.append(f"| ↳ alternativ hvis annoncen forsvinder | {fb.get('action')} | {money(fb.get('ask'))} | {money(fb.get('first_bid'))} | {money(fb.get('target'))} | {money(fb.get('walk_away'))} | {link(fb.get('name'),fb.get('url'))} |")
    actions += ['', '**Fortolkning:** `WAIT` betyder, at komponenten ikke skal købes til nuværende ASK. Target-buildet er kun realiserbart, hvis de brugte sælgere accepterer omtrent target-priserne.','']

    # Place the operation order directly after the technical BOM table and before explanations.
    marker='\n## Hvorfor hver permanent del vandt\n'
    if marker in text:text=text.replace(marker,'\n'+'\n'.join(actions)+marker,1)
    else:text+='\n\n'+'\n'.join(actions)

    # Replace the three-track section so old LIKELY is not presented as authoritative.
    value=d.get('value_foundation_build') or {};step=d.get('performance_step_up_build') or {}
    tracks='\n'.join(['## Tre selvbyg-spor — V21','',
        '| Spor | Løsning | Rolle |','|---|---|---|',
        f"| **Anbefalet balance** | **{money(rec.get('tcwp'))} — {rec.get('cpu')} + {rec.get('gpu')} — {rec.get('performance_class_v20')} — Z20 {h.get('z20_fit')}** | Teknisk V20-vinder med V21 indkøbsdisciplin. |",
        f"| **Billigste stærke fundament** | **{money(value.get('tcwp'))} — {value.get('cpu')} + {value.get('gpu')} — {value.get('performance_class_v20') or value.get('performance_class')}** | Billigste verificerede AM5/Z20-fundament; bridge-spor. |",
        f"| **Billigste SWEET SPOT** | **{money(step.get('tcwp'))} — {step.get('cpu')} + {step.get('gpu')} — {step.get('performance_class_v20') or step.get('performance_class')}** | Billigste SWEET-SPOT performance-rute. |",''])
    text=replace_section(text,'## Tre selvbyg-spor','## 🎮 Verificeret brugt GPU-marked — direkte DBA-links',tracks)

    # Direct head-to-head GPU explanation.
    comp=['## 🆚 Hvorfor hoved-GPU’en slår alternativerne','',
          '| GPU | ASK | Δ ASK | Perf. proxy | VRAM | Effekt | Z20 | Action | Target | Walk-away |',
          '|---|---:|---:|---:|---:|---:|---|---|---:|---:|']
    for g in p.get('gpu_comparison') or []:
        comp.append(f"| {link(g.get('gpu'),g.get('url'))} | **{money(g.get('ask'))}** | {money(g.get('ask_delta_vs_recommended'))} | {g.get('perf','—')} | {g.get('vram_gb','—')} GB | {g.get('power_w','—')} W | {g.get('z20_fit','UNKNOWN')} | {g.get('action','—')} | {money(g.get('target'))} | {money(g.get('walk_away'))} |")
    comp += ['',f"**V21-konklusion:** {rec.get('gpu')} er den tekniske hovedanbefaling. En billigere SWEET-SPOT GPU kan stadig være den bedste handel, hvis dens target/walk-away er bedre; tabellen gør denne trade-off eksplicit.",'']
    gpu_marker='\n## 🎮 Verificeret brugt GPU-marked — direkte DBA-links\n'
    if gpu_marker in text:text=text.replace(gpu_marker,'\n'+'\n'.join(comp)+gpu_marker,1)

    # Replace duplicate-heavy ranking with unique BOMs only.
    uniq=['## Selvbyg-ranking — unikke BOM’er','',f"Rå route-rækker: **{p.get('raw_count')}** · unikke BOM’er: **{p.get('unique_count')}**",'',
          '| # | TCWP | Beslutningsscore | CPU | GPU | WoW | V21 GPU-fit |',
          '|---:|---:|---:|---|---|---|---|']
    for i,r in enumerate((p.get('unique_self_builds') or [])[:20],1):
        cpu=selected(r,'CPU');gpu=selected(r,'GPU');gi=r.get('gpu_intelligence_v20') or {};gf=(gi.get('z20_fit_v20') or {}).get('status','UNKNOWN')
        uniq.append(f"| {i} | **{money(r.get('tcwp'))}** | {money(r.get('v20_decision_cost'))} | {link(r.get('cpu'),cpu.get('url'))} | {link(r.get('gpu'),gpu.get('url'))} | {r.get('performance_class_v20') or r.get('performance_class')} | {gf} |")
    text=replace_section(text,'## Selvbyg-ranking','## Færdige computere — markedsreference','\n'.join(uniq))

    # Remove persistent hard exclusions from the visible complete-PC table and show them explicitly.
    for x in p.get('historical_exclusions') or []:
        lid=str(x.get('listing_id') or '')
        text='\n'.join(line for line in text.splitlines() if f'/item/{lid})' not in line)
    excl=['## ⛔ Historiske hard exclusions','']
    if p.get('historical_exclusions'):
        excl += ['| Listing | Status | Årsag |','|---|---|---|']
        for x in p.get('historical_exclusions') or []:
            issue=x.get('issue') or {};lid=x.get('listing_id')
            excl.append(f"| [DBA {lid}](https://www.dba.dk/recommerce/forsale/item/{lid}) | **HARD EXCLUDE** | {str(issue.get('reason') or '—').replace('|','/')} |")
    else:excl.append('Ingen aktive historiske hard exclusions ramte denne kørsel.')
    complete_marker='\n## Færdige computere — markedsreference\n'
    if complete_marker in text:text=text.replace(complete_marker,'\n'+'\n'.join(excl)+complete_marker,1)

    # RAM must expose technical-vs-purchase decision explicitly.
    ram=next((a for a in p.get('actions') or [] if a.get('kind')=='RAM'),{})
    ram_section=['## 🧠 RAM — styrende købskonklusion','',
                 f"**Teknisk kandidat:** {link(ram.get('name'),ram.get('url'))} @ {money(ram.get('ask'))}",
                 f"**Handling:** {action_word(ram.get('procurement_action'))} · første bud {money(ram.get('first_bid'))} · target {money(ram.get('target'))} · walk-away {money(ram.get('walk_away'))}",'']
    if ram.get('procurement_action')=='WAIT':ram_section.append('**Køb ikke RAM-kittet til ASK.** Det forbliver kun den tekniske kandidat; V21 venter på en pris inden for walk-away eller en bedre 32GB/bridge-annonce.')
    ram_marker='\n## V20 — RAM-bud og bridge-kontrol\n'
    if ram_marker in text:text=text.replace(ram_marker,'\n'+'\n'.join(ram_section)+ram_marker,1)

    # Selected retail availability.
    retail=['## 🏪 Retail availability — valgte nye dele','',
            '| Del | Produkt | Pris | Lagerstatus | Konkret butik |',
            '|---|---|---:|---|---|']
    for a in p.get('actions') or []:
        if a.get('source')!='NEW RETAIL':continue
        s=a.get('store_offer') or {}
        retail.append(f"| {DA.get(a.get('kind'),a.get('kind'))} | {link(a.get('name'),a.get('url'))} | **{money(a.get('ask'))}** | {a.get('availability_status','UNVERIFIED')} | {link(s.get('seller'),s.get('url')) if s else 'Ikke konkret bevist'} |")
    retail += ['','En live sammenligningspris er ikke automatisk lig med dokumenteret lager. `CHECK_STOCK` må derfor ikke vises som `KØB NU`.','']
    dyn_marker='\n## V20 — dynamisk retail discovery\n'
    if dyn_marker in text:text=text.replace(dyn_marker,'\n'+'\n'.join(retail)+dyn_marker,1)

    # Baseline / previous-run deltas.
    delta=['## 📈 Prisændring siden sidste run og V19-golden baseline','',
           '| Del | Aktuel | Sidste publicerede run | Δ | V19 baseline | Δ |',
           '|---|---:|---:|---:|---:|---:|']
    for r in p.get('price_deltas') or []:
        delta.append(f"| {DA.get(r.get('kind'),r.get('kind'))} | **{money(r.get('current'))}** | {money(r.get('previous'))} | {money(r.get('previous_delta'))} | {money(r.get('baseline'))} | {money(r.get('baseline_delta'))} |")
    delta += ['','Prisændringer viser markedsbevægelse separat fra ændringer i modelvalget.','']
    cache_marker='\n## V20 — shared same-run T1-cache\n'
    if cache_marker in text:text=text.replace(cache_marker,'\n'+'\n'.join(delta)+cache_marker,1)

    text=text.replace('## V20 — GPU value, Z20-fit og budmodel','## V21 — GPU value, Z20-fit og budmodel')
    text=text.replace('## V20 — RAM-bud og bridge-kontrol','## V21 — RAM-bud og bridge-kontrol')
    text=text.replace('## V20 — CPU-bud','## V21 — CPU-bud')
    text=text.replace('## V20 — dynamisk retail discovery','## V21 — dynamisk retail discovery')
    text=text.replace('## V20 — shared same-run T1-cache','## V21 — shared same-run T1-cache')
    text=text.replace('## V20 — GPU discovery-pool','## V21 — GPU discovery-pool')

    for must in ('Hvad skal jeg gøre i dag?','ASK-build','Target-build','Walk-away-build','styrende Z20-fit','Hvorfor hoved-GPU','RAM — styrende købskonklusion','Retail availability','Prisændring siden sidste run','Historiske hard exclusions','Selvbyg-ranking — unikke BOM'):
        assert must.lower() in text.lower(),must
    assert '/item/7969913)' not in text,'Known-defect listing leaked into V21 report'
    for path in (OUT,CANONICAL,LEGACY,ALIAS):path.write_text(text,encoding='utf-8')
    print(json.dumps({'V21_REPORT':True,'ask_total':h.get('ask_total'),'target_total':h.get('target_total'),'walk_away_total':h.get('walk_away_total'),'z20_fit':h.get('z20_fit'),'unique_routes':p.get('unique_count'),'historical_exclusions':len(p.get('historical_exclusions') or [])},ensure_ascii=False))


if __name__=='__main__':main()
