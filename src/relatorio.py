# -*- coding: utf-8 -*-
"""relatorio.py - Le o resultado mais recente em data/resultados/ e gera
dashboard/index.html com filtros por status e secao separada de recheck."""
import csv, glob
from pathlib import Path
from datetime import datetime
from collections import Counter, defaultdict

ROOT    = Path(__file__).resolve().parents[1]
RES_DIR = ROOT / "data" / "resultados"
DASH    = ROOT / "dashboard" / "index.html"

# Erros reais: impactam disponibilidade do jogo para o usuario
ERROS_REAIS    = {"INDISPONIVEL", "ERRO_404", "ERRO_HTTP", "SESSAO_EXPIRADA", "DEMO_ONLY"}
# Recheck: nao sao erros confirmados, precisam de run separada para validar
RECHECK_STATUS = {"SEM_LAUNCH", "TIMEOUT"}

CORES = {
    "OK":              "#1faa59",
    "INDISPONIVEL":    "#c0392b",
    "DEMO_ONLY":       "#e67e22",
    "SEM_LAUNCH":      "#4a8fc7",
    "TIMEOUT":         "#5c6e82",
    "ERRO_404":        "#e74c3c",
    "ERRO_HTTP":       "#f39c12",
    "SESSAO_EXPIRADA": "#9b59b6",
    "NAO_CARREGOU":    "#d35400",
    "ERRO_LAUNCH":     "#e84393",
    "BLOQUEADO":       "#8e44ad",
    "KYC":             "#16a085",
    "COMING_SOON":     "#7f8c8d",
    "ERRO_REDE":       "#2980b9",
    "ERRO_ALEA":       "#c0392b",
    "ERRO_IFRAME":     "#e74c3c",
    "SITE_INACESSIVEL": "#34495e",
    "INCONCLUSIVO":    "#95a5a6",
}

LABELS = {
    "OK":              "OK",
    "INDISPONIVEL":    "Indisponivel",
    "DEMO_ONLY":       "Demo Only",
    "SEM_LAUNCH":      "Sem Launch",
    "TIMEOUT":         "Timeout",
    "ERRO_404":        "Erro 404",
    "ERRO_HTTP":       "Erro HTTP",
    "SESSAO_EXPIRADA": "Sessao Expirada",
    "NAO_CARREGOU":    "Nao Carregou",
    "ERRO_LAUNCH":     "Erro Launch",
    "BLOQUEADO":       "Bloqueado",
    "KYC":             "KYC",
    "COMING_SOON":     "Coming Soon",
    "ERRO_REDE":       "Erro Rede",
    "ERRO_ALEA":       "Erro Alea",
    "ERRO_IFRAME":     "Erro Iframe",
    "SITE_INACESSIVEL": "Site Inacessivel",
    "INCONCLUSIVO":    "Inconclusivo",
}

# ordem de exibicao dos cards/filtros
ORDEM = ["INDISPONIVEL", "ERRO_ALEA", "ERRO_IFRAME", "ERRO_REDE", "NAO_CARREGOU",
         "ERRO_404", "ERRO_HTTP", "ERRO_LAUNCH", "BLOQUEADO", "KYC",
         "SESSAO_EXPIRADA", "DEMO_ONLY", "COMING_SOON", "INCONCLUSIVO",
         "SEM_LAUNCH", "TIMEOUT", "SITE_INACESSIVEL"]

INFO_RECHECK = ('Estes jogos nao chamaram a API BFF /launch/game durante a verificacao. '
                'Podem ser providers com sistema de launch proprio ou timeouts de rede. ')


def ultimo_resultado(res_dir=RES_DIR):
    arquivos = sorted(glob.glob(str(res_dir / "resultado_*.csv")))
    if not arquivos:
        return None, []
    with open(arquivos[-1], encoding="utf-8-sig") as f:
        return arquivos[-1], list(csv.DictReader(f))


def _pill(status):
    c   = CORES.get(status, "#888")
    lbl = LABELS.get(status, status)
    return '<span class="pill" style="background:%s">%s</span>' % (c, lbl)


def _card(status, count):
    c   = CORES.get(status, "#888")
    lbl = LABELS.get(status, status)
    return ('<div class="card" style="border-top:4px solid %s">'
            '<div class="num" style="color:%s">%d</div>'
            '<div class="lbl">%s</div></div>') % (c, c, count, lbl)


