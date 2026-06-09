.PHONY: install dev test lint format clean golden

# 使用 uv 进行包管理（推荐）
# 需要先安装 uv: curl -LsSf https://astral.sh/uv/install.sh | sh

install:
	uv sync

dev:
	uv sync --extra dev

test:
	uv run pytest tests/ -v --tb=short

test-cov:
	uv run pytest tests/ -v --cov=agent_eval --cov-report=term-missing --cov-report=html

lint:
	uv run ruff check agent_eval/ tests/

format:
	uv run ruff format agent_eval/ tests/
	uv run ruff check --fix agent_eval/ tests/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf htmlcov/ .coverage .pytest_cache/
	rm -rf dist/ build/ *.egg-info/

golden:
	uv run pytest tests/golden/ -v
