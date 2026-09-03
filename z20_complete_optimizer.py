from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

MAIN = Path("results/wow_a3_latest.json")
PARTS = Path("results/z20_parts_latest.json")
DONORS = Path("results/z20_donors_latest.json")
REPORT = Path("results/wow_a3_report.md")

# Current retail baselines verified on 2026-09-03. They expire after 7 days so a stale
# web price can never silently create a READY_TO_BUY recommendation.
RETAIL = {
    "case": {"name":"Jonsbo Z20 Mesh White","price":751,"url":"https://www.proshop.dk/Kabinet/Jonsbo-Z20-Mesh-Kabinet-Minitower-Hvid/3407428","verified_at":"2026-09-03T22:55:00+02:00","fit":"PROVEN"},
    "psu": {"name":"Corsair RM650e (2025) 650W ATX 3.1","price":642,"url":"https://www.proshop.dk/Stroemforsyning/Corsair-RMe-Series-RM650e-2025-Stroemforsyning-650-Watt-120-mm-ATX-31-80-Plus-Gold-certified/3324406","verified_at":"2026-09-03T22:55:00+02:00","length_mm":140,"fit":"PROVEN","manufacturer_spec":"https://www.corsair.com/eu/en/p/psu/CP-9020302-EU/rme-series-rm650e-fully-modular-low-noise-atx-power-supply-eu-cp-9020302-eu"},
    "ssd": {"name":"Kingston NV3 1TB M.2 2280 PCIe 4.0","price":1269,"url":"https://www.proshop.dk/SSD/Kingston-NV3-SSD-1TB-PCIe-40-M2-2280/3284682","verified_at":"2026-09-03T22:55:00+02:00","fit":"PROVEN"},
    "cpu": {"name":"AMD Ryzen 5 7500F","price":1099,"url":"https://www.proshop.dk/CPU/AMD-Ryzen-5-7500F-Tray-CPU-6-kerner-37-GHz-AMD-AM5-Bulk-ingen-koeler/3195178","verified_at":"2026-09-03T22:55:00+02:00","cpu":"Ryzen 5 7500F","cpu_score":94,"socket":"AM5"},
    "cooler": {"name":"Arctic Freezer 36 Black","price":175,"url":"https://www.proshop.dk/CPU-Koeler/Arctic-Freezer-36-Black-CPU-Luftkoeler/3238363","verified_at":"2026-09-03T22:55:00+02:00","height_mm":159,"fit":"PROVEN"},
    "board_best": {"name":"ASRock B650M Pro RS","price":1038,"url":"https://www.proshop.dk/Bundkort/ASRock-B650M-PRO-RS-Bundkort-AMD-B650-AMD-AM5-DDR5-RAM-Micro-ATX/3183007","verified_at":"2026-09-03T22:55:00+02:00","form_factor":"Micro-ATX","dimm_slots":4,"m2_slots":3,"upgradeability":"EXCELLENT"},
    "board_budget": {"name":"ASUS PRIME B650M-R","price":599,"url":"https://www.proshop.dk/Bundkort/ASUS-PRIME-B650M-R-Bundkort-AMD-B650-AMD-AM5-DDR5-RAM-Micro-ATX/3236159","verified_at":"2026-09-03T22:55:00+02:00","form_factor":"Micro-ATX","dimm_slots":2,"m2_slots":2,"upgradeability":"EXCELLENT"},
    "ram_fallback": {"name":"G.Skill Flare X5 DDR5-5600 16GB (2x8GB)","price":2090,"url":"https://www.proshop.dk/RAM/GSkill-Flare-X5-DDR5-5600-16GB-CL36-Dual-Channel-2-pcs-AMD-EXPO/3431862","verified_at":"2026-09-03T22:55:00+02:00","memory":"DDR5","capacity_gb":16,"desktop":True},
}

