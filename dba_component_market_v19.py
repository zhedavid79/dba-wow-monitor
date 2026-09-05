from __future__ import annotations

from copy import deepcopy

import dba_component_optimizer_v19 as core

# Expanded current retail universe. Specs are explicit product facts; price is only
# a bootstrap value and is replaced by dba_retail_prices_v19.py in every V19 run.
EXTRA_RETAIL = {
    'MOTHERBOARD': [
        {
            'sku':'ASROCK_B850M_PRO_RS_WIFI','name':'ASRock B850M Pro RS WiFi','price':1067,
            'url':'https://prisjagt.dk/product.php?p=14363692','identity_aliases':['ASRock B850M Pro RS WiFi'],
            'source':'NEW RETAIL','socket':'AM5','form_factor':'mATX','ddr':'DDR5','dimm_slots':4,
            'wifi':'6E','lan_gbps':2.5,'m2_count':3,'pcie5_m2':True,'pcie5_x16':True,
            'power_tier':2,'drmos':True,'bios_flashback':True,'front_usb_c':True,
        },
        {
            'sku':'ASUS_TUF_B850M_PLUS_WIFI','name':'Asus TUF Gaming B850M-Plus WiFi','price':1170,
            'url':'https://prisjagt.dk/product.php?p=14022121','identity_aliases':['Asus TUF Gaming B850M-Plus WiFi'],
            'source':'NEW RETAIL','socket':'AM5','form_factor':'mATX','ddr':'DDR5','dimm_slots':4,
            'wifi':'6E','lan_gbps':2.5,'m2_count':3,'pcie5_m2':True,'pcie5_x16':True,
            'power_tier':4,'drmos':True,'bios_flashback':True,'front_usb_c':True,
        },
        {
            'sku':'ASUS_PRIME_B650M_A_WIFI_II','name':'Asus Prime B650M-A WiFi II','price':990,
            'url':'https://prisjagt.dk/product.php?p=10180194','identity_aliases':['Asus Prime B650M-A WiFi II'],
            'source':'NEW RETAIL','socket':'AM5','form_factor':'mATX','ddr':'DDR5','dimm_slots':4,
            'wifi':'6','lan_gbps':2.5,'m2_count':2,'pcie5_m2':True,'pcie5_x16':False,
            'power_tier':1,'drmos':False,'bios_flashback':True,'front_usb_c':True,
        },
        {
            'sku':'GIGABYTE_B650M_D3HP_AX','name':'Gigabyte B650M D3HP AX','price':951,
            'url':'https://prisjagt.dk/product.php?p=13534691','identity_aliases':['Gigabyte B650M D3HP AX'],
            'source':'NEW RETAIL','socket':'AM5','form_factor':'mATX','ddr':'DDR5','dimm_slots':4,
            'wifi':'6E','lan_gbps':2.5,'m2_count':2,'pcie5_m2':False,'pcie5_x16':False,
            'power_tier':1,'drmos':False,'bios_flashback':True,'front_usb_c':True,
        },
        {
            # Deliberately retained as a cheap hard-gate counterexample: price alone
            # cannot rescue a board with only two DIMM slots.
            'sku':'GIGABYTE_B650M_GAMING_WIFI6E','name':'Gigabyte B650M Gaming WIFI6E Micro ATX','price':939,
            'url':'https://prisjagt.dk/product.php?p=14840145','identity_aliases':['Gigabyte B650M Gaming WIFI6E Micro ATX'],
            'source':'NEW RETAIL','socket':'AM5','form_factor':'mATX','ddr':'DDR5','dimm_slots':2,
            'wifi':'6E','lan_gbps':2.5,'m2_count':2,'pcie5_m2':False,'pcie5_x16':False,
            'power_tier':1,'drmos':False,'bios_flashback':True,'front_usb_c':False,
        },
    ],
    'PSU': [
        {'sku':'MSI_A750GL_PCIE5','name':'MSI MAG A750GL PCIE5 750W','price':569,
         'url':'https://prisjagt.dk/product.php?p=11267596','identity_aliases':['MSI MAG A750GL PCIE5 750W'],
         'source':'NEW RETAIL','watt':750,'atx31':True,'modular':True,'length_mm':140,'gold':True},
        {'sku':'SEASONIC_FOCUS_GX750_ATX31','name':'Seasonic Focus GX 750W ATX 3.1','price':749,
         'url':'https://prisjagt.dk/product.php?p=13902592','identity_aliases':['Seasonic Focus GX 750W ATX 3.1'],
         'source':'NEW RETAIL','watt':750,'atx31':True,'modular':True,'length_mm':135,'gold':True},
        {'sku':'CORSAIR_RM850E_2025','name':'Corsair RM850e (2025) ATX 3.1 Gold 850W','price':919,
         'url':'https://prisjagt.dk/product.php?p=14366594','identity_aliases':['Corsair RM850e (2025) ATX 3.1 Gold 850W'],
         'source':'NEW RETAIL','watt':850,'atx31':True,'modular':True,'length_mm':140,'gold':True},
    ],
    'COOLER': [
        {'sku':'THERMALRIGHT_PA120_SE','name':'Thermalright Peerless Assassin 120 SE','price':275,
         'url':'https://prisjagt.dk/product.php?p=11485774','identity_aliases':['Thermalright Peerless Assassin 120 SE'],
         'source':'NEW RETAIL','am5':True,'height_mm':155,'cooling_tier':3},
        {'sku':'THERMALRIGHT_PS120_SE','name':'Thermalright Phantom Spirit 120 SE','price':319,
         'url':'https://prisjagt.dk/product.php?p=13067479','identity_aliases':['Thermalright Phantom Spirit 120 SE'],
         'source':'NEW RETAIL','am5':True,'height_mm':154,'cooling_tier':4},
        {'sku':'DEEPCOOL_AK400_ZERO_DARK','name':'Deepcool AK400 Zero Dark','price':233,
         'url':'https://prisjagt.dk/product.php?p=10192319','identity_aliases':['Deepcool AK400 Zero Dark'],
         'source':'NEW RETAIL','am5':True,'height_mm':155,'cooling_tier':1},
    ],
    'RAM': [
        {'sku':'CORSAIR_VENGEANCE_32_6000_CL30','name':'Corsair Vengeance DDR5 6000MHz 2x16GB CL30','price':3979,
         'url':'https://prisjagt.dk/product.php?p=13083153','identity_aliases':['Corsair Vengeance DDR5 6000MHz 2x16GB CMK32GX5M2B6000Z30'],
         'source':'NEW RETAIL','capacity_gb':32,'speed_mt':6000,'cl':30,'kit_dimms':2,'expo':True,'desktop_ddr5':True},
        {'sku':'KINGSTON_FURY_BEAST_32_6000_CL30','name':'Kingston Fury Beast Black DDR5 6000MHz 2x16GB','price':4501,
         'url':'https://prisjagt.dk/product.php?p=13438176','identity_aliases':['Kingston Fury Beast Black DDR5 6000MHz 2x16GB KF560C30BBEK2-32'],
         'source':'NEW RETAIL','capacity_gb':32,'speed_mt':6000,'cl':30,'kit_dimms':2,'expo':True,'desktop_ddr5':True},
    ],
    'STORAGE': [
        {'sku':'WD_BLUE_SN580_1TB','name':'WD Blue SN580 M.2 2280 1TB','price':859,
         'url':'https://prisjagt.dk/product.php?p=11916858','identity_aliases':['WD Blue SN580 M.2 2280 1TB'],
         'source':'NEW RETAIL','capacity_gb':1000,'nvme':True,'seq_read_mb':4150,'warranty_years':5,'tbw':600},
        {'sku':'LEXAR_NM790_1TB','name':'Lexar NM790 M.2 2280 PCIe Gen 4x4 NVMe SSD 1TB','price':1488,
         'url':'https://prisjagt.dk/product.php?p=12452771','identity_aliases':['Lexar NM790 M.2 2280 PCIe Gen 4x4 NVMe SSD 1TB'],
         'source':'NEW RETAIL','capacity_gb':1000,'nvme':True,'seq_read_mb':7400,'warranty_years':5,'tbw':0},
    ],
}

