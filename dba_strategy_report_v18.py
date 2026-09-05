from __future__ import annotations

import json
import re
from pathlib import Path

SRC = Path('results/wow_strategy_latest.json')
CANONICAL = Path('results/wow_self_build_report.md')
LEGACY = Path('results/wow_platform_first_report.md')
ALIAS = Path('results/wow_a3_report.md')

ORDER = ('MOTHERBOARD','PSU','CASE','COOLER','RAM','CPU','GPU','STORAGE')
DA = {'MOTHERBOARD':'Bundkort','PSU':'Strømforsyning','CASE':'Kabinet','COOLER':'CPU-køler','RAM':'RAM','CPU':'CPU','GPU':'Grafikkort','STORAGE':'SSD/lager'}
BAD_RAM = re.compile(r'\b(?:so[- ]?dimm|sodimm|rdimm|lrdimm|registered|server\s*ram|kingston\s+fury\s+impact|kf548s38ibk2(?:-\d+)?)\b', re.I)


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


def component_rank_link(route, kind, fallback):
    c = selected(route, kind)
    if c and c.get('url'):
        return f"[{fallback}]({c['url']})"
    return str(fallback)


def alternative_rows(route, kind, decision):
    rows = []
    cur = selected(route, kind)
    if cur:
        x = dict(cur)
        x['_status'] = 'VALGT I BUILD'
        rows.append(x)

    for a in ((route.get('component_alternatives') or {}).get(kind) or []):
        x = dict(a)
        x['_status'] = 'VERIFICERET ALTERNATIV' if x.get('source') == 'USED ASK' else 'NYT ALTERNATIV'
        rows.append(x)

    for key, status in (('best_used','BEDSTE BRUGT'), ('new_reference','NY REFERENCE')):
        a = (decision or {}).get(key)
        if a:
            x = dict(a)
            x.setdefault('source', 'USED ASK' if key == 'best_used' else 'NEW RETAIL')
            x['_status'] = status
            rows.append(x)

    out, seen = [], set()
    for x in rows:
        name = str(x.get('name') or '')
        if kind == 'RAM' and BAD_RAM.search(name):
            continue
        price = int(x.get('price') or 0)
        url = str(x.get('url') or '')
        if not name or price <= 0 or not url:
            continue
        key = (name, price, url)
        if key in seen:
            continue
        seen.add(key)
        out.append(x)
    return out[:12]


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
        'V18 sammenligner brugtprisen direkte mod en frisk nypris-reference for hver del og giver BUY/WAIT/USED/NEW-beslutning. Alle konkrete køb og alternativer i rapporten har direkte klikbare links. SO-DIMM/server-RAM er hard-excluded fra desktop-builds.',
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
        '| Del | Kilde / direkte link | Pris |',
        '|---|---|---:|',
    ]
    for kind in ORDER:
        c = selected(rec, kind)
        src = 'BRUGT' if c and c.get('source') == 'USED ASK' else 'NY'
        lines.append(f"| {DA[kind]} | {src}: {link(c)} | **{money((c or {}).get('price'))}** |")

    lines += ['', '## 🔗 Del-for-del alternativer — direkte links', '']
    for kind in ORDER:
        dec = decisions.get(kind) or {}
        alts = alternative_rows(rec, kind, dec)
        lines += [f"### {DA[kind]}", '']
        if not alts:
            lines += ['Ingen yderligere verificerede alternativer med direkte link i denne kørsel.', '']
            continue
        lines += [
            '| Valg | Kilde | Pris | Status |',
            '|---|---|---:|---|',
        ]
        for a in alts:
            src = 'BRUGT' if a.get('source') == 'USED ASK' else 'NY'
            lines.append(f"| {link(a)} | {src} | **{money(a.get('price'))}** | {a.get('_status')} |")
        lines.append('')

    lines += [
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
        'Færdige PC’er beholdes som prisanker og ekstraordinære køb, men er sekundære til det opgraderbare selvbyg-spor. PC-navnet linker direkte til den T1-verificerede DBA-annonce.',
        '',
        '| # | PC / direkte link | T1 ASK | WoW | Upgrade | Z20 |',
        '|---:|---|---:|---|---|---|',
    ]
    for i, r in enumerate(complete[:30], 1):
        lines.append(f"| {i} | {complete_link(r)} | **{money(r.get('tcwp'))}** | {r.get('performance_class')} | {r.get('upgradeability')} | {r.get('z20_fit')} |")

    lines += [
        '',
        '## Pris- og evidensregel',
        '',
        'USED ASK kræver live T0→T1-verificeret DBA listing-object. Nye priser er særskilte danske retail/prissammenligningsreferencer. GPU-nyprisen kan være en aktuel target-class reference frem for samme udgåede GPU-model; dette er markeret i data. Defekte dele, inaktive annoncer, accessory-falskpositiver og inkompatibel SO-DIMM/server-RAM er hard-excluded. En konkret del må ikke vises som købbar i rapporten uden et direkte URL-link.',
        '',
    ]

    text = '\n'.join(lines)
    assert 'KF548S38IBK2' not in text
    assert 'Brugt vs. nyt' in text
    assert 'Nypris' in text
    assert 'Handling' in text
    assert 'Del-for-del alternativer — direkte links' in text
    for c in rec.get('components') or []:
        assert c.get('url') and c['url'] in text
    CANONICAL.write_text(text, encoding='utf-8')
    LEGACY.write_text(text, encoding='utf-8')
    ALIAS.write_text(text, encoding='utf-8')
    print(json.dumps({'report': True, 'model': d['model_version'], 'recommended_tcwp': rec.get('tcwp'), 'rows': len(decisions), 'linked_components': len(rec.get('components') or [])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
