from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import dba_strategy_report_v19 as base

SRC=Path('results/wow_strategy_latest.json')
OUT=Path('results/wow_self_build_report_v20.md')
CANONICAL=Path('results/wow_self_build_report.md')
LEGACY=Path('results/wow_platform_first_report.md')
ALIAS=Path('results/wow_a3_report.md')
PARTS=Path('results/z20_parts_latest.json')
CACHE=Path('results/t1_cache_v20.json')


def money(v):
    try: return f"{int(v):,}".replace(',','.')+' kr.'
    except Exception: return '—'


def md_link(name,url):
    return f'[{name}]({url})' if url else str(name or '—')


def _action_order(x):
    return {'STRONG_BUY':0,'BUY':1,'FAIR':2,'WAIT':3,'NO_VALUE_MODEL':4}.get(x,5)


def gpu_lookup(data: dict) -> dict[str,dict]:
    out={}
    for r in data.get('self_build_ranked') or []:
        gi=r.get('gpu_intelligence_v20') or {}; lid=str(gi.get('listing_id') or '')
        if lid and lid not in out: out[lid]=gi | {'route':r}
    return out


def enrich_temp_for_base(data: dict) -> dict:
    t=deepcopy(data)
    t['model_version']='DBA-WOW-SELF-BUILD-FIRST-V19'
    t['strategy_mode']='EXPLAINABLE_MULTI_CRITERIA_SELF_BUILD'
    # Base V19 rendering is reused for the durable-component comparison, but the
    # GPU explanation must reflect the V20 decision actually shown at the top.
    for r in t.get('self_build_ranked') or []:
        gi=r.get('gpu_intelligence_v20') or {}; u=gi.get('utility') or {}; fit=gi.get('z20_fit_v20') or {}; bid=gi.get('bid') or {}
        dec=r.get('component_choice_v19') or {}
        if dec.get('GPU') is not None:
            dec['GPU']['reason']=(
                f"V20 GPU decision: performance proxy {u.get('perf_proxy_2080s_1_00','?')} (RTX 2080 Super=1.00), "
                f"{u.get('vram_gb','?')}GB VRAM, {u.get('power_w','?')}W, Z20 fit {fit.get('status','UNKNOWN')}; "
                f"ASK {gi.get('ask')} kr, target {bid.get('target')} kr, walk-away {bid.get('walk_away')} kr, action {bid.get('action')}."
            )
    rec=t.get('recommended_self_build') or {}
    gi=rec.get('gpu_intelligence_v20') or {}; u=gi.get('utility') or {}; fit=gi.get('z20_fit_v20') or {}; bid=gi.get('bid') or {}
    dec=rec.get('component_choice_v19') or {}
    if dec.get('GPU') is not None:
        dec['GPU']['reason']=(f"V20 GPU decision: performance proxy {u.get('perf_proxy_2080s_1_00','?')}, {u.get('vram_gb','?')}GB, {u.get('power_w','?')}W; Z20 {fit.get('status','UNKNOWN')}; ASK {gi.get('ask')} / target {bid.get('target')} / walk-away {bid.get('walk_away')} kr ({bid.get('action')}).")
    return t