# Annotate the original three boards and baseline cooler/storage with comparable
# project-specific facts. power_tier is not a brand score: 1=adequate/basic,
# 2=robust, 3=robust-plus, 4=strong high-current design.
_BASE_MB_FACTS = {
    'ASROCK_B850M_PRO_A_WIFI': {'power_tier':2},
    'MSI_B850M_GAMING_PLUS_WIFI6E': {'power_tier':3},
    'GIGABYTE_B650M_GAMING_PLUS_WIFI': {'power_tier':1},
}
for row in core.RETAIL_CANDIDATES['MOTHERBOARD']:
    row.update(_BASE_MB_FACTS.get(row.get('sku'), {}))
for row in core.RETAIL_CANDIDATES['COOLER']:
    if row.get('sku') == 'ARCTIC_FREEZER_36_BLACK': row['cooling_tier'] = 2
for row in core.RETAIL_CANDIDATES['STORAGE']:
    if row.get('sku') == 'KINGSTON_NV3_1TB':
        row.update({'seq_read_mb':6000,'warranty_years':3,'tbw':320})
    elif row.get('sku') == 'PNY_CS1030_500':
        row.update({'seq_read_mb':2000,'warranty_years':0,'tbw':0})

for kind, rows in EXTRA_RETAIL.items():
    existing = {x.get('sku') for x in core.RETAIL_CANDIDATES.setdefault(kind, [])}
    core.RETAIL_CANDIDATES[kind].extend(deepcopy(x) for x in rows if x.get('sku') not in existing)

