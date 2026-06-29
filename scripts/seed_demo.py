"""为可观测平台创建默认演示账户。

注册（若已存在则登录）demo@eval.local / demo12345，仅创建账户与组织，
不建项目 / 不签发 Key / 不摄取数据。运行后即可用该账号登录前端。
"""

from __future__ import annotations

import sys

import httpx

HOST = "http://localhost:9000"
DEMO_EMAIL = "demo@eval.local"
DEMO_PASSWORD = "demo12345"


def main() -> int:
    # 注册（若已存在则登录）
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
    print(f"[ok] 用户 {DEMO_EMAIL} / 组织 {sess['org']['name']}")

    print("\n✅ 默认账户就绪。")
    print(f"   访问: {HOST}")
    print(f"   账号: {DEMO_EMAIL} / 密码: {DEMO_PASSWORD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
