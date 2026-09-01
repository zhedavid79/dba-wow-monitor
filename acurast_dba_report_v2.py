from __future__ import annotations

"""DBA discovery wrapper for the V1.6 Mainnet valuation pipeline.

V1.6 ranks only on deployment-neutral Acurast Pulse Mainnet reward data. Discovery
uses the union of the AcurastBot device registry and Pulse Mainnet model catalog,
plus independent DBA brand-query discovery so one category feed is not a single
point of failure. Explicit-title fallbacks are allowed only when the model also has
a unique Mainnet Pulse reward match.
"""

import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests

import acurast_dba_report as base


_PULSE_CATALOG = None
_ORIGINAL_FALLBACK = base.fallback_core_model
_PULSE_FALLBACK_REJECTS = {}
BRAND_QUERY_MAX_PAGES = 8
IDENTITY_VARIANTS = {
    'ultra','pro','lite','fe','neo','fusion','plus','ce','gt','master',
    'max','mini','fold','flip','note'
}


def pulse_catalog():
    global _PULSE_CATALOG
    if _PULSE_CATALOG is None:
        from acurast_valuation_fixed import fetch_pulse_catalog
        _PULSE_CATALOG = fetch_pulse_catalog()
    return _PULSE_CATALOG


def token_set(text):
    text=(text or '').lower().replace('+',' plus ')
    text=re.sub(r'([a-z]+)(\d)',r'\1 \2',text)
    text=re.sub(r'(\d)([a-z]+)',r'\1 \2',text)
    return set(re.findall(r'[a-z0-9]+',text))


def strict_candidate_variant_ok(text, model):
    raw=(text or '').lower()
    text_tokens=token_set(text)
    model_tokens=token_set(model)
    if '+' in str(model) and not ('+' in raw or 'plus' in text_tokens):
        return False
    model_variants=model_tokens & IDENTITY_VARIANTS
    title_variants=text_tokens & IDENTITY_VARIANTS
    # A variant named by the resolved model must be present in seller text.
    if model_variants - title_variants:
        return False
    # Conversely, a seller-declared identity variant may not be silently dropped
    # by resolving to a broader base model (e.g. Nord CE -> Nord).
    if title_variants - model_variants:
        return False
    return True


def pulse_gated_fallback(title, description, catalog):
    candidate = _ORIGINAL_FALLBACK(title, description, catalog)
    if not candidate:
        return None
    from acurast_valuation_fixed import match_pulse
    row, method, confidence = match_pulse(candidate, pulse_catalog())
    if row is None or method in {'NO_MATCH', 'AMBIGUOUS_EXACT', 'AMBIGUOUS_VARIANT'}:
        key=(base.norm(candidate), base.norm(title))
        _PULSE_FALLBACK_REJECTS[key]={
            'candidate_model': candidate,
            'title': ' '.join((title or '').split()),
            'pulse_match_method': method,
            'pulse_match_confidence': confidence,
            'reason': 'Core-compatible explicit model has no unique Acurast Pulse Mainnet reward match',
        }
        return None
    return candidate


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
            'reward': best_reward,
            'processor_count': total_count,
            'catalog_source': 'ACURASTBOT',
        })

    by_key = {(base.norm(x['brand']), base.norm(x['model'])): x for x in catalog}
    for row in base._pulse_discovery_rows(catalog):
        key = (base.norm(row['brand']), base.norm(row['model']))
        old = by_key.get(key)
        if old is None:
            row['reward'] = 0.0
            catalog.append(row)
            by_key[key] = row
        else:
            old['aliases'] |= row['aliases']
            old['processor_count'] = max(old['processor_count'], row['processor_count'])
            old['catalog_source'] = 'ACURASTBOT+ACURAST_PULSE_MAINNET'

    catalog.sort(key=lambda x: (-x.get('reward', 0.0), -x['processor_count'], x['label']))
    return catalog


def discover_category(session, found, catalog):
    pages=0; docs_total=0; previous=None
    for page in range(1,base.CATEGORY_MAX_PAGES+1):
        payload=base.getj(session,base.SEARCH_API,{
            'product_category':base.MOBILE_CATEGORY,'sort':'PRICE_ASC','page':page
        })
        docs=payload.get('docs') or []
        if not docs: break
        ids=tuple(str(d.get('id') or '') for d in docs)
        if ids==previous: break
        previous=ids; pages+=1; docs_total+=len(docs)
        base.add_search_docs(found,docs,f'category:{page}',catalog)
        prices=[base.amount(d.get('price')) for d in docs if base.amount(d.get('price')) is not None]
        if prices and min(prices)>base.MAX_ASK_DKK: break
    return pages,docs_total


def discovery_brands(catalog):
    # Query every represented Android manufacturer once. This is dynamic and grows
    # automatically with the authoritative registry/Pulse union.
    names={}
    for row in catalog:
        n=base.norm(row.get('brand'))
        if not n or n in {'apple','iphone'}:
            continue
        names.setdefault(n,str(row.get('brand') or '').strip())
    return [names[k] for k in sorted(names)]


