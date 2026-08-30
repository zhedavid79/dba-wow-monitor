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
        # AcurastBot/community naming sometimes includes Xiaomi's legacy "Mi".
        if brand=='xiaomi' and t=='mi': continue
        if not out or out[-1]!=t: out.append(t)
    return out


def strict_reference_device(devices,label,stats_by_cfg):
    target_brand=BRAND_ALIASES.get(brand_of(label),brand_of(label))
    target=core_tokens(label,target_brand)
    target_set=set(target)
    candidates=[]; best=0.0

    for d in devices:
        company=BRAND_ALIASES.get(v.norm(d.get('company','')),v.norm(d.get('company','')))
        if company!=target_brand: continue

        cand=core_tokens(str(d.get('model') or ''),target_brand)
        cset=set(cand)
        overlap=len(target_set & cset)/len(target_set) if target_set else 0.0
        best=max(best,overlap)

        # Require every meaningful reference token and reject distinct family markers.
        # This accepts Galaxy/no-Galaxy, 5G/LTE, Nord2T/Nord 2T and Xiaomi Mi naming,
        # while still preventing Xiaomi 12 Pro -> Redmi Note 12 Pro+.
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
