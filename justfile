# Justfile for Ghost in the Droid
# https://github.com/casey/just

set dotenv-load

venv_dir := ".venv"
system_python := "python3"
system_pip := "pip3"
python := venv_dir / "bin" / "python"
pip := venv_dir / "bin" / "pip"
npm := "npm"

export PATH := venv_dir / "bin" + ":" + env_var_or_default("PATH", "")

# ── High-level workflows ───────────────────────────────────────────────────

# Install everything: Python deps, frontend deps, and a starter .env
install: python-deps frontend-deps env-file cli-wrapper
	@echo ""
	@echo "Install complete."
	@echo ""
	@echo "Run the app:            just dev"
	@echo "Run CLI commands:       just cli <command>"
	@echo "Examples:"
	@echo "  just cli skill list"
	@echo "  just cli skill search tiktok"
	@echo "  just cli skill install tiktok"
	@echo ""
	@echo "Or activate the venv manually:"
	@echo "  source .venv/bin/activate"
	@echo "  android-agent skill list"

# Update repo and dependencies
update:
	git pull
	{{pip}} install -e ".[all]" --upgrade
	cd frontend && {{npm}} install

# Start backend + frontend in parallel (Ctrl+C stops both)
dev:
	#!/usr/bin/env bash
	set -euo pipefail
	just backend &
	just frontend &
	wait

# Build the production frontend
build: frontend-deps
	cd frontend && {{npm}} run build

# ── Individual services ────────────────────────────────────────────────────

# Start the FastAPI backend
backend:
	{{python}} run.py

# Start the Vite frontend dev server
frontend:
	cd frontend && {{npm}} run dev

# ── Python environment ─────────────────────────────────────────────────────

# Create venv and install Python dependencies
python-deps:
	@test -d {{venv_dir}} || {{system_python}} -m venv {{venv_dir}}
	{{pip}} install -e ".[all]"

# ── Frontend ───────────────────────────────────────────────────────────────

# Install Node dependencies
frontend-deps:
	cd frontend && {{npm}} install

# ── Code quality ───────────────────────────────────────────────────────────

# Run the linter
check:
	ruff check gitd tests

# Auto-format Python code
fmt:
	ruff format gitd tests

# Run all checks (lint + type-check frontend)
test: check
	cd frontend && {{npm}} run type-check
	{{python}} -m pytest tests/ -v --tb=short

# ── Database ───────────────────────────────────────────────────────────────

db-migrate:
	alembic upgrade head

db-revision msg:
	alembic revision --autogenerate -m "{{msg}}"

# ── CLI ────────────────────────────────────────────────────────────────────

# Run the android-agent CLI inside the managed venv
cli *args:
	{{python}} -m gitd.cli {{args}}

# Create a project-root wrapper so `./android-agent` works without activating the venv
cli-wrapper:
	#!/usr/bin/env bash
	set -euo pipefail
	cat > android-agent <<'EOF'
	#!/usr/bin/env bash
	set -euo pipefail
	SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
	exec "$SCRIPT_DIR/.venv/bin/python" -m gitd.cli "$@"
	EOF
	chmod +x android-agent

# ── Global uv tool install ─────────────────────────────────────────────────

# Install android-agent as a global uv tool (available everywhere as `android-agent`)
tool-install:
	uv tool install --reinstall ".[all]"

# Uninstall the global uv tool
tool-uninstall:
	uv tool uninstall ghost-in-the-droid

# ── Skills ─────────────────────────────────────────────────────────────────

skill-search query:
	just cli skill search {{query}}

skill-install name:
	just cli skill install {{name}}

skill-list:
	just cli skill list

# ── MCP ────────────────────────────────────────────────────────────────────

mcp-install:
	claude mcp add android-agent -- uvx --from ghost-in-the-droid android-agent-mcp

# ── Utilities ──────────────────────────────────────────────────────────────

# Create .env from example if it doesn't exist
env-file:
	@test -f .env || cp .env.example .env

# Remove build artifacts and caches
clean:
	rm -rf frontend/dist
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +

# Show available recipes
help:
	@just --list
