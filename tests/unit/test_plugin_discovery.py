"""插件评估器自动发现测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_eval.core.types import EvalMethod, EvalStatus
from agent_eval.evaluation.base import BaseEvaluator
from agent_eval.evaluation.evaluators.plugins import discover_plugins
from agent_eval.evaluation.registry import registry


@pytest.fixture
def plugin_dir(tmp_path: Path) -> Path:
    """在临时目录中创建一个测试插件文件。"""
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    plugin = plugins_dir / "test_dummy.py"
    plugin.write_text(
        """\
from agent_eval.core.types import ConstraintTier, EvalMethod, EvalStatus
from agent_eval.evaluation.base import BaseEvaluator
from agent_eval.evaluation.registry import registry


@registry.register("test.dummy_plugin")
class DummyPluginEvaluator(BaseEvaluator):
    evaluator_id = "test.dummy_plugin"
    name = "测试插件评估器"
    tier = ConstraintTier.SOFT
    method = EvalMethod.RULE

    def evaluate(self, sample, context):
        return self._make_result(
            status=EvalStatus.PASS,
            score=1.0,
            reason="插件评估通过",
        )
""",
        encoding="utf-8",
    )
    return plugins_dir


def test_discover_plugins_loads_custom_evaluator(plugin_dir: Path) -> None:
    """discover_plugins 能发现并注册自定义目录下的评估器。"""
    assert not registry.is_registered("test.dummy_plugin")

    loaded = discover_plugins(plugin_dir)

    assert "test_dummy" in loaded
    assert registry.is_registered("test.dummy_plugin")

    ev = registry.create("test.dummy_plugin", {})
    assert isinstance(ev, BaseEvaluator)
    assert ev.method == EvalMethod.RULE

    result = ev.evaluate(None, {})
    assert result.status == EvalStatus.PASS
    assert result.score == 1.0

    # 清理注册表，避免影响其他测试
    registry.unregister("test.dummy_plugin")


def test_discover_plugins_skips_underscore_files(plugin_dir: Path) -> None:
    """以下划线开头的文件不会被当作插件加载。"""
    (plugin_dir / "_private.py").write_text(
        "from agent_eval.evaluation.registry import registry\n"
        "@registry.register('test.private_plugin')\n"
        "class PrivateEvaluator: pass\n",
        encoding="utf-8",
    )

    loaded = discover_plugins(plugin_dir)

    assert "_private" not in loaded
    assert not registry.is_registered("test.private_plugin")
