from __future__ import annotations

"""DBA discovery wrapper for the V1.6 Mainnet valuation pipeline.

V1.6 ranks only on deployment-neutral Acurast Pulse Mainnet reward data. Discovery
therefore uses the union of the AcurastBot device registry and Pulse Mainnet model
catalog. A conservative explicit-title fallback is allowed only when that model also
has a unique Mainnet Pulse reward match. This avoids both registry blindspots and
inflating the valuation denominator with models that cannot be ranked under V1.6.
"""

import json
from pathlib import Path

import acurast_dba_report as base


_PULSE_CATALOG = None
_ORIGINAL_FALLBACK = base.fallback_core_model
_PULSE_FALLBACK_REJECTS = {}


def pulse_catalog():
    global _PULSE_CATALOG
    if _PULSE_CATALOG is None:
        from acurast_valuation_fixed import fetch_pulse_catalog
        _PULSE_CATALOG = fetch_pulse_catalog()
    return _PULSE_CATALOG


def pulse_gated_fallback(title, description, catalog):
    candidate = _ORIGINAL_FALLBACK(title, description, catalog)
    if not candidate:
        return None
    from acurast_valuation_fixed import match_pulse
    row, method, confidence = match_pulse(candidate, pulse_catalog())
    if row is None or method in {'NO_MATCH', 'AMBIGUOUS_EXACT', 'AMBIGUOUS_VARIANT'}:
        key=(base.norm(candidate), base.norm(title))
        _PULSE_FALLBACK_REJECTS[key]={
            'candidate_model': candidate,
            'title': ' '.join((title or '').split()),
            'pulse_match_method': method,
            'pulse_match_confidence': confidence,
            'reason': 'Core-compatible explicit model has no unique Acurast Pulse Mainnet reward match',
        }
        return None
    return candidate


def build_catalog(session):
    devices = base.getj(session, base.BOT_BASE + '/devices/with-counts')
    stats = base.getj(session, base.BOT_BASE + '/devices/pool-statistics')
    stats_by_cfg = {
        int(x['deviceConfigurationId']): x
        for x in stats
        if x.get('deviceConfigurationId') is not None
    }
    catalog = []

    for d in devices:
        brand = base.norm(d.get('company', ''))
        model = str(d.get('model') or '').strip()
        if not brand or not model:
            continue

        best_reward = 0.0
        total_count = int(d.get('totalProcessorCount') or 0)
        for c in d.get('configurations') or []:
            cid = c.get('id')
            st = stats_by_cfg.get(int(cid)) if cid is not None else None
            if st:
                total_count = max(total_count, int(st.get('processorCount') or 0))
                try:
                    rw = float(st.get('expectedRewardMedian') or st.get('expectedRewardAvg') or 0)
                except Exception:
                    rw = 0.0
                best_reward = max(best_reward, rw)
            else:
                total_count = max(total_count, int(c.get('processorCount') or 0))

        full = f"{d.get('company', '')} {model}".strip()
        aliases = base.alias_variants(d.get('company', ''), model, full)
        catalog.append({
            'label': full,
            'brand': d.get('company', ''),
            'model': model,
            'aliases': aliases,
            # Retained only for deterministic legacy sorting. V1.6 never uses
            # this field for absolute reward or ranking.
            'reward': best_reward,
            'processor_count': total_count,
            'catalog_source': 'ACURASTBOT',
        })

    # The workflow wrapper must not override away Mainnet discovery. Merge Pulse
    # models into the same resolver universe while retaining deterministic sorting.
    by_key = {(base.norm(x['brand']), base.norm(x['model'])): x for x in catalog}
    for row in base._pulse_discovery_rows(catalog):
        key = (base.norm(row['brand']), base.norm(row['model']))
        old = by_key.get(key)
        if old is None:
            row['reward'] = 0.0
            catalog.append(row)
            by_key[key] = row
        else:
            old['aliases'] |= row['aliases']
            old['processor_count'] = max(old['processor_count'], row['processor_count'])
            old['catalog_source'] = 'ACURASTBOT+ACURAST_PULSE_MAINNET'

    catalog.sort(key=lambda x: (-x.get('reward', 0.0), -x['processor_count'], x['label']))
    return catalog


def persist_fallback_audit():
    path=Path('results/acurast_discovery_audit.json')
    if not path.exists():
        return
    try:
        audit=json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return
    rows=sorted(_PULSE_FALLBACK_REJECTS.values(),key=lambda x:(base.norm(x.get('candidate_model')),base.norm(x.get('title'))))
    audit['pulse_gated_fallback_rejects']=rows
    audit['pulse_gated_fallback_reject_count']=len(rows)
    path.write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')


# Patch the authoritative V1.6 discovery path used by the workflow.
base.build_catalog = build_catalog
base.fallback_core_model = pulse_gated_fallback

if __name__ == '__main__':
    base.main()
    persist_fallback_audit()
