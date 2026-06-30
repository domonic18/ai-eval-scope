"""eval-gateway — 第三方系统对接的评估接入服务。

对外提供 HTTP API（HMAC API Key 鉴权），异步调用评估器（agent-eval）评估，
经 observability 把结果回传到 Web 可观测平台，并提供任务状态查询。

设计基线：docs/arch/12第三方系统对接方案.md。
"""

from __future__ import annotations

__version__ = "0.1.0"
