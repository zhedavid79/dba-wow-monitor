from __future__ import annotations

import math
import re
from copy import deepcopy

# Relative raster-performance proxy for the target 3840x1600 workload.
# RTX 2080 Super = 1.00. The proxy is deliberately capped in the value model;
# it is not claimed to be a WoW FPS table. WoW CPU sensitivity is handled separately.
GPU_SPECS = {
    'RX 5700 XT':  {'perf':0.84,'vram_gb':8, 'power_w':225},
    'RX 6600':     {'perf':0.70,'vram_gb':8, 'power_w':132},
    'RX 6600 XT':  {'perf':0.80,'vram_gb':8, 'power_w':160},
    'RX 6650 XT':  {'perf':0.85,'vram_gb':8, 'power_w':176},
    'RTX 2060':    {'perf':0.68,'vram_gb':6, 'power_w':160},
    'RTX 2060 Super':{'perf':0.82,'vram_gb':8,'power_w':175},
    'RTX 2070':    {'perf':0.84,'vram_gb':8, 'power_w':175},
    'RTX 2070 Super':{'perf':0.94,'vram_gb':8,'power_w':215},
    'RTX 2080':    {'perf':0.95,'vram_gb':8, 'power_w':215},
    'RTX 2080 Super':{'perf':1.00,'vram_gb':8,'power_w':250},
    'RTX 3060 Ti': {'perf':1.10,'vram_gb':8, 'power_w':200},
    'RTX 3070':    {'perf':1.20,'vram_gb':8, 'power_w':220},
    'RTX 3070 Ti': {'perf':1.27,'vram_gb':8, 'power_w':290},
    'RTX 3080':    {'perf':1.48,'vram_gb':10,'power_w':320},
    'RTX 4060':    {'perf':0.94,'vram_gb':8, 'power_w':115},
    'RTX 4060 Ti': {'perf':1.09,'vram_gb':8, 'power_w':160},
    'RX 6700 XT':  {'perf':1.10,'vram_gb':12,'power_w':230},
    'RX 6750 XT':  {'perf':1.17,'vram_gb':12,'power_w':250},
    'RX 6800':     {'perf':1.34,'vram_gb':16,'power_w':250},
    'RX 6800 XT':  {'perf':1.50,'vram_gb':16,'power_w':300},
    'RX 7600':     {'perf':0.92,'vram_gb':8, 'power_w':165},
}

