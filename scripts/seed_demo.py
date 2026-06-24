"""为可观测平台播种演示数据（供前端体验测试）。

注册 demo@eval.local / demo12345 → 建项目 → 签发 Key → 摄取 5 次运行（DR 递增），
每次含样本/约束，并上传 1 个制品。运行后即可在浏览器看到趋势与详情。
"""

from __future__ import annotations

import sys
import uuid

import httpx

HOST = "http://localhost:9000"
DEMO_EMAIL = "demo@eval.local"
DEMO_PASSWORD = "demo12345"


def main() -> int:
    # 1. 注册（若已存在则登录）
    r = httpx.post(
        f"{HOST}/api/v1/auth/register",
        json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD, "name": "演示用户", "orgName": "演示组织"},
        timeout=30,
    )
    if r.status_code == 409:
        r = httpx.post(f"{HOST}/api/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}, timeout=30)
        r.raise_for_status()
    else:
        r.raise_for_status()
    sess = r.json()
    access = sess["access_token"]
    org = sess["org"]["id"]
    print(f"[ok] 用户 {DEMO_EMAIL} / 组织 {sess['org']['name']}")

    # 2. 建项目（已存在则复用）
    r = httpx.post(
        f"{HOST}/api/v1/orgs/{org}/projects",
        headers={"Authorization": f"Bearer {access}"},
        json={"name": "课件生成评估", "slug": "courseware"},
        timeout=30,
    )
    if r.status_code == 409:
        r = httpx.get(f"{HOST}/api/v1/orgs/{org}/projects", headers={"Authorization": f"Bearer {access}"}, timeout=30)
        project = next(p["id"] for p in r.json()["projects"] if p["slug"] == "courseware")
    else:
        r.raise_for_status()
        project = r.json()["project"]["id"]
    print(f"[ok] 项目 courseware ({project})")

    # 3. 签发 Key
    r = httpx.post(
        f"{HOST}/api/v1/projects/{project}/keys",
        headers={"Authorization": f"Bearer {access}"},
        json={"name": "seed"},
        timeout=30,
    )
    r.raise_for_status()
    key = r.json()["key"]
    print(f"[ok] API Key {key['publicKey']}")

    # 4. 用 Python ResultSink 客户端摄取
    from agent_eval.observability.client import IngestionClient
    from agent_eval.observability.config import load_config

    cfg = load_config(
        upload_override=True,
        env={
            "AGENT_EVAL_HOST": HOST,
            "AGENT_EVAL_PUBLIC_KEY": key["publicKey"],
            "AGENT_EVAL_SECRET_KEY": key["secretKey"],
            "AGENT_EVAL_PROJECT": project,
        },
    )
    client = IngestionClient(cfg)

    dr_trend = [0.58, 0.66, 0.71, 0.80, 0.88]
    for i, dr in enumerate(dr_trend):
        ext_run = f"demo_run_{i+1:02d}"
        events = [
            {
                "event_id": uuid.uuid4().hex,
                "type": "run",
                "data": {
                    "external_run_id": ext_run,
                    "mode": "eval_only",
                    "status": "completed",
                    "metrics": {"DR": dr, "CPR": round(dr * 0.85, 3), "avg_reward": round(dr * 0.9, 3), "condR": round(dr * 0.8, 3), "avg_time_ms": 980 + i * 40},
                    "total_samples": 2,
                    "rule_set_version": "v1.2",
                    "sut_version": "claude-sonnet-4",
                },
            }
        ]
        for sid_suffix in ("task_001", "task_002"):
            ext_sample = f"{ext_run}/{sid_suffix}"
            events.append({
                "event_id": uuid.uuid4().hex, "type": "sample",
                "data": {"external_run_id": ext_run, "external_sample_id": sid_suffix, "status": "completed",
                         "s_format": 1.0, "s_common": round(0.6 + dr * 0.3, 3), "s_soft": round(0.5 + dr * 0.4, 3),
                         "s_pref": round(0.55 + dr * 0.35, 3), "reward": round(dr, 3), "total_duration_ms": 1500, "llm_calls": 12, "token_usage": 8400},
            })
            # 三个约束：格式门控(通过)、质量(随 DR)、覆盖(随 DR)
            constraints = [
                ("format.structure", "hard_gate", "结构完整", dr > 0.6),
                ("quality.depth", "soft", "内容深度", dr > 0.7),
                ("coverage.topic", "preference", "主题覆盖", dr > 0.75),
            ]
            for cid, tier, name, passed in constraints:
                events.append({
                    "event_id": uuid.uuid4().hex, "type": "constraint",
                    "data": {"external_run_id": ext_run, "external_sample_id": sid_suffix, "constraint_id": cid,
                             "name": name, "tier": tier, "status": "pass" if passed else "fail",
                             "passed": passed, "score": 1.0 if passed else 0.3, "reason": "符合预期" if passed else "存在缺陷",
                             "duration_ms": 120, "judge_provider": "deepseek_judge", "judge_model": "deepseek-chat"},
                })
        resp = client.post_ingest(events)
        print(f"[ok] run {ext_run}: DR={dr} accepted={resp.accepted} dup={resp.duplicates}")

    # 5. 上传一个制品（manifest）并发出 artifact 事件，挂在首个 run 首个 sample
    manifest = '{"run":"demo_run_01","note":"demo artifact"}'.encode("utf-8")
    presigned = client.presign_put({"external_run_id": "demo_run_01", "kind": "manifest", "name": "run_manifest.json", "content_type": "application/json"})
    up = httpx.put(presigned["upload_url"], content=manifest, headers={"Content-Type": "application/json"}, timeout=30)
    up.raise_for_status()
    client.post_ingest([{
        "event_id": uuid.uuid4().hex, "type": "artifact",
        "data": {"external_run_id": "demo_run_01", "external_sample_id": "task_001", "kind": "manifest",
                 "object_key": presigned["object_key"], "content_type": "application/json",
                 "size_bytes": len(manifest), "original_name": "run_manifest.json"},
    }])
    print("[ok] 制品 run_manifest.json 已上传并关联")

    print("\n✅ 演示数据就绪。")
    print(f"   访问: {HOST}")
    print(f"   账号: {DEMO_EMAIL} / 密码: {DEMO_PASSWORD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
