.PHONY: install dev test test-cov lint format clean golden web-install web-test web-typecheck docker-build docker-up docker-down docker-logs hooks check

# 使用 uv 进行包管理（推荐）
# 需要先安装 uv: curl -LsSf https://astral.sh/uv/install.sh | sh
# 评估器代码在 evaluator/ 子目录（自包含，对称 web/）

install:
	cd evaluator && uv sync

dev:
	cd evaluator && uv sync --extra dev

test:
	cd evaluator && uv run pytest tests/ -v --tb=short

test-cov:
	cd evaluator && uv run pytest tests/ -v --cov=agent_eval --cov-report=term-missing --cov-report=html

lint:
	cd evaluator && uv run ruff check agent_eval/ tests/

format:
	cd evaluator && uv run ruff format agent_eval/ tests/
	cd evaluator && uv run ruff check --fix agent_eval/ tests/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf htmlcov/ .coverage .pytest_cache/
	rm -rf dist/ build/ *.egg-info/
	# 清理可观测平台后端依赖产物
	rm -rf web/backend/node_modules

golden:
	uv run pytest tests/golden/ -v

# ─── 可观测平台后端（web/backend，纯 JSON API）───

web-install:
	cd web/backend && npm install

web-test:
	cd web/backend && npm test

web-typecheck:
	cd web/backend && npm run typecheck

# ─── Docker（平台栈：postgres + minio + web，配置见根 docker-compose.yml + .env）───

docker-build:
	docker compose build web

docker-up:
	@test -f .env || { echo "❌ 缺少 .env：请先 cp .env.example .env 并填入凭据"; exit 1; }
	docker compose up -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f web

# ─── 代码规范（pre-commit + commitizen）───

# 安装 git hooks：pre-commit（代码检查）+ commit-msg（提交信息校验）
hooks:
	pre-commit install --install-hooks -t pre-commit -t commit-msg
	@echo "✅ git hooks 已安装（pre-commit + commit-msg）"

# 一键质量门禁：ruff 静态检查 + 单元测试
check:
	cd evaluator && uv run ruff check agent_eval tests
	cd evaluator && uv run pytest tests/unit -q
