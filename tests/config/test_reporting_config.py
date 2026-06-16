"""报告生成默认参数配置测试。"""

from __future__ import annotations

from agent_eval.config import REPORTING_DEFAULTS, ReportingDefaults


class TestReportingDefaults:
    """报告生成默认参数测试。"""

    def test_summary_list_max_items(self) -> None:
        """文件/截图列表最大展示数量。"""
        assert REPORTING_DEFAULTS.summary_list_max_items == 10

    def test_error_list_max_items(self) -> None:
        """错误/问题列表最大展示数量。"""
        assert REPORTING_DEFAULTS.error_list_max_items == 20

    def test_heading_summary_max_items(self) -> None:
        """标题摘要每文件最大标题数量。"""
        assert REPORTING_DEFAULTS.heading_summary_max_items == 5

    def test_class_exported(self) -> None:
        """ReportingDefaults 类可通过 config 包导出。"""
        assert ReportingDefaults is not None
