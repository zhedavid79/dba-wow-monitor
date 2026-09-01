from __future__ import annotations

"""V1.6 discovery entry point with conservative Mainnet Pulse family-proxy eligibility.

This keeps the proven v2 DBA retrieval/identity pipeline intact. A Core-compatible
explicit model missing a direct Pulse row may proceed only when at least two Mainnet
Pulse models from the same normalized manufacturer/family and adjacent generation
provide a conservative proxy. No AcurastBot/Canary reward is used.
"""

import acurast_dba_report_v2 as v2
from acurast_pulse_proxy import build_family_proxy


def pulse_or_proxy_gated_fallback(title, description, catalog):
    candidate=v2._ORIGINAL_FALLBACK(title,description,catalog)
    if not candidate:
        return None

    from acurast_valuation_fixed import match_pulse
    pulse=v2.pulse_catalog()
    row,method,confidence=match_pulse(candidate,pulse)
    if row is not None and method not in {'NO_MATCH','AMBIGUOUS_EXACT','AMBIGUOUS_VARIANT'}:
        return candidate

    proxy=build_family_proxy(candidate,pulse)
    if proxy is not None:
        return candidate

    key=(v2.base.norm(candidate),v2.base.norm(title))
    v2._PULSE_FALLBACK_REJECTS[key]={
        'candidate_model':candidate,
        'title':' '.join((title or '').split()),
        'pulse_match_method':method,
        'pulse_match_confidence':confidence,
        'reason':'Core-compatible explicit model has neither a unique direct Mainnet Pulse reward match nor an eligible conservative family proxy',
    }
    return None


v2.base.fallback_core_model=pulse_or_proxy_gated_fallback

if __name__=='__main__':
    v2.main()
