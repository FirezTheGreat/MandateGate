# MandateGate commands (CLAUDE.md §12).
# Recipes must run under both sh and Windows cmd.exe (GNU make on Windows falls back to
# cmd when no sh is on PATH): only `cd dir && cmd`, no cp/rm/export.

S ?= hero_attack
MODE ?= gated
AGENT ?= llm
STEP_UP ?= wait

.PHONY: setup gate pay web dev test scenario attacks reset

setup:
	cd backend && uv sync
	cd frontend && npm install
	uv run --no-project python backend/scripts/init_env.py

gate:
	cd backend && uv run --env-file ../.env uvicorn app.main:app --port 8000 --reload --reload-dir app

pay:
	cd backend && uv run --env-file ../.env uvicorn payment_service.main:app --port 8001 --reload --reload-dir payment_service --reload-dir app

web:
	cd frontend && npm run dev

# concurrently kills the whole process tree on Ctrl+C (incl. uvicorn reloader children on Windows).
dev:
	cd frontend && npx concurrently --kill-others -n gate,pay,web -c blue,magenta,green "make -C .. gate" "make -C .. pay" "make -C .. web"

test:
	cd backend && uv run pytest tests -q

scenario:
	cd backend && uv run --env-file ../.env python -m agents.run_scenario --scenario $(S) --mode $(MODE) --agent $(AGENT) --on-step-up $(STEP_UP)

attacks:
	cd backend && uv run --env-file ../.env python -m attacks.run_suite

reset:
	cd backend && uv run --env-file ../.env python -m scripts.reset
