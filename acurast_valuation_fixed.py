from __future__ import annotations

import re
import acurast_valuation as v

GENERIC={'galaxy','smartphone','phone','mobile','moto','5g','lte'}
FAMILY_BLOCK={'redmi','note','poco','edge','pixel','realme','oppo','honor'}

def tokens(s):
    n=v.norm(s)
    n=re.sub(r'([a-z]+)(\d)',r'\1 \2',n)
    return [t for t in n.split() if t not in GENERIC]

def strict_reference_device(devices,label,stats_by_cfg):
    target=tokens(label); target_set=set(target); target_brand=target[0] if target else ''
    candidates=[]; best=0.0
    for d in devices:
        company=v.norm(d.get('company',''))
        full=f"{d.get('company','')} {d.get('model','')}"
        cand=tokens(full); cset=set(cand)
        if company!=target_brand: continue
        overlap=len(target_set & cset)/len(target_set) if target_set else 0.0
        best=max(best,overlap)
        # All meaningful target tokens must be present. Extra generic/community
        # naming tokens are allowed, but distinct product-family tokens are not.
        if not target_set.issubset(cset): continue
        extra=cset-target_set
        if extra & FAMILY_BLOCK: continue
        observed=sum(int(stats_by_cfg.get(int(c.get('id')),{}).get('processorCount') or 0)
                     for c in (d.get('configurations') or []) if c.get('id') is not None)
        candidates.append((len(extra),-observed,d))
    if not candidates:return None,best
    candidates.sort(key=lambda x:(x[0],x[1]))
    return candidates[0][2],1.0

v.reference_device=strict_reference_device

if __name__=='__main__':
    v.main()
