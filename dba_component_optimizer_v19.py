from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path

import dba_self_build_v17 as v17

OUT = Path('results/wow_strategy_latest.json')
RETAIL_SNAPSHOT = Path('results/retail_prices_latest.json')

CATEGORY_POLICY = {
    'MOTHERBOARD': {'role':'PERMANENT FOUNDATION','hard':['AM5','mATX','DDR5','Wi-Fi','4 DIMM','>=2 M.2','>=2.5GbE','Z20 compatible'],'principle':'Choose the lowest effective cost after assigning only modest value to features that can extend useful platform life.'},
    'PSU': {'role':'PERMANENT FOUNDATION','hard':['NEW RETAIL preferred','>=750W','ATX 3.x','modular','<=160 mm preferred for Z20'],'principle':'Pay a modest premium for real headroom, compactness and modern GPU power; do not reward wattage beyond the plausible upgrade path.'},
    'CASE': {'role':'PERMANENT FOUNDATION','hard':['mATX compatible','GPU/cooler clearance compatible'],'principle':'Jonsbo Z20 is the intended final enclosure, so an exact Z20 receives value only because it avoids a later case replacement.'},
    'COOLER': {'role':'LONG-LIVED FOUNDATION','hard':['AM5 compatible','<=163 mm for Z20'],'principle':'Adequate air cooling wins; expensive cooling receives no gaming-performance premium unless it buys a concrete noise/thermal benefit.'},
    'RAM': {'role':'SEMI-DURABLE','hard':['desktop DDR5','non-RDIMM/SO-DIMM','>=16GB'],'principle':'32GB DDR5-6000 is the long-term target, but a 16GB bridge is valid only when the avoided spend clearly exceeds its future-upgrade penalty.'},
    'CPU': {'role':'REPLACEABLE PERFORMANCE','hard':['compatible with chosen AM5 foundation','function verified if used'],'principle':'Rank on WoW CPU score and price. Do not pay large future-proofing premiums when the socket itself preserves the X3D upgrade path.'},
    'GPU': {'role':'REPLACEABLE PERFORMANCE','hard':['function verified if used','Z20 fit must not be known-NO'],'principle':'Rank on target-resolution performance, price and a modest VRAM/longevity allowance. Performance hardware must earn its premium now.'},
    'STORAGE': {'role':'CONVENIENCE / EASY UPGRADE','hard':['NVMe','>=500GB'],'principle':'Capacity above adequacy gets only a modest value because storage is easy to add and gives little WoW FPS.'},
}

