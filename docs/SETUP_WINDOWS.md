# Setup on Windows

## Requirements

Install Python 3.12 or newer, Docker Desktop and a Discord application with a bot user.

## Environment

Copy `.env.example` to `.env`.

Set the Discord bot token, application client ID, application client secret, dashboard redirect URI and application secret. Generate a strong secret key with:

`py -3.12 -c "import secrets; print(secrets.token_urlsafe(48))"`

Copy the output into `APP_SECRET_KEY` in `.env`. The key must be at least 32 characters. In production, `DISCORD_REDIRECT_URI` and `DASHBOARD_URL` must use HTTPS. Do not commit `.env`.

## Infrastructure

From the project directory run:

`docker compose up -d postgres redis`

This starts PostgreSQL (required for persisted OAuth sessions and dashboard data) and Redis (the shared API rate limiter). In `APP_ENV=development`, the API can temporarily use a bounded per-process rate limiter when Redis is unavailable; production still requires Redis and fails closed if it is down.

### Redis não conecta no Windows

O bot/API executados diretamente no Windows devem usar `REDIS_URL=redis://127.0.0.1:6379/0`. O hostname `redis` costuma funcionar somente para processos dentro da mesma rede Docker do serviço Redis. Inicie e verifique o container:

`docker compose up -d redis`

`docker compose ps redis`

`docker compose exec redis redis-cli ping`

O último comando deve responder `PONG`. Se responder `PONG`, mas o bot continuar mostrando erros, use `127.0.0.1` em vez de `localhost` no `REDIS_URL` quando Python roda diretamente no Windows (o Docker publica a porta em IPv4). O runtime agora também normaliza `localhost` para IPv4 automaticamente no Windows. Reinicie o bot/API e execute `.venv\Scripts\python.exe scripts\check_redis.py`.

O fallback de cooldown local é apenas de desenvolvimento e não é compartilhado entre processos. O heartbeat Redis é usado para observabilidade; durante uma falha contínua, o bot continua tentando a cada 30 segundos, mas limita os avisos a um por cinco minutos e registra quando a conexão se recupera. Os logs incluem apenas a classe da exceção, sem expor URL ou credenciais. Para testar a conexão configurada no `.env` diretamente, execute `.venv\Scripts\python.exe scripts\check_redis.py`. O Compose também marca o Redis como `healthy` somente quando `redis-cli ping` funciona.

## Python environment

Create a virtual environment:

`py -3.12 -m venv .venv`

Install dependencies:

`.\.venv\Scripts\python.exe -m pip install -r requirements.txt`

Verifique o ambiente com `.\.venv\Scripts\python.exe scripts\doctor.py` antes de iniciar o bot.

For development dependencies use:

`.\.venv\Scripts\python.exe -m pip install -e ".[dev]"`

## Database

Run:

`.\.venv\Scripts\python.exe -m alembic upgrade head`

Run `.\.venv\Scripts\python.exe scripts\doctor.py` before starting the bot.

Run `.\.venv\Scripts\python.exe -m alembic upgrade head` after installing a newer BN Bot version.

Seed one Discord guild:

`.\.venv\Scripts\python.exe -m scripts.seed`

## Dashboard web oficial

Configure no Developer Portal a URI OAuth2 de redirecionamento exatamente como `DISCORD_REDIRECT_URI` em `.env`. O dashboard oficial usa o frontend React em `web/` e a API em `api/`. Mantenha os dois processos ativos.

Na primeira janela do terminal, inicie a API:

`.\.venv\Scripts\python.exe -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000`

Na segunda janela do CMD, inicie o frontend:

`npm --prefix web run dev -- --host localhost`

Abra `http://localhost:5173`. Em modo de desenvolvimento, o frontend já direciona as chamadas para a API na porta 8000; não é necessário definir `VITE_API_URL` para a configuração local padrão.

O `DASHBOARD_URL` deve apontar para o frontend, normalmente `http://localhost:5173` no ambiente local. No Discord, `/dashboard` envia um botão privado que abre esse endereço; depois, entre com sua conta Discord.

## Bot

Run in a separate terminal:

`.\.venv\Scripts\python.exe main.py`

Enable the required Discord intents in the Developer Portal before using message analytics or member activity collection.


### Sincronização de comandos em desenvolvimento

Defina `DISCORD_GUILD_ID` no `.env` para que o BN Bot publique a árvore atual diretamente na sua guild durante o desenvolvimento. Isso evita o uso de uma assinatura global antiga enquanto o Discord propaga alterações globais.
