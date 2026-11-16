import csv, shutil
from pathlib import Path
from datetime import datetime

ROOT   = Path(r"c:\Users\PauloHenriquePereira\Projetos\estrelabet-monitor")
ULTIMO = ROOT / "data" / "resultados" / "resultado_2026-06-18.csv"
HOJE   = datetime.now().strftime("%Y-%m-%d")
SAIDA  = ROOT / "data" / "resultados" / ("resultado_" + HOJE + ".csv")

fieldnames = ["data", "provedor", "nome", "url_jogo", "status", "detalhe", "gamecode", "tempo_ms"]

if SAIDA.exists():
    print("!! resultado_%s.csv ja existe. Abortando para nao sobrescrever." % HOJE)
    exit(1)

with open(ULTIMO, encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

traceid_rows = [r for r in rows if "traceid" in r.get("detalhe", "").lower()]

with open(SAIDA, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    for r in traceid_rows:
        w.writerow({
            "data":     HOJE,
            "provedor": r["provedor"],
            "nome":     r["nome"],
            "url_jogo": r["url_jogo"],
            "status":   r["status"],
            "detalhe":  r["detalhe"] + " [encaminhado]",
            "gamecode": r.get("gamecode", ""),
            "tempo_ms": r.get("tempo_ms", ""),
        })

print(">> Pre-populado %s com %d entradas traceid." % (SAIDA.name, len(traceid_rows)))
print(">> Execute: python main.py")