# Stable specs; prices are replaced by the live same-product retail snapshot.
# Prisjagt pages are used because they expose structured offers and are reachable from GitHub Actions.
RETAIL_CANDIDATES = {
    'MOTHERBOARD': [
        {'sku':'ASROCK_B850M_PRO_A_WIFI','name':'ASRock B850M Pro-A WiFi','price':1022,'url':'https://prisjagt.dk/product.php?p=14363712','identity_aliases':['ASRock B850M Pro-A WiFi'],'source':'NEW RETAIL','socket':'AM5','form_factor':'mATX','ddr':'DDR5','dimm_slots':4,'wifi':'6E','lan_gbps':2.5,'m2_count':3,'pcie5_m2':True,'pcie5_x16':True,'vrm_vcore_phases':8,'drmos':True,'bios_flashback':True,'front_usb_c':True},
        {'sku':'MSI_B850M_GAMING_PLUS_WIFI6E','name':'MSI B850M Gaming Plus WiFi6E','price':1130,'url':'https://prisjagt.dk/product.php?p=15126881','identity_aliases':['MSI B850M GAMING PLUS WIFI6E'],'source':'NEW RETAIL','socket':'AM5','form_factor':'mATX','ddr':'DDR5','dimm_slots':4,'wifi':'6E','lan_gbps':2.5,'m2_count':2,'pcie5_m2':True,'pcie5_x16':False,'vrm_vcore_phases':10,'drmos':True,'bios_flashback':True,'front_usb_c':True},
        {'sku':'GIGABYTE_B650M_GAMING_PLUS_WIFI','name':'Gigabyte B650M Gaming Plus WiFi','price':1088,'url':'https://prisjagt.dk/product.php?p=14500786','identity_aliases':['Gigabyte B650M Gaming Plus WiFi'],'source':'NEW RETAIL','socket':'AM5','form_factor':'mATX','ddr':'DDR5','dimm_slots':4,'wifi':'6','lan_gbps':2.5,'m2_count':2,'pcie5_m2':False,'pcie5_x16':False,'vrm_vcore_phases':5,'drmos':False,'bios_flashback':True,'front_usb_c':True},
    ],
    'PSU': [
        {'sku':'MSI_A850GL_PCIE5_II','name':'MSI MAG A850GL PCIE5 II','price':760,'url':'https://prisjagt.dk/product.php?p=15147757','identity_aliases':['MSI MAG A850GL PCIE5 II'],'source':'NEW RETAIL','watt':850,'atx31':True,'modular':True,'length_mm':140,'gold':True},
        {'sku':'CORSAIR_RM750E_2025','name':'Corsair RM750e (2025) ATX 3.1 750W','price':799,'url':'https://prisjagt.dk/product.php?p=14366565','identity_aliases':['Corsair RM750e (2025) ATX 3.1 750W'],'source':'NEW RETAIL','watt':750,'atx31':True,'modular':True,'length_mm':140,'gold':True},
    ],
    'CASE': [
        {'sku':'JONSBO_Z20_WHITE','name':'Jonsbo Z20 White','price':764,'url':'https://prisjagt.dk/product.php?p=14356470','identity_aliases':['Jonsbo Z20 Vit','Jonsbo Z20 White'],'source':'NEW RETAIL','matx':True,'exact_final_case':True,'gpu_clearance_mm':363,'cooler_clearance_mm':164},
    ],
    'COOLER': [
        {'sku':'ARCTIC_FREEZER_36_BLACK','name':'Arctic Freezer 36 Black','price':135,'url':'https://prisjagt.dk/product.php?p=15683387','identity_aliases':['Arctic Freezer 36 Black'],'source':'NEW RETAIL','am5':True,'height_mm':159,'value_air_cooler':True},
    ],
    'RAM': [
        {'sku':'CORSAIR_VENGEANCE_32_6000_CL38','name':'Corsair Vengeance DDR5-6000 32GB (2x16GB) EXPO CL38','price':3499,'url':'https://prisjagt.dk/product.php?p=15907662','identity_aliases':['Corsair Vengeance DDR5 6000MHz 32GB CMK32GX5M2B6000Z38'],'source':'NEW RETAIL','capacity_gb':32,'speed_mt':6000,'cl':38,'kit_dimms':2,'expo':True,'desktop_ddr5':True},
    ],
    'STORAGE': [
        {'sku':'PNY_CS1030_500','name':'PNY CS1030 M.2 NVMe SSD 500GB','price':683,'url':'https://prisjagt.dk/product.php?p=7281095','identity_aliases':['PNY CS1030 M.2 NVMe SSD 500GB'],'source':'NEW RETAIL','capacity_gb':500,'nvme':True},
        {'sku':'KINGSTON_NV3_1TB','name':'Kingston NV3 M.2 2280 PCIe 4.0 NVMe 1TB','price':1142,'url':'https://prisjagt.dk/product.php?p=13782579','identity_aliases':['Kingston NV3 M.2 2280 PCIe 4.0 NVMe 1TB'],'source':'NEW RETAIL','capacity_gb':1000,'nvme':True},
    ],
}

BAD_RAM = re.compile(r'\b(?:so[- ]?dimm|sodimm|rdimm|lrdimm|registered|server\s*ram|kingston\s+fury\s+impact|kf548s38ibk2(?:-\d+)?)\b', re.I)
GPU_VRAM = {'RX 5700 XT':8,'RX 6600':8,'RX 6600 XT':8,'RX 6650 XT':8,'RTX 2060 Super':8,'RTX 2070':8,'RTX 2070 Super':8,'RTX 2080':8,'RTX 2080 Super':8,'RTX 3060 Ti':8,'RTX 3070':8,'RTX 3070 Ti':8,'RX 6700 XT':12,'RX 6750 XT':12,'RX 6800':16,'RX 6800 XT':16,'RTX 3080':10,'RTX 4060':8,'RTX 4060 Ti':8,'RX 7600':8}


