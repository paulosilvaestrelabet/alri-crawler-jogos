# Instrucoes do Claude Project: Monitor de Jogos EstrelaBet

## Contexto
Sou da equipe da EstrelaBet (operacao autorizada). Projeto Python que monitora diariamente, na minha maquina, a disponibilidade de TODOS os ~3716 jogos do cassino: paginas 404, erros 5xx, jogos que nao carregam (tela branca / iframe vazio) e casos onde a sessao logada caiu.

## Fatos tecnicos ja validados
- Site com Cloudflare + bloqueio geografico: HTTP cru = 403. NUNCA usar requests/httpx puro. Usar Playwright (Chrome real), na minha maquina, logado.
- Maioria dos jogos so abre logado. Conta de TESTE; login email+senha, SEM captcha e SEM 2FA.
- URLs: /cassino-online/providers ; /cassino-online/studio/<slug> ; /gameplay/<slug> (ex: /gameplay/aviator).
- Roda DIARIAMENTE em Windows.

## Arquitetura
login.py -> coletar_jogos.py -> check_jogos.py -> relatorio.py (main.py orquestra).
Classificacao: OK / ERRO_404 / ERRO_HTTP / SESSAO_EXPIRADA / NAO_CARREGOU / TIMEOUT.

## Como o Claude deve ajudar
- Ajustar seletores CSS/XPath quando o site mudar.
- Evoluir classificacao de falhas e otimizar paralelismo.
- Trocar scrape por API interna quando descoberta (data/apis_descobertas.json).
- Python compativel com Windows, SEM acentos em comentarios. Preferir Playwright.
