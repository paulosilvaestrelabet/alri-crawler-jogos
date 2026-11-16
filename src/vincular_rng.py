# -*- coding: utf-8 -*-
"""vincular_rng.py - Vincula os jogos da aba "200 RNG" da planilha (public/)
aos jogos reais do site (data/jogos.csv). Mesma logica de vincular_live.py,
so muda a aba e o mapa de nomes de provider."""
from pathlib import Path

import vincular_live as base

ROOT = Path(__file__).resolve().parents[1]
SAIDA = ROOT / "data" / "vinculo_200rng.csv"

ABA = "200 RNG"

MAPA_PROVEDOR = {
    "3oaks":               "3 oaks",
    "playtech playtech":   "playtech",
    "pgsoft":              "pg soft",
    "playngo":             "playngo",
    "popok":               "popok",
    "pragmaticplay":       "pragmatic play",
    "nolimitcity":         "nolimit city",
    "tadagaming":          "tadagaming",
    "jogoglobal":          "jogo global",
    "softswiss quickfire": "games global",
    "jogo":                "estrelabet",
}


def vincular(linhas, por_provedor):
    import difflib
    resultados = []
    for linha in linhas:
        jogo_busca, provider_busca = _termo_busca(linha)
        prov_norm = MAPA_PROVEDOR.get(base._norm(provider_busca), base._norm(provider_busca))
        candidatos = por_provedor.get(prov_norm, [])
        jn = base._norm(jogo_busca)

        melhor, melhor_score = None, 0.0
        for c in candidatos:
            score = difflib.SequenceMatcher(None, jn, base._norm(c["nome"])).ratio()
            if score > melhor_score:
                melhor, melhor_score = c, score

        status = "OK" if melhor and melhor_score >= base.LIMIAR_REVISAO else "REVISAR"
        resultados.append({
            "jogo_planilha":     linha["Jogo"],
            "provider_planilha": linha["Provider"],
            "nome_site":         melhor["nome"] if melhor else "",
            "provedor_site":     melhor["provedor"] if melhor else "",
            "url_jogo":          melhor["url_jogo"] if melhor else "",
            "score":             round(melhor_score, 2),
            "status":            status,
        })
    return resultados


def _termo_busca(linha):
    """4 linhas da planilha tem Provider='Jogoglobal' com o nome errado
    (sufixo ' Jogo' colado por bug de planilha) para jogos que na verdade
    sao exclusivos EstrelaBet (o mesmo jogo ja aparece corretamente em
    outra linha com Provider='Jogo'). Retorna (jogo, provider) a usar na
    BUSCA -- os rotulos originais da planilha (jogo_planilha/provider_
    planilha) no CSV de saida continuam intactos, para bater com as
    celulas reais na hora de preencher a planilha."""
    jogo, provider = linha["Jogo"], linha["Provider"]
    if provider == "Jogoglobal" and str(jogo).endswith(" Jogo"):
        return jogo[: -len(" Jogo")], "Jogo"
    return jogo, provider


def rodar():
    caminho = base._achar_planilha()
    print(">> Planilha:", caminho.name)
    linhas = base.carregar_linhas_planilha(caminho, aba=ABA)
    print(">>", len(linhas), "jogos na aba", ABA)

    por_provedor = base.carregar_jogos_site()
    resultados = vincular(linhas, por_provedor)

    import csv
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    with open(SAIDA, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(resultados[0].keys()))
        w.writeheader()
        w.writerows(resultados)

    revisar = [r for r in resultados if r["status"] == "REVISAR"]
    sem_match = [r for r in resultados if not r["url_jogo"]]
    print(">> %d vinculados, %d para revisar, %d sem nenhum candidato."
          % (len(resultados) - len(revisar), len(revisar), len(sem_match)))
    print(">> Salvo em", SAIDA)
    if revisar:
        print("\n>> Conferir manualmente:")
        for r in revisar:
            print("  [%.2f] %-40s (%s) -> %s" % (
                r["score"], r["jogo_planilha"], r["provider_planilha"], r["nome_site"] or "???"))


if __name__ == "__main__":
    rodar()
