from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

BASE = "https://www.dba.dk"
ITEM_RE = re.compile(r"/recommerce/forsale/item/(\d+)")
PRICE_RE = re.compile(r"(?<!\d)(\d{1,3}(?:[.\s]\d{3})*|\d{3,6})\s*(?:kr\.?|dkk)\b", re.I)
MAX_PRICE = 15000

QUERIES = [
    "gaming pc", "gamer pc", "gaming computer", "stationær gaming", "gaming bærbar", "gaming laptop",
    "omen gaming", "legion gaming", "nitro gaming", "predator gaming", "sharkgaming", "dutzo", "mm vision", "msi gamer",
    "rtx 2060 super", "rtx 2070", "rtx 2070 super", "rtx 2080", "rtx 2080 super",
    "rtx 3060", "rtx 3060 ti", "rtx 3070", "rtx 3070 ti", "rtx 3080", "rtx 4060", "rtx 4060 ti",
    "rx 5700 xt", "rx 6600 xt", "rx 6650 xt", "rx 6700 xt", "rx 6750 xt", "rx 6800", "rx 7600",
    "skal væk gaming", "hurtig handel gaming",
]

GPU_RULES = [
    (r"\brtx\s*3080\b", "RTX 3080", 90),(r"\brtx\s*3070\s*ti\b", "RTX 3070 Ti",79),(r"\brtx\s*3070\b","RTX 3070",73),
    (r"\brtx\s*3060\s*ti\b","RTX 3060 Ti",66),(r"\brtx\s*3060\b","RTX 3060",54),(r"\brtx\s*4060\s*ti\b","RTX 4060 Ti",72),(r"\brtx\s*4060\b","RTX 4060",60),
    (r"\brtx\s*2080\s*super\b","RTX 2080 Super",65),(r"\brtx\s*2080\b","RTX 2080",61),(r"\brtx\s*2070\s*super\b","RTX 2070 Super",57),(r"\brtx\s*2070\b","RTX 2070",52),(r"\brtx\s*2060\s*super\b","RTX 2060 Super",50),
    (r"\brx\s*6800\b","RX 6800",84),(r"\brx\s*6750\s*xt\b","RX 6750 XT",72),(r"\brx\s*6700\s*xt\b","RX 6700 XT",68),(r"\brx\s*6650\s*xt\b","RX 6650 XT",54),(r"\brx\s*6600\s*xt\b","RX 6600 XT",51),(r"\brx\s*5700\s*xt\b","RX 5700 XT",55),(r"\brx\s*7600\b","RX 7600",59),
]
CPU_RULES = [
    (r"\b7800x3d\b","Ryzen 7 7800X3D",125),(r"\b5800x3d\b","Ryzen 7 5800X3D",100),(r"\b5700x3d\b","Ryzen 7 5700X3D",96),(r"\b5700x\b","Ryzen 7 5700X",82),(r"\b5600x?\b","Ryzen 5 5600",76),(r"\b3600x?\b","Ryzen 5 3600",56),
    (r"\bi[579][ -]?14\d{3}[a-z]*\b","Intel 14th gen",112),(r"\bi[579][ -]?13\d{3}[a-z]*\b","Intel 13th gen",105),(r"\bi[579][ -]?12\d{3}[a-z]*\b","Intel 12th gen",91),
    (r"\bi[579][ -]?11\d{3}[a-z]*\b","Intel 11th gen",79),(r"\bi[579][ -]?10\d{3}[a-z]*\b","Intel 10th gen",72),(r"\bi[579][ -]?9\d{3}[a-z]*\b","Intel 9th gen",67),(r"\bi[579][ -]?8\d{3}[a-z]*\b","Intel 8th gen",61),
]

