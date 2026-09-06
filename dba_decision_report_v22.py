from __future__ import annotations

import json
from pathlib import Path

import dba_decision_report as base

MAIN = Path('results/wow_a3_latest.json')
ISSUES = Path('dba_known_listing_issues_v21.json')


def active_hard_exclusions() -> dict[str, dict]:
    if not ISSUES.exists():
        return {}
    doc = json.loads(ISSUES.read_text(encoding='utf-8'))
    return {
        str(lid): row
        for lid, row in (doc.get('listings') or {}).items()
        if row.get('severity') == 'HARD_EXCLUDE' and row.get('cleared') is not True
    }


def main() -> None:
    data = json.loads(MAIN.read_text(encoding='utf-8'))
    exclusions = active_hard_exclusions()
    removed = []
    if exclusions:
        clean = []
        for row in data.get('ranked') or []:
            lid = str(row.get('listing_id') or '')
            if lid in exclusions:
                x = dict(row)
                x['resolution_reason'] = 'PERSISTENT_KNOWN_FUNCTIONAL_ISSUE'
                x['known_issue'] = exclusions[lid]
                removed.append(x)
            else:
                clean.append(row)
        data['ranked'] = clean
        data.setdefault('rejected', []).extend(removed)
        counts = data.setdefault('rejection_reason_counts', {})
        if removed:
            counts['PERSISTENT_KNOWN_FUNCTIONAL_ISSUE'] = int(counts.get('PERSISTENT_KNOWN_FUNCTIONAL_ISSUE') or 0) + len(removed)
        data['persistent_exclusions_applied_v22'] = [str(x.get('listing_id')) for x in removed]
        MAIN.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    base.main()
    final = json.loads(MAIN.read_text(encoding='utf-8'))
    buy_now = str(((final.get('decision_summary') or {}).get('buy_now_listing_id')) or '')
    assert buy_now not in exclusions, f'Persistent hard exclusion leaked into upstream buy_now: {buy_now}'
    assert all(str(r.get('listing_id') or '') not in exclusions for r in final.get('ranked') or [])
    print(json.dumps({
        'V22_UPSTREAM_EXCLUSION': True,
        'removed': [str(x.get('listing_id')) for x in removed],
        'buy_now': buy_now or None,
        'ranked': len(final.get('ranked') or []),
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
