from __future__ import annotations

import json
import re
from pathlib import Path

STRATEGY = Path('results/wow_strategy_latest.json')
PLAN = Path('results/procurement_plan_v22.json')
OFFERS = Path('results/retail_offers_v22.json')
BASE = Path('results/wow_self_build_report_v21.md')
OUT = Path('results/wow_self_build_report_v22.md')
CANONICAL = Path('results/wow_self_build_report.md')
LEGACY = Path('results/wow_platform_first_report.md')
ALIAS = Path('results/wow_a3_report.md')
DA = {'MOTHERBOARD':'Bundkort','PSU':'Strømforsyning','CASE':'Kabinet','COOLER':'CPU-køler','RAM':'RAM','CPU':'CPU','GPU':'Grafikkort','STORAGE':'SSD/lager'}


def money(v):
    try:
        return f"{int(v):,}".replace(',', '.') + ' kr.'
    except Exception:
        return '—'


def link(name, url):
    return f'[{name}]({url})' if url else str(name or '—')


def eligible_skus(strategy: dict) -> set[str]:
    out = set()
    rec = strategy.get('recommended_self_build') or {}
    dec = rec.get('component_choice_v19') or {}
    for d in dec.values():
        for x in (d or {}).get('evaluated') or []:
            if x.get('eligible') is True and x.get('sku'):
                out.add(str(x['sku']))
    return out


def action_section(p: dict) -> str:
    selected = {str(x.get('sku') or ''): x for x in (p.get('retail_offers_v22') or {}).get('selected') or []}
    lines = [
        '## ✅ Hvad skal jeg gøre i dag?', '',
        '| Del | Handling | ASK/reference | Første bud | Target | Walk-away | Kilde / note |',
        '|---|---|---:|---:|---:|---:|---|',
    ]
    for a in p.get('actions') or []:
        kind = DA.get(a.get('kind'), a.get('kind'))
        act = str(a.get('procurement_action') or '—')
        label = {'BUY_NOW':'KØB NU','BID':'BYD','WAIT':'VENT','CHECK_STORE':'TJEK BUTIK','VERIFY_VALUE':'TJEK VÆRDI'}.get(act, act)
        url = a.get('url')
        note = a.get('reason') or '—'
        if a.get('source') == 'NEW RETAIL':
            rr = selected.get(str(a.get('sku') or '')) or {}
            url = (rr.get('buy_url') if rr.get('purchase_ready') else rr.get('comparison_url')) or url
            if not rr.get('purchase_ready'):
                note = 'Prisreference בלבד; ekstern butik, samme pris og lager er ikke verificeret. Ikke KØB NU.'
        lines.append(
            f"| {kind} | **{label}** | {money(a.get('ask'))} | {money(a.get('first_bid'))} | {money(a.get('target'))} | {money(a.get('walk_away'))} | {link(a.get('name'), url)} — {note} |"
        )
    lines += ['', '`TJEK BUTIK` betyder, at produkt/pris er et aktuelt sammenligningslead, men ikke en købsklar pris. KØB NU kræver direkte slutbutik + samme produkt + samme pris + lager verificeret i samme run.', '']
    return '\n'.join(lines)


