"""规则集目录路由（/v1/rule-sets）— HTTP 与 CLI 对等的评测集选择（docs/arch/13 §3.7）。

- GET /v1/rule-sets  列出可用规则集及其派生能力（LLM/视觉），调用方提交前即知需求
- POST /v1/rule-sets 上传自定义规则集（P1，暂未实现）
"""

from __future__ import annotations

from fastapi import APIRouter

from eval_gateway.rules.registry import catalog

router = APIRouter(prefix="/v1/rule-sets", tags=["rule-sets"])


@router.get("")
async def list_rule_sets() -> dict[str, list[dict]]:
    """规则集目录：每项含 id/name/description/capabilities/scopes。"""
    return {"rule_sets": catalog()}


@router.post("", status_code=501)
async def upload_rule_set() -> dict[str, str]:
    """上传自定义规则集（P1，暂未实现）。

    第三方自有评分细则可经此上传 YAML → 落库得 id（项目隔离），
    与 CLI 指向任意本地文件对等。详见 docs/arch/13 §3.7。
    """
    return {"error": "custom rule-set upload not implemented yet (P1)", "code": "NOT_IMPLEMENTED"}