def _row_erro(l):
    return ('<tr data-status="%s">'
            '<td>%s</td>'
            '<td>%s</td>'
            '<td>%s</td>'
            '<td><a href="%s" target="_blank">abrir</a></td>'
            '<td style="color:#9ab;font-size:.78rem">%s</td>'
            '</tr>') % (
        l["status"],
        _pill(l["status"]),
        l.get("provedor", ""),
        l.get("nome", "")[:55],
        l.get("url_jogo", ""),
        l.get("detalhe", "")[:70],
    )


def _row_recheck(l):
    return ('<tr>'
            '<td>%s</td>'
            '<td>%s</td>'
            '<td>%s</td>'
            '<td><a href="%s" target="_blank">abrir</a></td>'
            '<td style="color:#9ab;font-size:.78rem">%s</td>'
            '</tr>') % (
        _pill(l["status"]),
        l.get("provedor", ""),
        l.get("nome", "")[:55],
        l.get("url_jogo", ""),
        l.get("detalhe", "")[:70],
    )


def gerar(res_dir=RES_DIR, dash=DASH, titulo="EstrelaBet",
          erros_reais=ERROS_REAIS, recheck_status=RECHECK_STATUS,
          info_recheck=INFO_RECHECK):
    arq, linhas = ultimo_resultado(res_dir)
    if not linhas:
        print("!! Nenhum resultado. Rode check_jogos.py antes.")
        return

    total    = len(linhas)
    cont     = Counter(l["status"] for l in linhas)
    data_str = linhas[0].get("data", datetime.now().strftime("%Y-%m-%d"))
    ok       = cont.get("OK", 0)
    taxa_ok  = (ok / total * 100) if total else 0

    erros   = [l for l in linhas if l["status"] in erros_reais]
    recheck = [l for l in linhas if l["status"] in recheck_status]
    ordem_erros   = [s for s in ORDEM if s in erros_reais]
    ordem_recheck = [s for s in ORDEM if s in recheck_status]

    por_prov = defaultdict(Counter)
    for l in linhas:
        por_prov[l["provedor"]][l["status"]] += 1

    # --- cards ---
    cards_ok = _card("OK", ok)
    cards_erros = "".join(
        _card(st, cont.get(st, 0))
        for st in ordem_erros
        if cont.get(st, 0) > 0
    )
    cards_recheck = "".join(
        _card(st, cont.get(st, 0))
        for st in ordem_recheck
        if cont.get(st, 0) > 0
    )

    # --- filter bar ---
    filtros = '<div class="filter-bar"><span>Filtrar:</span>'
    for st in ordem_erros:
        n = cont.get(st, 0)
        if n == 0:
            continue
        c   = CORES[st]
        lbl = LABELS[st]
        filtros += ('<button class="btn-f" data-status="%s" '
                    'style="border-color:%s;color:%s" '
                    'onclick="toggleFilter(this,\'%s\')">'
                    '%s (%d)</button>') % (st, c, c, st, lbl, n)
    filtros += ('<button class="btn-f" style="border-color:#445;color:#9ab" '
                'onclick="toggleAll(true)">Todos</button>')
    filtros += ('<button class="btn-f" style="border-color:#445;color:#9ab" '
                'onclick="toggleAll(false)">Nenhum</button>')
    filtros += '</div>'

    # --- tabela de erros ---
    rows_erros = "".join(_row_erro(l) for l in erros[:500])
    if len(erros) > 500:
        rows_erros += ('<tr><td colspan="5" style="color:#9ab;text-align:center">'
                       '... e mais %d (limite 500)</td></tr>') % (len(erros) - 500)

    # --- ranking de provedores (apenas erros reais) ---
    rank = sorted(
        por_prov.items(),
        key=lambda kv: sum(v for s, v in kv[1].items() if s in erros_reais),
        reverse=True
    )
    rows_rank = ""
    for prov, c in rank[:25]:
        f_ = sum(v for s, v in c.items() if s in erros_reais)
        if f_ == 0:
            continue
        tipos = " &nbsp; ".join(
            '<span class="pill" style="background:%s;font-size:.65rem">%s: %d</span>' % (
                CORES.get(s, "#888"), LABELS.get(s, s), v)
            for s, v in sorted(c.items())
            if s in erros_reais and v > 0
        )
        total_prov = sum(c.values())
        rows_rank += ('<tr>'
                      '<td>%s</td>'
                      '<td style="color:#e74c3c;font-weight:bold">%d</td>'
                      '<td>%s</td>'
                      '<td>%d</td>'
                      '</tr>') % (prov, f_, tipos, total_prov)

    # --- tabela de recheck ---
    rows_recheck = "".join(_row_recheck(l) for l in recheck)

    n_erros   = len(erros)
    n_recheck = len(recheck)

    parts = [
        '<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">',
        '<title>Monitor %s - %s</title>' % (titulo, data_str),
        '<style>', _CSS, '</style>',
        '</head><body>',
        '<h1>Monitor de Jogos &mdash; %s</h1>' % titulo,
        ('<p class="sub">%s &nbsp;&middot;&nbsp; %d jogos verificados &nbsp;&middot;&nbsp; '
         'taxa OK: <b style="color:#1faa59">%.1f%%</b></p>') % (data_str, total, taxa_ok),

        '<div class="cards-group">',
        '<div class="cards-label">Disponibilidade</div>',
        '<div class="cards">', cards_ok, cards_erros, '</div>',
        '</div>',
    ]

    if cards_recheck:
        parts += [
            '<div class="cards-group">',
            '<div class="cards-label">Pendente de Recheck '
            '<span class="recheck-badge">run separada</span></div>',
            '<div class="cards">', cards_recheck, '</div>',
            '</div>',
        ]

    parts += [
        '<h2>Falhas (%d jogos)</h2>' % n_erros,
        filtros,
        ('<div class="count-bar">'
         '<span><b id="n-vis">%d</b> falhas exibidas</span>'
         '<input type="search" id="busca" placeholder="Buscar por jogo ou provedor...">'
         '</div>') % n_erros,
        '<table id="tb-erros">',
        '<tr><th>Status</th><th>Provedor</th><th>Jogo</th><th>Link</th><th>Detalhe</th></tr>',
        rows_erros or '<tr><td colspan="5" style="color:#1faa59;text-align:center">Nenhuma falha encontrada</td></tr>',
        '</table>',

        '<h2>Provedores com mais falhas</h2>',
        '<table>',
        '<tr><th>Provedor</th><th>Falhas</th><th>Tipos</th><th>Total jogos</th></tr>',
        rows_rank or '<tr><td colspan="4" style="color:#1faa59;text-align:center">Nenhum</td></tr>',
        '</table>',
    ]

    if recheck:
        parts += [
            ('<h2>Recheck Pendente &mdash; '
             '<span style="color:#4a8fc7">%s</span> '
             '<span class="recheck-badge">%d jogos</span></h2>')
            % (" / ".join(ordem_recheck), n_recheck),
            ('<div class="section-info">%s'
             '<b>Nao sao contabilizados como erro</b> ate a run de recheck confirmar.'
             '</div>') % info_recheck,
            '<table>',
            '<tr><th>Status</th><th>Provedor</th><th>Jogo</th><th>Link</th><th>Detalhe</th></tr>',
            rows_recheck,
            '</table>',
        ]

    parts += [_JS, '</body></html>']

    html = "".join(parts)
    dash.parent.mkdir(parents=True, exist_ok=True)
    dash.write_text(html, encoding="utf-8")
    print(">> Dashboard gerado:", dash)
    print(">> Erros reais: %d | Recheck: %d | taxa OK: %.1f%%" % (n_erros, n_recheck, taxa_ok))


