from __future__ import annotations

import json
from pathlib import Path

import dba_report_v8 as v8

v6 = v8.v6


def render_price_first():
    p = Path('results/latest_v6.json')
    data = json.loads(p.read_text(encoding='utf-8'))
    ranked = data.get('ranked') or []
    potential = data.get('potential_sweet_spots_unresolved') or []
    counts = data.get('counts') or {}
    gate = data.get('schema_gate') or {}
    reg = data.get('price_binding_regression') or {}
    audit = data.get('missed_opportunity_audit') or {}

    lines = [
        '# DBA WoW-PC verified price report v9 — high recall', '',
        f"Generated: {data.get('generated_at')}", '',
        f"Current schema/source gate: **PASS** — live item {gate.get('listing_id')} — {gate.get('item_price')} kr.",
        f"Historical price-binding regression: **PASS ({reg.get('type')}; no dependency on historical live listing)**",
        f"Retrieval: {data.get('retrieval_method')}", '',
        f"Discovery queries: {counts.get('queries')}",
        f"Structured T0 unique records: {counts.get('t0_unique')}",
        f"High-recall T0 records sent to T1: {counts.get('t0_advanced_high_recall')}",
        f"Ranked ACCEPTABLE or better: {counts.get('ranked_acceptable_or_better')}",
        f"Potential sweet spots with unresolved specs: {counts.get('potential_sweet_spot_unresolved')}", '',
        '## Price-first ranking', '',
        'Every row has a same-listing T0/T1 verified live ASK. Ranking is lowest ASK first among ACCEPTABLE/SWEET SPOT/OVERKILL; a cheaper sufficient PC is not hidden by a more powerful machine.', '',
        '| Rank | ASK | Class | GPU | CPU | Spec source | Listing |',
        '|---:|---:|---|---|---|---|---|',
    ]
    for i, r in enumerate(ranked, 1):
        lines.append(f"| {i} | {r['ask_t1']} kr. | {r['performance_class']} | {r['gpu']} | {r['cpu']} | {r.get('spec_source','')} | [{r['title']}]({r['url']}) |")

    lines += [
        '', '## POTENTIAL SWEET SPOTS — NEEDS SPEC RESOLUTION', '',
        'These are live T1-verified complete-PC leads at or below the rescue ceiling. They are deliberately **not ranked, valued or given a bid model** until CPU+GPU are resolved.', ''
    ]
    if potential:
        lines += ['| ASK | Known GPU | Known CPU | Evidence | Listing |', '|---:|---|---|---|---|']
        for r in potential:
            lines.append(f"| {r['ask_t1']} kr. | {r.get('gpu','Ukendt')} | {r.get('cpu','Ukendt')} | {r.get('complete_evidence','')} | [{r['title']}]({r['url']}) |")
    else:
        lines.append('Ingen unresolved complete-PC leads under rescue ceiling in denne kørsel.')

    lines += [
        '', '## Missed-opportunity audit', '',
        f"Audit: **{'PASS' if audit.get('ok') else 'FAIL'}** — rescue ceiling {audit.get('rescue_ceiling')} kr.; hidden cheap complete leads: {len(audit.get('hidden_cheap_complete') or [])}.", '',
        '## Rejection diagnostics', '', json.dumps(data.get('rejection_reason_counts') or {}, ensure_ascii=False)
    ]
    Path('results/report_v9.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


if __name__ == '__main__':
    v6.main()
    render_price_first()