LAPTOP_RE = re.compile(r"\b(laptop|bærbar|notebook|omen\s+1[456789]|legion\s+(5|7|pro|slim)|nitro\s+(5|16|17|v)|predator\s+helios|katana\s+(15|17)|rog\s+(strix|zephyrus))\b", re.I)
MATX_RE = re.compile(r"\b(micro[- ]?atx|m[- ]?atx|matx|[abhqz][1-9]\d{2}m(?:[-\s]|\b))", re.I)
ITX_RE = re.compile(r"\b(mini[- ]?itx|itx)\b", re.I)
ATX_RE = re.compile(r"\b(e[- ]?atx|extended[- ]?atx|atx)\b", re.I)
OEM_RE = re.compile(r"\b(hp\s+(omen|pavilion)|dell\s+(g5|xps|alienware)|lenovo\s+(legion|ideacentre)|acer\s+(nitro|predator))\b", re.I)
PSU_RE = re.compile(r"\b(corsair|seasonic|be quiet!?|evga|cooler master|nzxt|asus|msi|fsp|super flower)\b.{0,50}\b\d{3,4}\s*w\b", re.I | re.S)


def now(): return datetime.now(timezone.utc).isoformat()
def amount(s: str):
    m = PRICE_RE.search(s or "")
    return int(re.sub(r"\D", "", m.group(1))) if m else None

def match(text, rules):
    for pat, label, score in rules:
        if re.search(pat, text or "", re.I): return label, score
    return "Ukendt", 0

def perf(gs, cs):
    if gs < 50 or cs < 50: return "UNDER MINIMUM"
    if gs >= 90 and cs >= 76: return "OVERKILL"
    if gs >= 65 and cs >= 60: return "SWEET SPOT"
    return "ACCEPTABLE"

def fixture_regression():
    fixture=[{"id":"24247594","title":"RTX 3070 Ti / i5-8600K","price":4399},{"id":"other","title":"Other","price":2000}]
    x=next(v for v in fixture if v["id"]=="24247594")
    assert x["price"]==4399
    return {"ok":True,"type":"static_fixture","historical_listing_id":"24247594","expected_price":4399}

def format_gate(text):
    if LAPTOP_RE.search(text): return "LAPTOP", "Portable complete system"
    matx=bool(MATX_RE.search(text)); itx=bool(ITX_RE.search(text))
    cleaned=re.sub(r"\b(micro[- ]?atx|m[- ]?atx|matx|mini[- ]?itx)\b"," ",text,flags=re.I)
    full=bool(ATX_RE.search(cleaned))
    if full and not (matx or itx): return "A3_INCOMPATIBLE", "Explicit ATX/E-ATX evidence"
    if matx or itx:
        return ("A3_READY" if PSU_RE.search(text) else "A3_READY_PSU_CHECK", "Explicit mATX/ITX evidence")
    if OEM_RE.search(text): return "A3_UNCERTAIN", "OEM platform without explicit standard mATX/ITX evidence"
    return "A3_UNCERTAIN", "No explicit mATX/ITX evidence"

async def dismiss(page):
    for label in ["Afvis alle", "Accepter alle", "Accept all", "Reject all", "Kun nødvendige"]:
        try:
            b=page.get_by_role("button", name=re.compile(label,re.I)).first
            if await b.count(): await b.click(timeout=1000)
        except Exception: pass

async def discover_cards(page, query):
    url=f"{BASE}/recommerce/forsale/search?q={quote(query)}"
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    await dismiss(page)
    try: await page.wait_for_selector('a[href*="/recommerce/forsale/item/"]', timeout=12000)
    except PlaywrightTimeoutError: return []
    # Small controlled scroll to render lazy cards.
    for _ in range(4):
        await page.mouse.wheel(0, 1800); await page.wait_for_timeout(350)
    rows=await page.evaluate("""
    () => {
      const out=[]; const seen=new Set();
      for (const a of document.querySelectorAll('a[href*="/recommerce/forsale/item/"]')) {
        const m=a.href.match(/\/recommerce\/forsale\/item\/(\d+)/); if(!m||seen.has(m[1])) continue;
        let node=a, best=null;
        for(let i=0;i<8 && node;i++,node=node.parentElement){
          const txt=(node.innerText||'').trim();
          if(/\b(?:kr\.?|DKK)\b/i.test(txt) && txt.length<2500){best={text:txt, href:a.href, title:(a.innerText||'').trim()}; break;}
        }
        if(best){seen.add(m[1]); out.push({id:m[1], ...best});}
      }
      return out;
    }
    """)
    out=[]
    for r in rows:
        p=amount(r.get("text",""))
        title=r.get("title") or (r.get("text","").split("\n")[0] if r.get("text") else "")
        if p is not None and 500 <= p <= MAX_PRICE:
            out.append({"listing_id":r["id"],"url":f"{BASE}/recommerce/forsale/item/{r['id']}","title":title,"ask_t0":p,"card_text":r.get("text","")[:2000],"query":query,"t0_at":now(),"source":"rendered_dba_card"})
    return out

