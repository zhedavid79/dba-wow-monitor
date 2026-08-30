from __future__ import annotations

import re
import acurast_valuation as v

GENERIC={'galaxy','smartphone','phone','mobile','moto','5g','lte'}
FAMILY_BLOCK={'redmi','note','poco','edge','pixel','realme','oppo','honor'}
BRAND_ALIASES={'one plus':'oneplus','oneplus':'oneplus','samsung':'samsung','xiaomi':'xiaomi'}


def split_tokens(s):
    n=v.norm(s)
    n=re.sub(r'([a-z]+)(\d)',r'\1 \2',n)
    n=re.sub(r'(\d)([a-z]+)',r'\1 \2',n)
    return [t for t in n.split() if t not in GENERIC]


def brand_of(label):
    n=v.norm(label)
    if n.startswith('one plus '): return 'oneplus'
    return n.split()[0] if n.split() else ''


def core_tokens(s,brand):
    toks=split_tokens(s)
    out=[]
    for t in toks:
        if t==brand: continue
        if brand=='xiaomi' and t=='mi': continue
        if not out or out[-1]!=t: out.append(t)
    return out


def strict_reference_device(devices,label,stats_by_cfg):
    target_brand=BRAND_ALIASES.get(brand_of(label),brand_of(label))
    target=core_tokens(label,target_brand)
    target_set=set(target)
    target_compact=''.join(target)
    candidates=[]; best=0.0
    for d in devices:
        company_raw=v.norm(d.get('company',''))
        company=BRAND_ALIASES.get(company_raw,company_raw)
        if not (company==target_brand or company.startswith(target_brand+' ')):
            continue
        cand=core_tokens(str(d.get('model') or ''),target_brand)
        cset=set(cand); cand_compact=''.join(cand)
        overlap=len(target_set & cset)/len(target_set) if target_set else 0.0
        best=max(best,overlap)
        token_match=target_set.issubset(cset)
        compact_match=bool(target_compact and target_compact in cand_compact)
        if not (token_match or compact_match): continue
        extra=cset-target_set
        if extra & FAMILY_BLOCK: continue
        observed=sum(int(stats_by_cfg.get(int(c.get('id')),{}).get('processorCount') or 0)
                     for c in (d.get('configurations') or []) if c.get('id') is not None)
        candidates.append((len(extra),-observed,d))
    if not candidates:return None,best
    candidates.sort(key=lambda x:(x[0],x[1]))
    return candidates[0][2],1.0


def safe_partial_calibration(devices,stats_by_cfg):
    samples=[]; missing=[]
    for label,title_hint,weight in v.REFERENCE_FARM:
        d,match_score=strict_reference_device(devices,label,stats_by_cfg)
        if not d:
            missing.append({'model':label,'best_match_score':round(match_score,3),'reason':'exact marketed model absent from current AcurastBot device catalog'})
            continue
        picked=v.choose_config(d,title_hint,stats_by_cfg)
        if not picked:
            missing.append({'model':label,'reason':'matched device has no reward stats'}); continue
        cfg,st=picked; rw=v.rewards(st)
        if not rw:
            missing.append({'model':label,'reason':'matched config has no expectedReward'}); continue
        matched_name=f"{d.get('company','')} {d.get('model','')}".strip()
        for _ in range(weight):
            samples.append({'model':label,'matched_device':matched_name,'match_score':round(match_score,3),'configuration_id':cfg.get('id'),'bot_base_acu_epoch':rw['base']})
    if len(samples)<2:
        return {'status':'INSUFFICIENT_REFERENCE_MATCH','scale':1.0,'matched':len(samples),'missing':missing,'samples':samples,
                'observed_floor':v.OBSERVED_REFERENCE_AVG_ACU_EPOCH_FLOOR,
                'reference_mode':'exact-only; no cross-family substitution'}
    bot_mean=sum(x['bot_base_acu_epoch'] for x in samples)/len(samples)
    scale=max(1.0,v.OBSERVED_REFERENCE_AVG_ACU_EPOCH_FLOOR/bot_mean) if bot_mean>0 else 1.0
    return {'status':'CALIBRATED_PARTIAL_REFERENCE','scale':scale,'matched':len(samples),'missing':missing,'samples':samples,
            'bot_reference_mean':bot_mean,'observed_floor':v.OBSERVED_REFERENCE_AVG_ACU_EPOCH_FLOOR,
            'calibrated_reference_mean':bot_mean*scale,
            'reference_mode':'partial exact-reference production-floor calibration; uniform scale preserves relative AAE ranking and bid ordering',
            'confidence':'LOW_ABSOLUTE_SCALE_HIGH_RELATIVE_RANKING'}


v.reference_device=strict_reference_device
v.reference_calibration=safe_partial_calibration

# Manual full-model run trigger; no valuation semantics changed.
if __name__=='__main__':
    v.main()
