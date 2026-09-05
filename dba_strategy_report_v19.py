from __future__ import annotations

import json
from pathlib import Path

import dba_strategy_report_v18 as legacy

SRC = Path('results/wow_strategy_latest.json')
OUT = Path('results/wow_self_build_report_v19.md')
CANONICAL = Path('results/wow_self_build_report.md')
LEGACY = Path('results/wow_platform_first_report.md')
ALIAS = Path('results/wow_a3_report.md')

ORDER = ('MOTHERBOARD','PSU','CASE','COOLER','RAM','CPU','GPU','STORAGE')
DA = {'MOTHERBOARD':'Bundkort','PSU':'Strømforsyning','CASE':'Kabinet','COOLER':'CPU-køler','RAM':'RAM','CPU':'CPU','GPU':'Grafikkort','STORAGE':'SSD/lager'}

money = legacy.money
link = legacy.link
selected = legacy.selected
build_summary = legacy.build_summary
complete_link = legacy.complete_link
component_rank_link = legacy.component_rank_link
market_rows = legacy.market_rows


def pareto_text(c: dict) -> str:
    if not c.get('eligible'):
        return '—'
    if c.get('dominated'):
        return 'DOMINERET af ' + str(c.get('dominated_by') or 'anden kandidat')
    return 'FRONTIER'


def candidate_table(lines: list[str], kind: str, decision: dict) -> None:
    rows = decision.get('evaluated') or []
    lines += [
        f'### {DA[kind]}',
        '',
        '| Kandidat | Kilde | Pris | Hard gate | Pareto | Feature-værdi | Effektiv omkostning | Fordele | Trade-offs |',
        '|---|---|---:|---|---|---:|---:|---|---|',
    ]
    if not rows:
        lines += ['Ingen evaluerede kandidater i denne kørsel.', '']
        return
    for c in rows[:20]:
        gate = 'PASS' if c.get('eligible') else 'FAIL: ' + ', '.join(c.get('hard_gate_failures') or [])
        src = 'BRUGT' if c.get('source') == 'USED ASK' else 'NY'
        pros = '; '.join(c.get('advantages') or []) or '—'
        cons = '; '.join(c.get('tradeoffs') or []) or '—'
        eff = money(c.get('effective_cost_dkk')) if c.get('eligible') else '—'
        lines.append(
            f"| {link(c)} | {src} | **{money(c.get('price'))}** | {gate} | {pareto_text(c)} | {money(c.get('feature_value_dkk'))} | **{eff}** | {pros} | {cons} |"
        )
    lines.append('')


