PYTHON ?= uv run
NPM ?= npm
BACKEND_HOST ?= 127.0.0.1
BACKEND_PORT ?= 8765
CONTAINER_ENGINE ?= docker

.PHONY: help install install-python install-frontend install-hooks dev-api dev-frontend demo-up demo-down demo-logs pre-commit audit test lint check-format build-frontend clean

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
	$(PYTHON) uvicorn stempelwerk.app:create_app --factory --reload --host $(BACKEND_HOST) --port $(BACKEND_PORT)

dev-frontend: ## Start the Vite frontend development server
	$(NPM) --prefix frontend run dev

demo-up: ## Start the container demo environment (CONTAINER_ENGINE=docker|podman)
	$(CONTAINER_ENGINE) compose -f demo/compose.yaml up --build -d

demo-down: ## Stop the container demo environment
	$(CONTAINER_ENGINE) compose -f demo/compose.yaml down

demo-logs: ## Follow container demo logs
	$(CONTAINER_ENGINE) compose -f demo/compose.yaml logs -f

pre-commit: ## Run pre-commit hooks on all tracked files
	$(PYTHON) pre-commit run --all-files

audit: ## Audit locked Python dependencies
	uv audit --locked

test: ## Run Python tests
	$(PYTHON) pytest

lint: ## Run Python lint checks
	$(PYTHON) ruff check .

check-format: ## Check Python formatting with Ruff
	$(PYTHON) ruff format --check

build-frontend: ## Build the frontend
	$(NPM) --prefix frontend run build

clean: ## Remove local test/build artifacts
	rm -rf .pytest_cache .ruff_cache htmlcov
	rm -rf frontend/dist
