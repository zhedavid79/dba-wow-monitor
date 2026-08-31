from __future__ import annotations

"""DBA discovery wrapper for the V1.6 Mainnet valuation pipeline.

The legacy report module used AcurastBot Canary pool-statistics as a prerequisite
for a model to enter the supported-device discovery catalog. V1.6 no longer uses
those statistics for absolute ACU rewards; Acurast Pulse Mainnet is authoritative.
Therefore a phone model present in AcurastBot's device registry must remain
eligible for DBA discovery even when no current/legacy pool-stat row exists.
"""

import acurast_dba_report as base


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
        })

    catalog.sort(key=lambda x: (-x['reward'], -x['processor_count'], x['label']))
    return catalog


# Patch only the discovery-catalog construction; all same-listing verification,
# identity gates and DBA retrieval remain the proven legacy implementation.
base.build_catalog = build_catalog

if __name__ == '__main__':
    base.main()
