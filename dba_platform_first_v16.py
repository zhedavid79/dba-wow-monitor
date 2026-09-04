from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import dba_browser_v2 as v2
import dba_strategy_optimizer as v15
from z20_complete_optimizer import RETAIL, fresh

PARTS=Path('results/z20_parts_latest.json')
OUT=Path('results/wow_strategy_latest.json')

# Live retail baselines verified 2026-09-05. These are decision inputs only; DBA USED ASK
# remains independently T0/T1 verified. Keep retail explicit so every build shows exactly
# which new parts must be bought and at what current price.
RETAIL.update({
    'case': {'name':'Jonsbo Z20 Mesh White','price':750,'url':'https://www.proshop.dk/Kabinet/Jonsbo-Z20-Mesh-Kabinet-Minitower-Hvid/3407428','verified_at':'2026-09-05T01:20:00+02:00','fit':'PROVEN'},
    'psu': {'name':'Corsair RM650e (2025) 650W ATX 3.1','price':647,'url':'https://www.proshop.dk/Stroemforsyning/Corsair-RMe-Series-RM650e-2025-Stroemforsyning-650-Watt-120-mm-ATX-31-80-Plus-Gold-certified/3324406','verified_at':'2026-09-05T01:20:00+02:00','length_mm':140,'fit':'PROVEN'},
    'ssd': {'name':'Kingston NV3 1TB M.2 2280 PCIe 4.0','price':1212,'url':'https://www.proshop.dk/SSD/Kingston-NV3-SSD-1TB-PCIe-40-M2-2280/3284682','verified_at':'2026-09-05T01:20:00+02:00','fit':'PROVEN'},
    'cpu': {'name':'AMD Ryzen 5 7500F','price':1099,'url':'https://www.proshop.dk/CPU/AMD-Ryzen-5-7500F-Tray-CPU-6-kerner-37-GHz-AMD-AM5-Bulk-ingen-koeler/3195178','verified_at':'2026-09-05T01:20:00+02:00','cpu':'Ryzen 5 7500F','cpu_score':94,'socket':'AM5'},
    'cooler': {'name':'Arctic Freezer 36 Black','price':175,'url':'https://www.proshop.dk/CPU-Koeler/Arctic-Freezer-36-Black-CPU-Luftkoeler/3238363','verified_at':'2026-09-05T01:20:00+02:00','height_mm':159,'fit':'PROVEN'},
    'ram_fallback': {'name':'Corsair Vengeance DDR5-6000 32GB CL30 EXPO','price':4290,'url':'https://www.proshop.dk/RAM/Corsair-Vengeance-DDR5-6000-32GB-CL30-Dual-Channel-2-pcs-AMD-EXPO-Intel-XMP-Hvid/3325848','verified_at':'2026-09-05T01:20:00+02:00','memory':'DDR5','capacity_gb':32,'desktop':True},
})

