"""核心枚举与类型别名定义。

定义系统全局使用的枚举类型和类型别名，供各模块共享引用。
"""

from enum import Enum


class RunMode(str, Enum):
    """运行模式 — 决定执行引擎与评估引擎的协作方式。"""

    RUN_ONLY = "run-only"  # 仅执行被测 Agent，不进行评估
    EVAL_ONLY = "eval-only"  # 仅对已有输出进行评估，不驱动 SUT
    PIPELINE = "pipeline"  # 依次执行 SUT 驱动和评估


class EvalMode(str, Enum):
    """评估模式 — 决定评估引擎内部使用 Pipeline 还是 Agent。"""

    PIPELINE = "pipeline"  # PipelineEngine（默认，确定性级联管线）
    AGENT = "agent"  # EvaluationAgent（可选，Agent 自适应评估）


class EvalStatus(str, Enum):
    """评估状态 — 单项约束或阶段的判定结果。"""

    PASS = "pass"  # 通过
    FAIL = "fail"  # 未通过
    SKIP = "skip"  # 前置阶段失败导致跳过
    ERROR = "error"  # 执行异常


class ConstraintTier(str, Enum):
    """约束层级 — 决定失败时的惩罚策略。"""

    HARD_GATE = "hard_gate"  # 硬性门控，失败终止 → S_format = -3
    HARD_SCORE = "hard_score"  # 硬性评分，失败归零 → S_common = 0
    SOFT = "soft"  # 软约束，归一化 [0, 1]
    PREFERENCE = "preference"  # 偏好约束，归一化 [0, 1]


class EvalMethod(str, Enum):
    """评估方法 — 评估器使用的判定手段。"""

    RULE = "rule"  # 规则判定
    FACT_VERIFY = "fact_verify"  # 事实验证（对比知识库）
    MATH_VERIFY = "math_verify"  # 数学公式验证
    LLM_JUDGE = "llm_judge"  # LLM 评分
    LLM_CONSISTENCY = "llm_consistency"  # LLM 一致性检查
    VISION = "vision"  # 多模态视觉评估


class CascadeStageID(str, Enum):
    """级联阶段标识。"""

    FORMAT_GATE = "format_gate"  # 格式门控
    COMMONSENSE_GATE = "commonsense_gate"  # 常识门控
    QUALITY_EVAL = "quality_eval"  # 质量评估


class ShortCircuitPolicy(str, Enum):
    """阶段短路策略。"""

    FAIL_FAST = "fail_fast"  # 任一失败则终止后续阶段
    CONTINUE_ALL = "continue_all"  # 所有评估器全部执行完毕


class PackageStatus(str, Enum):
    """执行包状态。"""

    SUCCESS = "success"  # 执行成功
    PARTIAL = "partial"  # 部分成功（部分文档缺失等）
    FAILED = "failed"  # 执行失败
