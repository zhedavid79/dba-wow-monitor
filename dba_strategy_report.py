from __future__ import annotations

import json
from pathlib import Path

SRC=Path("results/wow_strategy_latest.json")
REPORT=Path("results/wow_a3_report.md")


def money(n): return f"{int(n):,}".replace(",",".")+" kr."

def links(r):
    used=[c for c in r.get("components",[]) if c.get("source")=="USED ASK"]
    if not used: return "—"
    return "; ".join(f"[{c.get('kind')}: {c.get('name')}]({c.get('url')})" for c in used)

def line(r):
    if not r: return "Ingen verificeret kandidat i denne rute."
    return f"**{r['route']} — {money(r['tcwp'])} — {r['cpu']} + {r['gpu']} — {r['performance_class']} — upgrade {r['upgradeability']} — Z20 {r['z20_fit']}**\n\n{r['rationale']}\n\nBrugte kilder: {links(r)}"

def main():
    d=json.loads(SRC.read_text(encoding="utf-8"))
    assert d.get("gate_passed") is True
    lines=[
        "# FULDT PÅLIDELIG DBA-PRISRAPPORT — WoW CROSS-ROUTE V15","",
        f"Generated: {d.get('generated_at')}",
        "Mål: WoW Classic/Cataclysm, 3840×1600, op til 75 Hz; Jonsbo Z20 er foretrukket slutkabinet, ikke discovery hard gate.",
        "Strategisk reference: https://youtu.be/7HgAN5cEmkk?is=3HET1ZpzUj-j4zZq",
        "Princip: køb brugt hvor den absolutte besparelse er stor; køb nyt hvor garanti, kompatibilitet eller lille brugtbesparelse gør nyt bedre. Alle ruter konkurrerer på TCWP.","",
        f"Verificerede ruter: complete={d['counts']['complete_routes']}, PC+upgrade={d['counts']['upgrade_routes']}, used builds={d['counts']['used_builds']}, hybrid={d['counts']['hybrid_builds']}, samlet={d['counts']['ranked_routes']}.","",
        "## 🏆 BUY NOW","",line(d.get("buy_now")),"",
        "## 💰 CHEAPEST SWEET SPOT","",line(d.get("cheapest_sweet_spot")),"",
        "## 🔧 BEST UPGRADE PLATFORM","",line(d.get("best_upgrade_platform")),"",
        "## 🖥️ BEST COMPLETE PC","",line(d.get("best_complete_pc")),"",
        "## 🧩 BEST USED BUILD","",line(d.get("best_used_build")),"",
        "## ⚡ BEST HYBRID BUILD","",line(d.get("best_hybrid_build")),"",
        "## Samlet ranking — færdige løsninger","",
        "| # | TCWP | Route | CPU | GPU | WoW | Upgrade | Z20 | Brugte live-kilder |",
        "|---:|---:|---|---|---|---|---|---|---|",
    ]
    for i,r in enumerate((d.get("ranked") or [])[:50],1):
        lines.append(f"| {i} | {money(r['tcwp'])} | {r['route']} | {r['cpu']} | {r['gpu']} | {r['performance_class']} | {r['upgradeability']} | {r['z20_fit']} | {links(r)} |")
    lines += ["","## Pris- og evidensregel","","Alle USED ASK-komponenter i den rangerede del kommer fra live T0→T1-verificerede DBA listing-objects. NEW RETAIL er separat mærket. Search snippets/cached priser bruges aldrig som prisbevis. Kritisk ukendt kompatibilitet må ikke fremstilles som VERIFIED.",""]
    REPORT.write_text("\n".join(lines),encoding="utf-8")
    print(json.dumps({"report":True,"ranked":len(d.get('ranked') or []),"buy_now":(d.get('buy_now') or {}).get('route')},ensure_ascii=False))

if __name__=="__main__": main()