# Exact board-partner dimensions from manufacturer specifications. A title must
# match the model signature; chip-only titles never inherit these dimensions.
# source_url is retained in result evidence so every VERIFIED fit is auditable.
EXACT_GPU_MODELS = [
    {
        'pattern': re.compile(r'\basus\b.*\bdual\b.*\brtx\s*2070\b.*\bevo\b.*\bv2\b', re.I),
        'model':'ASUS Dual RTX 2070 EVO V2','gpu':'RTX 2070','length_mm':242,'height_mm':130,'thickness_mm':53,'slots':2.5,
        'source_url':'https://www.asus.com/dk/motherboards-components/graphics-cards/dual/dual-rtx2070-8g-evo-v2/techspec/',
    },
    {
        'pattern': re.compile(r'\b(?:asus\s+)?rog\s+strix\b.*\brtx\s*2070\b.*\bo8g\b', re.I),
        'model':'ASUS ROG Strix RTX 2070 O8G','gpu':'RTX 2070','length_mm':305,'height_mm':131,'thickness_mm':49,'slots':2.5,
        'source_url':'https://www.asus.com/jp/news/rogf0yejyzi5cyka/',
    },
    {
        'pattern': re.compile(r'\brtx\s*2070\b.*\bventus\s+gp\b|\bventus\s+gp\b.*\brtx\s*2070\b', re.I),
        'model':'MSI RTX 2070 Ventus GP','gpu':'RTX 2070','length_mm':232,'height_mm':127,'thickness_mm':42,'slots':2.1,
        'source_url':'https://www.msi.com/Graphics-Card/GeForce-RTX-2070-VENTUS-GP/Specification',
    },
    {
        'pattern': re.compile(r'\b(?:gigabyte\s+)?(?:aou?rus)\s+master\b.*\brtx\s*3070\b|\brtx\s*3070\b.*\b(?:aou?rus)\s+master\b', re.I),
        'model':'Gigabyte AORUS RTX 3070 Master','gpu':'RTX 3070','length_mm':290,'height_mm':131,'thickness_mm':60,'slots':3.0,
        'source_url':'https://www.gigabyte.com/eu/Graphics-Card/GV-N3070AORUS-M-8GD-rev-20/sp',
    },
    {
        'pattern': re.compile(r'\bgigabyte\b.*\brtx\s*3070\b.*\bvision\b|\bvision\b.*\brtx\s*3070\b', re.I),
        'model':'Gigabyte RTX 3070 Vision OC','gpu':'RTX 3070','length_mm':286,'height_mm':115,'thickness_mm':51,'slots':2.5,
        'source_url':'https://www.gigabyte.com/us/Graphics-Card/GV-N3070VISION-OC-8GD-rev-10/sp',
    },
    {
        'pattern': re.compile(r'\bgigabyte\b.*\brx\s*6700\s*xt\b.*\bgaming\s+oc\b|\brx\s*6700\s*xt\b.*\bgigabyte\b.*\bgaming\s+oc\b', re.I),
        'model':'Gigabyte RX 6700 XT Gaming OC 12G','gpu':'RX 6700 XT','length_mm':281,'height_mm':115,'thickness_mm':49,'slots':2.5,
        'source_url':'https://www.gigabyte.com/dk/Graphics-Card/GV-R67XTGAMING-OC-12GD/sp',
    },
    {
        'pattern': re.compile(r'\basrock\b.*\bphantom\s+gaming\b.*\brx\s*6650\s*xt\b|\brx\s*6650\s*xt\b.*\basrock\b.*\bphantom\s+gaming\b', re.I),
        'model':'ASRock RX 6650 XT Phantom Gaming D','gpu':'RX 6650 XT','length_mm':305,'height_mm':131,'thickness_mm':48,'slots':2.4,
        'source_url':'https://pg.asrock.com/Graphics-Card/AMD/Radeon%20RX%206650%20XT%20Phantom%20Gaming%20D%208GB%20OC/index.asp',
    },
]

Z20_GPU_MAX_MM = 363
Z20_EXPANSION_SLOTS = 4
Z20_PREFERRED_ATX_PSU_MAX_MM = 140


def round50(value: float) -> int:
    return max(0, int(math.floor(value / 50.0) * 50))


def gpu_spec(model: str) -> dict:
    return deepcopy(GPU_SPECS.get(str(model or ''), {}))


def exact_model_evidence(title: str, gpu: str | None = None) -> dict | None:
    title = str(title or '')
    for row in EXACT_GPU_MODELS:
        if row['pattern'].search(title):
            if gpu and row.get('gpu') and row['gpu'] != gpu:
                continue
            return deepcopy({k:v for k,v in row.items() if k != 'pattern'})
    return None


def z20_fit(title: str, gpu: str | None, psu_length_mm: int | None = None) -> dict:
    evidence = exact_model_evidence(title, gpu)
    if evidence is None:
        return {
            'status':'UNKNOWN',
            'reason':'Exact board-partner GPU model/dimensions not proven from listing title.',
            'gpu_model_evidence':None,
            'psu_length_mm':psu_length_mm,
        }
    length = int(evidence['length_mm'])
    slots = float(evidence['slots'])
    if length > Z20_GPU_MAX_MM or slots > Z20_EXPANSION_SLOTS:
        status = 'NO'
        reason = f'Exact model is {length}mm / {slots:g} slots, exceeding Z20 limit.'
    elif psu_length_mm is not None and int(psu_length_mm) > Z20_PREFERRED_ATX_PSU_MAX_MM:
        status = 'LIKELY'
        reason = f'GPU dimensions fit, but ATX PSU is {psu_length_mm}mm (>140mm preferred), so combined clearance is not fully proven.'
    else:
        status = 'VERIFIED'
        reason = f'Exact model dimensions {length}x{evidence["height_mm"]}x{evidence["thickness_mm"]}mm fit the Z20 363mm / 4-slot envelope; PSU is within preferred length when known.'
    return {
        'status':status,
        'reason':reason,
        'gpu_model_evidence':evidence,
        'psu_length_mm':psu_length_mm,
    }


