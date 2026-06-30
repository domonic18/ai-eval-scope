#!/usr/bin/env python3
"""模拟课件平台以「课件包(zip)」方式调用 eval-gateway 提交单元级评估（端到端）。

与 sim_courseware_gateway.py（单文件内联）互补：本脚本验证**单元/包级**评估全链路——
把一个课件目录（含多文件、目录树，如 samples/大单元学习总导）打成 zip，
按 docs/arch/12 §4.3 的 multipart 上传约定提交给 gateway：

    POST /v1/jobs
    Content-Type: multipart/form-data; boundary=...
    -- file = <courseware.zip>          （单元 zip，gateway 解包后整体打包为 ExecutionPackage）
    -- rule_set_id = coursework-default （或 format-only）

gateway 物化(zip→解包→scope=unit) → PackageBuilder 打包 → eval_packages() 评估 →
observability 回传 web。本脚本轮询任务态，打印指标与 web 平台链接。

签名：复用 eval_gateway.auth.crypto.sign_hmac，对**原始 multipart body 字节**签名
（gateway verify_api_key 先 await request.body() 缓存再 form 解析，故 multipart 可验签）。

用法（从仓库根）：
  cd gateway && uv run python ../scripts/sim_courseware_package_gateway.py
环境变量（均可选，有默认）：
  SAMPLE_DIR       待评估课件目录（默认 samples/大单元学习总导）
  RULE_SET_ID      规则集（默认 coursework-default；纯格式冒烟用 format-only）
  GATEWAY_URL      gateway 地址（默认 http://localhost:9102）
  POLL_TIMEOUT     轮询超时秒（默认 600，大单元 + LLM 较慢）
  AGENT_EVAL_PUBLIC_KEY / AGENT_EVAL_SECRET_KEY  HMAC API Key（见根 .env，ingest scope）
"""

from __future__ import annotations

import io
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

# 复用 gateway 的 HMAC 实现，确保签名算法与验签 100% 一致
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "gateway"))
from eval_gateway.auth.crypto import sign_hmac  # noqa: E402

GATEWAY = os.environ.get("GATEWAY_URL", "http://localhost:9102").rstrip("/")
DEFAULT_SAMPLE_DIR = _REPO / "samples" / "大单元学习总导"
RULE_SET = os.environ.get("RULE_SET_ID", "coursework-default")
POLL_INTERVAL = 3.0
# 单元包含多文件，评估器基线 LLM 评判（commonsense/soft/pref）较慢，实测 24 文件 ≈ 5min；
# 默认留足余量，避免脚本早于任务完成而误报超时。
POLL_TIMEOUT = float(os.environ.get("POLL_TIMEOUT", "900"))

# 打包时排除的系统/隐藏文件（与 PackageBuilder 的 ignore 一致）
_IGNORE_NAMES = {".DS_Store", "Thumbs.db"}
_IGNORE_DIRS = {"__MACOSX"}


