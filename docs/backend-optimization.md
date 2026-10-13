# Backend: segunda fase de melhorias

## O que mudou

- JWT de acesso agora dura 15 minutos. A aplicação valida emissor, audiência, assinatura e claims obrigatórias.
- O dashboard usa cookies `HttpOnly`, `SameSite` configurável e proteção CSRF nas operações que alteram dados.
- Sessões são persistidas em `api_auth_sessions`. O banco guarda o hash do refresh token, os tokens OAuth do Discord são criptografados, e o refresh token é rotacionado. Uma janela de 5 segundos evita que duas abas revoguem a sessão por uma renovação simultânea. Reutilização fora da janela revoga a sessão.
- Adicionada migração `0014_api_auth_sessions.py` para sessões e `0015_audit_query_indexes.py` para índices de auditoria e moderação.
- Adicionado rate limit distribuído com Redis para autenticação, alterações e listas de consulta mais caras. Se Redis não estiver disponível, as rotas protegidas pelo limitador respondem 503.
- O `overview` reúne as sete contagens em uma instrução SQL, reduzindo round trips ao banco. Não foi possível medir tempo real sem uma base representativa.
- Escritas do AutoMod agora bloqueiam a linha do servidor (`SELECT ... FOR UPDATE`) durante a transação, serializando mutações de configuração, regras e listas para a mesma guilda.
- As listagens limitam o número de página a 10.000. O pool de conexões PostgreSQL pode ser configurado com `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT` e `DB_POOL_RECYCLE`. Os valores são validados antes de criar o engine.
- Logs de requisição usam ID, método, caminho sem query string, status e duração. Erros internos retornam mensagem genérica e ID da requisição.
- O endpoint autenticado `/health/dependencies` mostra estados da API, banco, Redis e heartbeat do bot.
- O alias de autenticação `/auth` da API foi removido. As rotas oficiais estão em `/api/v1/auth`; o dashboard legado conserva o próprio fluxo no seu aplicativo.

## Comandos de validação

```powershell
python -m compileall -q api app tests scripts main.py
python scripts/audit.py
python -m pytest -q
python -m alembic heads
npm --prefix web run lint
npm --prefix web run build
```

## Resultado desta execução

- Testes Python: 324 aprovados.
- Compilação Python: aprovada.
- Auditoria do repositório: aprovada.
- Migração head: `0015_audit_query_indexes`.
- ESLint: aprovado sem warnings.
- Build React: bloqueado porque o pacote local de Rolldown não inclui o binding Linux previsto pelo lockfile. O registry npm estava indisponível, então as dependências não foram atualizadas.
- Ruff: indisponível no ambiente.
- O pacote não contém workflow existente em `.github/workflows`; a configuração de CI permanece pendente no repositório de hospedagem.

## Pendências de implantação

- Rodar migrações em uma cópia de PostgreSQL e testar o fluxo de login com Discord real.
- Confirmar Redis em execução, porque os endpoints cobertos pelo rate limiter falham fechados com 503 sem ele.
- Rodar instalação limpa e build React em ambiente que consiga baixar dependências.
- Não alterar `.env` durante a auditoria. Rever a configuração operacional de `APP_SECRET_KEY`, `AUTH_COOKIE_SAMESITE`, `CORS_ALLOWED_ORIGINS`, `DASHBOARD_URL`, `DISCORD_REDIRECT_URI`, `REDIS_URL` e os parâmetros opcionais do pool sem compartilhar os valores.


## Estatísticas avançadas - atualização de 12 de outubro de 2026

A seção de resultados acima é um registro histórico da execução da segunda fase. A versão atual adiciona a migração `0016_advanced_analytics` e os fluxos de estatísticas/counters/cargos descritos em [`advanced-analytics.md`](advanced-analytics.md). A cadeia de migrações atual termina em `0016_advanced_analytics`. Na validação mais recente, os testes Python passaram (`356 passed`), a compilação Python e as auditorias disponíveis foram aprovadas. O lint e o build React permanecem não verificados neste ambiente porque a instalação npm não completou; também faltam testes em serviços reais de homologação.