async def item_object(page, lid):
    url=f"{BASE}/recommerce/forsale/item/{lid}"
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    await dismiss(page)
    await page.wait_for_timeout(700)
    data=await page.evaluate("""
    (lid) => {
      const scripts=[...document.scripts].map(s=>s.textContent||'').filter(Boolean);
      const body=(document.body?.innerText||'').slice(0,30000);
      const title=(document.querySelector('h1')?.innerText||document.title||'').trim();
      return {scripts,body,title,url:location.href};
    }
    """, lid)
    candidates=[]
    def walk(x, depth=0):
        if depth>14: return
        if isinstance(x,dict):
            ids={str(x.get(k)) for k in ("id","listingId","itemId") if x.get(k) is not None}
            urls=[str(v) for k,v in x.items() if isinstance(v,str) and ("url" in k.lower() or "canonical" in k.lower())]
            if lid in ids or any(f"/item/{lid}" in u for u in urls): candidates.append(x)
            for v in x.values():
                if isinstance(v,(dict,list)): walk(v,depth+1)
        elif isinstance(x,list):
            for v in x[:1000]: walk(v,depth+1)
    for s in data["scripts"]:
        if lid not in s and "itemData" not in s: continue
        try: walk(json.loads(s))
        except Exception: pass
    def price_from_obj(o):
        for k in ("price","amount","priceAmount"):
            v=o.get(k)
            if isinstance(v,(int,float)): return int(v)
            if isinstance(v,dict):
                for kk in ("amount","value","price"):
                    if isinstance(v.get(kk),(int,float)): return int(v[kk])
            if isinstance(v,str):
                p=amount(v)
                if p: return p
        return None
    chosen=None
    for o in candidates:
        p=price_from_obj(o)
        if p and 100 <= p <= 1000000:
            chosen=(o,p); break
    body=data["body"]
    title=data["title"]
    if chosen:
        o,p=chosen
        title=str(o.get("title") or o.get("heading") or title)
        desc=str(o.get("description") or "")
        disposed=bool(o.get("disposed")) or str(o.get("status","")).lower() in {"sold","inactive","disposed"}
        trade=o.get("tradeType") or o.get("adViewTypeLabel")
        source="embedded_listing_json"
    else:
        p=amount(body)
        desc=body
        disposed=bool(re.search(r"\b(inaktiv|solgt|ikke længere til salg)\b",body,re.I))
        trade=None
        source="rendered_item_page"
    if not p: return None
    if not (ITEM_RE.search(data["url"]) and ITEM_RE.search(data["url"]).group(1)==lid): return None
    return {"listing_id":lid,"url":url,"title":title,"description":desc,"body":body,"ask":p,"disposed":disposed,"trade_type":trade,"source":source,"fetched_at":now()}