def _snapshot_candidates(kind: str) -> list[dict]:
    candidates = deepcopy(RETAIL_CANDIDATES.get(kind) or [])
    if not RETAIL_SNAPSHOT.exists():
        return candidates
    try:
        snap = json.loads(RETAIL_SNAPSHOT.read_text(encoding='utf-8'))
    except Exception:
        return []
    by_sku = {str(x.get('sku')): x for x in snap.get('products') or [] if x.get('sku')}
    verified = []
    for c in candidates:
        live = by_sku.get(str(c.get('sku')))
        if not live or live.get('verified') is not True or int(live.get('price') or 0) <= 0:
            continue
        c['price'] = int(live['price'])
        c['url'] = str(live.get('url') or c['url'])
        c['verified_at'] = live.get('verified_at')
        c['availability'] = live.get('availability')
        c['price_evidence'] = 'LIVE_RETAIL_SNAPSHOT'
        verified.append(c)
    return verified


def ram_capacity(name: str) -> int:
    m = re.search(r'\b(2|4)\s*x\s*(8|16|32)\s*gb\b', name or '', re.I)
    if m: return int(m.group(1))*int(m.group(2))
    vals = [int(x) for x in re.findall(r'\b(8|16|32|64)\s*gb\b', name or '', re.I)]
    return max(vals) if vals else 0


def enrich_used(kind: str, c: dict) -> dict:
    x = deepcopy(c); name = str(x.get('name') or '')
    if kind == 'RAM':
        x['capacity_gb'] = int(x.get('capacity_gb') or ram_capacity(name))
        x['desktop_ddr5'] = bool('ddr5' in name.lower() and not BAD_RAM.search(name))
        m = re.search(r'\b(4[8-9]00|5[0-9]00|6[0-9]00|7[0-9]00)\s*(?:mhz|mt/s)?\b', name, re.I); x['speed_mt'] = int(m.group(1)) if m else 0
        cl = re.search(r'\bcl\s*([2345]\d)\b', name, re.I); x['cl'] = int(cl.group(1)) if cl else None
        kit = re.search(r'\b(2|4)\s*x\s*(?:8|16|32)\b', name, re.I); x['kit_dimms'] = int(kit.group(1)) if kit else None
        x['expo'] = bool(re.search(r'\bexpo\b', name, re.I))
    return x


def used_candidates(route: dict, kind: str) -> list[dict]:
    rows=[]; cur=next((c for c in route.get('components') or [] if c.get('kind')==kind),None)
    if cur and cur.get('source')=='USED ASK': rows.append(cur)
    rows += [c for c in ((route.get('component_alternatives') or {}).get(kind) or []) if c.get('source')=='USED ASK']
    out=[]; seen=set()
    for c in rows:
        if not c.get('url') or int(c.get('price') or 0)<=0: continue
        key=str(c.get('listing_id') or c.get('url'))
        if key in seen: continue
        seen.add(key); out.append(enrich_used(kind,c))
    return out


