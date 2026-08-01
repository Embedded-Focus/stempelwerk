PYTHON ?= uv run
NPM ?= npm
BACKEND_HOST ?= 127.0.0.1
BACKEND_PORT ?= 8765

.PHONY: help install install-python install-frontend install-hooks dev-api dev-frontend pre-commit test lint build-frontend clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-24s\033[0m %s\n", $$1, $$2}'

install: install-python install-frontend install-hooks ## Install dependencies and Git hooks

install-python: ## Install Python dependencies
	uv sync

install-frontend: ## Install frontend dependencies
	$(NPM) --prefix frontend install

install-hooks: ## Install pre-commit hooks
	$(PYTHON) pre-commit install

dev-api: ## Start the FastAPI development server
	$(PYTHON) uvicorn org_clock_calendar.app:create_app --factory --reload --host $(BACKEND_HOST) --port $(BACKEND_PORT)

dev-frontend: ## Start the Vite frontend development server
	$(NPM) --prefix frontend run dev

pre-commit: ## Run pre-commit hooks on tracked and untracked files
	$(PYTHON) pre-commit run --files $$(git ls-files --cached --others --exclude-standard)

test: ## Run Python tests
	$(PYTHON) pytest

lint: ## Run Python lint checks
	$(PYTHON) ruff check .

build-frontend: ## Build the frontend
	$(NPM) --prefix frontend run build

clean: ## Remove local test/build artifacts
	rm -rf .pytest_cache .ruff_cache htmlcov
	rm -rf frontend/dist