RETAIL_CANDIDATES = core.RETAIL_CANDIDATES
_BASE_HARD_GATE = core.hard_gate


def _wifi_rank(v) -> int:
    s = str(v or '').upper()
    return 4 if s == '7' else 3 if s == '6E' else 2 if s == '6' else 1 if s else 0


def feature_vector(kind: str, c: dict) -> tuple:
    if kind == 'MOTHERBOARD':
        return (
            int(c.get('power_tier') or 0), int(c.get('dimm_slots') or 0), int(c.get('m2_count') or 0),
            _wifi_rank(c.get('wifi')), float(c.get('lan_gbps') or 0), int(bool(c.get('pcie5_m2'))),
            int(bool(c.get('pcie5_x16'))), int(bool(c.get('bios_flashback'))), int(bool(c.get('front_usb_c'))),
        )
    if kind == 'PSU':
        return (int(c.get('watt') or 0), int(bool(c.get('gold'))), max(0, 200-int(c.get('length_mm') or 200)))
    if kind == 'COOLER':
        return (int(c.get('cooling_tier') or 0),)
    if kind == 'STORAGE':
        return (int(c.get('capacity_gb') or 0), int(c.get('seq_read_mb') or 0), int(c.get('warranty_years') or 0), int(c.get('tbw') or 0))
    return ()


def _dominates(kind: str, a: dict, b: dict) -> bool:
    if kind not in {'MOTHERBOARD','PSU','COOLER','STORAGE'}: return False
    if int(a.get('price') or 10**9) > int(b.get('price') or 10**9): return False
    av, bv = feature_vector(kind,a), feature_vector(kind,b)
    if not av or len(av) != len(bv): return False
    all_ge = all(x >= y for x,y in zip(av,bv))
    strict = int(a.get('price') or 10**9) < int(b.get('price') or 10**9) or any(x > y for x,y in zip(av,bv))
    return all_ge and strict