def hard_gate(kind: str, c: dict) -> tuple[bool,list[str]]:
    f=[]
    if int(c.get('price') or 0)<=0 or not c.get('url'): f.append('missing price/url')
    if c.get('source')=='USED ASK' and c.get('functional_defect') is not False: f.append('used function not verified')
    if kind=='MOTHERBOARD':
        if c.get('socket')!='AM5': f.append('not AM5')
        if str(c.get('form_factor')).lower() not in {'matx','micro-atx','micro atx'}: f.append('not mATX')
        if c.get('ddr')!='DDR5': f.append('not DDR5')
        if int(c.get('dimm_slots') or 0)<4: f.append('<4 DIMM')
        if not c.get('wifi'): f.append('no Wi-Fi')
        if float(c.get('lan_gbps') or 0)<2.5: f.append('<2.5GbE')
        if int(c.get('m2_count') or 0)<2: f.append('<2 M.2')
    elif kind=='PSU':
        if int(c.get('watt') or 0)<750: f.append('<750W')
        if not c.get('atx31'): f.append('not ATX 3.x')
        if not c.get('modular'): f.append('not modular')
        if int(c.get('length_mm') or 999)>160: f.append('too long for preferred Z20 packaging')
    elif kind=='CASE':
        if not c.get('matx'): f.append('not mATX compatible')
    elif kind=='COOLER':
        if not c.get('am5'): f.append('not AM5 compatible')
        if int(c.get('height_mm') or 999)>163: f.append('>163mm')
    elif kind=='RAM':
        name=str(c.get('name') or '')
        if BAD_RAM.search(name) or not c.get('desktop_ddr5'): f.append('not proven desktop DDR5')
        if int(c.get('capacity_gb') or 0)<16: f.append('<16GB')
    elif kind=='STORAGE':
        if not c.get('nvme'): f.append('not NVMe')
        if int(c.get('capacity_gb') or 0)<500: f.append('<500GB')
    return not f,f


def feature_value(kind: str,c: dict)->tuple[int,list[str],list[str]]:
    v=0; a=[]; t=[]
    if kind=='MOTHERBOARD':
        if 'B850' in str(c.get('name') or '').upper(): v+=50; a.append('B850 chipset (+50)')
        phases=int(c.get('vrm_vcore_phases') or 0)
        if phases>=8: v+=100; a.append('>=8 VCore phases (+100)')
        if phases>=10: v+=30; a.append('10+ VCore phases (+30)')
        if c.get('drmos'): v+=30; a.append('DrMOS power stage (+30)')
        if c.get('pcie5_m2'): v+=75; a.append('PCIe 5.0 M.2 (+75)')
        if int(c.get('m2_count') or 0)>=3: v+=75; a.append('3+ M.2 slots (+75)')
        wifi=str(c.get('wifi') or '').upper()
        if wifi in {'6E','7'}: v+=40; a.append(f'Wi-Fi {wifi} (+40)')
        if wifi=='7': v+=30; a.append('Wi-Fi 7 extra longevity (+30)')
        if c.get('pcie5_x16'): v+=50; a.append('PCIe 5.0 x16 (+50)')
        if c.get('bios_flashback'): v+=50; a.append('BIOS Flashback (+50)')
        if c.get('front_usb_c'): v+=30; a.append('front USB-C header (+30)')
        if float(c.get('lan_gbps') or 0)>=5: v+=40; a.append('5GbE (+40)')
        if phases<8: t.append('basic VRM headroom')
        if not c.get('pcie5_m2'): t.append('no Gen5 M.2')
        if int(c.get('m2_count') or 0)<3: t.append('only 2 M.2 slots')
    elif kind=='PSU':
        if int(c.get('watt') or 0)>=850: v+=75; a.append('850W useful GPU headroom (+75)')
        if c.get('atx31'): v+=50; a.append('ATX 3.1 (+50)')
        if int(c.get('length_mm') or 999)<=140: v+=50; a.append('140mm compact Z20-friendly length (+50)')
        if c.get('gold'): v+=25; a.append('80 Plus Gold-class efficiency (+25)')
        if c.get('modular'): v+=25; a.append('modular cabling (+25)')
    elif kind=='CASE':
        if c.get('exact_final_case'): v+=250; a.append('exact intended final Jonsbo Z20; avoids later case replacement (+250)')
    elif kind=='COOLER':
        if c.get('value_air_cooler'): v+=100; a.append('known value-class AM5 air cooler (+100)')
    elif kind=='RAM':
        if int(c.get('capacity_gb') or 0)>=32: v+=600; a.append('32GB long-term target (+600)')
        else: t.append('16GB bridge; future RAM replacement likely')
        if int(c.get('speed_mt') or 0)>=6000: v+=100; a.append('DDR5-6000 target speed (+100)')
        if c.get('expo'): v+=40; a.append('AMD EXPO (+40)')
        cl=c.get('cl')
        if cl and int(cl)<=32: v+=75; a.append('tight <=CL32 timings (+75)')
        elif cl and int(cl)<=38: v+=30; a.append('reasonable <=CL38 timings (+30)')
        if int(c.get('kit_dimms') or 0)==2: v+=30; a.append('2-DIMM dual-channel kit (+30)')
    elif kind=='STORAGE':
        if int(c.get('capacity_gb') or 0)>=1000: v+=250; a.append('1TB comfort capacity (+250)')
    return v,a,t


