PYTHON ?= python
UVICORN ?= uvicorn
NPM ?= npm

.PHONY: install install-web infra migrate seed test audit dashboard dashboard-api dashboard-web dashboard-build dashboard-lint dashboard-legacy bot

install:
	$(PYTHON) -m pip install -e ".[dev]"

install-web:
	$(NPM) --prefix web ci

infra:
	docker compose up -d postgres redis

migrate:
	alembic upgrade head

seed:
	$(PYTHON) -m scripts.seed

test:
	$(PYTHON) -m pytest -q

audit:
	$(PYTHON) scripts/audit.py

dashboard: dashboard-web

dashboard-api:
	$(UVICORN) api.main:app --reload --host 127.0.0.1 --port 8000

dashboard-web:
	$(NPM) --prefix web run dev -- --host 127.0.0.1

dashboard-build:
	$(NPM) --prefix web run build

dashboard-lint:
	$(NPM) --prefix web run lint

dashboard-legacy:
	$(UVICORN) app.dashboard.main:app --reload --host 127.0.0.1 --port 8000

bot:
	$(PYTHON) main.py
