# -*- coding: utf-8 -*-
"""publicar_runs.py (Alri) - Junta os resultado_*.csv em data/alri/artefato/runs.json,
o arquivo de dados do artefato "Alri GameCheck" (a pagina le esse json).
Cada linha: [provedor, nome, slug, status, detalhe, launch_host, http_launch,
tempo_ms, game_code]. Runs da mais recente para a mais antiga.
Depois de gerar, o json e republicado no artefato pelo Claude (a pagina nao muda).
"""
import csv, glob, json
from pathlib import Path

ROOT    = Path(__file__).resolve().parents[2]
RES_DIR = ROOT / "data" / "alri" / "resultados"
SAIDA   = ROOT / "data" / "alri" / "artefato" / "runs.json"
MAX_RUNS = 60
PREFIXO  = "https://alri.com/casino/games/"


def _run(arq):
    with open(arq, encoding="utf-8-sig") as f:
        linhas = list(csv.DictReader(f))
    rows = []
    for l in linhas:
        url  = l.get("url_jogo", "")
        slug = url[len(PREFIXO):].strip("/") if url.startswith(PREFIXO) else url
        try:
            ms = int(float(l.get("tempo_ms") or 0))
        except ValueError:
            ms = 0
        rows.append([l.get("provedor", ""), l.get("nome", ""), slug,
                     l.get("status", ""), l.get("detalhe", ""),
                     l.get("launch_host", ""), l.get("http_launch", ""), ms,
                     l.get("game_code", "")])
    data = Path(arq).stem.replace("resultado_", "")
    return {"date": data, "rows": rows}


def gerar():
    arquivos = sorted(glob.glob(str(RES_DIR / "resultado_*.csv")), reverse=True)
    runs = [_run(a) for a in arquivos[:MAX_RUNS]]
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps({"runs": runs}, ensure_ascii=False,
                                separators=(",", ":")), encoding="utf-8")
    print(">> runs.json gerado: %d runs (%s)" % (
        len(runs), ", ".join(r["date"] for r in runs)))
    return SAIDA


if __name__ == "__main__":
    gerar()
