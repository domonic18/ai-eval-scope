"""数据集域工具声明 — 纯数据单一真相源。

description 即行为面（随 prompt 发给 LLM）。数据集域与执行域同款：无轮内
预算（TOOL_BUDGETS）——download_dataset 必经用户确认门槛，确认即预算。
"""

from __future__ import annotations

from agent_eval.agent.core.tools import ToolSpec

__all__ = ["DATASET_TOOL_SPECS"]

DATASET_TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="list_datasets",
        description=(
            "列出评测数据集：内置索引清单（id/名称/类别/双源 repo 地址）+ 本地已下载"
            "状态（落盘路径与下载时间，扫描 workspace/datasets/ 的清单文件）。"
            "回答「有哪些数据集 / 某数据集下载了没」先调本工具，不要凭记忆作答。只读，不出网。"
        ),
        method="list_datasets",
    ),
    ToolSpec(
        name="download_dataset",
        description=(
            "下载评测数据集到 workspace/datasets/{name}/（写路径白名单，不接受自定义"
            "落盘目录）。下载前必经用户确认（展示等价 CLI 命令 + 来源 repo + 目标目录），"
            "确认文本须原样转达；出网仅经数据集下载单出口（HuggingFace/ModelScope 域），"
            "域名随 source 参数结构性收窄。访问 token 只经环境变量（HF_TOKEN /"
            " MODELSCOPE_API_TOKEN）传入下载器——工具参数与回执不含任何 token，"
            "也不要向用户索要 token 明文。"
        ),
        method="download_dataset",
    ),
]
