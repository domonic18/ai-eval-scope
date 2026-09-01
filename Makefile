.PHONY: install dev test test-cov lint format clean golden web-install web-test web-typecheck docker-build docker-up docker-down docker-logs db-init db-migrate-prod hooks check executor-install executor-dev executor-test executor-lint executor-format executor-check

# 使用 uv 进行包管理（推荐）
# 需要先安装 uv: curl -LsSf https://astral.sh/uv/install.sh | sh
# 评估器代码在 evaluator/ 子目录（自包含，对称 web/）

install:
	cd evaluator && uv sync

dev:
	cd evaluator && uv sync --group dev

test:
	cd evaluator && uv run pytest tests/ -v --tb=short -n auto

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

# ─── Executor（评测执行；SCF 事件函数镜像，docs/arch/09 §7.7 / 12）───

executor-install:
	cd executor && uv sync

executor-dev:
	cd executor && uv sync --extra dev

executor-test:
	cd executor && uv run pytest tests/ -v --tb=short

executor-lint:
	cd executor && uv run ruff check eval_executor tests

executor-format:
	cd executor && uv run ruff format eval_executor tests
	cd executor && uv run ruff check --fix eval_executor tests

executor-check:
	cd executor && uv run ruff check eval_executor tests
	cd executor && uv run pytest tests/unit -q

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

# 全库建库/迁移统一应用（本地 docker 栈）：web(public, Prisma) 单一 schema，含 eval_jobs。
# 前置：make docker-up。schema 来源 = web/backend/prisma（详见 web/CLAUDE.md）。
db-init:
	@test -f .env || { echo "❌ 缺少 .env：请先 cp .env.example .env"; exit 1; }
	bash scripts/db-apply.sh

# 线上增量迁移：从 .secret/.env 读生产凭据，只补 web pending。
db-migrate-prod:
	bash scripts/db-apply-prod.sh

# ─── 代码规范（pre-commit + commitizen）───

# 安装 git hooks：pre-commit（代码检查）+ commit-msg（提交信息校验）
hooks:
	pre-commit install --install-hooks -t pre-commit -t commit-msg
	@echo "✅ git hooks 已安装（pre-commit + commit-msg）"

# 一键质量门禁：ruff 静态检查 + 单元测试
check:
	cd evaluator && uv run ruff check agent_eval tests
	cd evaluator && uv run pytest tests/unit -q
	cd executor && uv run ruff check eval_executor tests
	cd executor && uv run pytest tests/unit -q
