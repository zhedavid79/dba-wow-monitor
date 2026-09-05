from __future__ import annotations

import json
from pathlib import Path

SRC = Path('results/wow_strategy_latest.json')
CANONICAL = Path('results/wow_self_build_report.md')
LEGACY = Path('results/wow_platform_first_report.md')
ALIAS = Path('results/wow_a3_report.md')
EXCLUDED_LISTING_IDS = {'7969913': 'PURCHASE_ATTEMPTED', '11596289': 'ACCESSORY_FALSE_POSITIVE'}

KIND_ORDER = ('MOTHERBOARD', 'PSU', 'CASE', 'COOLER', 'RAM', 'CPU', 'GPU', 'STORAGE')
KIND_DA = {
    'MOTHERBOARD': 'Bundkort', 'PSU': 'Strømforsyning', 'CASE': 'Kabinet', 'COOLER': 'CPU-køler',
    'RAM': 'RAM', 'CPU': 'CPU', 'GPU': 'Grafikkort', 'STORAGE': 'SSD/lager',
}


def money(n):
    return f"{int(n):,}".replace(',', '.') + ' kr.'


def listing_ids(route):
    return {str(c.get('listing_id')) for c in (route or {}).get('components', []) if c.get('listing_id')}


def excluded(route):
    return bool(listing_ids(route) & set(EXCLUDED_LISTING_IDS))


def component(route, kind):
    return next((c for c in (route or {}).get('components', []) if c.get('kind') == kind), None)


def linked(c):
    if not c:
        return '—'
    name = str(c.get('name') or c.get('kind') or 'Del').replace('|', '/')
    if c.get('url'):
        name = f"[{name}]({c['url']})"
    src = 'BRUGT' if c.get('source') == 'USED ASK' else 'NY'
    return f"{src}: {name} — {money(c.get('price', 0))}"


def complete_link(route):
    comps = (route or {}).get('components') or []
    c = next((x for x in comps if x.get('source') == 'USED ASK' and x.get('url')), None)
    if not c:
        return f"{route.get('cpu')} + {route.get('gpu')}"
    return f"[{route.get('cpu')} + {route.get('gpu')}]({c['url']})"


def build_summary(route):
    if not route:
        return 'Ingen verificeret selvbyg-rute.'
    return (
        f"**{money(route['tcwp'])} — {route.get('cpu')} + {route.get('gpu')} — "
        f"{route.get('performance_class')} — upgrade {route.get('upgradeability')} — Z20 {route.get('z20_fit')}**"
    )


def alt_rows(route, kind, limit=4):
    alts = ((route or {}).get('component_alternatives') or {}).get(kind) or []
    out = []
    seen = set()
    for a in alts:
        key = (a.get('name'), int(a.get('price') or 0), a.get('url'))
        if key in seen:
            continue
        seen.add(key)
        name = str(a.get('name') or kind).replace('|', '/')
        if a.get('url'):
            name = f"[{name}]({a['url']})"
        out.append((name, int(a.get('price') or 0), a.get('source') or '—', a.get('pros') or '—', a.get('cons') or '—'))
        if len(out) >= limit:
            break
    return out