def evaluate(kind:str,candidates:list[dict])->list[dict]:
    out=[]
    for c in candidates:
        x=deepcopy(c); ok,f=hard_gate(kind,x); fv,a,t=feature_value(kind,x)
        x.update({'eligible':ok,'hard_gate_failures':f,'feature_value_dkk':fv,'effective_cost_dkk':int(x.get('price') or 10**9)-fv if ok else 10**9,'advantages':a,'tradeoffs':t}); out.append(x)
    out.sort(key=lambda x:(not x['eligible'],int(x['effective_cost_dkk']),int(x.get('price') or 10**9)))
    return out


def choose(kind:str,route:dict)->dict:
    candidates=_snapshot_candidates(kind)
    if kind=='RAM': candidates += used_candidates(route,kind)
    evaluated=evaluate(kind,candidates); eligible=[x for x in evaluated if x['eligible']]
    winner=eligible[0] if eligible else None; runner=eligible[1] if len(eligible)>1 else None
    why='No eligible candidate.'
    if winner:
        why=f"Lowest effective cost: {winner['price']} kr price - {winner['feature_value_dkk']} kr justified feature value = {winner['effective_cost_dkk']} kr."
        if runner:
            pd=int(winner['price'])-int(runner['price']); fd=int(winner['feature_value_dkk'])-int(runner['feature_value_dkk']); ed=int(runner['effective_cost_dkk'])-int(winner['effective_cost_dkk'])
            why += f" Versus runner-up: price delta {pd:+d} kr, feature-value delta {fd:+d} kr, effective advantage {ed} kr."
    return {'kind':kind,'policy':CATEGORY_POLICY[kind],'winner':winner,'runner_up':runner,'evaluated':evaluated,'reason':why}


def _replace(route:dict,kind:str,candidate:dict)->None:
    if not candidate: return
    comps=route.get('components') or []; r=deepcopy(candidate)
    for k in ('eligible','hard_gate_failures','feature_value_dkk','effective_cost_dkk','advantages','tradeoffs','identity_aliases'): r.pop(k,None)
    r['kind']=kind; r.setdefault('source','NEW RETAIL')
    for i,c in enumerate(comps):
        if c.get('kind')==kind: comps[i]=r; break
    route['components']=comps; route['tcwp']=sum(int(c.get('price') or 0) for c in comps)


def cpu_gpu_explanation(route:dict,kind:str)->dict:
    c=next((x for x in route.get('components') or [] if x.get('kind')==kind),None)
    if not c: return {'kind':kind,'reason':'No selected component.'}
    price=int(c.get('price') or 0); score=int(route.get('cpu_score' if kind=='CPU' else 'gpu_score') or 0)
    result={'kind':kind,'selected':c,'price':price,'performance_score':score,'performance_class':route.get('performance_class')}
    if kind=='GPU':
        model=str(route.get('gpu') or ''); vram=GPU_VRAM.get(model); longevity=0 if not vram or vram<=8 else 150 if vram<=12 else 250
        result.update({'vram_gb':vram,'vram_longevity_value_dkk':longevity,'reason':f"Selected through whole-build ranking: GPU score {score}, {vram or 'unknown'}GB VRAM, {price} kr ask; VRAM receives at most {longevity} kr longevity value so it cannot dominate current value."})
    else:
        result['reason']=f"Selected through whole-build ranking: WoW CPU score {score} at {price} kr on an AM5 foundation; future X3D capability is valued through the socket rather than overbuying this CPU."
    return result


