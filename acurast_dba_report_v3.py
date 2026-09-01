from __future__ import annotations

"""V1.6 discovery entry point with conservative Mainnet Pulse family-proxy eligibility.

This keeps the proven DBA retrieval/identity pipeline intact while hardening the
remaining false-negative paths. Compatibility evidence may use observed Acurast
device-registry presence, but absolute ACU remains Mainnet Pulse only.
"""

import re
import requests

import acurast_dba_report_v2 as v2
import acurast_valuation as compat
from acurast_core_compat import core_compatibility as enhanced_core_compatibility
from acurast_pulse_proxy import build_family_proxy


_LEGACY_CORE=compat.core_compatibility

def _core(model:str,title:str='',description:str=''):
    return enhanced_core_compatibility(model,title,description,_LEGACY_CORE)

# All downstream discovery compatibility checks in this process use the same
# evidence hierarchy: explicit incompatible state -> observed Acurast processor
# model -> conservative legacy Android-12 allowlist.
compat.core_compatibility=_core

STOPWORDS={
    'velholdt','perfekt','god','rimelig','defekt','skadet','ødelagt','revnet','sort','hvid',
    'blå','bla','grøn','gron','rød','rod','lilla','grå','gra','sølv','solv','gold','guld',
    'sælges','saelges','telefon','mobil','smartphone','som','ny','stand','pris'
}


def canonical_fallback_model(candidate:str)->str:
    """Keep the explicit marketing identity while stripping seller prose/capacity.

    Unlike the old first-numeric-token rule this preserves identities such as S21 FE,
    13T Pro, Nothing Phone 2a and Xperia 5 III.
    """
    text=' '.join((candidate or '').split())
    text=re.sub(r'\b(?:32|64|128|256|512|1024)\s*gb\b',' ',text,flags=re.I)
    text=re.sub(r'\b(?:3|4|6|8|10|12|16|18|24)\s*gb\s*(?:ram)?\b',' ',text,flags=re.I)
    text=re.sub(r'\s+',' ',text).strip(' -–—,|()[]')
    if not text:
        return text

    # Seller prose after a dash/comma is not model identity when the leading segment
    # already contains a generation/model digit.
    parts=re.split(r'\s+[–—-]\s+|\s*\|\s*|,\s+',text,maxsplit=1)
    if len(parts)>1 and re.search(r'\d',parts[0]):
        text=parts[0].strip()

    toks=re.findall(r'[A-Za-zÆØÅæøå0-9+]+',text)
    out=[]
    seen_model_signal=False
    for tok in toks:
        low=tok.lower()
        if out and seen_model_signal and low in STOPWORDS:
            break
        out.append(tok)
        if re.search(r'\d',tok) or low in {'pro','ultra','lite','fe','neo','fusion','plus','ce','gt','max','mini','fold','flip','note','ii','iii','iv','v','vi'}:
            seen_model_signal=True
    return ' '.join(out).strip()


def pulse_or_proxy_gated_fallback(title, description, catalog):
    candidate=v2._ORIGINAL_FALLBACK(title,description,catalog)
    if not candidate:
        return None
    candidate=canonical_fallback_model(candidate)
    if not candidate:
        return None

    core_ok,_=_core(candidate,title,description)
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


def _authoritative_listing_ids(payload:dict)->set[str]:
    ids=set()
    item=payload.get('itemData') if isinstance(payload,dict) else None
    for obj in (item,payload):
        if not isinstance(obj,dict):
            continue
        for key in ('listingId','itemId','id'):
            value=obj.get(key)
            if value is not None and str(value).isdigit():
                ids.add(str(value))

    # Canonical/item URLs are strong identity evidence anywhere in the payload.
    stack=[payload]
    while stack:
        x=stack.pop()
        if isinstance(x,dict):
            for k,val in x.items():
                if isinstance(val,str) and ('url' in k.lower() or 'canonical' in k.lower()):
                    m=re.search(r'/item/(\d+)',val)
                    if m:
                        ids.add(m.group(1))
                elif isinstance(val,(dict,list)):
                    stack.append(val)
        elif isinstance(x,list):
            stack.extend(x[:300])
    return ids


def fetch_item_v16(lid):
    r=requests.get(v2.base.ITEM_URL.format(id=lid),headers=v2.base.HEADERS,timeout=v2.base.TIMEOUT)
    r.raise_for_status()
    payload=r.json()
    item=payload.get('itemData') or {}
    ids=_authoritative_listing_ids(payload)
    return {
        'listing_id':lid,
        'identity_ok':str(lid) in ids,
        'url':v2.base.ITEM_URL.format(id=lid),
        'title':str(item.get('title') or '').strip(),
        'price':v2.base.amount(item.get('price')),
        'disposed':bool(item.get('disposed')),
        'trade_type':item.get('tradeType') or item.get('adViewTypeLabel'),
        'description':str(item.get('description') or ''),
    }


def product_identity_v16(title,description,model,price,catalog):
    t=' '.join((title or '').split())
    d=' '.join((description or '').split())
    both=f'{t} {d}'
    explicit=v2.base.detected_brand(t,catalog)
    if explicit=='apple':
        return False,'Apple/iPhone listing is not an Android Acurast Core candidate'
    if price is not None and price>v2.base.MAX_ASK_DKK:
        return False,'ASK ceiling'
    if not model:
        return False,'no supported model resolved'
    hit=next((x for x in catalog if x['label']==model),None)
    model_brand=v2.base.norm(hit['brand']) if hit else v2.base.detected_brand(model,catalog)
    if explicit and model_brand and explicit!=model_brand:
        return False,f'explicit brand mismatch: {explicit} != {model_brand}'
    if explicit and not model_brand:
        return False,'resolved model brand not verified'
    model_name=hit['model'] if hit else model
    if not v2.base.candidate_variant_ok(both,model_name):
        return False,'resolved model variant is not supported by seller text'

    complete=bool(v2.base.COMPLETE_PHONE_RE.search(both))
    functional=bool(v2.base.FUNCTION_RE.search(both))
    specs=bool(v2.base.SPEC_RE.search(both))
    explicit_model_title=bool(v2.base.model_of(t,catalog) or v2.base.fallback_core_model(t,d,catalog))
    title_accessory=bool(v2.base.ACCESSORY_RE.search(t))
    bundled_accessory=bool(re.search(r'\b(?:med|inkl\.?|inkluderer|medfølger)\b',t,re.I))

    # Accessory words are only fatal when the title looks like the accessory itself.
    # "S21 cover" stays rejected; "S21 med cover" may pass once a phone model is
    # explicit and the rest of the identity evidence is consistent.
    if title_accessory and not (explicit_model_title and bundled_accessory):
        return False,'accessory/part title'
    if price is not None and price<150 and not (complete and (functional or specs)):
        return False,'weak complete-phone evidence'
    if v2.base.ACCESSORY_RE.search(d) and not (complete and functional) and not (explicit_model_title and functional):
        return False,'description indicates part without explicit functional phone evidence'
    source='registry/Pulse catalog' if hit else 'Core-compatible explicit-title fallback'
    return True,f'{source} + strict brand/model/variant identity + live product identity passed'


v2.base.fetch_item=fetch_item_v16
v2.base.product_identity=product_identity_v16
v2.base.fallback_core_model=pulse_or_proxy_gated_fallback

if __name__=='__main__':
    v2.main()