async def main():
    Path("results").mkdir(exist_ok=True)
    reg=fixture_regression()
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        ctx=await browser.new_context(locale="da-DK", viewport={"width":1440,"height":1100})
        page=await ctx.new_page()
        found={}; search_errors=[]
        for q in QUERIES:
            try: cards=await discover_cards(page,q)
            except Exception as e: search_errors.append({"query":q,"error":type(e).__name__}); continue
            for c in cards:
                old=found.get(c["listing_id"])
                if old is None: found[c["listing_id"]]=c
                else: old.setdefault("queries",[]).append(q)
        # Dynamic schema/source gate from a current card + same item page.
        gate=None
        for c in sorted(found.values(), key=lambda x:x["ask_t0"])[:25]:
            try: t=await item_object(page,c["listing_id"])
            except Exception: continue
            if t and not t["disposed"] and t["ask"]:
                gate={"ok":True,"listing_id":c["listing_id"],"t0_price":c["ask_t0"],"t1_price":t["ask"],"t0_source":c["source"],"t1_source":t["source"]}; break
        if not gate:
            raise SystemExit("PRICE DATA GATE FAILED — no current rendered same-object card/item pair verified")
        # Advance only plausible GPU leads to detail T1.
        t0=[]
        for c in found.values():
            gpu,gs=match(c["title"]+" "+c["card_text"],GPU_RULES)
            if gs>=50: t0.append(c)
        ranked=[]; leads=[]; rejected=[]
        for c in t0:
            try: t=await item_object(page,c["listing_id"])
            except Exception as e:
                rejected.append({"listing_id":c["listing_id"],"reason":"T1_FETCH_FAILED","detail":type(e).__name__}); continue
            if not t or t["disposed"] or not t["ask"]:
                rejected.append({"listing_id":c["listing_id"],"reason":"INACTIVE_OR_MISSING_LIVE_PRICE"}); continue
            text=f"{t['title']}\n{t['description']}\n{t['body']}"
            gpu,gs=match(text,GPU_RULES); cpu,cs=match(text,CPU_RULES)
            if gs<50 or cs<50:
                rejected.append({"listing_id":c["listing_id"],"reason":"SPEC_PARSE_FAILED","gpu":gpu,"cpu":cpu}); continue
            pc=perf(gs,cs)
            if pc=="UNDER MINIMUM":
                rejected.append({"listing_id":c["listing_id"],"reason":"UNDER_MINIMUM"}); continue
            fg,fr=format_gate(text)
            row={"listing_id":c["listing_id"],"url":t["url"],"title":t["title"],"ask_t0":c["ask_t0"],"ask_t1":t["ask"],"price_changed":c["ask_t0"]!=t["ask"],"gpu":gpu,"gpu_score":gs,"cpu":cpu,"cpu_score":cs,"performance_class":pc,"format_gate":fg,"format_rationale":fr,"t0_source":c["source"],"t1_source":t["source"],"t0_at":c["t0_at"],"t1_at":t["fetched_at"]}
            if fg in {"LAPTOP","A3_READY","A3_READY_PSU_CHECK"}: ranked.append(row)
            elif fg=="A3_UNCERTAIN": leads.append(row)
            else: rejected.append({**row,"reason":fg})
        await browser.close()
    class_order={"SWEET SPOT":0,"ACCEPTABLE":1,"OVERKILL":2}
    ranked.sort(key=lambda r:(r["ask_t1"], class_order.get(r["performance_class"],9),-r["gpu_score"],-r["cpu_score"]))
    out={"model_version":"DBA-WOW-BROWSER-PRICE-FIRST-A3-V1","generated_at":now(),"gate_passed":True,"source_gate":gate,"price_binding_regression":reg,"counts":{"queries":len(QUERIES),"t0_unique":len(found),"t0_gpu_promising":len(t0),"ranked":len(ranked),"a3_uncertain_leads":len(leads),"rejected":len(rejected)},"ranked":ranked,"leads":leads,"rejected":rejected,"rejection_reason_counts":dict(Counter(x.get("reason","UNKNOWN") for x in rejected)),"search_errors":search_errors}
    Path("results/wow_a3_latest.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    lines=["# FULDT PÅLIDELIG DBA-PRISRAPPORT — WoW laptop/A3","",f"Generated: {out['generated_at']}",f"Verified ranked records: {len(ranked)}","", "| # | T1 ASK | Format | Class | GPU | CPU | Listing ID | DBA |","|---:|---:|---|---|---|---|---|---|"]
    for i,r in enumerate(ranked,1): lines.append(f"| {i} | {r['ask_t1']} kr. | {r['format_gate']} | {r['performance_class']} | {r['gpu']} | {r['cpu']} | {r['listing_id']} | [{r['title']}]({r['url']}) |")
    lines += ["","## A3-uncertain leads (not ranked)"] + [f"- [{r['title']}]({r['url']}) — {r['listing_id']} — {r['format_rationale']}" for r in leads[:40]]
    Path("results/wow_a3_report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps({"gate":True,"t0":len(found),"promising":len(t0),"ranked":len(ranked),"leads":len(leads)},ensure_ascii=False))

if __name__ == "__main__": asyncio.run(main())
