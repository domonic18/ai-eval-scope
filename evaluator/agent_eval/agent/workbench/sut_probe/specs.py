"""探测工具面规格 — 工具声明 / 超时 / 轮内预算的纯数据单源。

description 文案随 prompt 发给 LLM，是行为面：改文案即改工具调用行为。
"""

from __future__ import annotations

from agent_eval.agent.core.tools import ToolSpec

PROBE_TIMEOUT_S = 10.0
# 轮内预算按工具分池：单工具的暴力试探不得饿死发现链（真机实测 probe_url 逐路径
# 猜接口烧光共享预算后，discover_login 被拒、页面分析整段跳过）。额度从宽——
# 只兜住失控循环，不卡正常调试（候选跨域验证、用户纠正后重试都有余量）
TOOL_BUDGETS: dict[str, int] = {
    "request": 25,  # 门控请求原语（抓取与登录实测同池）：前端主包与分块
    # 抓取、登录实测、链式认证步全走 request——同一池防多入口绕限；从宽只兜
    # 逐路径扫描式空转
    "declare_token": 10,  # 事后声明式提取：不重发请求，试错只在路径拼写——从宽
    "discover_login": 5,  # 页面发现内含多条子请求，独立小池
    "search_content": 30,  # 分析主循环：真实会话中含噪检索词（post/user/token 命中
    # axios 库代码）与 js/css 双 hash 表分辨都要烧次数——额度从宽只兜空转
    "probe_protocol": 8,  # 裸探 + 带 configurable 重探 + modelId 试参（503 试错）+ 鉴权后
    # 重探——真机实测一轮正常调试即耗 4 次，用户纠正/换参后的重试都计于此
}

PROBE_TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="request",
        description=(
            "门控请求原语（探测面的裸请求工具，抓取与接口调试同一出口）："
            'method/url/headers/body 自由构造（headers 用 "Key: Value"、多项以'
            " | 分隔），返回状态码 + 响应头 + 响应体。GET 即「抓取」：完整响应体"
            " 自动入缓存供 search_content 检索（返回含 cached_bytes 与"
            " search_hint）；非 GET 即接口调试——要看原始响应（405 的 Allow 头、"
            " 400/422 的业务错误消息、重定向 Location）用它。"
            " body/headers 支持 Jinja2 模板：凭证变量 {{ 字段 }} 由服务端从密钥区"
            " 注入（须带 ref，与包 credential_ref 同值；凭证值不经对话、返回中"
            " 不回显），带凭证请求首次外发前经用户授权一次；多步认证链用"
            " step=名字 声明本步响应，后续请求以 {{ stepN.路径 }} 引用其值"
            "（值全程服务端流动）。body 只收单层 JSON 对象（dict 形态或对象形态"
            " 的 JSON 文本；勿双重编码——外层多一层引号 SUT 收到的是字符串而非"
            " 对象；渲染后非对象/非法 JSON 会在发送前被拦下）。form/multipart "
            "不支持：body 非空按 application/json 发送——显式给了非 JSON "
            " Content-Type 而 body 是 JSON 对象时标签会被机械归一化（返回含 "
            " content_type_normalized）"
            " Authorization/Cookie 头禁传：已声明的会话凭证"
            " 自动挂载；新 host 首访会经用户确认；带凭证请求被 4xx/5xx 拒绝后"
            " 同组合不自动重发（防锁）。带凭证 2xx 响应在 declare_token 声明前"
            " 只回键路径结构不回原文（响应可能含会话凭证）"
        ),
        method="request",
    ),
    ToolSpec(
        name="discover_login",
        description=(
            "从页面登录地址发现登录 API（快速通道）：机械解析页面全部 form 与脚本清单"
            " → paths（自拟候选登录路径，| 分隔，≤10 条）定向检查 → OpenAPI 文档探测 →"
            " 兜底问答引导（不给凭证）；页面与同域脚本入缓存，未命中时用 search_content"
            " 深入分析前端包"
        ),
        method="discover_login",
    ),
    ToolSpec(
        name="search_content",
        description=(
            "在已抓取的页面/脚本内容中检索子串（大小写不敏感，非正则），返回带上下文"
            "的摘录（≤12 条）——前端包分析的主用工具。先 request(GET) 抓取目标再检索；"
            "一次没命中就换更短的词（业务词、请求构造痕迹、分包机制痕迹）"
        ),
        method="search_content",
    ),
    ToolSpec(
        name="probe_protocol",
        description=(
            "agent-protocol 符合性矩阵（与执行器契约同构）：POST /threads →"
            " commands（run.start 信封 + 会话路由头 + 已声明的会话凭证自动挂载）→"
            " state → stream 逐端点 ✅/❌（含写操作，收尾清理线程）。POST /threads"
            " 404 不影响判定——AG-UI 网关族由客户端生成线程 ID、首个 run.start"
            " 隐式建线程，协议判定以 send_command/run_wait 为准。"
            " configurable 传与 sut_config.configurable 同形的对象（如"
            ' {"modelId": "19"}）——网关要求业务参数时裸探会 400/422，带参重探'
            " 核心 ✅ 才算验证通过（执行器同款下发路径）；落盘前的最后一次协议"
            " 探测应携带最终参数"
        ),
        method="probe_protocol",
    ),
    ToolSpec(
        name="declare_token",
        description=(
            "声明会话凭证提取（登录实测成功后调用，事后声明不重发请求）："
            "token_path 用点分路径从该 ref 最近一次带凭证 2xx 响应的 JSON 中取值"
            "（数组用数字下标，如 data.0.token——以 request 返回的键路径结构树"
            " 为准）；token_source 三态：bearer（默认，Authorization: Bearer 自动"
            " 挂载）/ header:X（挂到自定义头 X）/ cookie:名字（会话 cookie——"
            " 响应 Set-Cookie 已按名提取，也可 token_path 从响应体取）。成功返回"
            " 可直接照抄的 sut_config_auth_snippet（原样写入包的 auth: 段，勿改写）；"
            " 路径提取失败会给出实际可用的键路径清单。"
            " 用户直接提供 token（如浏览器已登录态）而无登录实测时，改用 "
            " static_field=密钥区字段名：按 token_source 挂载该静态值解锁探测"
            "（不入证据账本、不生成 auth: 段——落盘认证仍须实测路径）"
        ),
        method="declare_token",
    ),
    ToolSpec(
        name="ask_user",
        description=(
            "向用户提问，一次只问一个问题（多项信息拆成多次调用，问题不超 200 字）。"
            "kind 三态：text=开放答案（地址/描述，默认）；choice=明确候选，options 用 | 分隔"
            "（如 需要登录|免登录）；credential=凭证字段录入，必带 ref、field 与 desc——"
            "desc 用一句话说明该字段实际要输入什么（从你的分析结论得出），一次只录"
            "一个字段（输入直写密钥区不回流）。不要用 options 表达「请文本输入」之类的说明"
        ),
        method="ask_user",
    ),
]
