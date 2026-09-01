from __future__ import annotations

import re
from functools import lru_cache
from typing import Callable

import requests

BOT_DEVICES='https://api.acurastbot.com/devices/with-counts'
INCOMPATIBLE_STATE_RE=re.compile(r'\b(rooted|rootet|magisk|lineage\s*os|lineageos|custom\s*rom|bootloader\s*(?:unlocked|oplåst)|oplåst\s+bootloader)\b',re.I)
NOISE={'galaxy','phone','smartphone','mobile','mobil','5g','4g','lte','nr'}


def norm(s:str)->str:
    s=(s or '').lower().replace('+',' plus ')
    s=re.sub(r'\bone\s+plus\b','oneplus',s)
    s=re.sub(r'\bmoto\b','motorola',s)
    s=re.sub(r'([a-z])([0-9])',r'\1 \2',s)
    s=re.sub(r'([0-9])([a-z])',r'\1 \2',s)
    s=re.sub(r'[^a-z0-9]+',' ',s).strip()
    toks=[]
    for t in s.split():
        if t in NOISE:
            continue
        if not toks or toks[-1]!=t:
            toks.append(t)
    return ' '.join(toks)


@lru_cache(maxsize=1)
def observed_processor_models()->set[str]:
    r=requests.get(BOT_DEVICES,headers={'User-Agent':'Mozilla/5.0'},timeout=30)
    r.raise_for_status()
    out=set()
    for d in r.json():
        total=int(d.get('totalProcessorCount') or 0)
        if total<=0:
            total=sum(int(c.get('processorCount') or 0) for c in (d.get('configurations') or []))
        if total<=0:
            continue
        company=str(d.get('company') or '').strip()
        model=str(d.get('model') or '').strip()
        if model:
            out.add(norm(model))
            out.add(norm(f'{company} {model}'))
    return {x for x in out if x}


def core_compatibility(model:str,title:str='',description:str='',legacy:Callable[[str,str,str],tuple[bool,str]]|None=None)->tuple[bool,str]:
    text=f'{model} {title} {description}'
    if INCOMPATIBLE_STATE_RE.search(text):
        return False,'listing indicates rooted/custom-ROM/unlocked-bootloader state'

    key=norm(model)
    try:
        if key and key in observed_processor_models():
            return True,'Acurast device registry has observed processor(s) for this normalized model; compatibility evidence only, never reward calibration'
    except Exception:
        pass

    if legacy is not None:
        return legacy(model,title,description)
    return False,'Android 12+ / Acurast Core compatibility not independently verified'
