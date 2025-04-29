UV ?= uv                      # ensure `uv` is on PATH (brew, scoop, or `pipx install astral-uv`)

VENV := .venv
ACTIVATE := . $(VENV)/bin/activate  # POSIX‑friendly source shortcut

.PHONY: bootstrap db-up db-down migrate init-alembic test clean

bootstrap: ## create uv venv, install deps, spin up DB, run migrations
	$(UV) venv $(VENV)
	$(UV) pip install -e .[dev]     # editable install + dev extras
	make db-up
	make init-alembic
	$(ACTIVATE) && alembic upgrade head
	@echo "🏗️  Environment ready. Run: '$(ACTIVATE)' to enter the venv."

init-alembic: ## one‑time alembic init (idempotent)
	@if [ ! -f alembic/env.py ]; then \
		$(ACTIVATE) && alembic init alembic; \
		sed -e 's/^script_location.*/script_location = alembic/' \
			-i '' alembic.ini 2>/dev/null || sed -i 's/^script_location.*/script_location = alembic/' alembic.ini; \
		echo "# custom env tweaks can go here" >> alembic/env.py; \
		echo "✔ Alembic initialised"; \
	fi

# --- docker helpers ---

db-up:
	docker compose up -d postgres

db-down:
	docker compose down

# --- misc tasks ---

migrate:
	$(ACTIVATE) && alembic upgrade head

test:
	$(ACTIVATE) && pytest -q

clean:
	rm -rf $(VENV) pgdata __pycache__ .pytest_cache alembic alembic.ini