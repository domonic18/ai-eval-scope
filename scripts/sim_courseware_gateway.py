#!/usr/bin/env python3
"""模拟课件制作平台调用 eval-gateway 提交课件质量评估（端到端冒烟）。

场景：课件平台无法装 Python/跑 CLI，改为以 HMAC API Key 调用 gateway。
本脚本扮演课件平台侧 SDK：用与 gateway 完全一致的 HMAC 算法签名（复用 eval_gateway.auth.crypto），
提交一份课件 HTML，轮询任务状态，打印评估指标与 web 平台链接。

用法（从仓库根）：
  cd gateway && uv run python ../scripts/sim_courseware_gateway.py
环境：根 .env 需有 AGENT_EVAL_PUBLIC_KEY / AGENT_EVAL_SECRET_KEY（复用 ingest scope 的 API Key）。
默认 rule_set_id=format-only（纯格式门控，无 LLM 依赖，便于离线冒烟）。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# 复用 gateway 的 HMAC 实现，确保签名算法与验签 100% 一致
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "gateway"))
from eval_gateway.auth.crypto import sign_hmac  # noqa: E402

GATEWAY = os.environ.get("GATEWAY_URL", "http://localhost:9102").rstrip("/")
# 默认走真实课件规则集（coursework-default：含 LLM Judge 常识/软约束/偏好，需 DEEPSEEK_API_KEY）。
# 如需纯格式冒烟（无 LLM）：RULE_SET_ID=format-only。
RULE_SET = os.environ.get("RULE_SET_ID", "coursework-default")
POLL_INTERVAL = 2.0
POLL_TIMEOUT = 240.0

SAMPLE_LESSON_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>三角函数入门 · 第一课时</title></head>
<body>
<h1>三角函数入门</h1>
<h2>教学目标</h2>
<ol><li>理解正弦/余弦/正切的定义</li><li>掌握单位圆与三角函数的关系</li></ol>
<h2>核心内容</h2>
<p>在直角三角形中，正弦 = 对边/斜边，余弦 = 邻边/斜边，正切 = 对边/邻边。</p>
<h2>小结</h2>
<p>本节介绍了三角函数的基本定义，下节将进入单位圆与诱导公式。</p>
</body></html>
"""


def load_env() -> None:
    env_file = _REPO / ".env"
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def _request(method: str, path: str, public_key: str, secret: str, body: bytes | None) -> dict:
    sig = sign_hmac(secret, method, path, body)
    headers = {"Authorization": f"Eval {public_key}:{sig}"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = body
    req = urllib.request.Request(GATEWAY + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"{method} {path} → HTTP {exc.code}: {detail}") from exc


def submit(public_key: str, secret: str) -> dict:
    body = json.dumps(
        {"content": {"filename": "lesson.html", "text": SAMPLE_LESSON_HTML}, "rule_set_id": RULE_SET},
        ensure_ascii=False,
    ).encode("utf-8")
    return _request("POST", "/v1/jobs", public_key, secret, body)


def poll(public_key: str, secret: str, job_id: str) -> dict:
    return _request("GET", f"/v1/jobs/{job_id}", public_key, secret, None)


def main() -> int:
    load_env()
    pk = os.environ.get("AGENT_EVAL_PUBLIC_KEY")
    sk = os.environ.get("AGENT_EVAL_SECRET_KEY")
    if not pk or not sk:
        print("❌ 缺少 AGENT_EVAL_PUBLIC_KEY / AGENT_EVAL_SECRET_KEY（见根 .env）", file=sys.stderr)
        return 2

    print(f"== 模拟课件平台 → gateway（{GATEWAY}），rule_set_id={RULE_SET} ==")
    print("① 提交课件评估（lesson.html）...")
    sub = submit(pk, sk)
    job_id = sub["job_id"]
    print(f"   ✅ 已受理 job_id={job_id} status={sub['status']} poll_url={sub['poll_url']}")

    print("② 轮询任务状态 ...")
    job: dict = sub
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        job = poll(pk, sk, job_id)
        status = job.get("status")
        print(f"   ... status={status}")
        if status in ("completed", "failed"):
            break
    else:
        print(f"⚠️ 超时（{POLL_TIMEOUT}s）仍未结束，最后状态：{job.get('status')}")

    print("\n========== 评估结果 ==========")
    print(json.dumps(job, ensure_ascii=False, indent=2))

    status = job.get("status")
    if status == "completed":
        web_url = job.get("web_run_url")
        print(f"\n✅ 评估完成。web 平台查看：{web_url}")
        return 0
    print(f"\n❌ 评估未成功（status={status}），见上方 error 字段。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
