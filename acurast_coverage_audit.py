from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

DISC=Path('results/acurast_discovery_audit.json')
LATEST=Path('results/acurast_latest.json')
VAL=Path('results/acurast_valuation.json')
OUT=Path('results/acurast_coverage_audit.json')
MD=Path('results/acurast_coverage_audit.md')


def load(p): return json.loads(p.read_text(encoding='utf-8'))


def main():
    disc=load(DISC); latest=load(LATEST); val=load(VAL)
    quality_rejects=[x for x in latest.get('excluded',[]) if 'BUNDLE/PRICE IDENTITY GATE' in str(x.get('reason',''))]
    core=val.get('core_incompatible',[]) or []
    pulse=val.get('unsupported',[]) or []
    blind=disc.get('likely_model_blindspots',[]) or []
    pulse_fallback=disc.get('pulse_gated_fallback_rejects',[]) or []

    # These buckets are not automatically errors. They are the places where a valid phone
    # can disappear for reasons other than price, so they are surfaced for deterministic review.
    suspects=[]
    for x in blind:
        suspects.append({'stage':'DISCOVERY/MODEL','severity':'HIGH','listing_id':x.get('listing_id'),'title':x.get('title') or x.get('title_t0'),'ask':x.get('price') or x.get('ask_t0'),'url':x.get('url'),'reason':x.get('reason')})
    for x in pulse_fallback:
        suspects.append({'stage':'DISCOVERY/PULSE','severity':'MEDIUM','listing_id':None,'model':x.get('candidate_model'),'title':x.get('title'),'ask':None,'url':None,'reason':f"{x.get('reason')} ({x.get('pulse_match_method')})"})
    for x in quality_rejects:
        suspects.append({'stage':'QUALITY','severity':'MEDIUM','listing_id':x.get('listing_id'),'title':x.get('title'),'ask':x.get('ask'),'url':x.get('url'),'reason':x.get('reason')})
    for x in core:
        suspects.append({'stage':'CORE','severity':'MEDIUM','listing_id':x.get('listing_id'),'model':x.get('model'),'url':x.get('url'),'reason':x.get('reason')})
    for x in pulse:
        suspects.append({'stage':'PULSE','severity':'MEDIUM','listing_id':x.get('listing_id'),'model':x.get('model'),'url':x.get('url'),'reason':x.get('reason')})

    counts=Counter(x['stage'] for x in suspects)
    out={'generated_at':val.get('generated_at'),'audit_gate':True,'purpose':'trace every non-economic exclusion path that can hide a valid Acurast procurement candidate','counts':{'t0_unique':disc.get('t0_unique'),'verified_before_quality':disc.get('verified_before_quality'),'final_after_quality':latest.get('counts',{}).get('final_refetched'),'ranked':len(val.get('ranked') or []),'discovery_model_blindspots':len(blind),'pulse_gated_discovery_review':len(pulse_fallback),'quality_review':len(quality_rejects),'core_review':len(core),'pulse_review':len(pulse)},'suspect_stage_counts':dict(counts),'suspects':suspects,'pulse_gated_fallback_rejects':pulse_fallback,'discovery_reject_stage_counts':disc.get('reject_stage_counts',{}),'discovery_reject_reason_counts':disc.get('reject_reason_counts',{})}
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')

    lines=['# Acurast coverage audit','',f"Generated: {out['generated_at']}",'',f"T0 listings <= ceiling: **{out['counts']['t0_unique']}**  ",f"Verified before quality: **{out['counts']['verified_before_quality']}**  ",f"Final after quality: **{out['counts']['final_after_quality']}**  ",f"Mainnet ranked: **{out['counts']['ranked']}**",'', '## Review buckets','',f"- Discovery/model blindspots: **{len(blind)}**",f"- Core-compatible explicit models stopped by Pulse gate: **{len(pulse_fallback)}**",f"- Quality-gate review: **{len(quality_rejects)}**",f"- Core allowlist review: **{len(core)}**",f"- Pulse-match review: **{len(pulse)}**",'']
    if pulse_fallback:
        lines += ['## Core-compatible discovery models without unique Mainnet Pulse match','', '| Candidate model | DBA title | Pulse result |','|---|---|---|']
        for x in pulse_fallback:
            lines.append(f"| {str(x.get('candidate_model') or '').replace('|','/')} | {str(x.get('title') or '').replace('|','/')} | {str(x.get('pulse_match_method') or '').replace('|','/')} |")
        lines += ['']
    if suspects:
        lines += ['## Suspects','', '| Stage | ID | Model/title | ASK | Reason |','|---|---:|---|---:|---|']
        for x in suspects[:250]:
            label=x.get('model') or x.get('title') or ''
            ask='' if x.get('ask') is None else str(x.get('ask'))
            reason=str(x.get('reason') or '').replace('|','/')
            lines.append(f"| {x['stage']} | {x.get('listing_id') or ''} | {label.replace('|','/')} | {ask} | {reason} |")
    MD.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(out['counts'],ensure_ascii=False,indent=2))

if __name__=='__main__': main()
