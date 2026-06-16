"""报告生成默认参数配置。

集中管理报告渲染、列表截断、字段展示等与报告输出相关的默认值，
避免散落在 reporting/ 模块中 hardcode。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReportingDefaults:
    """报告生成默认参数。"""

    # 摘要报告中文件/截图列表的最大展示数量
    summary_list_max_items: int = 10
    # 摘要报告中错误/问题列表的最大展示数量
    error_list_max_items: int = 20
    # 标题摘要中每文件展示的最大标题数量
    heading_summary_max_items: int = 5


# 模块级单例
REPORTING_DEFAULTS = ReportingDefaults()
