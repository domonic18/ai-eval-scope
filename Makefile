.PHONY: install dev test lint format clean

PYTHON ?= python3
PIP ?= pip3

install:
	$(PIP) install -e .

dev:
	$(PIP) install -e ".[dev]"

test:
	pytest tests/ -v --tb=short

test-cov:
	pytest tests/ -v --cov=agent_eval --cov-report=term-missing --cov-report=html

lint:
	ruff check agent_eval/ tests/
	mypy agent_eval/

format:
	ruff format agent_eval/ tests/
	ruff check --fix agent_eval/ tests/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf htmlcov/ .coverage .pytest_cache/
	rm -rf dist/ build/ *.egg-info/

golden:
	pytest tests/golden/ -v