GPU_FIT = [
    (re.compile(r"msi.*rtx\s*3060\s*ti.*ventus\s*2x|rtx\s*3060\s*ti.*ventus\s*2x", re.I), {"model":"MSI RTX 3060 Ti Ventus 2X","length_mm":235,"thickness_mm":52,"psu_w":600,"source":"https://www.msi.com/Graphics-Card/GeForce-RTX-3060-Ti-VENTUS-2X-8G-OCV1-LHR/Specification"}),
    (re.compile(r"(?:gigabyte|aorus).*rtx\s*3070.*(?:aorus\s+master|master)|rtx\s*3070.*aorus\s+master", re.I), {"model":"Gigabyte AORUS RTX 3070 Master","length_mm":290,"thickness_mm":60,"psu_w":650,"source":"https://www.gigabyte.com/eu/Graphics-Card/GV-N3070AORUS-M-8GD-rev-10-11/sp"}),
]
UPGRADE = {"EXCELLENT":4,"GOOD":3,"LIMITED":2,"POOR":1,"UNVERIFIED":0}


def fresh() -> bool:
    now = datetime.now(timezone.utc)
    return all((now-datetime.fromisoformat(v["verified_at"]).astimezone(timezone.utc)).days <= 7 for v in RETAIL.values())


def retail(kind: str, key: str) -> dict:
    x=RETAIL[key]
    return {"kind":kind,"source":"NEW_RETAIL","name":x["name"],"price":x["price"],"url":x["url"],"verified_at":x["verified_at"]}


def used(kind: str, r: dict) -> dict:
    return {"kind":kind,"source":"DBA_USED_LIVE","name":r["title"],"price":r["ask_t1"],"url":r["url"],"listing_id":r["listing_id"]}


def ram_meta(title: str) -> tuple[str|None,int|None]:
    t=title.lower(); mem="DDR5" if "ddr5" in t else "DDR4" if "ddr4" in t else None
    nums=[]
    for a,b in re.findall(r"\b(2|4)\s*x\s*(8|16|32)\s*gb\b",t): nums.append(int(a)*int(b))
    nums += [int(x) for x in re.findall(r"\b(8|16|32|64)\s*gb\b",t)]
    return mem,max(nums) if nums else None


def compatible_ram(parts:list[dict], memory="DDR5") -> list[dict]:
    out=[]
    for r in parts:
        if r.get("kind")!="RAM" or r.get("condition")=="DEFECT_DISCLOSED" or r.get("ram_compatibility")!="DESKTOP_COMPATIBLE": continue
        mem,gb=ram_meta(r.get("title", ""))
        if mem==memory and gb and gb>=16: out.append(r)
    return sorted(out,key=lambda r:(r["ask_t1"], -(ram_meta(r["title"])[1] or 0)))


def exact_gpu(r:dict) -> dict:
    for pat,spec in GPU_FIT:
        if pat.search(r.get("title", "")):
            return {"status":"PROVEN_FIT",**spec}
    return {"status":"UNVERIFIED_SKU"}


def platform_memory(r:dict) -> str|None:
    t=r.get("title","").lower()
    if any(x in t for x in ("b650","a620","x670","am5")): return "DDR5"
    if any(x in t for x in ("b550","b450","x570","b560","h510")): return "DDR4"
    if any(x in t for x in ("b660","b760","z690","z790")):
        if "ddr4" in t:return "DDR4"
        if "ddr5" in t:return "DDR5"
    return None


def target_status(cpu_score:int,gpu_score:int)->str:
    if cpu_score>=90 and gpu_score>=66:return "STRONG_3840x1600_75HZ_TARGET"
    if cpu_score>=76 and gpu_score>=60:return "SUFFICIENT_3840x1600_75HZ_TARGET"
    return "MARGINAL"


def finalize(route:str,components:list[dict],cpu:str,cpu_score:int,gpu:str,gpu_score:int,upgradeability:str,gpu_fit:dict,notes:list[str],board_fit="PROVEN") -> dict:
    total=sum(int(x["price"]) for x in components)
    missing=[]
    if board_fit!="PROVEN":missing.append("motherboard Z20 fit")
    if gpu_fit.get("status")!="PROVEN_FIT":missing.append("exact GPU SKU dimensions")
    if not fresh():missing.append("refresh retail prices")
    perf=target_status(cpu_score,gpu_score)
    if perf=="MARGINAL":missing.append("performance target")
    status="READY_TO_BUY" if not missing and UPGRADE.get(upgradeability,0)>=3 else "NEEDS_VERIFICATION"
    utility=round((0.48*min(cpu_score,110)+0.42*min(gpu_score,75)+2.5*UPGRADE.get(upgradeability,0)),2)
    return {"route":route,"status":status,"total_price":total,"cpu":cpu,"cpu_score":cpu_score,"gpu":gpu,"gpu_score":gpu_score,"performance":perf,"upgradeability":upgradeability,"z20_fit":"PROVEN" if not missing else "PARTIAL","gpu_fit":gpu_fit,"missing_evidence":missing,"notes":notes,"utility":utility,"components":components}


