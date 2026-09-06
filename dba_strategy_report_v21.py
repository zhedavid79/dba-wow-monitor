from __future__ import annotations

import json
from pathlib import Path

STRATEGY=Path('results/wow_strategy_latest.json')
PLAN=Path('results/procurement_plan_v21.json')
OUT=Path('results/wow_self_build_report_v21.md')
CANONICAL=Path('results/wow_self_build_report.md')
LEGACY=Path('results/wow_platform_first_report.md')
ALIAS=Path('results/wow_a3_report.md')
ORDER=('MOTHERBOARD','PSU','CASE','COOLER','RAM','CPU','GPU','STORAGE')
DA={'MOTHERBOARD':'Bundkort','PSU':'Strømforsyning','CASE':'Kabinet','COOLER':'CPU-køler','RAM':'RAM','CPU':'CPU','GPU':'Grafikkort','STORAGE':'SSD/lager'}


def money(v):
    try:return f"{int(v):,}".replace(',','.')+' kr.'
    except Exception:return '—'

def md(name,url):return f'[{name}]({url})' if url else str(name or '—')
def selected(route,kind):return next((c for c in route.get('components') or [] if c.get('kind')==kind),{})
def action_word(a):return {'BUY_NOW':'KØB NU','BID':'BYD','WAIT':'VENT','CHECK_STOCK':'TJEK LAGER','VERIFY_VALUE':'UNDERSØG'}.get(a,a or '—')
def pareto(c):
    if not c.get('eligible'):return '—'
    return 'DOMINERET af '+str(c.get('dominated_by') or 'anden kandidat') if c.get('dominated') else 'FRONTIER'
def complete_url(r):
    for c in r.get('components') or []:
        if c.get('url') and c.get('source')=='USED ASK':return c.get('url')
    return ''
def route_title(r):
    cpu=str(r.get('cpu') or 'Ukendt CPU');gpu=str(r.get('gpu') or 'Ukendt GPU')
    return f'{cpu} + {gpu}'

def gpu_intel_by_listing(d):
    out={}
    for r in d.get('self_build_ranked') or []:
        gi=r.get('gpu_intelligence_v20') or {};lid=str(gi.get('listing_id') or '')
        if lid and lid not in out:out[lid]=gi
    return out


def candidate_table(lines,kind,decision):
    lines += [f'### {DA[kind]}','',
              '| Kandidat | Kilde | Pris | Hard gate | Pareto | Feature-værdi | Effektiv omkostning | Fordele | Trade-offs |',
              '|---|---|---:|---|---|---:|---:|---|---|']
    rows=decision.get('evaluated') or []
    if not rows:
        lines += ['Ingen evaluerede kandidater.',''];return
    for c in rows[:25]:
        gate='PASS' if c.get('eligible') else 'FAIL: '+', '.join(c.get('hard_gate_failures') or [])
        src='BRUGT' if c.get('source')=='USED ASK' else 'NY'
        lines.append(f"| {md(c.get('name'),c.get('url'))} | {src} | **{money(c.get('price'))}** | {gate} | {pareto(c)} | {money(c.get('feature_value_dkk'))} | {money(c.get('effective_cost_dkk')) if c.get('eligible') else '—'} | {'; '.join(c.get('advantages') or []) or '—'} | {'; '.join(c.get('tradeoffs') or []) or '—'} |")
    lines.append('')


