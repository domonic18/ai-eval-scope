.PHONY: install dev test lint format clean golden web-build web-dev docker-build docker-up docker-down docker-logs

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
	# 清理 Web Portal 构建产物
	rm -rf web/backend/public
	rm -rf web/frontend/dist
	rm -rf web/backend/node_modules
	rm -rf web/frontend/node_modules

golden:
	uv run pytest tests/golden/ -v

web-build:
	cd web/frontend && npm install && npm run build
	rm -rf web/backend/public
	cp -r web/frontend/dist web/backend/public

web-dev:
	cd web/backend && npm install && npm run dev &
	cd web/frontend && npm install && npm run dev

# ─── Docker targets ───

docker-build:
	docker build -f web/Dockerfile -t agent-eval-web:latest .

docker-up:
	docker compose up -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f web-portal