FOUNDATION_BOARD={
    'name':'GIGABYTE B650M GAMING PLUS WIFI', 'price':1170,
    'url':'https://www.proshop.dk/Bundkort/GIGABYTE-B650M-GAMING-PLUS-WIFI-Bundkort-AMD-B650-AMD-AM5-DDR5-RAM-Micro-ATX/3335794',
    'verified_at':'2026-09-05T01:20:00+02:00', 'socket':'AM5', 'chipset':'B650',
    'form_factor':'Micro-ATX', 'wifi':True, 'dimm_slots':4,
}
GRADE={'A':4,'B':3,'C':2,'D':1}
DEFECT=re.compile(r'\b(?:delvist\s+defekt|defekt|virker\s+ikke|fungerer\s+ikke|ustabil|artefakt(?:er)?|artifact(?:s)?|til\s+dele|reservedele|reparation)\b',re.I)
GPU_ACCESSORY=re.compile(r'\b(?:vandk(?:ø|oe)lings?\s*blok|vandblok|water\s*block|waterblock|gpu\s*block|backplate|k(?:ø|oe)ler|cooler|heatsink|radiator|fan\s*shroud|shroud|riser(?:\s*(?:cable|kabel))?|vertical\s*mount|gpu\s*holder|support\s*bracket|bracket|adapter|replacement\s*fan|bl(?:æ|ae)ser|tom\s*(?:kasse|emballage)|empty\s*box|emballage|box\s*only)\b', re.I)
CPU_ACCESSORY=re.compile(r'\b(?:cpu[- ]?k(?:ø|oe)ler|k(?:ø|oe)ler|cooler|heatsink|vandblok|water\s*block|waterblock|aio|radiator|contact\s*frame|mount(?:ing)?\s*(?:kit|bracket)|beslag|backplate|delid|ihs|tom\s*(?:kasse|emballage)|empty\s*box|emballage|box\s*only)\b', re.I)
AM5_CPU=re.compile(r'\b(?:7500f|7600x?|7700x?|7800x3d|7900x?|7950x3d|8400f|8500g|8600g|8700g|9600x|9700x|9800x3d|9900x3d|9950x3d)\b',re.I)
AM5_COOLER=re.compile(r'\bam5\b',re.I)
DDR5_32=re.compile(r'\bddr5\b.*\b32\s*gb\b|\b32\s*gb\b.*\bddr5\b',re.I)
FOUNDATION_USED_BOARD=re.compile(r'\b(?:b650m|b850m)\b',re.I)
WIFI=re.compile(r'\b(?:wifi|wi-fi|wireless|\w+\s+ax)\b',re.I)


def row_text(r): return ' '.join(str(r.get(k) or '') for k in ('title','description','name'))
def genuine_gpu(r): return r.get('kind')=='GPU' and not GPU_ACCESSORY.search(row_text(r))
def genuine_cpu(r): return r.get('kind')=='CPU' and not CPU_ACCESSORY.search(row_text(r))

def route_has_genuine_parts(r):
    for c in r.get('components') or []:
        if c.get('source') not in {'USED ASK','DBA_USED_LIVE'}: continue
        name=str(c.get('name') or '')
        if c.get('kind')=='GPU' and GPU_ACCESSORY.search(name): return False
        if c.get('kind')=='CPU' and CPU_ACCESSORY.search(name): return False
    return True

def used_ok(r): return r.get('condition')!='DEFECT_DISCLOSED' and not DEFECT.search(row_text(r))
def used(kind,r):
    if not used_ok(r): raise ValueError('functional defect hard-excluded')
    if kind=='GPU' and not genuine_gpu(r): raise ValueError('GPU accessory/non-GPU hard-excluded')
    if kind=='CPU' and not genuine_cpu(r): raise ValueError('CPU accessory/non-CPU hard-excluded')
    return {'kind':kind,'source':'USED ASK','name':r.get('title'),'price':int(r['ask_t1']),'url':r.get('url'),'listing_id':str(r.get('listing_id')),'functional_defect':False}

def new(kind,x): return {'kind':kind,'source':'NEW RETAIL','name':x['name'],'price':int(x['price']),'url':x['url'],'verified_at':x['verified_at']}
def ram_capacity(title):
    vals=[]
    for a,b in re.findall(r'\b(2|4)\s*x\s*(8|16|32)\s*gb\b',title,re.I): vals.append(int(a)*int(b))
    vals += [int(x) for x in re.findall(r'\b(16|32|64)\s*gb\b',title,re.I)]
    return max(vals) if vals else 0

def pclass(cpu_score,gpu_score): return v2.performance_class(int(gpu_score),int(cpu_score))
def fresh_board():
    age=datetime.now(timezone.utc)-datetime.fromisoformat(FOUNDATION_BOARD['verified_at']).astimezone(timezone.utc)
    return age.days<=7

def used_board_candidates(parts):
    out=[]
    for r in parts:
        t=r.get('title') or ''
        if r.get('kind')!='MOTHERBOARD' or not used_ok(r): continue
        if not FOUNDATION_USED_BOARD.search(t) or not WIFI.search(t): continue
        if not re.search(r'\b(?:4\s*(?:x\s*)?(?:dimm|ram)|4\s+ram[- ]?slots?)\b',t,re.I): continue
        if int(r.get('ask_t1') or 10**9) > int(FOUNDATION_BOARD['price']*0.60): continue
        out.append(r)
    return sorted(out,key=lambda r:r['ask_t1'])

