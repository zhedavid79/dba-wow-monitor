from __future__ import annotations

"""V1.6 discovery entry point with conservative Mainnet Pulse family-proxy eligibility.

This keeps the proven v2 DBA retrieval/identity pipeline intact. A Core-compatible
explicit model missing a direct Pulse row may proceed only when at least two Mainnet
Pulse models from the same normalized manufacturer/family and adjacent generation
provide a conservative proxy. No AcurastBot/Canary reward is used.
"""

import re

import acurast_dba_report_v2 as v2
from acurast_pulse_proxy import build_family_proxy


MODEL_SUFFIXES={
    't','pro','ultra','lite','fe','neo','fusion','plus','ce','gt','master',
    'max','mini','fold','flip','note','5g','4g','lte'
}


def canonical_fallback_model(candidate:str)->str:
    """Strip seller condition/capacity prose from an explicit fallback model.

    The identity is kept through the first numeric generation token plus recognized
    model suffixes. This is generic across supported phone families and prevents
    words such as colour/condition/"som ny" from becoming part of model identity.
    """
    text=' '.join((candidate or '').split())
    text=re.sub(r'\b(?:32|64|128|256|512|1024)\s*gb\b',' ',text,flags=re.I)
    text=re.sub(r'\b(?:3|4|6|8|10|12|16|18|24)\s*gb\s*(?:ram)?\b',' ',text,flags=re.I)
    text=re.sub(r'\s+',' ',text).strip(' -–—,|()[]')
    toks=re.findall(r'[A-Za-z0-9+]+',text)
    if not toks:
        return text
    number_idx=next((i for i,t in enumerate(toks) if re.fullmatch(r'\d{1,4}',t)),None)
    if number_idx is None:
        return text
    end=number_idx+1
    while end<len(toks):
        t=toks[end].lower()
        # Compact generation suffixes such as 2T are already inside one token.
        if t in MODEL_SUFFIXES:
            end+=1
            continue
        break
    return ' '.join(toks[:end]).strip()


def pulse_or_proxy_gated_fallback(title, description, catalog):
    candidate=v2._ORIGINAL_FALLBACK(title,description,catalog)
    if not candidate:
        return None
    candidate=canonical_fallback_model(candidate)
    if not candidate:
        return None

    # Re-run the conservative Core gate on the canonical identity so cleanup can
    # never turn a previously explicit seller title into an unverified model.
    try:
        import acurast_valuation as compat
        core_ok,_=compat.core_compatibility(candidate,title,description)
    except Exception:
        return None
    if not core_ok:
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