def feature_value(kind: str, c: dict):
    value=0; advantages=[]; tradeoffs=[]
    if kind == 'MOTHERBOARD':
        tier=int(c.get('power_tier') or 0)
        tier_value={0:0,1:0,2:75,3:100,4:125}.get(tier,125)
        if tier_value: value+=tier_value; advantages.append(f'power-delivery headroom tier {tier} (+{tier_value})')
        if c.get('drmos'): value+=25; advantages.append('DrMOS power stages (+25)')
        if c.get('pcie5_m2'): value+=50; advantages.append('PCIe 5.0 M.2 (+50)')
        if int(c.get('m2_count') or 0)>=3: value+=75; advantages.append('3 M.2 slots (+75)')
        if _wifi_rank(c.get('wifi'))>=3: value+=25; advantages.append(f"Wi-Fi {c.get('wifi')} (+25)")
        if _wifi_rank(c.get('wifi'))>=4: value+=25; advantages.append('Wi-Fi 7 incremental longevity (+25)')
        if c.get('pcie5_x16'): value+=25; advantages.append('PCIe 5.0 x16 (+25)')
        if c.get('bios_flashback'): value+=50; advantages.append('BIOS Flashback (+50)')
        if c.get('front_usb_c'): value+=25; advantages.append('front USB-C header (+25)')
        if tier<=1: tradeoffs.append('basic power-delivery headroom')
        if not c.get('pcie5_m2'): tradeoffs.append('no Gen5 M.2')
        if int(c.get('m2_count') or 0)<3: tradeoffs.append('only 2 M.2 slots')
    elif kind == 'PSU':
        if int(c.get('watt') or 0)>=850: value+=75; advantages.append('850W useful GPU headroom (+75)')
        if int(c.get('length_mm') or 999)<=140: value+=25; advantages.append('<=140mm Z20-friendly length (+25)')
        if c.get('gold'): value+=25; advantages.append('80 Plus Gold-class efficiency (+25)')
    elif kind == 'CASE':
        if c.get('exact_final_case'): value+=250; advantages.append('exact intended final Z20; avoids later replacement (+250)')
    elif kind == 'COOLER':
        tier=int(c.get('cooling_tier') or 0)
        if tier>1:
            premium=(tier-1)*50; value+=premium; advantages.append(f'cooling-structure tier {tier} (+{premium})')
        if tier<=1: tradeoffs.append('adequate single-tower class')
    elif kind == 'RAM':
        cap=int(c.get('capacity_gb') or 0)
        if cap>=32: value+=600; advantages.append('32GB long-term target (+600)')
        else: value-=350; tradeoffs.append('16GB bridge replacement penalty (+350 effective cost)')
        if int(c.get('speed_mt') or 0)>=6000: value+=100; advantages.append('DDR5-6000 target speed (+100)')
        if c.get('expo'): value+=40; advantages.append('AMD EXPO (+40)')
        cl=c.get('cl')
        if cl and int(cl)<=32: value+=75; advantages.append('<=CL32 (+75)')
        elif cl and int(cl)<=38: value+=30; advantages.append('<=CL38 (+30)')
        if int(c.get('kit_dimms') or 0)==2: value+=30; advantages.append('2-DIMM kit (+30)')
    elif kind == 'STORAGE':
        if int(c.get('capacity_gb') or 0)>=1000: value+=250; advantages.append('1TB comfort capacity (+250)')
        wy=int(c.get('warranty_years') or 0)
        if wy>=5: value+=75; advantages.append('5-year warranty (+75)')
        elif wy>=3: value+=25; advantages.append('3-year warranty (+25)')
        tbw=int(c.get('tbw') or 0)
        if tbw>=600: value+=75; advantages.append('>=600 TBW (+75)')
        elif tbw>=300: value+=25; advantages.append('>=300 TBW (+25)')
        read=int(c.get('seq_read_mb') or 0)
        if read>=7000: value+=50; advantages.append('>=7GB/s sequential class (+50)')
        elif read>=5000: value+=25; advantages.append('>=5GB/s sequential class (+25)')
    return value,advantages,tradeoffs


def evaluate(kind: str, candidates: list[dict]) -> list[dict]:
    rows=[]
    for c in candidates:
        x=deepcopy(c); ok,failures=_BASE_HARD_GATE(kind,x); fv,adv,trade=feature_value(kind,x)
        x.update({'eligible':ok,'hard_gate_failures':failures,'feature_value_dkk':fv,
                  'effective_cost_dkk':int(x.get('price') or 10**9)-fv if ok else 10**9,
                  'advantages':adv,'tradeoffs':trade,'dominated':False,'dominated_by':None})
        rows.append(x)
    eligible=[x for x in rows if x['eligible']]
    for b in eligible:
        dominators=[a for a in eligible if a is not b and _dominates(kind,a,b)]
        if dominators:
            dominators.sort(key=lambda a:(int(a.get('price') or 10**9),-sum(feature_vector(kind,a))))
            b['dominated']=True; b['dominated_by']=dominators[0].get('name')
    rows.sort(key=lambda x:(not x['eligible'],bool(x.get('dominated')),int(x['effective_cost_dkk']),int(x.get('price') or 10**9)))
    return rows