def main() -> None:
    s = json.loads(STRATEGY.read_text(encoding='utf-8'))
    p = json.loads(PLAN.read_text(encoding='utf-8'))
    o = json.loads(OFFERS.read_text(encoding='utf-8'))
    assert p.get('version') == 'V22' and (s.get('offer_optimizer_v22') or {}).get('active') is True and BASE.exists()

    text = BASE.read_text(encoding='utf-8')
    text = text.replace('SELF-BUILD FIRST V21 — PROCUREMENT', 'SELF-BUILD FIRST V22 — PROCUREMENT + DEALS')
    text = text.replace('V21 bruger', 'V22 bruger').replace('V21 beholder', 'V22 beholder').replace('STYRENDE V21-STATUS', 'STYRENDE V22-STATUS')

    headline = p.get('headline') or {}
    ready = bool(headline.get('ready_to_buy_complete_build_today'))
    fit = str(headline.get('z20_fit') or 'UNKNOWN')
    ready_phrase = f"**Kan hele buildet købes rationelt i dag? {'JA' if ready else 'NEJ'}**"
    text = re.sub(r"\*\*Kan hele buildet købes rationelt i dag\? (?:JA|NEJ)\*\*", ready_phrase, text, count=1)
    text = re.sub(r"\*\*Styrende Z20-fit:\*\* [^\n]+", f"**Styrende Z20-fit:** {fit}", text, count=1)

    # Replace inherited V21 action table so old BUY_NOW labels can never leak.
    new_actions = action_section(p)
    text, n = re.subn(r'## ✅ Hvad skal jeg gøre i dag\?\n.*?(?=\n## )', new_actions + '\n', text, count=1, flags=re.S)
    assert n == 1, 'Could not replace V21 action section'

    selected = (p.get('retail_offers_v22') or {}).get('selected') or []
    direct_selected = [x for x in selected if x.get('purchase_ready')]
    reference_selected = [x for x in selected if not x.get('purchase_ready')]

    lines = [
        '## 🏷️ Nye dele — tilbud, butik og leveret pris', '',
        '**Sikkerhedsregel:** Prisjagt alene er en prisreference/lead. En pris bliver først KØB NU, når den eksterne slutbutik selv er verificeret med samme produkt, pris og lager i samme run.', '',
        '| Del | Produkt | Pris | Evidens | Handling |',
        '|---|---|---:|---|---|',
    ]
    for r in selected:
        if r.get('purchase_ready'):
            lines.append(f"| {DA.get(r.get('kind'), r.get('kind'))} | {link(r.get('name'), r.get('buy_url'))} | **{money(r.get('delivered_price_dkk'))}** | Direkte ekstern butik verificeret | **KØB NU** |")
        else:
            lines.append(f"| {DA.get(r.get('kind'), r.get('kind'))} | {link(r.get('name'), r.get('comparison_url'))} | **{money(r.get('comparison_price_dkk'))}** | Sammenligningspris; slutbutik ikke verificeret | **TJEK BUTIK** |")
    lines += ['', f"Direkte købsklare nye dele: **{len(direct_selected)}/{len(selected)}**. Prisreference-only: **{len(reference_selected)}**."]
    if reference_selected:
        lines += ['', '**Der vises ingen samlet autoritativ købsklar pris for de nye dele**, fordi mindst én pris kun er en sammenligningsreference.']
    else:
        lines += ['', f"**Leveret, købsklar pris for alle valgte nye dele:** {money(sum(int(x.get('delivered_price_dkk') or 0) for x in direct_selected))}."]
    lines.append('')

    eligible = eligible_skus(s)
    deal_rows = []
    for r in o.get('rows') or []:
        if str(r.get('sku') or '') not in eligible:
            continue
        if r.get('delivered_price_verified') is not True or r.get('external_url_resolved') is not True:
            continue
        deal_rows.append(r)
    deal_rows.sort(key=lambda x: int(x.get('delivered_price_dkk') or 10**9))

    lines += [
        '## 🔎 Andre kvalificerede nye tilbud fundet', '',
        f"Sammenligningsunivers: **{o.get('products_total')}** produkter · Prisjagt/store-card leads: **{o.get('delivered_price_verified')}** · direkte eksternt resolvebare tilbud: **{o.get('external_urls_resolved')}**.", '',
        '| Del | Direkte verificeret butikstilbud | Leveret | Status |',
        '|---|---|---:|---|',
    ]
    for r in deal_rows[:25]:
        lines.append(f"| {DA.get(r.get('kind'), r.get('kind'))} | {link(r.get('name'), r.get('buy_url'))} | **{money(r.get('delivered_price_dkk'))}** | DIREKTE VERIFICERET |")
    if not deal_rows:
        lines.append('| — | Ingen tilbud havde en verificerbar ekstern slutbutik i dette run | — | Prisjagt-leads er ikke KØB NU |')
    lines += ['', '**Regel:** Et tilbudsbadge eller en Prisjagt offer-ID giver ingen købsgodkendelse. Kun direkte butiksevidens må ændre den autoritative købsklare pris.', '']

    blockers = p.get('blockers') or []
    gate = ['## 🚦 KØBSKLAR-gate', '', f"**Hele buildet KØBSKLAR nu: {'JA' if ready else 'NEJ'}**", '', f"**Styrende Z20-fit:** {fit}", '']
    if blockers:
        gate.append('Aktuelle blokeringer:')
        for b in blockers:
            gate.append(f"- **{b.get('kind')} — {b.get('procurement_action')}:** {b.get('reason') or '—'}")
    else:
        gate.append('Ingen blokeringer; alle valgte dele er købsklare på de verificerede vilkår.')
    gate += ['', '`UNKNOWN` fit eller uverificeret slutbutik må aldrig give KØBSKLAR.', '']

    marker = '\n## Hvorfor hver permanent del vandt\n'
    addition = '\n'.join(lines + gate)
    if marker in text:
        text = text.replace(marker, '\n' + addition + marker, 1)
    else:
        text += '\n\n' + addition

    text = text.replace('## V21 — GPU value, Z20-fit og budmodel', '## V22 — GPU value, Z20-fit og budmodel')
    text = text.replace('## V21 — RAM-bud og bridge-kontrol', '## V22 — RAM-bud og bridge-kontrol')
    text = text.replace('## V21 — CPU-bud', '## V22 — CPU-bud')
    text = text.replace('## V21 — dynamisk retail discovery', '## V22 — dynamisk retail discovery')
    text = text.replace('## V21 — shared same-run T1-cache', '## V22 — shared same-run T1-cache')
    text = text.replace('## V21 — GPU discovery-pool', '## V22 — GPU discovery-pool')

    assert 'Nye dele — tilbud, butik og leveret pris' in text
    assert 'Andre kvalificerede nye tilbud fundet' in text
    assert 'KØBSKLAR-gate' in text
    assert ready_phrase in text
    if not ready:
        assert '**Kan hele buildet købes rationelt i dag? JA**' not in text
    if reference_selected:
        assert '**TJEK BUTIK**' in text
        assert '**Der vises ingen samlet autoritativ købsklar pris for de nye dele**' in text
    assert '7969913' not in '\n'.join(line for line in text.splitlines() if 'HARD EXCLUDE' not in line and 'Historiske hard exclusions' not in line)

    for path in (OUT, CANONICAL, LEGACY, ALIAS):
        path.write_text(text, encoding='utf-8')
    print(json.dumps({
        'V22_REPORT': True,
        'ask_total_reference': headline.get('ask_total'),
        'authoritative_purchase_total': headline.get('authoritative_purchase_total'),
        'fit': fit,
        'ready_today': ready,
        'direct_buy_ready_new': len(direct_selected),
        'reference_only_new': len(reference_selected),
        'direct_offer_rows': len(deal_rows),
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