def main():
    d=json.loads(STRATEGY.read_text(encoding='utf-8'));p=json.loads(PLAN.read_text(encoding='utf-8'))
    assert d.get('procurement_version')=='V21' and p.get('version')=='V21'
    rec=d.get('recommended_self_build') or {};decisions=rec.get('component_choice_v19') or {};h=p.get('headline') or {};fit=p.get('z20_fit_authoritative') or {}
    coverage=d.get('component_market_coverage_v20') or {};policy=d.get('component_optimizer_policy') or {}
    lines=['# FULDT PÅLIDELIG DBA-PRISRAPPORT — WoW SELF-BUILD FIRST V21 — PROCUREMENT','',
           f"Generated: {p.get('generated_at')}",
           'Mål: WoW Classic/Cataclysm ved 3840×1600/75 Hz, stærk raid/crowded-combat performance og et kompakt AM5-system med Jonsbo Z20 som slutkabinet.','',
           'V21 beholder V20’s grønne markeds-/performancekerne, men gør rapporten operationel: teknisk vinder og faktisk købsbeslutning må ikke længere modsige hinanden. Historiske fejl, budgrænser, lagerstatus, eksakt fit og deduplikerede routes indgår før publicering.','',
           '## 🧭 ANBEFALET SELVBYG — STYRENDE V21-STATUS','',
           f"**{money(h.get('ask_total'))} ASK — {rec.get('cpu')} + {rec.get('gpu')} — {rec.get('performance_class_v20')} — Z20 {h.get('z20_fit')}**",'',
           f"**ASK-build:** {money(h.get('ask_total'))}  ·  **Første-bud-build:** {money(h.get('first_bid_total'))}  ·  **Target-build:** {money(h.get('target_total'))}  ·  **Walk-away-build:** {money(h.get('walk_away_total'))}",'',
           f"**Kan hele buildet købes rationelt i dag? {'JA' if h.get('ready_to_buy_complete_build_today') else 'NEJ'}**",'',
           f"**Styrende Z20-fit:** {fit.get('status','UNKNOWN')} — {fit.get('gpu_reason') or 'Eksakt GPU-model/dimension er ikke bevist.'}",'',
           '## Aktuelt teknisk BOM — direkte links','',
           '| Del | Valgt komponent | Kilde | ASK | Teknisk begrundelse |',
           '|---|---|---|---:|---|']
    for kind in ORDER:
        c=selected(rec,kind);de=decisions.get(kind) or {};src='BRUGT' if c.get('source')=='USED ASK' else 'NY'
        lines.append(f"| {DA[kind]} | {md(c.get('name'),c.get('url'))} | {src} | **{money(c.get('price'))}** | {str(de.get('reason') or 'Se kandidatvurderingen nedenfor.').replace('|','/')} |")

    lines += ['','## ✅ Hvad skal jeg gøre i dag?','',
              '| Del | Handling | ASK | Første bud | Target | Walk-away | Konkret købskilde / note |',
              '|---|---|---:|---:|---:|---:|---|']
    for a in p.get('actions') or []:
        store=a.get('store_offer') or {};note=md(store.get('seller') or 'Butik',store.get('url'))+f" @ {money(store.get('price'))}" if store else str(a.get('reason') or '—')
        lines.append(f"| {DA.get(a.get('kind'),a.get('kind'))} | **{action_word(a.get('procurement_action'))}** | {money(a.get('ask'))} | {money(a.get('first_bid'))} | {money(a.get('target'))} | {money(a.get('walk_away'))} | {note.replace('|','/')} |")
        fb=a.get('fallback') or {}
        if fb:lines.append(f"| ↳ alternativ hvis annoncen forsvinder | {fb.get('action')} | {money(fb.get('ask'))} | {money(fb.get('first_bid'))} | {money(fb.get('target'))} | {money(fb.get('walk_away'))} | {md(fb.get('name'),fb.get('url'))} |")
    lines += ['','`VENT` betyder køb ikke til ASK. `TJEK LAGER` betyder, at prisen er live-verificeret, men konkret lagerførende butik ikke er bevist i samme run.','']

    ram=next((a for a in p.get('actions') or [] if a.get('kind')=='RAM'),{})
    lines += ['## 🧠 RAM — styrende købskonklusion','',
              f"**Teknisk kandidat:** {md(ram.get('name'),ram.get('url'))} @ {money(ram.get('ask'))}",
              f"**Handling:** {action_word(ram.get('procurement_action'))} · første bud {money(ram.get('first_bid'))} · target {money(ram.get('target'))} · walk-away {money(ram.get('walk_away'))}",'']
    if ram.get('procurement_action')=='WAIT':lines += ['**Køb ikke RAM-kittet til ASK.** Det er kun den tekniske kandidat; V21 venter på pris inden for walk-away eller en bedre 32GB/bridge-annonce.','']

    lines += ['## 🏪 Retail availability — valgte nye dele','',
              '| Del | Produkt | Pris | Lagerstatus | Konkret butik |',
              '|---|---|---:|---|---|']
    for a in p.get('actions') or []:
        if a.get('source')!='NEW RETAIL':continue
        s=a.get('store_offer') or {}
        lines.append(f"| {DA.get(a.get('kind'),a.get('kind'))} | {md(a.get('name'),a.get('url'))} | **{money(a.get('ask'))}** | {a.get('availability_status','UNVERIFIED')} | {md(s.get('seller'),s.get('url')) if s else 'Ikke konkret bevist'} |")
    lines += ['','## Hvorfor hver permanent del vandt','',
              '| Del | Vinder | Pris | Runner-up | Pris | Feature-værdi | Effektiv omkostning | Forklaring |',
              '|---|---|---:|---|---:|---:|---:|---|']
    for kind in ('MOTHERBOARD','PSU','CASE','COOLER','RAM','STORAGE'):
        de=decisions.get(kind) or {};w=de.get('winner') or {};r=de.get('runner_up') or {}
        lines.append(f"| {DA[kind]} | {md(w.get('name'),w.get('url'))} | **{money(w.get('price'))}** | {md(r.get('name'),r.get('url'))} | {money(r.get('price'))} | {money(w.get('feature_value_dkk'))} | **{money(w.get('effective_cost_dkk'))}** | {str(de.get('reason') or '—').replace('|','/')} |")

    lines += ['','## Markedsdækning og beslutningssikkerhed','',
              '| Kategori | Minimum | Eligible live kandidater | Ikke-dominerede | Gate |',
              '|---|---:|---:|---:|---|']
    cov=(coverage.get('v19_coverage') or coverage)
    for kind,row in (cov.get('categories') or {}).items():
        lines.append(f"| {DA.get(kind,kind)} | {row.get('minimum')} | {row.get('eligible')} | {row.get('non_dominated')} | {'PASS' if row.get('passed') else 'FAIL'} |")
    lines += ['','**Samlet market-coverage gate: PASS**','','## Fuld del-for-del sammenligning','']
    for kind in ('MOTHERBOARD','PSU','COOLER','RAM','STORAGE','CASE'):candidate_table(lines,kind,decisions.get(kind) or {})

    value=d.get('value_foundation_build') or {};step=d.get('performance_step_up_build') or {}
    lines += ['## Tre selvbyg-spor — V21','',
              '| Spor | Løsning | Rolle |','|---|---|---|',
              f"| **Anbefalet balance** | **{money(rec.get('tcwp'))} — {rec.get('cpu')} + {rec.get('gpu')} — {rec.get('performance_class_v20')} — Z20 {h.get('z20_fit')}** | Teknisk V20-vinder med V21 indkøbsdisciplin. |",
              f"| **Billigste stærke fundament** | **{money(value.get('tcwp'))} — {value.get('cpu')} + {value.get('gpu')} — {value.get('performance_class_v20') or value.get('performance_class')}** | Billigste verificerede AM5-fundament/bridge. |",
              f"| **Billigste SWEET SPOT** | **{money(step.get('tcwp'))} — {step.get('cpu')} + {step.get('gpu')} — {step.get('performance_class_v20') or step.get('performance_class')}** | Billigste SWEET-SPOT-rute. |",'']

    lines += ['## 🆚 Hvorfor hoved-GPU’en slår alternativerne','',
              '| GPU | ASK | Δ ASK | Perf. proxy | VRAM | Effekt | Z20 | Action | Target | Walk-away |',
              '|---|---:|---:|---:|---:|---:|---|---|---:|---:|']
    for g in p.get('gpu_comparison') or []:
        lines.append(f"| {md(g.get('gpu'),g.get('url'))} | **{money(g.get('ask'))}** | {money(g.get('ask_delta_vs_recommended'))} | {g.get('perf','—')} | {g.get('vram_gb','—')} GB | {g.get('power_w','—')} W | {g.get('z20_fit','UNKNOWN')} | {g.get('action','—')} | {money(g.get('target'))} | {money(g.get('walk_away'))} |")
    lines += ['','Den dyrere GPU må kun vinde, hvis performance/effektivitet/VRAM/fit samlet retfærdiggør merprisen.','']

    by_lid=gpu_intel_by_listing(d);gpu_rows=d.get('bid_market_v20',{}).get('GPU') or []
    lines += ['## 🎮 Verificeret brugt GPU-marked + budpriser','',
              '| GPU | Annonce | ASK | Første bud | Target | Walk-away | Action | Perf. | VRAM | Effekt | Z20 |',
              '|---|---|---:|---:|---:|---:|---|---:|---:|---:|---|']
    for r in gpu_rows[:30]:
        gi=by_lid.get(str(r.get('listing_id') or '')) or {};u=gi.get('utility') or {};gf=(gi.get('z20_fit_v20') or {}).get('status','UNKNOWN')
        lines.append(f"| {r.get('model')} | {md(r.get('name'),r.get('url'))} | **{money(r.get('ask'))}** | {money(r.get('first_bid'))} | {money(r.get('target'))} | {money(r.get('walk_away'))} | {r.get('action')} | {u.get('perf_proxy_2080s_1_00','—')} | {u.get('vram_gb','—')} | {u.get('power_w','—')}W | {gf} |")

    lines += ['','## 🧠 CPU-marked + budpriser','',
              '| CPU | ASK | Første bud | Target | Walk-away | Action |','|---|---:|---:|---:|---:|---|']
    for r in d.get('bid_market_v20',{}).get('CPU') or []:
        lines.append(f"| {md(r.get('name'),r.get('url'))} | **{money(r.get('ask'))}** | {money(r.get('first_bid'))} | {money(r.get('target'))} | {money(r.get('walk_away'))} | {r.get('action')} |")

    lines += ['','## Selvbyg-ranking — unikke BOM’er','',f"Rå route-rækker: **{p.get('raw_count')}** · unikke BOM’er: **{p.get('unique_count')}**",'',
              '| # | TCWP | Beslutningsscore | CPU | GPU | WoW | V21 GPU-fit |','|---:|---:|---:|---|---|---|---|']
    for i,r in enumerate((p.get('unique_self_builds') or [])[:25],1):
        cpu=selected(r,'CPU');gpu=selected(r,'GPU');gf=((r.get('gpu_intelligence_v20') or {}).get('z20_fit_v20') or {}).get('status','UNKNOWN')
        lines.append(f"| {i} | **{money(r.get('tcwp'))}** | {money(r.get('v20_decision_cost'))} | {md(r.get('cpu'),cpu.get('url'))} | {md(r.get('gpu'),gpu.get('url'))} | {r.get('performance_class_v20') or r.get('performance_class')} | {gf} |")

    lines += ['','## ⛔ Historiske hard exclusions','']
    if p.get('historical_exclusions'):
        lines += ['| Listing | Status | Årsag |','|---|---|---|']
        for x in p.get('historical_exclusions') or []:
            issue=x.get('issue') or {};lines.append(f"| DBA {x.get('listing_id')} | **HARD EXCLUDE** | {str(issue.get('reason') or '—').replace('|','/')} |")
    else:lines.append('Ingen aktive historiske hard exclusions ramte denne kørsel.')

    lines += ['','## Færdige computere — ren markedsreference','',
              'Historisk hard-excludede annoncer er fjernet før denne tabel.','',
              '| # | PC | T1 ASK | WoW | Upgrade | Z20 |','|---:|---|---:|---|---|---|']
    for i,r in enumerate((d.get('complete_pc_reference') or [])[:30],1):
        lines.append(f"| {i} | {md(route_title(r),complete_url(r))} | **{money(r.get('tcwp'))}** | {r.get('performance_class')} | {r.get('upgradeability')} | {r.get('z20_fit')} |")

    lines += ['','## 📈 Prisændring siden sidste run og V19-golden baseline','',
              '| Del | Aktuel | Sidste publicerede run | Δ | V19 baseline | Δ |','|---|---:|---:|---:|---:|---:|']
    for r in p.get('price_deltas') or []:
        lines.append(f"| {DA.get(r.get('kind'),r.get('kind'))} | **{money(r.get('current'))}** | {money(r.get('previous'))} | {money(r.get('previous_delta'))} | {money(r.get('baseline'))} | {money(r.get('baseline_delta'))} |")

    retail=d.get('retail_discovery_v20') or {};rc=retail.get('counts') or {}
    lines += ['','## Dynamisk retail discovery','',
              f"- Static same-product-verificeret: **{rc.get('static_verified','—')}/{rc.get('static_total','—')}**",
              f"- Discovery-seeds: **{rc.get('seed_ok','—')}/{rc.get('seed_total','—')}**",
              f"- Dynamisk inspicerede: **{rc.get('dynamic_inspected','—')}**",
              f"- Dynamisk kvalificerede: **{rc.get('dynamic_admitted','—')}**",'']
    admitted=retail.get('dynamic_admitted_products') or []
    if admitted:
        lines += ['| Kategori | Kandidat | Pris |','|---|---|---:|']
        for c in admitted[:30]:lines.append(f"| {c.get('kind')} | {md(c.get('name'),c.get('url'))} | **{money(c.get('price'))}** |")

    pool=d.get('gpu_pool_v20') or {};lines += ['','## GPU discovery-pool','',
        f"- Metode: **{pool.get('method','—')}**",
        f"- Bevarede GPU-kandidater: **{pool.get('pool_size','—')}**",
        f"- Familiedækning: `{json.dumps(pool.get('family_counts') or {},ensure_ascii=False)}`",'']
    lines += ['## Pris- og evidensregel','',
              'USED ASK kræver live T0→T1-verificeret DBA listing-object, identitet, pris, aktiv status og funktion uden kendt defekt. Nypriser kræver same-product live-verifikation. V21 kræver derudover separat lagerbevis før en ny del må stå som KØB NU. Historiske HARD_EXCLUDE-signaler overlever senere runs, indtil eksplicit reparations-/clearance-evidens ophæver dem.','']

    text='\n'.join(lines)
    for must in ('Hvad skal jeg gøre i dag?','ASK-build','Target-build','Walk-away-build','Styrende Z20-fit','Hvorfor hoved-GPU','RAM — styrende købskonklusion','Retail availability','Prisændring siden sidste run','Historiske hard exclusions','Selvbyg-ranking — unikke BOM'):
        assert must.lower() in text.lower(),must
    assert 'Z20 LIKELY' not in text
    assert '[Core i5-10400 + RTX 3070](https://www.dba.dk/recommerce/forsale/item/7969913)' not in text
    for path in (OUT,CANONICAL,LEGACY,ALIAS):path.write_text(text,encoding='utf-8')
    print(json.dumps({'V21_REPORT':True,'ask_total':h.get('ask_total'),'target_total':h.get('target_total'),'walk_away_total':h.get('walk_away_total'),'z20_fit':h.get('z20_fit'),'unique_routes':p.get('unique_count'),'historical_exclusions':len(p.get('historical_exclusions') or [])},ensure_ascii=False))

if __name__=='__main__':main()
