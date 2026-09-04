from __future__ import annotations

import json
import re
from pathlib import Path

import dba_browser_v2 as v2
from z20_complete_optimizer import RETAIL, fresh

MAIN = Path("results/wow_a3_latest.json")
PARTS = Path("results/z20_parts_latest.json")
DONORS = Path("results/z20_donors_latest.json")
OUT = Path("results/wow_strategy_latest.json")

UPGRADE_GRADE = {"EXCELLENT":"A", "GOOD":"B", "LIMITED":"C", "POOR":"D", "UNVERIFIED":"C", "NOT_APPLICABLE":"C"}
GRADE_NUM = {"A":4,"B":3,"C":2,"D":1}


def pclass(cpu_score:int, gpu_score:int) -> str:
    return v2.performance_class(gpu_score, cpu_score)


def used_component(kind:str, row:dict) -> dict:
    return {"kind":kind,"source":"USED ASK","name":row.get("title"),"price":int(row.get("ask_t1")),"url":row.get("url"),"listing_id":str(row.get("listing_id"))}


def new_component(kind:str, key:str) -> dict:
    x=RETAIL[key]
    return {"kind":kind,"source":"NEW RETAIL","name":x["name"],"price":int(x["price"]),"url":x["url"],"verified_at":x["verified_at"]}


def complete_route(row:dict) -> dict:
    intel=row.get("listing_intelligence") or {}
    up=(intel.get("upgradeability") or {}).get("class") or "UNVERIFIED"
    fit=(intel.get("motherboard_z20_fit") or {}).get("value") or "UNVERIFIED"
    fit_map={"COMPATIBLE":"VERIFIED","INCOMPATIBLE":"NO","UNVERIFIED":"UNKNOWN"}
    return {
        "route":"COMPLETE_USED_PC","label":row.get("title"),"tcwp":int(row["ask_t1"]),
        "cpu":row.get("cpu"),"cpu_score":int(row.get("cpu_score") or 0),"gpu":row.get("gpu"),"gpu_score":int(row.get("gpu_score") or 0),
        "performance_class":row.get("performance_class"),"upgradeability":UPGRADE_GRADE.get(up,"C"),"z20_fit":fit_map.get(fit,"UNKNOWN"),
        "components":[used_component("COMPLETE_PC",row)],"rationale":"Complete, live-verified used PC; TCWP equals T1 ASK.",
    }


def ram_meta(title:str):
    t=title.lower(); mem="DDR5" if "ddr5" in t else "DDR4" if "ddr4" in t else None
    nums=[]
    for a,b in re.findall(r"\b(2|4)\s*x\s*(8|16|32)\s*gb\b",t): nums.append(int(a)*int(b))
    nums += [int(x) for x in re.findall(r"\b(8|16|32|64)\s*gb\b",t)]
    return mem,max(nums) if nums else None


def platform_memory(p:dict):
    t=(p.get("title") or "").lower()
    if any(x in t for x in ("b650","a620","x670","am5")): return "DDR5"
    if any(x in t for x in ("b550","b450","x570","b560","h510")): return "DDR4"
    if any(x in t for x in ("b660","b760","z690","z790")):
        if "ddr4" in t:return "DDR4"
        if "ddr5" in t:return "DDR5"
    return None


def socket_for(p:dict):
    t=(p.get("title") or "").lower()
    if any(x in t for x in ("b650","a620","x670","am5")): return "AM5"
    if any(x in t for x in ("b550","b450","x570","am4")) or "ryzen" in t:return "AM4"
    if any(x in t for x in ("b660","b760","z690","z790","lga1700")) or re.search(r"i[3579][- ]?1[234]\d{3}",t): return "LGA1700"
    if any(x in t for x in ("b560","h510","lga1200")): return "LGA1200"
    return None


def cheapest(rows, kind, pred=lambda r: True):
    xs=[r for r in rows if r.get("kind")==kind and pred(r)]
    return min(xs,key=lambda r:int(r.get("ask_t1") or 10**9),default=None)


def build_route(route:str, components:list[dict], platform:dict, gpu:dict, z20_fit:str, rationale:str):
    tcwp=sum(int(x["price"]) for x in components)
    grade=UPGRADE_GRADE.get(platform.get("upgradeability") or "UNVERIFIED","C")
    return {
        "route":route,"label":f"{platform.get('cpu')} + {gpu.get('gpu')}","tcwp":tcwp,
        "cpu":platform.get("cpu"),"cpu_score":int(platform.get("cpu_score") or 0),"gpu":gpu.get("gpu"),"gpu_score":int(gpu.get("gpu_score") or 0),
        "performance_class":pclass(int(platform.get("cpu_score") or 0),int(gpu.get("gpu_score") or 0)),
        "upgradeability":grade,"z20_fit":z20_fit,"components":components,"rationale":rationale,
    }