def new_am5_builds(parts:list[dict],gpus:list[dict])->list[dict]:
    rams=compatible_ram(parts,"DDR5")
    ram_choices=rams[:3] if rams else []
    # Always preserve a complete new fallback, despite the unusually high current DDR5 retail price.
    ram_entries=[("USED",r) for r in ram_choices]+[("NEW",None)]
    builds=[]
    for board_key,route in (("board_best","NEW_AM5_LONG_TERM"),("board_budget","NEW_AM5_BUDGET")):
        for gpu in gpus[:20]:
            gf=exact_gpu(gpu)
            for ram_source,rr in ram_entries:
                comps=[retail("MOTHERBOARD",board_key),retail("CPU","cpu"),retail("COOLER","cooler")]
                comps.append(used("RAM",rr) if rr else retail("RAM","ram_fallback"))
                comps += [used("GPU",gpu),retail("CASE","case"),retail("PSU","psu"),retail("SSD","ssd")]
                notes=["AM5 foundation; CPU can be upgraded later without replacing the platform."]
                if board_key=="board_best":notes.append("4 DIMM slots and 3 M.2 slots make this the preferred long-term foundation.")
                else:notes.append("Cheapest current B650 mATX foundation; only 2 DIMM slots, so lower expansion headroom.")
                builds.append(finalize(route,comps,RETAIL["cpu"]["cpu"],RETAIL["cpu"]["cpu_score"],gpu["gpu"],gpu["gpu_score"],"EXCELLENT",gf,notes))
    return builds


def used_bundle_builds(parts:list[dict],gpus:list[dict])->list[dict]:
    builds=[]; rams_by={"DDR4":compatible_ram(parts,"DDR4"),"DDR5":compatible_ram(parts,"DDR5")}
    platforms=[p for p in parts if p.get("kind")=="PLATFORM_BUNDLE" and p.get("z20_fit")=="COMPATIBLE" and p.get("condition")!="DEFECT_DISCLOSED" and UPGRADE.get(p.get("upgradeability"),0)>=3]
    for p in platforms[:15]:
        mem=platform_memory(p)
        if not mem:continue
        # If RAM capacity/type is explicitly in bundle title, no extra DIMM is needed.
        p_mem,p_gb=ram_meta(p.get("title","")); has_ram=p_gb is not None and p_gb>=16 and (p_mem is None or p_mem==mem)
        ram_options=[None] if has_ram else rams_by[mem][:2]
        if not ram_options:continue
        for gpu in gpus[:15]:
            for rr in ram_options:
                comps=[used("PLATFORM_BUNDLE",p)]
                if rr:comps.append(used("RAM",rr))
                comps += [used("GPU",gpu),retail("CASE","case"),retail("PSU","psu"),retail("SSD","ssd")]
                builds.append(finalize("USED_PLATFORM_MIX",comps,p["cpu"],p["cpu_score"],gpu["gpu"],gpu["gpu_score"],p["upgradeability"],exact_gpu(gpu),["Motherboard form factor is title-proven mATX/ITX."]))
    return builds