_CSS = """
* { box-sizing: border-box; }
body { font-family: Segoe UI, Arial, sans-serif; background: #0C121C; color: #eee; margin: 0; padding: 24px 32px; }
h1 { color: #FCD535; margin: 0 0 4px; font-size: 1.5rem; }
h2 { color: #FCD535; font-size: 1.05rem; margin: 28px 0 10px; border-bottom: 1px solid #1e293b; padding-bottom: 6px; }
.sub { color: #9ab; margin: 0 0 28px; font-size: .88rem; }
.section-info { color: #7ab3d4; background: #0f1e2e; border-left: 4px solid #4a8fc7; padding: 10px 16px; border-radius: 0 8px 8px 0; margin-bottom: 14px; font-size: .82rem; line-height: 1.5; }
.cards-group { margin-bottom: 20px; }
.cards-label { font-size: .72rem; text-transform: uppercase; letter-spacing: .09em; color: #7ab; margin-bottom: 8px; font-weight: 600; }
.cards { display: flex; gap: 12px; flex-wrap: wrap; }
.card { background: #131B29; border-radius: 10px; padding: 14px 22px; min-width: 110px; text-align: center; border-top: 4px solid #333; }
.num { font-size: 1.85rem; font-weight: bold; }
.lbl { font-size: .72rem; color: #9ab; margin-top: 3px; }
table { width: 100%; border-collapse: collapse; background: #131B29; border-radius: 10px; overflow: hidden; margin-bottom: 16px; font-size: .82rem; }
th, td { padding: 9px 13px; text-align: left; border-bottom: 1px solid #1a2535; }
th { background: #0f1622; color: #FCD535; font-size: .75rem; text-transform: uppercase; letter-spacing: .06em; font-weight: 600; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: #162030; }
.pill { padding: 3px 9px; border-radius: 20px; color: #fff; font-size: .68rem; font-weight: bold; white-space: nowrap; }
a { color: #5ab0ff; text-decoration: none; }
a:hover { text-decoration: underline; }
.filter-bar { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 10px; }
.filter-bar > span { color: #9ab; font-size: .78rem; margin-right: 2px; }
.btn-f { padding: 5px 14px; border-radius: 20px; border: 2px solid; cursor: pointer; font-size: .74rem; font-weight: bold; background: transparent; opacity: .35; transition: opacity .15s; }
.btn-f.on { opacity: 1; }
.btn-f:hover { opacity: .75; }
.count-bar { background: #131B29; border-radius: 8px; padding: 10px 16px; margin-bottom: 12px; font-size: .83rem; color: #9ab; display: flex; gap: 20px; align-items: center; flex-wrap: wrap; }
.count-bar b { color: #eee; font-size: 1.05rem; }
input[type=search] { background: #0f1622; border: 1px solid #2a3a52; border-radius: 20px; color: #eee; padding: 6px 14px; font-size: .8rem; outline: none; width: 260px; }
input[type=search]::placeholder { color: #5a7a8a; }
.recheck-badge { display: inline-block; background: #0f1e2e; border: 1px solid #4a8fc7; color: #7ab3d4; border-radius: 6px; padding: 1px 8px; font-size: .7rem; margin-left: 6px; vertical-align: middle; font-weight: normal; }
"""

