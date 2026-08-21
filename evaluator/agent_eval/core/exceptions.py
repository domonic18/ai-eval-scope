"""公共异常定义。

系统各模块使用的异常类体系，按模块分层组织。
"""


# ─── 基础异常 ───


class AgentEvalError(Exception):
    """Agent 评估系统基础异常。"""

    def __init__(self, message: str = "", *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} | details={self.details}"
        return self.message


# ─── 配置相关 ───


class ConfigError(AgentEvalError):
    """配置加载或校验失败。"""


class SchemaValidationError(ConfigError):
    """JSON Schema 校验失败。"""

    def __init__(self, message: str, *, errors: list[dict] | None = None):
        super().__init__(message, details={"validation_errors": errors or []})
        self.validation_errors = errors or []


class ConfigFileNotFoundError(ConfigError):
    """配置文件不存在。"""

    def __init__(self, path: str):
        super().__init__(f"配置文件不存在: {path}", details={"path": path})
        self.path = path


# ─── 执行引擎相关 ───


class ExecutionError(AgentEvalError):
    """执行引擎基础异常。"""


class AgentError(ExecutionError):
    """ExecutionAgent 执行失败。

    适用场景：
    - Claude Agent SDK 调用失败（连接错误、认证失败等）
    - Agent 执行超过 max_turns 限制
    - Agent 产出物解析失败
    - Agent 工具调用权限不足
    """


class AgentTimeoutError(AgentError):
    """Agent 执行超时（超过 max_turns 或 wall-clock timeout）。"""


class BudgetExceededError(AgentError):
    """Agent 执行超出预算（超过 max_budget_usd）。"""


class ToolExecutionError(ExecutionError):
    """MCP Tool 执行失败（HTTP 请求失败、CLI 执行错误、文件操作失败等）。"""


class CollectionError(ExecutionError):
    """结果采集失败（文件复制错误、目录遍历失败等）。"""


class TaskBuildError(ExecutionError):
    """任务集构建失败（模板渲染错误、LLM 生成异常等）。"""


class SUTAuthError(ExecutionError):
    """SUT 鉴权失败（凭证缺失、登录失败、自动重登超频等，arch/03 §4.0）。"""


class SUTChannelError(ExecutionError):
    """SUT 通道交互失败（请求异常、协议响应不合规等）。"""


class AgentProtocolError(SUTChannelError):
    """Agent Protocol 通道错误（runs/threads/agents 接口调用失败，arch/03 §4.0.6）。"""


# ─── 评估引擎相关 ───


class EvaluationError(AgentEvalError):
    """评估引擎基础异常。"""


class EvaluatorNotFoundError(EvaluationError):
    """评估器未注册。"""

    def __init__(self, evaluator_id: str, available: list[str] | None = None):
        avail_str = f"，已注册: {available}" if available else ""
        super().__init__(
            f"未注册的评估器: {evaluator_id}{avail_str}",
            details={"evaluator_id": evaluator_id, "available": available or []},
        )
        self.evaluator_id = evaluator_id
        self.available = available or []


class EvaluatorError(EvaluationError):
    """评估器执行异常。"""


class ScoreAggregationError(EvaluationError):
    """评分聚合异常。"""


class ScenarioError(EvaluationError):
    """场景化配置异常（AggregationPolicy / MetricDefinition 解析或执行失败）。"""


class ScenarioExpressionError(ScenarioError):
    """场景化指标表达式求值失败（语法错误、未知变量、非法节点等）。"""


class VisionError(EvaluationError):
    """视觉评估异常（截图渲染失败、playwright/浏览器不可用等）。"""


# ─── 数据包相关 ───


class PackageError(AgentEvalError):
    """执行包操作异常。"""


class PackageNotFoundError(PackageError):
    """执行包不存在。"""

    def __init__(self, path: str):
        super().__init__(f"执行包不存在: {path}", details={"path": path})
        self.path = path


class PackageValidationError(PackageError):
    """执行包校验失败（缺少必要文件等）。"""


# ─── 场景包（Scenario Package）相关 ───


class ScenarioPackageError(AgentEvalError):
    """场景包操作异常（manifest 解析、版本/标签解析、拉取等）。"""


class ScenarioPackageNotFoundError(ScenarioPackageError):
    """场景包不存在。"""

    def __init__(self, ref: str):
        super().__init__(f"场景包不存在: {ref}", details={"ref": ref})
        self.ref = ref


class ScenarioPackageValidationError(ScenarioPackageError):
    """场景包校验失败（manifest 非法、缺资源目录等）。"""


# ─── LLM 相关 ───


class LLMError(AgentEvalError):
    """LLM 调用异常。"""


class ProviderNotFoundError(LLMError):
    """Provider 未找到。"""

    def __init__(self, provider_name: str, available: list[str] | None = None):
        avail_str = f"，可用: {available}" if available else ""
        super().__init__(
            f"未找到 LLM Provider: {provider_name}{avail_str}",
            details={"provider_name": provider_name, "available": available or []},
        )
        self.provider_name = provider_name
        self.available = available or []


class LLMResponseError(LLMError):
    """LLM 响应解析失败。"""


class LLMNetworkError(LLMError):
    """LLM 网络错误（连接超时/DNS/5xx）— 瞬时，可重试。"""


class LLMRateLimitError(LLMError):
    """LLM 限流（HTTP 429）— 瞬时，可重试。"""


class LLMQuotaExceededError(LLMError):
    """LLM 额度耗尽/余额不足 — 不可恢复，不应重试。"""


class LLMAuthError(LLMError):
    """LLM 鉴权失败（401/API Key 无效）— 不可恢复，不应重试。"""


# ─── 编排调度相关 ───


class OrchestratorError(AgentEvalError):
    """编排调度异常。"""


# ─── Workspace 相关 ───


class WorkspaceError(AgentEvalError):
    """Workspace 操作异常。"""


# ─── 数据集相关 ───


class DatasetError(AgentEvalError):
    """数据集下载或管理异常。"""


class DatasetNotFoundError(DatasetError):
    """数据集不存在（注册表未命中，或指定源上未提供 id）。"""

    def __init__(self, name: str):
        super().__init__(f"数据集不存在: {name}", details={"name": name})
        self.name = name


class DatasetDownloadError(DatasetError):
    """数据集下载失败（网络错误、源不可用、可选依赖缺失等）。"""
