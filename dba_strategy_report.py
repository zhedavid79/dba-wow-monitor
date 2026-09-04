from __future__ import annotations

import json
from pathlib import Path

SRC=Path("results/wow_strategy_latest.json")
REPORT=Path("results/wow_a3_report.md")


def money(n): return f"{int(n):,}".replace(",",".")+" kr."
def links(r):
    used=[c for c in (r or {}).get("components",[]) if c.get("source")=="USED ASK"]
    return "—" if not used else "; ".join(f"[{c.get('kind')}: {c.get('name')}]({c.get('url')})" for c in used)
def line(r):
    if not r:return "Ingen verificeret kandidat i denne kategori."
    extra=""
    if r.get('foundation'): extra=f" — foundation {r['foundation']}"
    return f"**{r['route']} — {money(r['tcwp'])} — {r['cpu']} + {r['gpu']} — {r['performance_class']} — upgrade {r['upgradeability']} — Z20 {r['z20_fit']}{extra}**\n\n{r['rationale']}\n\nBrugte kilder: {links(r)}"

def main():
    d=json.loads(SRC.read_text(encoding='utf-8'))
    assert d.get('gate_passed') is True
    assert d.get('model_version')=='DBA-WOW-PLATFORM-FIRST-V16'
    lines=[
      '# FULDT PÅLIDELIG DBA-PRISRAPPORT — WoW PLATFORM-FIRST V16','',
      f"Generated: {d.get('generated_at')}",
      'Mål: WoW Classic/Cataclysm, 3840×1600/75 Hz. Jonsbo Z20 er ønsket slutkabinet.',
      'Strategi: platform først, performance opportunistisk. AM5/B650-B850 mATX/Wi-Fi/4-DIMM/DDR5 er foretrukket permanent fundament; en billig ACCEPTABLE GPU må bruges som bridge.',
      'Indkøb: brugt først GPU→CPU→RAM→luftkøler; motherboard/kabinet brugt kun ved reel besparelse; PSU/SSD/blæsere nyt først.',
      f"WAIT / BUY: **{d.get('wait_buy')}**",'',
      '## 🏆 BUY NOW','',line(d.get('buy_now')),'',
      '## 🧱 BEST FOUNDATION','',line(d.get('best_foundation')),'',
      '## 💰 CHEAPEST VIABLE','',line(d.get('cheapest_viable')),'',
      '## 🎯 BEST OPPORTUNISTIC BUY','',line(d.get('best_opportunistic_buy')),'',
      '## 🖥️ BEST COMPLETE PC','',line(d.get('best_complete_pc')),'',
      '## 🔧 BEST DONOR/UPGRADE ROUTE','',line(d.get('best_donor_upgrade_route')),'',
      '## ⚡ BEST HYBRID BUILD','',line(d.get('best_hybrid_build')),'',
      '## Samlet ranking — færdige løsninger','',
      '| # | TCWP | Strategic cost | Route | CPU | GPU | WoW | Upgrade | Z20 | Foundation | Brugte live-kilder |',
      '|---:|---:|---:|---|---|---|---|---|---|---|---|',
    ]
    for i,r in enumerate((d.get('ranked') or [])[:50],1):
        lines.append(f"| {i} | {money(r['tcwp'])} | {money(r.get('strategic_effective_cost',r['tcwp']))} | {r['route']} | {r['cpu']} | {r['gpu']} | {r['performance_class']} | {r['upgradeability']} | {r['z20_fit']} | {r.get('foundation','—')} | {links(r)} |")
    lines += ['', '## Pris- og evidensregel','', 'Alle USED ASK-komponenter i ranking kommer fra live T0→T1-verificerede DBA listing-objects. Funktionelt defekte dele er hard-excluded. NEW RETAIL er separat mærket. Search snippets/cached priser er aldrig prisbevis. UNKNOWN kompatibilitet må ikke fremstilles som VERIFIED.','']
    REPORT.write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'report':True,'model':d['model_version'],'ranked':len(d.get('ranked') or []),'wait_buy':d.get('wait_buy')},ensure_ascii=False))

if __name__=='__main__':main()