def main():
    d = json.loads(SRC.read_text(encoding='utf-8'))
    assert d.get('gate_passed') is True
    assert d.get('model_version') == 'DBA-WOW-SELF-BUILD-FIRST-V17'
    assert d.get('strategy_mode') == 'SELF_BUILD_FIRST_UPGRADEABLE'

    self_build = [r for r in (d.get('self_build_ranked') or []) if not excluded(r)]
    completes = [r for r in (d.get('complete_pc_reference') or []) if not excluded(r)]
    recommended = d.get('recommended_self_build')
    if recommended and excluded(recommended):
        recommended = self_build[0] if self_build else None
    value = d.get('value_foundation_build')
    if value and excluded(value):
        value = self_build[0] if self_build else None
    step = d.get('performance_step_up_build')
    if step and excluded(step):
        step = None
    policy = d.get('part_policy') or {}

    lines = [
        '# FULDT PÅLIDELIG DBA-PRISRAPPORT — WoW SELF-BUILD FIRST V17',
        '',
        f"Generated: {d.get('generated_at')}",
        'Mål: WoW Classic/Cataclysm ved 3840×1600 op til 75 Hz, stærk raid/crowded-combat performance og et kompakt, løbende opgraderbart system.',
        'Primært mål: byg selv på et permanent AM5/Z20-fundament. Komplette brugte PC’er beholdes som markedsreference og kan kun slå selvbyg-sporet ved en ekstraordinær totalhandel.',
        '',
        '## Strategisk fokus',
        '',
        '- **Køb én gang:** bundkort, PSU, kabinet og i høj grad køler.',
        '- **Køb fornuftigt nu, opgrader senere:** CPU og især GPU.',
        '- **Undgå prestige-overbetaling:** betal for funktioner og levetid, ikke chipset/branding uden konkret behov.',
        '- **Bevar optionalitet:** en billig ACCEPTABLE bridge-del må gerne vinde, hvis næste performance-trin er dårligt prissat.',
        '- **PSU-headroom er bevidst:** lidt ekstra kapacitet på en kvalitets-PSU kan være billigere end at købe PSU to gange.',
        '',
        f"HANDLING: **{d.get('wait_buy')}**",
        '',
        '## 🧭 ANBEFALET SELVBYG',
        '',
        build_summary(recommended),
        '',
    ]

    if recommended:
        lines += ['| Del | Valg nu | Rolle | Hvorfor dette fokus |', '|---|---|---|---|']
        for kind in KIND_ORDER:
            p = policy.get(kind) or {}
            lines.append(f"| {KIND_DA[kind]} | {linked(component(recommended, kind))} | **{p.get('role','—')}** | {p.get('spend_rule','—')} |")
        lines.append('')

    lines += [
        '## Tre selvbyg-spor',
        '',
        '| Spor | Løsning | Hvornår det giver mening |',
        '|---|---|---|',
        f"| **Anbefalet balance** | {build_summary(recommended)} | Bedste samlede kombination af permanent platform, nuværende WoW-performance og pris. |",
        f"| **Billigste stærke fundament** | {build_summary(value)} | Når du vil minimere indgangsprisen og acceptere bridge-performance nu. |",
        f"| **Performance step-up** | {build_summary(step)} | Billigste verificerede AM5/Z20-rute i SWEET SPOT, hvis merprisen er rimelig. |",
        '',
        '## Del-for-del købsplan',
        '',
    ]

    for kind in KIND_ORDER:
        p = policy.get(kind) or {}
        cur = component(recommended, kind) if recommended else None
        lines += [
            f"### {KIND_DA[kind]}",
            '',
            f"**Bedst princip:** {p.get('best','—')}",
            '',
            f"**Valg nu:** {linked(cur)}",
            '',
            f"**Købsregel:** {p.get('spend_rule','—')}",
            '',
            f"**Brugt/nyt:** {p.get('used_rule','—')}",
            '',
        ]
        alts = alt_rows(recommended, kind)
        if alts:
            lines += ['| Alternativ | Pris | Kilde | Fordel | Ulempe |', '|---|---:|---|---|---|']
            for name, price, src, pros, cons in alts:
                lines.append(f"| {name} | {money(price)} | {src} | {pros} | {cons} |")
            lines.append('')

    lines += [
        '## Selvbyg-ranking',
        '',
        '| # | TCWP | Beslutningsscore | CPU | GPU | WoW | Upgrade | Z20 | Foundation |',
        '|---:|---:|---:|---|---|---|---|---|---|',
    ]
    for i, r in enumerate(self_build[:40], 1):
        lines.append(
            f"| {i} | **{money(r['tcwp'])}** | {money(r.get('self_build_effective_cost', r['tcwp']))} | "
            f"{r.get('cpu')} | {r.get('gpu')} | {r.get('performance_class')} | {r.get('upgradeability')} | {r.get('z20_fit')} | {r.get('foundation','—')} |"
        )

    lines += [
        '',
        '## Færdige computere — markedsreference',
        '',
        'De færdige PC’er er fortsat med, men de er ikke længere rapportens primære BUY NOW-logik. De bruges som prisanker og som mulighed, hvis en komplet maskine giver mere hardwareværdi end selvbyg-ruten uden at ødelægge opgraderingsmålet.',
        '',
        '| # | PC | T1 ASK | WoW | Upgrade | Z20 |',
        '|---:|---|---:|---|---|---|',
    ]
    for i, r in enumerate(completes[:30], 1):
        lines.append(f"| {i} | {complete_link(r)} | **{money(r['tcwp'])}** | {r.get('performance_class')} | {r.get('upgradeability')} | {r.get('z20_fit')} |")

    lines += [
        '',
        '## Pris- og evidensregel',
        '',
        'Alle USED ASK-dele og komplette PC’er i rapporten skal komme fra live T0→T1-verificerede DBA listing-objects. Defekte dele, accessory-falskpositiver og inaktive annoncer er hard-excluded. Nye retail-dele er separat mærket og bruges som konkrete fundament-/fallback-priser.',
        '',
    ]

    text = '\n'.join(lines)
    assert '/item/11596289' not in text
    assert '## Færdige computere — markedsreference' in text
    assert '## Del-for-del købsplan' in text
    assert '## 🧭 ANBEFALET SELVBYG' in text
    CANONICAL.write_text(text, encoding='utf-8')
    LEGACY.write_text(text, encoding='utf-8')
    ALIAS.write_text(text, encoding='utf-8')
    print(json.dumps({
        'report': True,
        'model': d['model_version'],
        'self_build_rows': min(40, len(self_build)),
        'complete_pc_rows': min(30, len(completes)),
        'recommended_tcwp': (recommended or {}).get('tcwp'),
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