def pure_used_builds(parts:list[dict]) -> list[dict]:
    out=[]
    platforms=[p for p in parts if p.get("kind")=="PLATFORM_BUNDLE" and p.get("z20_fit")=="COMPATIBLE" and p.get("upgradeability") in {"GOOD","EXCELLENT"}]
    gpus=sorted([g for g in parts if g.get("kind")=="GPU" and int(g.get("gpu_score") or 0)>=60],key=lambda x:int(x["ask_t1"]))[:8]
    case=cheapest(parts,"CASE")
    storage=cheapest(parts,"STORAGE")
    psu=cheapest(parts,"PSU",lambda r: bool(re.search(r"\b(?:650|700|750|800|850)\s*w",r.get("title","").lower())))
    for p in sorted(platforms,key=lambda x:int(x["ask_t1"]))[:8]:
        mem=platform_memory(p); _,gb=ram_meta(p.get("title","")); ram=None if gb and gb>=16 else cheapest(parts,"RAM",lambda r: r.get("ram_compatibility")=="DESKTOP_COMPATIBLE" and ram_meta(r.get("title",""))[0]==mem and (ram_meta(r.get("title",""))[1] or 0)>=16)
        sock=socket_for(p); cooler=cheapest(parts,"COOLER",lambda r: sock and sock.lower() in r.get("title","").lower())
        if not all([case,storage,psu,cooler]) or (ram is None and not (gb and gb>=16)): continue
        for g in gpus:
            comps=[used_component("PLATFORM_BUNDLE",p),used_component("GPU",g),used_component("CASE",case),used_component("PSU",psu),used_component("STORAGE",storage),used_component("COOLER",cooler)]
            if ram: comps.append(used_component("RAM",ram))
            out.append(build_route("USED_BUILD",comps,p,g,"LIKELY","All required parts are live-verified USED ASK; Z20-family fit is title-proven for platform/case, exact GPU clearance remains a manual check."))
    return out


def hybrid_builds(parts:list[dict]) -> list[dict]:
    out=[]
    platforms=[p for p in parts if p.get("kind")=="PLATFORM_BUNDLE" and p.get("z20_fit")=="COMPATIBLE" and p.get("upgradeability") in {"GOOD","EXCELLENT"}]
    gpus=sorted([g for g in parts if g.get("kind")=="GPU" and int(g.get("gpu_score") or 0)>=60],key=lambda x:int(x["ask_t1"]))[:10]
    for p in sorted(platforms,key=lambda x:int(x["ask_t1"]))[:10]:
        mem=platform_memory(p); _,gb=ram_meta(p.get("title","")); ram=None if gb and gb>=16 else cheapest(parts,"RAM",lambda r: r.get("ram_compatibility")=="DESKTOP_COMPATIBLE" and ram_meta(r.get("title",""))[0]==mem and (ram_meta(r.get("title",""))[1] or 0)>=16)
        if ram is None and not (gb and gb>=16): continue
        sock=socket_for(p)
        for g in gpus:
            comps=[used_component("PLATFORM_BUNDLE",p),used_component("GPU",g),new_component("CASE","case"),new_component("PSU","psu"),new_component("STORAGE","ssd")]
            if ram: comps.append(used_component("RAM",ram))
            # Retail cooler is socket-universal for the intended AM4/AM5/LGA1700 routes.
            comps.append(new_component("COOLER","cooler"))
            out.append(build_route("HYBRID_USED_NEW",comps,p,g,"LIKELY",f"Used value concentrated in platform/GPU; new case/PSU/SSD/cooler reduce low-value used hunting and improve warranty/fit. Socket={sock or 'UNKNOWN'}."))
    return out


def donor_upgrade_routes(donors:list[dict]) -> list[dict]:
    out=[]
    for d in donors:
        if not isinstance(d.get("ask_t1"),int): continue
        if int(d.get("gpu_score") or 0)<50 or int(d.get("cpu_score") or 0)<50: continue
        comps=[{"kind":"USED_PC_CORE","source":"USED ASK","name":d.get("title"),"price":d["ask_t1"],"url":d.get("url"),"listing_id":str(d.get("listing_id"))}]
        # This route keeps the complete machine usable first; upgrades are optional later, so TCWP is the live PC ASK.
        grade=UPGRADE_GRADE.get(d.get("upgradeability") or "UNVERIFIED","C")
        fit="VERIFIED" if d.get("motherboard_fit")=="COMPATIBLE" else "NO" if d.get("motherboard_fit")=="INCOMPATIBLE" else "UNKNOWN"
        out.append({"route":"USED_PC_PLUS_FUTURE_UPGRADE","label":d.get("title"),"tcwp":d["ask_t1"],"cpu":d.get("cpu"),"cpu_score":int(d.get("cpu_score") or 0),"gpu":d.get("gpu"),"gpu_score":int(d.get("gpu_score") or 0),"performance_class":pclass(int(d.get("cpu_score") or 0),int(d.get("gpu_score") or 0)),"upgradeability":grade,"z20_fit":fit,"components":comps,"rationale":"Complete used PC benchmarked as a usable system now with explicit future-upgrade path; no speculative resale is credited."})
    return out