_JS = """
<script>
var activeFilters = new Set();

function toggleFilter(btn, status) {
    if (activeFilters.has(status)) {
        activeFilters.delete(status);
        btn.classList.remove('on');
    } else {
        activeFilters.add(status);
        btn.classList.add('on');
    }
    applyFilters();
}

function applyFilters() {
    var busca = document.getElementById('busca');
    var q = busca ? busca.value.toLowerCase() : '';
    var rows = document.querySelectorAll('#tb-erros tr[data-status]');
    var vis = 0;
    rows.forEach(function(r) {
        var st = r.getAttribute('data-status');
        var txt = r.textContent.toLowerCase();
        var passFilter = activeFilters.size === 0 || activeFilters.has(st);
        var passSearch = q === '' || txt.indexOf(q) !== -1;
        r.style.display = (passFilter && passSearch) ? '' : 'none';
        if (passFilter && passSearch) vis++;
    });
    var el = document.getElementById('n-vis');
    if (el) el.textContent = vis;
}

function toggleAll(on) {
    document.querySelectorAll('.btn-f[data-status]').forEach(function(b) {
        var st = b.getAttribute('data-status');
        if (on) { activeFilters.add(st); b.classList.add('on'); }
        else    { activeFilters.delete(st); b.classList.remove('on'); }
    });
    applyFilters();
}

document.addEventListener('DOMContentLoaded', function() {
    toggleAll(true);
    var s = document.getElementById('busca');
    if (s) s.addEventListener('input', applyFilters);
});
</script>
"""


if __name__ == "__main__":
    gerar()