def main() -> None:
    d = json.loads(SRC.read_text(encoding='utf-8'))
    assert d.get('gate_passed') is True
    assert d.get('model_version') == 'DBA-WOW-SELF-BUILD-FIRST-V19'
    assert d.get('strategy_mode') == 'EXPLAINABLE_MULTI_CRITERIA_SELF_BUILD'

    rec = d.get('recommended_self_build') or {}
    decisions = rec.get('component_choice_v19') or {}
    policy = d.get('component_optimizer_policy') or {}
    coverage = d.get('component_market_coverage_v19') or {}
    self_build = d.get('self_build_ranked') or []
    complete = d.get('complete_pc_reference') or []
    value = d.get('value_foundation_build')
    step = d.get('performance_step_up_build')

    required = set(ORDER)
    assert set(decisions) == required
    assert coverage.get('passed') is True

    lines = [
        '# FULDT PÅLIDELIG DBA-PRISRAPPORT — WoW SELF-BUILD FIRST V19',
        '',
        f"Generated: {d.get('generated_at')}",
        'Mål: WoW Classic/Cataclysm ved 3840×1600/75 Hz, stærk raid/crowded-combat performance og et kompakt AM5-system med Jonsbo Z20 som slutkabinet.',
        'V19 vælger ikke længere dele mod én fast reference. Hver permanent/semi-permanent del går gennem hard gates, Pareto-dominans og en begrænset rational-premium-vurdering. CPU/GPU forbliver opportunistiske performancekøb på den opgraderbare platform.',
        '',
        f"**Formel:** `{policy.get('formula')}`",
        '',
        '**Ingen brand- eller chipsetbonus:** producentnavn og B850/B650 giver ingen værdi i sig selv. Kun konkrete projektrelevante egenskaber kan retfærdiggøre en merpris.',
        '',
        '## 🧭 ANBEFALET SELVBYG',
        '',
        build_summary(rec),
        '',
        '## Aktuelt anbefalet BOM — direkte links',
        '',
        '| Del | Valgt komponent | Kilde | Pris | Hvorfor |',
        '|---|---|---|---:|---|',
    ]

    for kind in ORDER:
        c = selected(rec, kind)
        dec = decisions.get(kind) or {}
        reason = dec.get('reason') or 'Se kandidatvurderingen nedenfor.'
        src = 'BRUGT' if c and c.get('source') == 'USED ASK' else 'NY'
        lines.append(f"| {DA[kind]} | {link(c)} | {src} | **{money((c or {}).get('price'))}** | {str(reason).replace('|','/')} |")

    lines += [
        '',
        '## Hvorfor hver permanent del vandt',
        '',
        '| Del | Vinder | Pris | Runner-up | Pris | Feature-værdi | Effektiv omkostning | Forklaring |',
        '|---|---|---:|---|---:|---:|---:|---|',
    ]
    for kind in ('MOTHERBOARD','PSU','CASE','COOLER','RAM','STORAGE'):
        dec = decisions.get(kind) or {}
        w = dec.get('winner') or {}
        r = dec.get('runner_up') or {}
        lines.append(
            f"| {DA[kind]} | {link(w)} | **{money(w.get('price'))}** | {link(r)} | {money(r.get('price'))} | {money(w.get('feature_value_dkk'))} | **{money(w.get('effective_cost_dkk'))}** | {str(dec.get('reason') or '—').replace('|','/')} |"
        )

    lines += ['', '### CPU og GPU — opportunistisk performance', '']
    for kind in ('CPU','GPU'):
        dec = decisions.get(kind) or {}
        c = dec.get('selected') or selected(rec, kind)
        lines.append(f"- **{DA[kind]} — {link(c)} / {money((c or {}).get('price'))}:** {dec.get('reason','—')}")

    lines += [
        '',
        '## Markedsdækning og beslutningssikkerhed',
        '',
        '| Kategori | Minimum | Eligible live kandidater | Ikke-dominerede | Gate |',
        '|---|---:|---:|---:|---|',
    ]
    for kind, row in (coverage.get('categories') or {}).items():
        lines.append(f"| {DA.get(kind,kind)} | {row.get('minimum')} | {row.get('eligible')} | {row.get('non_dominated')} | {'PASS' if row.get('passed') else 'FAIL'} |")
    lines += ['', f"**Samlet market-coverage gate: {'PASS' if coverage.get('passed') else 'FAIL'}**", '']

    lines += ['## Fuld del-for-del sammenligning', '']
    for kind in ('MOTHERBOARD','PSU','COOLER','RAM','STORAGE','CASE'):
        candidate_table(lines, kind, decisions.get(kind) or {})

    lines += [
        '## Tre selvbyg-spor',
        '',
        '| Spor | Løsning | Rolle |',
        '|---|---|---|',
        f"| **Anbefalet balance** | {build_summary(rec)} | Laveste V19 effektive omkostning efter kompatibilitet, markedspris og begrænset feature-værdi. |",
        f"| **Billigste stærke fundament** | {build_summary(value)} | Laveste verificerede TCWP på det ønskede AM5/Z20-fundament. |",
        f"| **Performance step-up** | {build_summary(step)} | Billigste SWEET SPOT-rute på samme opgraderbare fundament. |",
        '',
    ]

    gpu_market = market_rows(self_build, 'GPU')
    lines += [
        '## 🎮 Verificeret brugt GPU-marked — direkte DBA-links',
        '',
        '| GPU | Annonce | Brugtpris | WoW-klasse i ruten | TCWP med ruten |',
        '|---|---|---:|---|---:|',
    ]
    for r in gpu_market:
        lines.append(f"| {r['model']} | {link(r['component'])} | **{money(r['price'])}** | {r['performance_class']} | {money(r['tcwp'])} |")

    cpu_market = market_rows(self_build, 'CPU')
    lines += [
        '',
        '## 🧠 Verificeret brugt CPU-marked — direkte DBA-links',
        '',
        '| CPU | Annonce | Brugtpris | WoW-klasse i ruten | TCWP med ruten |',
        '|---|---|---:|---|---:|',
    ]
    for r in cpu_market:
        lines.append(f"| {r['model']} | {link(r['component'])} | **{money(r['price'])}** | {r['performance_class']} | {money(r['tcwp'])} |")

    lines += [
        '',
        '## Selvbyg-ranking',
        '',
        '| # | TCWP | Beslutningsscore | CPU | GPU | WoW | Upgrade | Z20 |',
        '|---:|---:|---:|---|---|---|---|---|',
    ]
    for i, r in enumerate(self_build[:30], 1):
        cpu_txt = component_rank_link(r, 'CPU', r.get('cpu'))
        gpu_txt = component_rank_link(r, 'GPU', r.get('gpu'))
        lines.append(f"| {i} | **{money(r.get('tcwp'))}** | {money(r.get('self_build_effective_cost',r.get('tcwp')))} | {cpu_txt} | {gpu_txt} | {r.get('performance_class')} | {r.get('upgradeability')} | {r.get('z20_fit')} |")

    lines += [
        '',
        '## Færdige computere — markedsreference',
        '',
        'Færdige PC’er er sekundære prisankre og ekstraordinære køb. Hver række linker kun til den konkrete T1-verificerede DBA-annonce, som ruten stammer fra.',
        '',
        '| # | PC / direkte link | T1 ASK | WoW | Upgrade | Z20 |',
        '|---:|---|---:|---|---|---|',
    ]
    for i, r in enumerate(complete[:30], 1):
        lines.append(f"| {i} | {complete_link(r)} | **{money(r.get('tcwp'))}** | {r.get('performance_class')} | {r.get('upgradeability')} | {r.get('z20_fit')} |")

    lines += [
        '',
        '## Del-for-del policy',
        '',
    ]
    for kind in ORDER:
        p = (policy.get('categories') or {}).get(kind) or {}
        hard = ', '.join(p.get('hard') or [])
        lines.append(f"- **{DA[kind]} ({p.get('role','—')}):** hard gates: {hard}. {p.get('principle','—')}")

    lines += [
        '',
        '## Pris- og evidensregel',
        '',
        'USED ASK kræver live T0→T1-verificeret DBA listing-object, identitet, pris, aktiv status og direkte URL. Funktionelle fejl er HARD EXCLUDE. Retailkandidater kræver samme-produkt live prisverifikation i den aktuelle run; et uverificeret retailprodukt kan ikke vinde og gamle hardcodede priser bruges ikke som fallback.',
        '',
        '## Metodisk forskel fra V18',
        '',
        '- V18 sammenlignede primært en brugtpris mod én fast ny reference.',
        '- V19 sammenligner et live-verificeret kandidatunivers.',
        '- V19 hard-excluder kandidater, der ikke opfylder fundamentkravene, uanset pris.',
        '- V19 bruger Pareto-dominans før vægtning, så en dyrere del uden projektrelevant fordel ikke kan reddes af en score.',
        '- V19 kræver en eksplicit og begrænset økonomisk værdi for de features, der retfærdiggør en premium.',
        '',
    ]

    text = '\n'.join(lines)
    for marker in ('ANBEFALET SELVBYG','Hvorfor hver permanent del vandt','Markedsdækning','Fuld del-for-del sammenligning','Pareto','GPU-marked','CPU-marked','Selvbyg-ranking','Færdige computere — markedsreference','Pris- og evidensregel'):
        assert marker in text, marker
    for c in rec.get('components') or []:
        assert c.get('url') and c['url'] in text
    for r in gpu_market + cpu_market:
        assert r['component'].get('url') and r['component']['url'] in text
    for r in complete[:30]:
        c = next((x for x in r.get('components',[]) if x.get('source') == 'USED ASK' and x.get('url')), None)
        if c:
            assert c['url'] in text

    OUT.write_text(text, encoding='utf-8')
    CANONICAL.write_text(text, encoding='utf-8')
    LEGACY.write_text(text, encoding='utf-8')
    ALIAS.write_text(text, encoding='utf-8')
    print(json.dumps({
        'report': True,
        'model': d['model_version'],
        'recommended_tcwp': rec.get('tcwp'),
        'market_coverage': coverage.get('passed'),
        'linked_components': len(rec.get('components') or []),
        'linked_gpu_market': len(gpu_market),
        'linked_cpu_market': len(cpu_market),
        'complete_pc_rows': min(30, len(complete)),
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