def rank_key(r:dict):
    perf_order={"SWEET SPOT":0,"ACCEPTABLE":1,"OVERKILL":2,"UNDER MINIMUM":9}
    # Price first among sufficient systems, then upgradeability as a tiebreak/controlled premium signal.
    return (perf_order.get(r.get("performance_class"),9),int(r.get("tcwp") or 10**9),-GRADE_NUM.get(r.get("upgradeability"),0),-int(r.get("cpu_score") or 0),-int(r.get("gpu_score") or 0))


def main():
    main=json.loads(MAIN.read_text(encoding="utf-8")); parts_doc=json.loads(PARTS.read_text(encoding="utf-8")); donors_doc=json.loads(DONORS.read_text(encoding="utf-8")) if DONORS.exists() else {"donors":[]}
    assert main.get("gate_passed") is True
    assert parts_doc.get("gate_passed") is True
    assert fresh(), "NEW RETAIL BASELINES EXPIRED — refresh before hybrid ranking"
    routes=[]
    routes += [complete_route(r) for r in (main.get("ranked") or [])]
    routes += donor_upgrade_routes(donors_doc.get("donors") or [])
    routes += pure_used_builds(parts_doc.get("opportunities") or [])
    routes += hybrid_builds(parts_doc.get("opportunities") or [])
    routes=[r for r in routes if r.get("performance_class") in {"ACCEPTABLE","SWEET SPOT","OVERKILL"}]
    # Deduplicate exact component sets.
    seen=set(); dedup=[]
    for r in routes:
        key=(r["route"],tuple(sorted(str(c.get("listing_id") or c.get("name")) for c in r["components"])))
        if key in seen: continue
        seen.add(key); dedup.append(r)
    dedup.sort(key=rank_key)
    complete=[r for r in dedup if r["route"]=="COMPLETE_USED_PC"]
    used=[r for r in dedup if r["route"]=="USED_BUILD"]
    hybrid=[r for r in dedup if r["route"]=="HYBRID_USED_NEW"]
    upg=[r for r in dedup if r["route"]=="USED_PC_PLUS_FUTURE_UPGRADE"]
    sweet=[r for r in dedup if r["performance_class"]=="SWEET SPOT"]
    best_upgrade=min((r for r in dedup if r["upgradeability"] in {"A","B"}),key=lambda r:(r["tcwp"],-GRADE_NUM[r["upgradeability"]]),default=None)
    out={
        "model_version":"DBA-WOW-CROSS-ROUTE-V15","generated_at":main.get("generated_at"),"gate_passed":True,
        "strategy_reference":"https://youtu.be/7HgAN5cEmkk?is=3HET1ZpzUj-j4zZq",
        "strategy":"Buy used where absolute savings are large; use new parts where warranty/fit/low used savings make new better. Compare finished solutions by TCWP, WoW suitability and upgrade path.",
        "target":{"game":"WoW Classic/Cataclysm","resolution":"3840x1600","refresh_hz":75,"preferred_case":"Jonsbo Z20"},
        "counts":{"complete_routes":len(complete),"upgrade_routes":len(upg),"used_builds":len(used),"hybrid_builds":len(hybrid),"ranked_routes":len(dedup)},
        "buy_now":dedup[0] if dedup else None,
        "cheapest_sweet_spot":min(sweet,key=lambda r:r["tcwp"],default=None),
        "best_upgrade_platform":best_upgrade,
        "best_complete_pc":complete[0] if complete else None,
        "best_used_build":used[0] if used else None,
        "best_hybrid_build":hybrid[0] if hybrid else None,
        "ranked":dedup,
        "source_gates":{"complete_pc":main.get("coverage"),"parts":parts_doc.get("coverage")},
    }
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"gate":True,**out["counts"],"buy_now":(out["buy_now"] or {}).get("route"),"buy_now_tcwp":(out["buy_now"] or {}).get("tcwp")},ensure_ascii=False))

if __name__=="__main__":
    main()
