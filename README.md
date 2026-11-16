# Monitor de Jogos - EstrelaBet

Health-check diario dos ~3716 jogos do cassino. Detecta 404, erros 5xx, sessao expirada, jogos que nao carregam e timeouts.

## Por que Playwright (nao requests)?
O site usa Cloudflare + bloqueio geografico: HTTP cru retorna 403 (Pais indisponivel). Usamos Chrome real (Playwright) que passa pela protecao, roda na sua maquina (Brasil), mantem a sessao logada e intercepta a rede do site p/ descobrir a API interna.

## Instalacao (uma vez)
    pip install -r requirements.txt
    playwright install chromium
Copie config/.env.example para config/.env e preencha email/senha da conta TESTE.

## Uso
    python main.py --login --coletar   # 1a vez
    python main.py                     # dias seguintes
Abra dashboard/index.html para ver o resultado.

## Estrutura
    src/login.py           login -> data/sessao.json
    src/coletar_jogos.py   monta data/jogos.csv (+ espiao de API)
    src/check_jogos.py     verifica cada jogo e classifica a falha
    src/relatorio.py       gera dashboard/index.html
    main.py                orquestra tudo

## Status por jogo
OK, ERRO_404, ERRO_HTTP, SESSAO_EXPIRADA, NAO_CARREGOU, TIMEOUT.

## Padroes de URL
    Provedor: /cassino-online/studio/<slug>
    Jogo:     /gameplay/<slug>

# Monitor de Jogos - Alri (alri.com)

Mesmo fluxo, modulos em src/alri/ e dados em data/alri/.

## Uso
Preencha ALRI_EMAIL / ALRI_SENHA em config/.env (sem elas, a janela abre para login manual).

    python main_alri.py --teste        # login + coleta + 10 jogos
    python main_alri.py                # run completa
    python main_alri.py --sem-login --sem-coleta   # reaproveita sessao e lista
Abra dashboard/alri.html para ver o resultado.

O login roda a cada execucao: a sessao expira apos 24h ociosa. Deslogado, todo o
site redireciona para /waitlist/.

## Como funciona
- Coleta: /providers/ -> /casino/providers/<slug>/ (rola a pagina) -> /casino/games/<seoSlug>/.
  Cruza com o catalogo publico stellar-assets.alri.com/casino/manifest/alri/catalog.json
  para obter o gameCode; jogos do catalogo ausentes da pagina entram com origem=catalogo.
- Launch: POST https://api.pam.alri.com/api/v1/games/play {game: gameCode, device}
  -> {url}. Erro vem como {code, error, details.reason}.
- Token: localStorage brand-auth-token (salvo no storage_state).

## Status
OK, ERRO_ALEA (TraceId da Alea, ex: BGaming), ERRO_IFRAME (texto de erro no frame
do provedor, ex: Play'n GO "Something went wrong"), ERRO_REDE (frame do provedor caiu
em chrome-error://, ex: Galaxsys), NAO_CARREGOU (sem iframe), ERRO_404, ERRO_HTTP,
ERRO_LAUNCH, BLOQUEADO, KYC, SESSAO_EXPIRADA, COMING_SOON, SEM_LAUNCH, TIMEOUT,
SITE_INACESSIVEL (a propria pagina da Alri recusou a conexao).
Env opcionais: ALRI_ABAS (padrao 4), ALRI_HEADLESS=1, ALRI_LIMITE.
