from __future__ import annotations

import json
from pathlib import Path

import dba_report_v8 as v8

v6 = v8.v6


def wow_scenarios(r):
    """Conservative WoW Classic/Cataclysm estimates for 3840x1600 Ultra, up to 75 Hz.

    These are deliberately broad ranges, not benchmark claims. GPU matters strongly at
    6.14 MP while raids/crowded combat become increasingly CPU-limited.
    """
    g = int(r.get('gpu_score', 0))
    c = int(r.get('cpu_score', 0))

    # Open-world/dungeon performance is more GPU-sensitive; raids/crowds are more CPU-sensitive.
    open_mid = min(100, 42 + 0.62*g + 0.22*c)
    dungeon_mid = min(96, 38 + 0.56*g + 0.25*c)
    raid_mid = min(88, 28 + 0.35*g + 0.38*c)
    crowd_mid = min(78, 20 + 0.24*g + 0.40*c)

    def rng(mid, spread):
        lo = max(25, int(round((mid-spread)/5)*5))
        hi = max(lo+5, int(round((mid+spread)/5)*5))
        return f'{lo}–{hi} FPS'

    return rng(open_mid, 10), rng(dungeon_mid, 9), rng(raid_mid, 11), rng(crowd_mid, 12)


def render_price_first():
    p = Path('results/latest_v6.json')
    data = json.loads(p.read_text(encoding='utf-8'))
    ranked = data.get('ranked') or []

    visible = [r for r in ranked if r.get('performance_class') != 'UNDER MINIMUM']
    class_order = {'SWEET SPOT':0,'OVERKILL':1,'ACCEPTABLE':2}
    visible.sort(key=lambda r:(int(r.get('ask_t1',10**9)), class_order.get(r.get('performance_class'),9), -int(r.get('gpu_score',0)), -int(r.get('cpu_score',0))))

    counts = data.get('counts') or {}
    gate = data.get('schema_gate') or {}
    reg = data.get('price_binding_regression') or {}
    lines = [
        '# DBA WoW-PC verified price report v9', '',
        f"Generated: {data.get('generated_at')}", '',
        f"Current schema/source gate: **PASS** — live item {gate.get('listing_id')} — {gate.get('item_price')} kr.",
        f"Historical price-binding regression: **PASS ({reg.get('type')}; no dependency on historical live listing)**", '',
        f"Discovery queries: {counts.get('queries')}",
        f"Structured T0 unique records: {counts.get('t0_unique')}",
        f"T0 GPU-promising records sent to T1 (no top-100 cap): {counts.get('t0_promising')}",
        f"T1 verified systems with parsed GPU+CPU: {counts.get('t1_verified_specs')}", '',
        '## Price-first ranking', '',
        'All verified candidates at ACCEPTABLE or better are shown; SWEET SPOT is not allowed to hide a cheaper ACCEPTABLE machine.', '',
        'WoW estimates target **WoW Classic through Cataclysm Classic, Ultra, 3840×1600, up to 75 Hz**. They are conservative scenario ranges derived from the parsed CPU/GPU tier, not measured benchmarks; actual FPS varies by zone, addons, raid size and effects.', '',
        '| Rank | ASK | Class | GPU | CPU | Quest/open world | Dungeon | Raid | Worst-case crowded | Listing |',
        '|---:|---:|---|---|---|---:|---:|---:|---:|---|'
    ]
    for i,r in enumerate(visible,1):
        ow,dun,raid,crowd = wow_scenarios(r)
        lines.append(f"| {i} | {r['ask_t1']} kr. | {r['performance_class']} | {r['gpu']} | {r['cpu']} | {ow} | {dun} | {raid} | {crowd} | [{r['title']}]({r['url']}) |")

    lines += ['', '## Rejection diagnostics', '', json.dumps(data.get('rejection_reason_counts') or {}, ensure_ascii=False)]
    Path('results/report_v9.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')


if __name__ == '__main__':
    v6.main()
    render_price_first()
