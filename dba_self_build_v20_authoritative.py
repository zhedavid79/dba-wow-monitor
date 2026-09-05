from __future__ import annotations

import json
from pathlib import Path

import dba_gpu_model_v20 as gpu20
import dba_self_build_v20 as base

PARTS=Path('results/z20_parts_latest.json')
OUT=Path('results/wow_strategy_latest.json')
EVIDENCE: dict[str,str] = {}
ORIGINAL_APPLY = base.apply_gpu_model


def load_evidence() -> dict[str,str]:
    if not PARTS.exists(): return {}
    d=json.loads(PARTS.read_text(encoding='utf-8'))
    out={}
    for r in d.get('opportunities') or []:
        lid=str(r.get('listing_id') or '')
        text=str(r.get('gpu_identity_text_v20') or '').strip()
        if lid and text: out[lid]=text
    return out


def apply_with_t1_evidence(route: dict, anchor_ask: int) -> dict:
    r=ORIGINAL_APPLY(route,anchor_ask)
    gi=r.get('gpu_intelligence_v20') or {}
    lid=str(gi.get('listing_id') or '')
    text=EVIDENCE.get(lid)
    if not text:
        return r
    psu=next((x for x in r.get('components') or [] if x.get('kind')=='PSU'),{})
    psu_len=int(psu.get('length_mm')) if psu.get('length_mm') else None
    fit=gpu20.z20_fit(text,str(r.get('gpu') or ''),psu_len)
    old_penalty=int(r.get('v20_fit_uncertainty_penalty_dkk') or 0)
    new_penalty={'VERIFIED':0,'LIKELY':40,'UNKNOWN':75,'NO':100000}.get(fit.get('status'),100)
    gi['z20_fit_v20']=fit
    gi['gpu_fit_evidence_source_v20']='CURRENT_RUN_T1_TITLE_DESCRIPTION_BRAND'
    gi['gpu_fit_evidence_text_available']=True
    r['gpu_intelligence_v20']=gi
    r['z20_fit_v20']=fit.get('status') or 'UNKNOWN'
    r['v20_fit_uncertainty_penalty_dkk']=new_penalty
    r['v20_decision_cost']=int(r.get('v20_decision_cost') or 0)-old_penalty+new_penalty
    return r


def main() -> None:
    global EVIDENCE
    EVIDENCE=load_evidence()
    base.apply_gpu_model=apply_with_t1_evidence
    base.main()
    d=json.loads(OUT.read_text(encoding='utf-8'))
    rec=d.get('recommended_self_build') or {}; gi=rec.get('gpu_intelligence_v20') or {}
    d['gpu_fit_evidence_v20']={
        't1_component_evidence_rows':len(EVIDENCE),
        'rule':'Use current-run T1 title + description + brand for exact board-partner model matching. Generic/unproven model remains UNKNOWN; exact known-NO is excluded by V20 route filter.',
        'recommended_evidence_source':gi.get('gpu_fit_evidence_source_v20','LISTING_TITLE_ONLY_OR_UNPROVEN'),
    }
    OUT.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'V20_AUTHORITATIVE_FIT':True,'evidence_rows':len(EVIDENCE),'recommended_gpu':rec.get('gpu'),'recommended_fit':rec.get('z20_fit_v20'),'evidence_source':gi.get('gpu_fit_evidence_source_v20','LISTING_TITLE_ONLY_OR_UNPROVEN')},ensure_ascii=False))


if __name__=='__main__': main()