def discover_brand_queries(session, found, catalog):
    pages=0; docs_total=0; errors=[]
    for brand in discovery_brands(catalog):
        previous=None
        for page in range(1,BRAND_QUERY_MAX_PAGES+1):
            try:
                payload=base.getj(session,base.SEARCH_API,{
                    'q':brand,'sort':'PRICE_ASC','page':page
                })
            except Exception as exc:
                errors.append({'brand':brand,'page':page,'error':type(exc).__name__})
                break
            docs=payload.get('docs') or []
            if not docs: break
            ids=tuple(str(d.get('id') or '') for d in docs)
            if ids==previous: break
            previous=ids; pages+=1; docs_total+=len(docs)
            base.add_search_docs(found,docs,f'brand:{base.norm(brand)}:{page}',catalog)
            prices=[base.amount(d.get('price')) for d in docs if base.amount(d.get('price')) is not None]
            if prices and min(prices)>base.MAX_ASK_DKK: break
    return pages,docs_total,errors


def persist_fallback_audit(path=Path('results/acurast_discovery_audit.json')):
    if not path.exists(): return
    try:
        audit=json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return
    rows=sorted(_PULSE_FALLBACK_REJECTS.values(),key=lambda x:(base.norm(x.get('candidate_model')),base.norm(x.get('title'))))
    audit['pulse_gated_fallback_rejects']=rows
    audit['pulse_gated_fallback_reject_count']=len(rows)
    path.write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    session=requests.Session(); Path('results').mkdir(exist_ok=True)
    catalog=build_catalog(session); found={}
    category_pages,category_docs=discover_category(session,found,catalog)
    brand_pages,brand_docs,search_errors=discover_brand_queries(session,found,catalog)

    pool=sorted(found.values(),key=lambda r:(r['ask_t0'],r['listing_id']))
    verified=[]; rejects=[]
    with ThreadPoolExecutor(max_workers=base.T1_WORKERS) as ex:
        futures=[ex.submit(base.verify,r,catalog) for r in pool]
        for f in as_completed(futures):
            x,rej=f.result()
            if x: verified.append(x)
            elif rej: rejects.append(rej)
    verified.sort(key=lambda r:(r['ask_t2'],r['model']))
    if not verified:
        raise SystemExit('PRICE DATA GATE FAILED — no verified supported devices')

    likely_unresolved=[r for r in rejects if r.get('stage')=='PRODUCT_IDENTITY' and r.get('reason')=='no supported model resolved' and r.get('brand_t0') not in (None,'apple')]
    stage_counts=Counter(r.get('stage') for r in rejects)
    reason_counts=Counter(r.get('reason') for r in rejects)
    audit={
        'generated_at':datetime.now(timezone.utc).isoformat(),
        'catalog_models':len(catalog),'t0_unique':len(pool),
        'verified_before_quality':len(verified),
        'discovery_sources':{
            'category_pages':category_pages,'category_docs':category_docs,
            'brand_query_pages':brand_pages,'brand_query_docs':brand_docs,
            'brand_queries':discovery_brands(catalog)
        },
        'reject_stage_counts':dict(stage_counts),'reject_reason_counts':dict(reason_counts),
        'likely_model_blindspots':sorted(likely_unresolved,key=lambda r:(r.get('ask_t0') or 999999,r.get('listing_id')))[:250],
        'all_rejects':rejects
    }
    Path('results/acurast_discovery_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    persist_fallback_audit()

    out={
        'generated_at':datetime.now(timezone.utc).isoformat(),
        'gate_passed':True,'product_identity_gate':True,
        'max_ask_dkk':base.MAX_ASK_DKK,
        'data_gate':'AcurastBot registry + Acurast Pulse Mainnet model discovery + DBA category/brand-query union + same-listing verification',
        'counts':{
            'category_pages':category_pages,'category_docs':category_docs,
            'brand_query_pages':brand_pages,'brand_query_docs':brand_docs,
            'catalog_models':len(catalog),'t0_unique':len(found),'t1_attempted':len(pool),
            't1_verified_active_product':len(verified),
            'product_identity_excluded':stage_counts.get('PRODUCT_IDENTITY',0),
            'final_refetched':len(verified)
        },
        'ranked_by_verified_ask':verified,'excluded':[],'search_errors':search_errors
    }
    Path('results/acurast_latest.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({
        'gate':True,'catalog_models':len(catalog),'category_pages':category_pages,
        'brand_query_pages':brand_pages,'t0_unique':len(found),'verified':len(verified),
        'reject_stages':dict(stage_counts),'likely_model_blindspots':len(likely_unresolved),
        'pulse_gated_fallback_rejects':len(_PULSE_FALLBACK_REJECTS)
    },ensure_ascii=False,indent=2))


# Patch the authoritative V1.6 resolver functions used by verification.
base.build_catalog = build_catalog
base.candidate_variant_ok = strict_candidate_variant_ok
base.fallback_core_model = pulse_gated_fallback

if __name__ == '__main__':
    main()