def main() -> None:
    data=json.loads(SRC.read_text(encoding='utf-8'))
    assert data.get('model_version')=='DBA-WOW-SELF-BUILD-FIRST-V20'
    assert data.get('strategy_mode')=='V20_GPU_FIT_RAM_RETAIL_CACHE_BID'
    original=SRC.read_bytes()
    try:
        SRC.write_text(json.dumps(enrich_temp_for_base(data),ensure_ascii=False,indent=2),encoding='utf-8')
        base.main()
        text=Path(base.OUT).read_text(encoding='utf-8')
    finally:
        SRC.write_bytes(original)

    text=text.replace('WoW SELF-BUILD FIRST V19','WoW SELF-BUILD FIRST V20').replace('V19','V20')
    gpu_by_id=gpu_lookup(data)
    bids=data.get('bid_market_v20') or {}
    retail=data.get('retail_discovery_v20') or {}

    lines=['','## V20 — GPU value, Z20-fit og budmodel','',
           'GPU-rangeringen bruger et 3840×1600 raster-performance-proxy, begrænset VRAM-værdi, strøm/effektivitet og eksakt board-partner-fit. Ukendt model-fit er ikke hard exclude; kendt NO er hard exclude.',
           '',
           '| GPU | Annonce | ASK | Første bud | Target | Walk-away | Action | Perf. proxy | VRAM | Effekt | Z20-fit |',
           '|---|---|---:|---:|---:|---:|---|---:|---:|---:|---|']
    gpu_rows=sorted(bids.get('GPU') or [],key=lambda x:(_action_order(x.get('action')),int(x.get('ask') or 10**9)))
    for row in gpu_rows[:30]:
        gi=gpu_by_id.get(str(row.get('listing_id') or '')) or {}; u=gi.get('utility') or {}; fit=gi.get('z20_fit_v20') or {}
        lines.append(f"| {row.get('model')} | {md_link(row.get('name'),row.get('url'))} | **{money(row.get('ask'))}** | {money(row.get('first_bid'))} | {money(row.get('target'))} | **{money(row.get('walk_away'))}** | {row.get('action')} | {u.get('perf_proxy_2080s_1_00','—')} | {u.get('vram_gb','—')} GB | {u.get('power_w','—')} W | **{fit.get('status','UNKNOWN')}** |")

    rec=data.get('recommended_self_build') or {}; rgi=rec.get('gpu_intelligence_v20') or {}; rfit=rgi.get('z20_fit_v20') or {}; ev=rfit.get('gpu_model_evidence') or {}
    lines += ['', '### Anbefalet GPU — fit-evidens', '',
              f"- **GPU:** {rec.get('gpu')} / {money(rgi.get('ask'))}",
              f"- **V20 Z20-fit:** {rfit.get('status','UNKNOWN')} — {rfit.get('reason','—')}"]
    if ev:
        lines.append(f"- **Eksakt model:** {ev.get('model')} — {ev.get('length_mm')}×{ev.get('height_mm')}×{ev.get('thickness_mm')} mm / {ev.get('slots')} slots — [producentkilde]({ev.get('source_url')})")

    lines += ['', '## V20 — RAM-bud og bridge-kontrol', '',
              '| RAM | ASK | Første bud | Target | Walk-away | Action | Ny 32GB-anchor |',
              '|---|---:|---:|---:|---:|---|---:|']
    for row in sorted(bids.get('RAM') or [],key=lambda x:(_action_order(x.get('action')),int(x.get('ask') or 10**9)))[:20]:
        lines.append(f"| {md_link(row.get('name'),row.get('url'))} | **{money(row.get('ask'))}** | {money(row.get('first_bid'))} | {money(row.get('target'))} | **{money(row.get('walk_away'))}** | {row.get('action')} | {money(row.get('new_32gb_anchor'))} |")

    lines += ['', '## V20 — CPU-bud', '',
              '| CPU | ASK | Første bud | Target | Walk-away | Action |',
              '|---|---:|---:|---:|---:|---|']
    for row in sorted(bids.get('CPU') or [],key=lambda x:(_action_order(x.get('action')),int(x.get('ask') or 10**9)))[:15]:
        lines.append(f"| {md_link(row.get('name'),row.get('url'))} | **{money(row.get('ask'))}** | {money(row.get('first_bid'))} | {money(row.get('target'))} | **{money(row.get('walk_away'))}** | {row.get('action')} |")

    rc=retail.get('counts') or {}
    lines += ['', '## V20 — dynamisk retail discovery', '',
              f"- Static live-verificeret katalog: **{rc.get('static_verified','—')}/{rc.get('static_total','—')}**",
              f"- Discovery-seeds bestået: **{rc.get('seed_ok','—')}/{rc.get('seed_total','—')}**",
              f"- Dynamisk inspicerede produkter: **{rc.get('dynamic_inspected','—')}**",
              f"- Nye produkter med tilstrækkelig hard-gate-evidens og live pris: **{rc.get('dynamic_admitted','—')}**",
              '- Discovery-resultater uden tilstrækkelig kompatibilitetsevidens forbliver audit-leads og kan ikke vinde.',
              '']
    admitted=retail.get('dynamic_admitted_products') or []
    if admitted:
        lines += ['| Kategori | Dynamisk kandidat | Pris |','|---|---|---:|']
        for c in sorted(admitted,key=lambda x:(str(x.get('kind')),int(x.get('price') or 10**9)))[:30]:
            lines.append(f"| {c.get('kind')} | {md_link(c.get('name'),c.get('url'))} | **{money(c.get('price'))}** |")
        lines.append('')

    cache_stats={}
    if PARTS.exists():
        try: cache_stats=((json.loads(PARTS.read_text(encoding='utf-8')).get('coverage') or {}).get('t1') or {})
        except Exception: pass
    lines += ['## V20 — shared same-run T1-cache','',
              f"- Cache hits i komponent-T1: **{cache_stats.get('same_run_cache_hits','—')}**",
              f"- Nye netværks-fetches i komponent-T1: **{cache_stats.get('network_fetches','—')}**",
              f"- T1 coverage complete: **{cache_stats.get('complete','—')}**",
              '- Cache accepteres kun fra samme workflow-run-vindue; stale cache ignoreres og kan ikke erstatte frisk T1-verifikation.',
              '']

    pool=data.get('gpu_pool_v20') or {}
    lines += ['## V20 — GPU discovery-pool','',
              f"- Pool-metode: **{pool.get('method','—')}**",
              f"- GPU-kandidater bevaret til route-universet: **{pool.get('pool_size','—')}**",
              f"- Familie-dækning: `{json.dumps(pool.get('family_counts') or {},ensure_ascii=False)}`",
              '- RX 6800 XT / RX 6800 / RX 6700 XT m.fl. kan ikke længere falde ud alene på grund af en billigste-N cutoff.',
              '']

    insert='\n'.join(lines)
    marker='\n## Del-for-del policy\n'
    if marker in text: text=text.replace(marker,'\n'+insert+marker,1)
    else: text += '\n'+insert

    assert 'V20 — GPU value, Z20-fit og budmodel' in text
    assert 'V20 — dynamisk retail discovery' in text
    assert 'V20 — shared same-run T1-cache' in text
    for p in (OUT,CANONICAL,LEGACY,ALIAS): p.write_text(text,encoding='utf-8')
    print(json.dumps({'report':True,'model':'V20','recommended_tcwp':rec.get('tcwp'),'gpu':rec.get('gpu'),'z20_fit_v20':rec.get('z20_fit_v20'),'gpu_bid_rows':len(gpu_rows),'dynamic_admitted':rc.get('dynamic_admitted')},ensure_ascii=False))


if __name__=='__main__':
    main()