def load_env() -> None:
    env_file = _REPO / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def make_zip(sample_dir: Path) -> tuple[bytes, int]:
    """把课件目录打成内存 zip，保留目录树，排除隐藏/系统文件。

    Returns:
        (zip_bytes, file_count) — file_count 为纳入 zip 的文件数。
    """
    buf = io.BytesIO()
    count = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(sample_dir.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(sample_dir)
            if any(part in _IGNORE_DIRS for part in rel.parts):
                continue
            if p.name in _IGNORE_NAMES or p.name.startswith("._"):
                continue
            # 显式 UTF-8 标记，避免中文路径在解压端乱码
            zi = zipfile.ZipInfo(filename=str(rel), date_time=(2024, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            zf.writestr(zi, p.read_bytes())
            count += 1
    return buf.getvalue(), count


def build_multipart(
    fields: list[tuple[str, str | tuple[str, bytes, str]]],
    boundary: str,
) -> bytes:
    """构造 multipart/form-data body（RFC 7578）。

    fields 中：
      - (name, str_value)              → 普通字段
      - (name, (filename, bytes, mime)) → 文件字段
    """
    parts: list[bytes] = []
    for name, value in fields:
        parts.append(f"--{boundary}\r\n".encode())
        if isinstance(value, tuple):
            filename, content, mime = value
            parts.append(
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                f"Content-Type: {mime}\r\n\r\n".encode()
            )
            parts.append(content)
        else:
            parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
            parts.append(value.encode("utf-8"))
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts)


def submit_zip(zip_bytes: bytes, public_key: str, secret: str, zip_name: str) -> dict:
    """multipart 上传 zip 到 /v1/jobs，返回 {job_id, status, poll_url}。"""
    boundary = f"----evalsim{secrets.token_hex(12)}"
    body = build_multipart(
        [
            ("rule_set_id", RULE_SET),
            ("file", (zip_name, zip_bytes, "application/zip")),
        ],
        boundary,
    )
    sig = sign_hmac(secret, "POST", "/v1/jobs", body)
    headers = {
        "Authorization": f"Eval {public_key}:{sig}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    req = urllib.request.Request(GATEWAY + "/v1/jobs", data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"POST /v1/jobs → HTTP {exc.code}: {detail}") from exc


def poll(public_key: str, secret: str, job_id: str) -> dict:
    """GET /v1/jobs/{id}（无 body，签名 sha256(b'')）。"""
    sig = sign_hmac(secret, "GET", f"/v1/jobs/{job_id}", None)
    headers = {"Authorization": f"Eval {public_key}:{sig}"}
    req = urllib.request.Request(GATEWAY + f"/v1/jobs/{job_id}", method="GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"GET /v1/jobs/{job_id} → HTTP {exc.code}: {detail}") from exc


def main() -> int:
    load_env()
    pk = os.environ.get("AGENT_EVAL_PUBLIC_KEY")
    sk = os.environ.get("AGENT_EVAL_SECRET_KEY")
    if not pk or not sk:
        print("❌ 缺少 AGENT_EVAL_PUBLIC_KEY / AGENT_EVAL_SECRET_KEY（见根 .env）", file=sys.stderr)
        return 2

    sample_dir = Path(os.environ.get("SAMPLE_DIR", str(DEFAULT_SAMPLE_DIR)))
    if not sample_dir.is_dir():
        print(f"❌ 样本目录不存在: {sample_dir}", file=sys.stderr)
        return 2

    print(f"== 模拟课件平台 → gateway（{GATEWAY}），单元包评估 ==")
    print(f"   样本目录: {sample_dir}")
    print(f"   规则集  : {RULE_SET}")

    print("① 打包课件目录为 zip ...")
    zip_bytes, file_count = make_zip(sample_dir)
    print(f"   ✅ zip 生成：{file_count} 个文件，{len(zip_bytes)} 字节")

    print("② multipart 提交到 gateway /v1/jobs ...")
    sub = submit_zip(zip_bytes, pk, sk, "courseware-package.zip")
    job_id = sub["job_id"]
    print(f"   ✅ 已受理 job_id={job_id} status={sub['status']} poll_url={sub['poll_url']}")

    print(f"③ 轮询任务状态（超时 {POLL_TIMEOUT:.0f}s）...")
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
        print(f"⚠️ 超时仍未结束，最后状态：{job.get('status')}")

    print("\n========== 评估结果 ==========")
    print(json.dumps(job, ensure_ascii=False, indent=2))

    status = job.get("status")
    if status == "completed":
        web_url = job.get("web_run_url")
        # gateway 存储的 metrics 为 report.to_dict()：{run_id, metrics:{DR,...}, thresholds, ...}
        report = job.get("metrics") or {}
        m = report.get("metrics") or {}
        print("\n========== 摘要 ==========")
        print(f"  样本数 total_samples : {report.get('total_samples')}")
        print(f"  DR / CPR             : {m.get('DR')} / {m.get('CPR')}")
        print(f"  avg_reward           : {m.get('avg_reward')}")
        print(f"  avg_soft / avg_pref  : {m.get('avg_soft')} / {m.get('avg_pref')}")
        print(f"  llm_skipped          : {m.get('llm_skipped')}")
        print(f"\n✅ 单元包评估完成。web 平台查看：{web_url}")
        return 0
    print(f"\n❌ 评估未成功（status={status}），见上方 error 字段。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