def optimize_route(route:dict)->dict:
    r=deepcopy(route); decisions={}
    for kind in ('MOTHERBOARD','PSU','CASE','COOLER','RAM','STORAGE'):
        dec=choose(kind,r); decisions[kind]=dec
        if dec.get('winner'): _replace(r,kind,dec['winner'])
    decisions['CPU']=cpu_gpu_explanation(r,'CPU'); decisions['GPU']=cpu_gpu_explanation(r,'GPU'); r['component_choice_v19']=decisions; v17.self_build_effective_cost(r); return r


def finalize(data:dict)->dict:
    routes=[optimize_route(r) for r in data.get('self_build_ranked') or [] if r.get('foundation')=='AM5_B650_B850_MATX_WIFI_4DIMM']
    routes.sort(key=lambda r:(int(r.get('self_build_effective_cost') or 10**9),int(r.get('tcwp') or 10**9)))
    recommended=routes[0] if routes else None; foundation_by_price=sorted(routes,key=lambda r:int(r.get('tcwp') or 10**9)); sweet=sorted([r for r in routes if r.get('performance_class')=='SWEET SPOT'],key=lambda r:int(r.get('tcwp') or 10**9)); complete=list(data.get('complete_pc_reference') or [])
    data.update({'self_build_ranked':routes,'recommended_self_build':recommended,'value_foundation_build':foundation_by_price[0] if foundation_by_price else recommended,'performance_step_up_build':sweet[0] if sweet else None,'buy_now':recommended,'ranked':routes+complete})
    data['component_optimizer_policy']={'version':'V19','method':'HARD_GATES_THEN_RATIONAL_PREMIUM_EFFECTIVE_COST','brand_bias':'NONE','formula':'effective_cost_dkk = market_price - capped_feature_value_dkk; lowest eligible effective cost wins','categories':CATEGORY_POLICY,'rule':'Every selected durable component must expose winner, runner-up, hard-gate result, price delta, feature-value delta and effective-cost delta.','retail_rule':'When a live retail snapshot exists, unverified retail candidates are excluded; no stale hardcoded-price fallback is allowed.'}
    data['retail_candidate_catalog']=RETAIL_CANDIDATES; data['model_version']='DBA-WOW-SELF-BUILD-FIRST-V19'; data['strategy_mode']='EXPLAINABLE_MULTI_CRITERIA_SELF_BUILD'; return data


def regression()->None:
    dummy={'components':[],'component_alternatives':{}}
    existed=RETAIL_SNAPSHOT.exists(); saved=RETAIL_SNAPSHOT.read_bytes() if existed else None
    if existed: RETAIL_SNAPSHOT.unlink()
    try:
        mb=choose('MOTHERBOARD',dummy); assert mb['winner'] and mb['winner']['sku']=='ASROCK_B850M_PRO_A_WIFI',mb; assert mb['runner_up'] is not None and 'effective advantage' in mb['reason']
        psu=choose('PSU',dummy); assert psu['winner'] and psu['winner']['sku']=='MSI_A850GL_PCIE5_II',psu
        bad={'name':'Laptop DDR5 SO-DIMM 32GB','price':100,'url':'x','source':'USED ASK','functional_defect':False,'capacity_gb':32,'desktop_ddr5':False}; ok,failures=hard_gate('RAM',bad); assert not ok and failures
    finally:
        if existed and saved is not None: RETAIL_SNAPSHOT.write_bytes(saved)


def main()->None:
    regression(); data=json.loads(OUT.read_text(encoding='utf-8')); data=finalize(data); OUT.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8'); rec=data.get('recommended_self_build') or {}; mb=((rec.get('component_choice_v19') or {}).get('MOTHERBOARD') or {}).get('winner') or {}; print(json.dumps({'model':data.get('model_version'),'recommended_tcwp':rec.get('tcwp'),'cpu':rec.get('cpu'),'gpu':rec.get('gpu'),'motherboard':mb.get('name'),'motherboard_price':mb.get('price')},ensure_ascii=False))


if __name__=='__main__': main()
