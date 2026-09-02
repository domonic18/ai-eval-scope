"""登录 API 发现 — 机械解析 + 定向探测阶梯，语义判断全部交 Agent（arch/15 §6.6）。

阶梯：①页面结构机械解析（全部 form 原样返回，不判断哪个是登录表单）→
②Agent 自拟候选路径定向检查（GET 只读，不发凭证）→ ③OpenAPI/身份文档探测
（挂载点为工具规范约定，与 HTML 规范同类）→ 兜底问答引导。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

from agent_eval.agent.probe.fetch import _host_of, _wrap_evidence

# 语义判断一律不上移到代码：候选登录路径由 Agent 经 discover_login(paths=…) 自拟
# （其世界知识远多于写死清单）；请求构造/分包机制的识别由 Agent 用 search_content
# 自拟模式检索；凭证字段的含义由 Agent 经 ask_user(desc=…) 传给用户——
# 代码只保留格式解析与机械探测
_MAX_DISCOVER_PATHS = 10


class _PageStructureParser(HTMLParser):
    """页面结构机械解析（HTML 规范语义，非站点知识）。

    收集全部 <form>（action/method + 字段名）与外链 <script src>——**不做任何
    语义过滤**（哪个 form 是登录表单由 Agent 判读；按「有无密码字段」过滤会漏掉
    短信验证码登录等无密码形态）。标准库解析器替代手搓正则：属性引号变体、
    大小写、未闭合标签均按规范处理。
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: list[dict[str, Any]] = []
        self.script_srcs: list[str] = []
        self._form: dict[str, Any] | None = None
        self._fields: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {k: v or "" for k, v in attrs}
        if tag == "form":
            self._form = {"action": values.get("action", ""), "method": values.get("method", "")}
            self._fields = []
        elif tag == "script" and values.get("src"):
            self.script_srcs.append(values["src"])
        elif self._form is not None and tag in ("input", "select", "textarea"):
            if values.get("name"):
                self._fields.append(values["name"])

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self._form is not None:
            self._form["fields"] = self._fields
            self.forms.append(self._form)
            self._form = None


def _dig(data: Any, *keys: str) -> Any:
    """沿 dict 链安全下钻（第三方文档字段缺失/类型异常一律得 None）。"""
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


