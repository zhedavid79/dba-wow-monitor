from __future__ import annotations

import json
from pathlib import Path

SRC = Path('results/wow_strategy_latest.json')
CANONICAL = Path('results/wow_self_build_report.md')
LEGACY = Path('results/wow_platform_first_report.md')
ALIAS = Path('results/wow_a3_report.md')

ORDER = ('MOTHERBOARD','PSU','CASE','COOLER','RAM','CPU','GPU','STORAGE')
DA = {'MOTHERBOARD':'Bundkort','PSU':'Strømforsyning','CASE':'Kabinet','COOLER':'CPU-køler','RAM':'RAM','CPU':'CPU','GPU':'Grafikkort','STORAGE':'SSD/lager'}


def money(n):
    if n is None:
        return '—'
    return f"{int(n):,}".replace(',', '.') + ' kr.'


def link(obj, fallback='—'):
    if not obj:
        return fallback
    name = str(obj.get('name') or fallback).replace('|','/')
    url = obj.get('url')
    return f"[{name}]({url})" if url else name


def selected(route, kind):
    return next((c for c in (route or {}).get('components',[]) if c.get('kind') == kind), None)


def build_summary(route):
    if not route:
        return 'Ingen verificeret kandidat.'
    return f"**{money(route.get('tcwp'))} — {route.get('cpu')} + {route.get('gpu')} — {route.get('performance_class')} — upgrade {route.get('upgradeability')} — Z20 {route.get('z20_fit')}**"


def complete_link(route):
    c = next((x for x in route.get('components',[]) if x.get('source') == 'USED ASK' and x.get('url')), None)
    name = f"{route.get('cpu')} + {route.get('gpu')}"
    return f"[{name}]({c['url']})" if c else name


def main():
    d = json.loads(SRC.read_text(encoding='utf-8'))
    assert d.get('gate_passed') is True
    assert d.get('model_version') == 'DBA-WOW-SELF-BUILD-FIRST-V18'
    rec = d.get('recommended_self_build') or {}
    decisions = rec.get('component_market_decisions') or {}
    self_build = d.get('self_build_ranked') or []
    complete = d.get('complete_pc_reference') or []
    value = d.get('value_foundation_build')
    step = d.get('performance_step_up_build')

    lines = [
        '# FULDT PÅLIDELIG DBA-PRISRAPPORT — WoW SELF-BUILD FIRST V18',
        '',
        f"Generated: {d.get('generated_at')}",
        'Mål: WoW Classic/Cataclysm ved 3840×1600/75 Hz, stærk raid/crowded-combat performance og et kompakt AM5-system, der kan opgraderes løbende.',
        'V18 sammenligner nu brugtprisen direkte mod en frisk nypris-reference for hver del og giver BUY/WAIT/USED/NEW-beslutning. SO-DIMM/server-RAM er hard-excluded fra desktop-builds.',
        '',
        '## 🧭 ANBEFALET SELVBYG',
        '',
        build_summary(rec),
        '',
        '## 💸 Brugt vs. nyt — del-for-del købsbeslutning',
        '',
        '| Del | Valgt i build | Bedste verificerede brugt | Brugtpris | Ny reference | Nypris | Besparelse vs. ny | Handling |',
        '|---|---|---|---:|---|---:|---:|---|',
    ]

    for kind in ORDER:
        dec = decisions.get(kind) or {}
        cur = selected(rec, kind)
        used = dec.get('best_used')
        new = dec.get('new_reference')
        saving = dec.get('saving_dkk')
        pct = dec.get('saving_pct')
        saving_txt = '—' if saving is None else f"{money(saving)} ({pct:.1f}%)"
        cur_src = 'BRUGT' if cur and cur.get('source') == 'USED ASK' else 'NY' if cur else '—'
        cur_txt = f"{cur_src}: {link(cur)} — {money((cur or {}).get('price'))}" if cur else '—'
        lines.append(
            f"| {DA[kind]} | {cur_txt} | {link(used)} | {money(dec.get('used_price'))} | {link(new)} | {money(dec.get('new_price'))} | {saving_txt} | **{dec.get('decision','WAIT')}** |"
        )

    lines += ['', '### Hvorfor modellen vælger sådan', '']
    for kind in ORDER:
        dec = decisions.get(kind) or {}
        lines.append(f"- **{DA[kind]} — {dec.get('decision','WAIT')}:** {dec.get('reason','—')}")

    lines += [
        '',
        '## Tre selvbyg-spor',
        '',
        '| Spor | Løsning | Rolle |',
        '|---|---|---|',
        f"| **Anbefalet balance** | {build_summary(rec)} | Bedste kombination af aktuel performance, permanent platform og markedspris. |",
        f"| **Billigste stærke fundament** | {build_summary(value)} | Lavest verificerede TCWP med det rigtige AM5/Z20-fundament. |",
        f"| **Performance step-up** | {build_summary(step)} | Billigste SWEET SPOT-rute på samme opgraderbare fundament. |",
        '',
        '## Aktuelt anbefalet BOM',
        '',
        '| Del | Kilde | Pris |',
        '|---|---|---:|',
    ]
    for kind in ORDER:
        c = selected(rec, kind)
        src = 'BRUGT' if c and c.get('source') == 'USED ASK' else 'NY'
        lines.append(f"| {DA[kind]} | {src}: {link(c)} | **{money((c or {}).get('price'))}** |")

    lines += [
        '',
        '## Selvbyg-ranking',
        '',
        '| # | TCWP | Beslutningsscore | CPU | GPU | WoW | Upgrade | Z20 |',
        '|---:|---:|---:|---|---|---|---|---|',
    ]
    for i, r in enumerate(self_build[:30], 1):
        lines.append(f"| {i} | **{money(r.get('tcwp'))}** | {money(r.get('self_build_effective_cost',r.get('tcwp')))} | {r.get('cpu')} | {r.get('gpu')} | {r.get('performance_class')} | {r.get('upgradeability')} | {r.get('z20_fit')} |")

    lines += [
        '',
        '## Færdige computere — markedsreference',
        '',
        'Færdige PC’er beholdes som prisanker og ekstraordinære køb, men er sekundære til det opgraderbare selvbyg-spor.',
        '',
        '| # | PC | T1 ASK | WoW | Upgrade | Z20 |',
        '|---:|---|---:|---|---|---|',
    ]
    for i, r in enumerate(complete[:30], 1):
        lines.append(f"| {i} | {complete_link(r)} | **{money(r.get('tcwp'))}** | {r.get('performance_class')} | {r.get('upgradeability')} | {r.get('z20_fit')} |")

    lines += [
        '',
        '## Pris- og evidensregel',
        '',
        'USED ASK kræver live T0→T1-verificeret DBA listing-object. Nye priser er særskilte danske retail/prissammenligningsreferencer verificeret 5. september 2026. GPU-nyprisen kan være en aktuel target-class reference frem for samme udgåede GPU-model; dette er markeret i data. Defekte dele, inaktive annoncer, accessory-falskpositiver og inkompatibel SO-DIMM/server-RAM er hard-excluded.',
        '',
    ]

    text = '\n'.join(lines)
    assert 'KF548S38IBK2' not in text
    assert 'Brugt vs. nyt' in text
    assert 'Nypris' in text
    assert 'Handling' in text
    CANONICAL.write_text(text, encoding='utf-8')
    LEGACY.write_text(text, encoding='utf-8')
    ALIAS.write_text(text, encoding='utf-8')
    print(json.dumps({'report': True, 'model': d['model_version'], 'recommended_tcwp': rec.get('tcwp'), 'rows': len(decisions)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