def gpu_utility_dkk(model: str) -> dict:
    s = gpu_spec(model)
    if not s:
        return {'known':False,'utility_dkk':0,'performance_value_dkk':0,'vram_value_dkk':0,'efficiency_value_dkk':0,'power_penalty_dkk':0}
    perf = min(float(s['perf']), 1.55)
    performance_value = round(perf * 1500)
    vram = int(s['vram_gb'])
    vram_value = 0 if vram <= 8 else 75 if vram <= 10 else 200 if vram <= 12 else 350
    power = int(s['power_w'])
    efficiency_value = 75 if power <= 200 else 25 if power <= 230 else 0
    power_penalty = max(0, power - 250)
    utility = performance_value + vram_value + efficiency_value - power_penalty
    return {
        'known':True,'perf_proxy_2080s_1_00':perf,'vram_gb':vram,'power_w':power,
        'performance_value_dkk':performance_value,'vram_value_dkk':vram_value,
        'efficiency_value_dkk':efficiency_value,'power_penalty_dkk':power_penalty,
        'utility_dkk':utility,
        'rule':'performance proxy capped at 1.55; VRAM and efficiency receive bounded value; >250W receives a small power penalty',
    }


def anchor_walkaway(model: str, anchor_model: str='RTX 2080 Super', anchor_ask: int=1600) -> int | None:
    u = gpu_utility_dkk(model); a = gpu_utility_dkk(anchor_model)
    if not u.get('known') or not a.get('known'):
        return None
    return round50(int(anchor_ask) + int(u['utility_dkk']) - int(a['utility_dkk']))


def bid_guidance(model: str, ask: int, anchor_model: str='RTX 2080 Super', anchor_ask: int=1600) -> dict:
    ask = int(ask or 0)
    walk = anchor_walkaway(model, anchor_model, anchor_ask)
    if ask <= 0 or walk is None:
        return {'first_bid':None,'target':None,'walk_away':None,'action':'NO_VALUE_MODEL'}
    first = min(ask, round50(min(ask * 0.85, walk * 0.82)))
    target = min(ask, round50(min(ask * 0.93, walk * 0.92)))
    if ask <= walk * 0.90: action='STRONG_BUY'
    elif ask <= walk * 0.98: action='BUY'
    elif ask <= walk * 1.05: action='FAIR'
    else: action='WAIT'
    return {
        'first_bid':first,'target':target,'walk_away':walk,'action':action,
        'anchor_model':anchor_model,'anchor_ask':anchor_ask,
        'rule':'First bid and target are negotiation levels; walk-away is value-based against the cheapest current RTX 2080 Super anchor, not a prediction of seller acceptance.',
    }


def route_gpu_intelligence(route: dict, anchor_ask: int=1600) -> dict:
    model = str(route.get('gpu') or '')
    comp = next((x for x in route.get('components') or [] if x.get('kind') == 'GPU'), {})
    psu = next((x for x in route.get('components') or [] if x.get('kind') == 'PSU'), {})
    ask = int(comp.get('price') or 0)
    title = str(comp.get('name') or '')
    utility = gpu_utility_dkk(model)
    fit = z20_fit(title, model, int(psu.get('length_mm')) if psu.get('length_mm') else None)
    bid = bid_guidance(model, ask, anchor_ask=anchor_ask)
    net_gpu_cost = ask - int(utility.get('utility_dkk') or 0) if utility.get('known') else ask
    return {
        'gpu':model,'listing_id':comp.get('listing_id'),'ask':ask,'url':comp.get('url'),
        'utility':utility,'net_gpu_cost_v20':net_gpu_cost,'z20_fit_v20':fit,'bid':bid,
    }


def regression() -> None:
    assert gpu_utility_dkk('RX 6800 XT')['utility_dkk'] > gpu_utility_dkk('RX 6700 XT')['utility_dkk'] > gpu_utility_dkk('RTX 2080 Super')['utility_dkk']
    assert bid_guidance('RX 6800 XT', 2500)['action'] in {'STRONG_BUY','BUY'}
    assert bid_guidance('RX 6700 XT', 2000)['action'] in {'BUY','FAIR'}
    fit = z20_fit('GIGABYTE RX 6700 XT GAMING OC 12 GB', 'RX 6700 XT', 140)
    assert fit['status'] == 'VERIFIED', fit
    unknown = z20_fit('RTX 2080 Super 8GB', 'RTX 2080 Super', 140)
    assert unknown['status'] == 'UNKNOWN', unknown


if __name__ == '__main__':
    regression()
    print('PASS V20 GPU MODEL')