def choose(kind: str, route: dict) -> dict:
    candidates=core._snapshot_candidates(kind)
    if kind=='RAM': candidates += core.used_candidates(route,kind)
    evaluated=evaluate(kind,candidates)
    frontier=[x for x in evaluated if x['eligible'] and not x.get('dominated')]
    winner=frontier[0] if frontier else None; runner=frontier[1] if len(frontier)>1 else None
    reason='No eligible non-dominated candidate.'
    if winner:
        reason=f"Pareto-frontier winner: {winner['price']} kr - {winner['feature_value_dkk']} kr capped justified feature value = {winner['effective_cost_dkk']} kr effective cost."
        if runner:
            pd=int(winner['price'])-int(runner['price']); fd=int(winner['feature_value_dkk'])-int(runner['feature_value_dkk']); ed=int(runner['effective_cost_dkk'])-int(winner['effective_cost_dkk'])
            reason += f" Runner-up delta: price {pd:+d} kr, feature-value {fd:+d} kr, effective advantage {ed} kr."
    return {'kind':kind,'policy':core.CATEGORY_POLICY[kind],'winner':winner,'runner_up':runner,
            'evaluated':evaluated,'pareto_frontier_count':len(frontier),'reason':reason}


# Activate the expanded market logic inside the core optimizer.
core.feature_value=feature_value
core.evaluate=evaluate
core.choose=choose

MIN_COVERAGE={'MOTHERBOARD':6,'PSU':4,'COOLER':3,'RAM':3,'STORAGE':3,'CASE':1}


def market_coverage(route: dict) -> dict:
    cats={}; passed=True
    for kind,minimum in MIN_COVERAGE.items():
        candidates=core._snapshot_candidates(kind)
        if kind=='RAM': candidates += core.used_candidates(route,kind)
        ev=evaluate(kind,candidates)
        eligible=sum(1 for x in ev if x.get('eligible'))
        non_dominated=sum(1 for x in ev if x.get('eligible') and not x.get('dominated'))
        ok=eligible>=minimum
        cats[kind]={'minimum':minimum,'eligible':eligible,'non_dominated':non_dominated,'passed':ok}
        passed = passed and ok
    return {'passed':passed,'categories':cats,'rule':'V19 cannot be authoritative when candidate coverage is below category minimums.'}


def finalize(data: dict) -> dict:
    out=core.finalize(data)
    rec=out.get('recommended_self_build') or {}
    coverage=market_coverage(rec)
    out['component_market_coverage_v19']=coverage
    out['component_optimizer_policy']['pareto_rule']='A more expensive candidate cannot win if a cheaper candidate is at least as good on every project-relevant feature and strictly better on price or one feature.'
    out['component_optimizer_policy']['chipset_label_premium']='NONE; B850/B650 labels carry no intrinsic score. Only concrete features matter.'
    out['component_optimizer_policy']['coverage_minimums']=MIN_COVERAGE
    return out


def regression() -> None:
    # Temporarily suppress any persisted live snapshot so formula/dominance regression
    # is deterministic; live evidence is tested separately by the smoke workflow.
    existed=core.RETAIL_SNAPSHOT.exists(); saved=core.RETAIL_SNAPSHOT.read_bytes() if existed else None
    if existed: core.RETAIL_SNAPSHOT.unlink()
    try:
        dummy={'components':[],'component_alternatives':{}}
        mb=choose('MOTHERBOARD',dummy)
        assert mb['winner']['sku']=='ASROCK_B850M_PRO_A_WIFI',mb
        excluded=next(x for x in mb['evaluated'] if x.get('sku')=='GIGABYTE_B650M_GAMING_WIFI6E')
        assert excluded['eligible'] is False and '<4 DIMM' in excluded['hard_gate_failures'],excluded
        dominated=next(x for x in mb['evaluated'] if x.get('sku')=='GIGABYTE_B650M_GAMING_PLUS_WIFI')
        assert dominated['dominated'] is True and dominated['dominated_by'],dominated
        assert 'B850 chipset' not in ' '.join(mb['winner'].get('advantages') or [])
        psu=choose('PSU',dummy); assert psu['winner']['sku']=='MSI_A850GL_PCIE5_II',psu
        cooler=choose('COOLER',dummy); assert cooler['winner']['sku']=='ARCTIC_FREEZER_36_BLACK',cooler
        storage=choose('STORAGE',dummy); assert storage['winner']['sku']=='WD_BLUE_SN580_1TB',storage
    finally:
        if existed and saved is not None: core.RETAIL_SNAPSHOT.write_bytes(saved)


# Re-export the interface consumed by verifier/workflow.
OUT=core.OUT
RETAIL_SNAPSHOT=core.RETAIL_SNAPSHOT
CATEGORY_POLICY=core.CATEGORY_POLICY
