from __future__ import annotations

import json
from pathlib import Path

SRC = Path('results/wow_strategy_latest.json')
OUT = Path('results/wow_self_build_report_v19.md')

ORDER = ('MOTHERBOARD','PSU','CASE','COOLER','RAM','CPU','GPU','STORAGE')
DA = {'MOTHERBOARD':'Bundkort','PSU':'Strømforsyning','CASE':'Kabinet','COOLER':'CPU-køler','RAM':'RAM','CPU':'CPU','GPU':'Grafikkort','STORAGE':'SSD/lager'}


def money(n):
    if n is None: return '—'
    return f"{int(n):,}".replace(',', '.') + ' kr.'


def link(obj, fallback='—'):
    if not obj: return fallback
    name = str(obj.get('name') or fallback).replace('|','/')
    url = obj.get('url')
    return f"[{name}]({url})" if url else name


def selected(route, kind):
    return next((c for c in (route or {}).get('components',[]) if c.get('kind') == kind), None)


def summary(route):
    if not route: return 'Ingen gyldig rute.'
    return f"**{money(route.get('tcwp'))} — {route.get('cpu')} + {route.get('gpu')} — {route.get('performance_class')} — upgrade {route.get('upgradeability')} — Z20 {route.get('z20_fit')}**"


def main():
    d = json.loads(SRC.read_text(encoding='utf-8'))
    assert d.get('gate_passed') is True
    assert d.get('model_version') == 'DBA-WOW-SELF-BUILD-FIRST-V19'
    rec = d.get('recommended_self_build') or {}
    decisions = rec.get('component_choice_v19') or {}
    policy = d.get('component_optimizer_policy') or {}
    coverage = d.get('component_market_coverage_v19') or {}

    lines = [
        '# WoW SELF-BUILD FIRST V19 — EXPLAINABLE COMPONENT MODEL',
        '',
        f"Generated from DBA verified snapshot: {d.get('generated_at')}",
        '',
        'V19 bruger ikke længere én hardcoded SKU som facit. Hver permanent/semi-permanent del går gennem hard gates, Pareto-dominans og derefter en begrænset rational-premium-vurdering. En dyrere del må kun vinde, hvis konkrete relevante egenskaber forsvarer merprisen.',
        '',
        f"**Formel:** `{policy.get('formula')}`",
        '',
        '**Ingen chipset- eller brandbonus:** B850/B650 og producentnavn giver 0 point i sig selv. Kun konkrete features, kompatibilitet, pris og samlet build-effekt må flytte anbefalingen.',
        '',
        '## 🧭 Anbefalet build', '', summary(rec), '',
        '## Aktuelt anbefalet BOM', '',
        '| Del | Valgt komponent | Pris |', '|---|---|---:|',
    ]
    for kind in ORDER:
        c = selected(rec, kind)
        lines.append(f"| {DA[kind]} | {link(c)} | **{money((c or {}).get('price'))}** |")

    lines += ['', '## Hvorfor hver del vandt', '',
              '| Del | Vinder | Pris | Runner-up | Pris | Feature-værdi | Effektiv omkostning | Begrundelse |',
              '|---|---|---:|---|---:|---:|---:|---|']
    for kind in ('MOTHERBOARD','PSU','CASE','COOLER','RAM','STORAGE'):
        dec=decisions.get(kind) or {}; w=dec.get('winner') or {}; r=dec.get('runner_up') or {}
        lines.append(f"| {DA[kind]} | {link(w)} | **{money(w.get('price'))}** | {link(r)} | {money(r.get('price'))} | {money(w.get('feature_value_dkk'))} | **{money(w.get('effective_cost_dkk'))}** | {str(dec.get('reason') or '—').replace('|','/')} |")

    lines += ['', '### CPU og GPU', '']
    for kind in ('CPU','GPU'):
        dec=decisions.get(kind) or {}; c=dec.get('selected') or selected(rec,kind)
        lines.append(f"- **{DA[kind]} — {link(c)} / {money((c or {}).get('price'))}:** {dec.get('reason','—')}")

    lines += ['', '## Bundkort — fuld sammenligning', '',
              '| Kandidat | Pris | Hard gate | Pareto | Feature-værdi | Effektiv omkostning | Fordele | Trade-offs |',
              '|---|---:|---|---|---:|---:|---|---|']
    mb=decisions.get('MOTHERBOARD') or {}
    for c in mb.get('evaluated') or []:
        gate='PASS' if c.get('eligible') else 'FAIL: '+', '.join(c.get('hard_gate_failures') or [])
        if not c.get('eligible'): pareto='—'
        elif c.get('dominated'): pareto='DOMINERET af '+str(c.get('dominated_by') or 'anden kandidat')
        else: pareto='FRONTIER'
        pros='; '.join(c.get('advantages') or []) or '—'; cons='; '.join(c.get('tradeoffs') or []) or '—'
        lines.append(f"| {link(c)} | **{money(c.get('price'))}** | {gate} | {pareto} | {money(c.get('feature_value_dkk'))} | **{money(c.get('effective_cost_dkk')) if c.get('eligible') else '—'}** | {pros} | {cons} |")

    lines += ['', '## Markedsdækning', '',
              '| Kategori | Minimum | Eligible live kandidater | Ikke-dominerede | Gate |',
              '|---|---:|---:|---:|---|']
    for kind,row in (coverage.get('categories') or {}).items():
        lines.append(f"| {DA.get(kind,kind)} | {row.get('minimum')} | {row.get('eligible')} | {row.get('non_dominated')} | {'PASS' if row.get('passed') else 'FAIL'} |")
    lines.append('')
    lines.append(f"**Samlet market-coverage gate: {'PASS' if coverage.get('passed') else 'FAIL'}**")

    lines += ['', '## Del-for-del policy', '']
    for kind in ORDER:
        p=(policy.get('categories') or {}).get(kind) or {}; hard=', '.join(p.get('hard') or [])
        lines.append(f"- **{DA[kind]} ({p.get('role','—')}):** hard gates: {hard}. {p.get('principle','—')}")

    lines += ['', '## Metodisk forskel fra V18', '',
              '- V18: sammenlignede hovedsageligt brugtpris mod én fast ny reference pr. kategori.',
              '- V19: sammenligner et live-verificeret kandidatunivers og kræver en eksplicit økonomisk begrundelse for hver premium-feature.',
              '- V19: Pareto-dominans fjerner kandidater, der er dyrere uden at være bedre på nogen projektrelevant egenskab.',
              '- V19: rapporterer vinder, runner-up, prisdelta, feature-værdi, hard-gate-resultat, dominans og effektiv omkostning.',
              '- V19: B850/B650 eller et producentnavn har ingen selvstændig værdi; konkrete egenskaber skal retfærdiggøre merprisen.',
              '', '## Evidensregel', '',
              'Brugte DBA-dele bevarer den eksisterende T0→T1 identity/price/status gate og HARD EXCLUDE for funktionelle fejl. Retail-kandidater skal have eksplicit produktidentitet, URL, pris og stabile specs. V19 må ikke publiceres som autoritativ daglig rapport, hvis retail-priser eller minimumsdækning ikke er frisk-verificeret i den aktuelle run.', '']

    text='\n'.join(lines)
    for marker in ('Bundkort — fuld sammenligning','Runner-up','Pareto','Markedsdækning','Metodisk forskel fra V18'):
        assert marker in text, marker
    winner=(mb.get('winner') or {}).get('name'); assert winner and winner in text
    OUT.write_text(text,encoding='utf-8')
    print(json.dumps({'report':True,'model':d['model_version'],'recommended_tcwp':rec.get('tcwp'),'motherboard':winner,'market_coverage':coverage.get('passed')},ensure_ascii=False))


if __name__=='__main__': main()
