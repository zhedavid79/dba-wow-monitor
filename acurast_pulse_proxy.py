from __future__ import annotations

import re
from typing import Any


NOISE={'galaxy','phone','smartphone','mobile','mobil','5g','4g','lte','nr'}
VARIANTS={'ultra','pro','lite','fe','neo','fusion','plus','ce','gt','master','max','mini','fold','flip','note'}


def pnorm(s:str)->str:
    s=(s or '').lower().replace('+',' plus ')
    s=re.sub(r'\bone\s+plus\b','oneplus',s)
    s=re.sub(r'\bmoto\b','motorola',s)
    s=re.sub(r'([a-z])([0-9])',r'\1 \2',s)
    s=re.sub(r'([0-9])([a-z])',r'\1 \2',s)
    return re.sub(r'\s+',' ',re.sub(r'[^a-z0-9]+',' ',s)).strip()


def signature(model:str)->tuple[str,str,int]|None:
    toks=[t for t in pnorm(model).split() if t not in NOISE]
    if len(toks)<3:
        return None
    brand=toks[0]
    number_idx=None
    generation=None
    for i,t in enumerate(toks[1:],1):
        m=re.fullmatch(r'(\d{1,2})',t)
        if m:
            number_idx=i; generation=int(m.group(1)); break
    if number_idx is None or generation is None:
        return None
    family_tokens=[t for t in toks[1:number_idx] if t not in VARIANTS]
    if not family_tokens:
        return None
    family=' '.join(family_tokens[:2])
    if len(family)<3:
        return None
    return brand,family,generation


def build_family_proxy(model:str,catalog:list[dict[str,Any]])->dict[str,Any]|None:
    sig=signature(model)
    if not sig:
        return None
    brand,family,generation=sig
    refs=[]
    seen=set()
    for row in catalog:
        psig=signature(str(row.get('pulse_model') or ''))
        if not psig:
            continue
        pbrand,pfamily,pgen=psig
        if pbrand!=brand or pfamily!=family or abs(pgen-generation)>1:
            continue
        key=str(row.get('pulse_model_id') or row.get('pulse_model'))
        if key in seen:
            continue
        seen.add(key)
        observed_epoch=float(row.get('observed_acu_epoch') or 0)
        earnings_day=float(row.get('earnings_day') or 0)
        baseline_day=row.get('baseline_day')
        baseline_day=float(baseline_day) if baseline_day is not None else (earnings_day/1.10 if earnings_day>0 else 0)
        if observed_epoch<=0 or earnings_day<=0 or baseline_day<=0:
            continue
        refs.append((baseline_day,observed_epoch,earnings_day,row))
    if len(refs)<2:
        return None

    # Fail conservative: use the lowest independently observed baseline/day and
    # observed ACU/epoch across the eligible family references.
    baseline_day=min(x[0] for x in refs)
    observed_epoch=min(x[1] for x in refs)
    earnings_day=min(x[2] for x in refs)
    ref_rows=[x[3] for x in refs]
    return {
        'pulse_model_id':'family-proxy:'+brand+':'+family.replace(' ','-')+':'+str(generation),
        'pulse_url':None,
        'pulse_model':'FAMILY PROXY — '+model,
        'pulse_brand':brand,
        'observed_acu_epoch':observed_epoch,
        'earnings_day':earnings_day,
        'baseline_day':min(baseline_day,earnings_day),
        'processors':1,
        'active':None,
        'uptime_pct':None,
        'variant_count':len(ref_rows),
        'proxy_reference_models':[str(r.get('pulse_model')) for r in ref_rows],
        'proxy_reference_ids':[str(r.get('pulse_model_id')) for r in ref_rows],
        'proxy_policy':'same brand + normalized product family + generation ±1; minimum Mainnet Pulse baseline and observed reward; >=2 references required',
        'proxy_confidence':0.55,
    }