class DiscoveryMixin:
    """工具二：登录 API 发现（阶梯，不给凭证）。"""

    async def discover_login(self, page_url: str, paths: str = "") -> dict[str, Any]:
        """登录 API 快速通道：机械解析 + 定向探测，语义判断全部交 Agent。

        - 页面结构机械解析（全部 form 原样返回，不判断哪个是登录表单）；
        - ``paths`` 由 Agent 自拟候选登录路径（世界知识 + 页面线索，| 或逗号分隔，
          ≤10 条），工具只做 GET 定向检查（不发凭证）；
        - OpenAPI/Swagger 文档挂载点是工具规范约定（与 HTML 规范同类），命中后
          POST 端点原样列出（不做 login 关键字过滤），文档原文入缓存可检索。
        """
        if budget_err := self._budget("discover_login"):
            return budget_err
        if host_err := await self._ensure_host(page_url):
            return {"error": host_err}
        base = f"{urlparse(page_url).scheme}://{urlparse(page_url).netloc}"
        page = await self._fetch_text(page_url)
        if page is None:
            return {"error": f"页面不可达: {page_url}"}
        # 传入接口地址（响应非 HTML）的识别：用户直接给登录 API 时无需页面发现
        head = page[:1000].lower()
        looks_like_html = any(
            tag in head for tag in ("<html", "<body", "<div", "<form", "<!doctype")
        )
        candidates: list[dict[str, Any]] = []

        # 阶梯①：页面结构机械解析——全部 form 原样返回（哪个是登录表单由 Agent
        # 判读；按「有无密码字段」过滤会漏掉短信验证码登录等无密码形态）
        parser = _PageStructureParser()
        parser.feed(page)
        for form in parser.forms:
            action = str(form["action"])
            candidates.append(
                {
                    "source": "form",
                    "path": action or "(当前页面)",
                    "fields": list(form["fields"]),
                    "method": str(form["method"]).upper() or "GET(未声明)",
                }
            )

        # 页面与同 host 外链脚本入缓存（≤5 个）——请求构造/分包机制的识别不写死
        # 在代码里，交 Agent 用 search_content 自拟模式检索
        script_srcs = [
            src
            for src in parser.script_srcs[:5]
            if not src.startswith(("http", "//")) or _host_of(src) == urlparse(page_url).netloc
        ]
        self._cache_content(page_url, page)
        for src in script_srcs:
            script_url = src if src.startswith("http") else f"{base}/{src.lstrip('/')}"
            js = await self._fetch_text(script_url)
            if js:
                self._cache_content(script_url, js)

        # 阶梯②：Agent 自拟候选路径的定向检查（≤10 条，GET 只读，非 404 记为存在）
        probe_paths = [p for p in re.split(r"[|,，、\s]+", paths.strip()) if p][
            :_MAX_DISCOVER_PATHS
        ]
        if probe_paths:
            client_cm = await self._client()
            async with client_cm as client:
                for path in probe_paths:
                    target = path if path.startswith("/") else f"/{path}"
                    try:
                        response = await client.get(f"{base}{target}")
                    except Exception:  # noqa: BLE001 — 单路径失败不阻断清单
                        continue
                    if response.status_code != 404:
                        candidates.append(
                            {
                                "source": "probed_path",
                                "path": target,
                                "fields": [],
                                "method": f"GET 存在（HTTP {response.status_code}）",
                            }
                        )

        # 阶梯③：OpenAPI/身份文档探测（挂载点为工具规范约定；POST 端点原样列出，
        # 哪个是登录由 Agent 判读，文档原文已入缓存可 search_content 检索）
        if not candidates:
            client_cm = await self._client()
            async with client_cm as client:
                for doc_path in (
                    "/openapi.json",
                    "/api/openapi.json",
                    "/api-docs",
                    "/swagger.json",
                    "/v3/api-docs",
                ):
                    try:
                        response = await client.get(f"{base}{doc_path}")
                        if response.status_code != 200:
                            continue
                        spec = response.json()
                    except Exception:  # noqa: BLE001 — 单路径失败不阻断清单
                        continue
                    if not isinstance(spec, dict):
                        continue
                    self._cache_content(f"{base}{doc_path}", response.text)
                    for pathname, methods in (spec.get("paths") or {}).items():
                        if not isinstance(methods, dict) or "post" not in methods:
                            continue
                        props = _dig(
                            methods.get("post"),
                            "requestBody",
                            "content",
                            "application/json",
                            "schema",
                            "properties",
                        )
                        candidates.append(
                            {
                                "source": "openapi",
                                "path": str(pathname),
                                "fields": sorted(props) if isinstance(props, dict) else [],
                                "method": "POST（openapi 声明）",
                            }
                        )
                    if candidates:
                        break  # 命中一份文档即止
        self._log("discover_login", page_url=page_url, candidates=len(candidates))
        result: dict[str, Any] = {
            "candidates": candidates[:8],
            "scripts": script_srcs,
            "cached": list(self._fetched),
            "page_evidence": _wrap_evidence(f"页面 {page_url}", page),
            "next_step": (
                "有候选→判读哪个是真正的登录端点（form 可能是搜索框等非登录表单），"
                "用 probe_login 实测验证（相对路径候选以登录页域为缺省 base_url，"
                "404 可换接口域再试——不同域即新组合）；"
                "快检未命中→前端包分析：search_content 在已缓存内容中检索（模式自拟——"
                "业务词、请求构造痕迹、脚本分包机制痕迹），命中后从摘录读出真实路径与"
                "请求体字段；主包没有登录请求字面量是常态（框架按路由分包）——从摘录"
                "识别分块命名规则、推算页面分块文件名，probe_url 抓取该分块后再检索；"
                "接口域与页面域可能分离——检索接口基址配置，与相对路径组合成完整 URL；"
                "还可带 paths 参数（自拟候选登录路径）重跑本工具做定向检查；"
                "全部落空→只向用户问登录接口地址一项；"
                "字段名不要问用户——从检索摘录中的请求体对象读出（真实提取），"
                "全无线索才用常见约定（username/password）拟定，"
                "probe_login 发送前的脱敏预览会让用户看到字段并可纠正"
            ),
        }
        if not looks_like_html:
            # 接口地址场景下覆盖兜底指引——两套指引并存方向相反时，Agent 会滑回
            # probe_url 逐路径猜（实测教训）；单一权威指引
            result["next_step"] = (
                "传入地址疑似接口而非登录页面（响应非 HTML）。用户提供的地址是权威输入——"
                "不要再用 probe_url 试其他路径：立即用该地址调用 probe_login 做实测"
                "（可先最小 login_cfg：body_template 传 '{}' 做存在性探测——POST 404=路径"
                "不存在；400/401/422=接口存在，再补真实字段与凭证实测）；"
                "发送前脱敏预览会请用户确认"
            )
        return result