def foundation_routes(parts):
    cpus=sorted([r for r in parts if genuine_cpu(r) and used_ok(r) and AM5_CPU.search((r.get('cpu') or '')+' '+(r.get('title') or '')) and int(r.get('cpu_score') or 0)>=76],key=lambda r:r['ask_t1'])[:12]
    rams=sorted([r for r in parts if r.get('kind')=='RAM' and used_ok(r) and r.get('ram_compatibility')=='DESKTOP_COMPATIBLE' and DDR5_32.search(r.get('title') or '') and ram_capacity(r.get('title') or '')>=32],key=lambda r:r['ask_t1'])[:8]
    gpus=sorted([r for r in parts if genuine_gpu(r) and used_ok(r) and int(r.get('gpu_score') or 0)>=45],key=lambda r:r['ask_t1'])[:24]
    coolers=sorted([r for r in parts if r.get('kind')=='COOLER' and used_ok(r) and AM5_COOLER.search(r.get('title') or '')],key=lambda r:r['ask_t1'])[:4]
    boards=used_board_candidates(parts)
    routes=[]
    if not fresh_board(): raise AssertionError('FOUNDATION BOARD RETAIL BASELINE EXPIRED')
    if not fresh(): raise AssertionError('NEW RETAIL BASELINES EXPIRED')
    if not gpus: return routes
    cpu_choices=[('USED',c) for c in cpus]+[('NEW',None)]
    ram_choices=[('USED',r) for r in rams]
    if RETAIL.get('ram_fallback'): ram_choices.append(('NEW',None))
    board_choices=[('NEW',None)]+[('USED',b) for b in boards[:3]]
    cooler_choices=[('USED',c) for c in coolers[:3]]+[('NEW',None)]
    for csrc,cpu in cpu_choices:
      cpu_name=cpu.get('cpu') if cpu else RETAIL['cpu']['cpu']
      cpu_score=int(cpu.get('cpu_score') or 0) if cpu else int(RETAIL['cpu']['cpu_score'])
      for rsrc,ram in ram_choices[:9]:
       for gpu in gpus:
        perf=pclass(cpu_score,gpu.get('gpu_score') or 0)
        if perf not in {'ACCEPTABLE','SWEET SPOT','OVERKILL'}: continue
        for bsrc,b in board_choices:
         for ksrc,cooler in cooler_choices[:4]:
          comps=[used('CPU',cpu) if cpu else new('CPU',RETAIL['cpu']), used('RAM',ram) if ram else new('RAM',RETAIL['ram_fallback']), used('GPU',gpu)]
          comps.append(used('MOTHERBOARD',b) if bsrc=='USED' else new('MOTHERBOARD',FOUNDATION_BOARD))
          comps.append(used('COOLER',cooler) if cooler else new('COOLER',RETAIL['cooler']))
          comps += [new('CASE',RETAIL['case']),new('PSU',RETAIL['psu']),new('STORAGE',RETAIL['ssd'])]
          routes.append({'route':'PLATFORM_FIRST_AM5','label':f"AM5 foundation: {cpu_name} + {gpu.get('gpu')}",'tcwp':sum(x['price'] for x in comps),'cpu':cpu_name,'cpu_score':cpu_score,'gpu':gpu.get('gpu'),'gpu_score':int(gpu.get('gpu_score') or 0),'performance_class':perf,'upgradeability':'A','z20_fit':'LIKELY','components':comps,'foundation':'AM5_B650_B850_MATX_WIFI_4DIMM','bridge_gpu':perf=='ACCEPTABLE','rationale':'Platform-first AM5/Z20 foundation. Each row is a complete working-PC bill of materials; USED ASK and NEW RETAIL are explicit per component.'})
    return routes