def donor_builds(donors:list[dict])->list[dict]:
    builds=[]
    for d in donors:
        if d.get("condition")=="DEFECT_DISCLOSED" or d.get("motherboard_fit")!="COMPATIBLE" or UPGRADE.get(d.get("upgradeability"),0)<3:continue
        if not d.get("desktop_ram_evidence"):continue
        gf=d.get("gpu_sku") or {"status":"UNVERIFIED"}
        gf={"status":"PROVEN_FIT",**{k:v for k,v in gf.items() if k!="status"}} if gf.get("status")=="PROVEN" else {"status":"UNVERIFIED_SKU"}
        # Donor price covers reusable board/CPU/RAM/GPU. Use known-new PSU/SSD/cooler/case to remove
        # unknown age/fit risk from those parts. This is intentionally conservative.
        comps=[{"kind":"DONOR_CORE","source":"DBA_USED_LIVE","name":d["title"],"price":d["ask_t1"],"url":d["url"],"listing_id":d["listing_id"]},retail("COOLER","cooler"),retail("CASE","case"),retail("PSU","psu"),retail("SSD","ssd")]
        builds.append(finalize("USED_COMPLETE_PC_DONOR",comps,d["cpu"],d["cpu_score"],d["gpu"],d["gpu_score"],d["upgradeability"],gf,["Donor core reuses motherboard, CPU, RAM and GPU only; new PSU/SSD/cooler reduce hidden-condition risk."]))
    return builds


def main()->None:
    d=json.loads(MAIN.read_text(encoding="utf-8")); p=json.loads(PARTS.read_text(encoding="utf-8")); q=json.loads(DONORS.read_text(encoding="utf-8"))
    parts=p.get("opportunities") or []
    gpus=[r for r in parts if r.get("kind")=="GPU" and r.get("condition")!="DEFECT_DISCLOSED" and int(r.get("gpu_score") or 0)>=60]
    all_builds=new_am5_builds(parts,gpus)+used_bundle_builds(parts,gpus)+donor_builds(q.get("donors") or [])
    # dedupe and rank READY first, then value-adjusted utility. Long-term AM5 gets natural benefit through upgrade score.
    seen=set(); builds=[]
    for b in all_builds:
        key=tuple((x["kind"],x.get("listing_id") or x["name"]) for x in b["components"])
        if key in seen:continue
        seen.add(key); builds.append(b)
    builds.sort(key=lambda b:(b["status"]!="READY_TO_BUY",-(b["utility"]/max(b["total_price"],1)),b["total_price"]))
    d["model_version"]="DBA-WOW-Z20-COMPLETE-SYSTEM-V13"
    d["complete_system_optimizer"]={"policy":"Compare whole used donors, mixed used/new systems and new upgradeable foundations. READY_TO_BUY requires live DBA T1 evidence, proven mATX/ITX board fit, exact GPU SKU fit, non-defective used parts, adequate 140mm RM650e PSU, 159mm cooler and fresh retail baselines.","retail_baselines":RETAIL,"retail_fresh":fresh(),"ready_count":sum(b["status"]=="READY_TO_BUY" for b in builds),"builds":builds[:50],"donor_scan":q}
    MAIN.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding="utf-8")

    lines=["# DBA WoW / Jonsbo Z20 — COMPLETE SYSTEM OPTIMIZER V13","",f"Generated: {d.get('generated_at')}","Target: optimal complete Z20 computer for WoW Classic/progression at 3840×1600 / up to 75 Hz, balancing total cost, proven physical fit and future upgrades.","","## Recommended complete configurations","","| # | Status | Route | Total | CPU | GPU | Upgrade | Target | Components |","|---:|---|---|---:|---|---|---|---|---|"]
    for i,b in enumerate(builds[:10],1):
        comps="; ".join(f"[{x['name']}]({x['url']}) {x['price']} kr." for x in b["components"])
        lines.append(f"| {i} | {b['status']} | {b['route']} | {b['total_price']} kr. | {b['cpu']} | {b['gpu']} | {b['upgradeability']} | {b['performance']} | {comps} |")
    if not builds:lines.append("| - | NO VALID COMPLETE CONFIGURATION | - | - | - | - | - | - | Current live evidence does not yet cover a complete safe build. |")
    lines += ["","## Unresolved complete-PC donor leads","","| ASK | CPU | GPU | Board fit | Upgrade | GPU SKU | DBA |","|---:|---|---|---|---|---|---|"]
    for x in (q.get("donors") or [])[:15]:
        lines.append(f"| {x['ask_t1']} kr. | {x['cpu']} | {x['gpu']} | {x['motherboard_fit']} | {x['upgradeability']} | {x['gpu_sku'].get('status')} | [{x['title']}]({x['url']}) |")
    REPORT.write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps({"model":d["model_version"],"builds":len(builds),"ready":d["complete_system_optimizer"]["ready_count"]}))

if __name__=="__main__":main()
