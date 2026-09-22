"""PackageToolServer 的工具规格定义（与实现分离）。

spec 描述即 Agent 侧工具文档：写清「何时用 / 怎么用 / 边界在哪」。
同名异步方法实现见 tools_fs / tools_manifest / tools_packages；
类属性挂载与组合见 tools.PackageToolServer。
"""

from __future__ import annotations

from agent_eval.agent.core.tools import ToolSpec

TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        "list_files",
        "列出目录文件：会话根内（含暂存态标记 added/staged/deleted/unchanged）/ "
        "随包资源 assets/ / 运行产物区 workspace/（数据集、run 产物，自动授权免弹窗）；"
        "外部目录向用户申请授权后为普通清单",
        "list_files",
    ),
    ToolSpec(
        "read_file",
        "读取文件（格式感知）：会话根内（暂存版本优先）/ assets/ / workspace/ "
        "（自动授权）/ 外部路径（向用户申请授权）。结构化格式 parquet/CSV/JSONL/"
        "JSON/zip 自动解析为列名 + 行数 + 样本行（limit 控制样本条数 1-20，"
        "parquet 需 uv sync --extra datasets）；文本类返回截断原文（max_chars）",
        "read_file",
    ),
    ToolSpec(
        "write_file",
        "写入/新建包内文件（进暂存区，落盘需宿主确认+校验通过）",
        "write_file",
    ),
    ToolSpec("delete_file", "删除包内文件（进暂存区）", "delete_file"),
    ToolSpec("read_manifest", "读取 agent_eval.yaml 包清单（暂存版本优先）", "read_manifest"),
    ToolSpec(
        "update_manifest",
        "浅合并更新包清单字段（如 version/labels/default_rule_set）",
        "update_manifest",
    ),
    ToolSpec(
        "write_sut_config",
        "机械物化 sut_configs/ 配置（在线被测系统落盘的唯一正道）：filename 传"
        " sut_configs/<名字>.yaml 或裸名 <名字>.yaml（自动归位 sut_configs/）；"
        "只给决策字段（name/channel/base_url/timeout/request_template/"
        "response_mapping 等），auth: 段由服务端从本会话登录实测账本**原样注入**"
        "（不接受手写 auth）；装配后内联 schema 校验，幻觉字段当场打回",
        "write_sut_config",
    ),
    ToolSpec(
        "validate_package",
        "校验暂存视图（清单合法 + 资源目录 + 规则 YAML 可解析 + 骨架开槽检查），返回错误列表",
        "validate_package",
    ),
    ToolSpec(
        "list_packages",
        "列出全部已发现的场景包（builtin 内置 / local 本地缓存 / project 项目目录"
        "三源，与 scenario list 同源）——回答「有哪些包 / 有没有现成包」先调此工具，"
        "不要凭记忆或目录列举判断；读包内文件走 read_reference（按 ref）",
        "list_packages",
    ),
    ToolSpec(
        "search_reference",
        "检索内置包（chat/code/courseware）按文件名匹配，返回命中文件与各包真实"
        "文件清单（read_reference 的 path 以此为准）",
        "search_reference",
    ),
    ToolSpec(
        "read_reference",
        "只读已发现包（三源）的文件内容（ref 如 chat 或项目包 scenario/id，见 "
        "list_packages；path 为包内相对路径）——参照真实格式，read_file 仅限本包",
        "read_reference",
    ),
    ToolSpec(
        "list_evaluators",
        "列出当前可用的评估器注册 ID（注册表实时快照，含本包 entry_points 声明的）——"
        "rules 的 evaluator 字段从此清单原样复制，勿凭记忆臆造",
        "list_evaluators",
    ),
    ToolSpec(
        "preview_diff",
        "预览暂存区 vs 磁盘原文的统一 diff（宿主确认界面同源）",
        "preview_diff",
    ),
    ToolSpec(
        "edit_package",
        "切换会话目标到既有场景包做原位编辑（ref 取 list_packages 返回的 scenario/"
        "id 段或包路径）——用户确认后沙盒根切到该包，后续读写/diff/确认落盘**原位生效**；"
        "轻量修改（加/改/删用例、调规则、改提示词、修 sut_config）的正道，无需"
        " SKELETON/fork/换 id。内置包只读不支持",
        "edit_package",
    ),
]