def foundation_score(r):
    score=100 if r.get('foundation')=='AM5_B650_B850_MATX_WIFI_4DIMM' else 0
    score += 12*GRADE.get(r.get('upgradeability'),0)
    if r.get('z20_fit') in {'VERIFIED','LIKELY'}: score+=15
    return score

def sourcing_penalty(r):
    penalty=0
    for c in r.get('components') or []:
        k=c.get('kind'); src=c.get('source')
        if k in {'GPU','CPU','RAM','COOLER'} and src=='NEW RETAIL': penalty+=4
        if k in {'PSU','STORAGE'} and src=='USED ASK': penalty+=12
    return penalty

def strategic_key(r):
    foundation=foundation_score(r); penalty=sourcing_penalty(r)
    perf={'ACCEPTABLE':0,'SWEET SPOT':-60,'OVERKILL':20}.get(r.get('performance_class'),100)
    effective=int(r['tcwp']) - min(foundation*8,1200) + penalty*20 + perf
    r['foundation_score']=foundation; r['sourcing_penalty']=penalty; r['strategic_effective_cost']=effective
    return (effective,int(r['tcwp']),-foundation)

def main():
    v15.main()
    d=json.loads(OUT.read_text(encoding='utf-8')); p=json.loads(PARTS.read_text(encoding='utf-8'))
    inherited=[r for r in (d.get('ranked') or []) if route_has_genuine_parts(r)]
    routes=inherited+foundation_routes(p.get('opportunities') or [])
    seen=set(); unique=[]
    for r in routes:
        if not route_has_genuine_parts(r): continue
        key=tuple(sorted((str(c.get('source')),str(c.get('listing_id') or c.get('name')),int(c.get('price') or 0)) for c in r.get('components') or []))
        if key in seen: continue
        seen.add(key); unique.append(r)
    unique.sort(key=strategic_key)
    foundation=[r for r in unique if r.get('foundation')=='AM5_B650_B850_MATX_WIFI_4DIMM']
    viable=sorted(unique,key=lambda r:r['tcwp'])
    opportunistic=sorted([r for r in unique if any(c.get('kind')=='GPU' and c.get('source')=='USED ASK' for c in r.get('components') or [])],key=strategic_key)
    complete=[r for r in unique if r.get('route')=='COMPLETE_USED_PC']; donor=[r for r in unique if r.get('route')=='USED_PC_PLUS_FUTURE_UPGRADE']; hybrid=[r for r in unique if r.get('route') in {'HYBRID_USED_NEW','PLATFORM_FIRST_AM5'}]
    d.update({'model_version':'DBA-WOW-PLATFORM-FIRST-V16','strategy_mode':'PLATFORM_FIRST_OPPORTUNISTIC','purchase_hierarchy':{'used_first':['GPU','CPU','RAM','COOLER'],'used_if_material_saving':['MOTHERBOARD','CASE'],'new_first':['PSU','STORAGE','FANS']},'foundation_target':'AM5 + B650/B850 mATX + Wi-Fi + 4 DIMM + DDR5 + Jonsbo Z20','ranked':unique,'buy_now':unique[0] if unique else None,'best_foundation':foundation[0] if foundation else None,'cheapest_viable':viable[0] if viable else None,'best_opportunistic_buy':opportunistic[0] if opportunistic else None,'best_complete_pc':complete[0] if complete else None,'best_donor_upgrade_route':donor[0] if donor else None,'best_hybrid_build':hybrid[0] if hybrid else None,'wait_buy':'BUY' if unique and unique[0].get('foundation_score',0)>=100 else 'WAIT_FOR_FOUNDATION_OR_EXCEPTIONAL_COMPLETE_PC','counts':{**(d.get('counts') or {}),'platform_first_routes':len(foundation),'ranked_routes':len(unique)}})
    assert all(route_has_genuine_parts(r) for r in unique), 'ACCESSORY LEAKED INTO PUBLISHED RANKING'
    OUT.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'model':d['model_version'],'ranked':len(unique),'foundation':len(foundation),'buy_now':(d.get('buy_now') or {}).get('route'),'wait_buy':d['wait_buy']},ensure_ascii=False))

if __name__=='__main__': main()
