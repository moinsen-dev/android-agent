# Justfile for Ghost in the Droid
# https://github.com/casey/just

set dotenv-load

python := "python3"
pip := "pip3"
npm := "npm"
venv_dir := ".venv"
venv_python := venv_dir / "bin" / "python"
venv_pip := venv_dir / "bin" / "pip"

export PATH := venv_dir / "bin" + ":" + env_var_or_default("PATH", "")

# ── High-level workflows ───────────────────────────────────────────────────

# Install everything: Python deps, frontend deps, and a starter .env
install: python-deps frontend-deps env-file
	@echo "Install complete. Run 'just dev' to start."

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
	@test -d {{venv_dir}} || {{python}} -m venv {{venv_dir}}
	{{venv_pip}} install -e ".[all]"

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

# ── Skills ─────────────────────────────────────────────────────────────────

skill-search query:
	{{python}} -m gitd.cli skill search {{query}}

skill-install name:
	{{python}} -m gitd.cli skill install {{name}}

skill-list:
	{{python}} -m gitd.cli skill list

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
