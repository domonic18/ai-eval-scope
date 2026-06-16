"""评估器插件自动发现。

将自定义 Evaluator 的 .py 文件放入本目录，系统启动时会自动导入并触发
@registry.register("custom.xxx") 装饰器完成注册。
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path


def discover_plugins(package_path: Path | str | None = None) -> list[str]:
    """发现并导入 plugins/ 目录下所有非下划线开头的 .py 模块。

    Args:
        package_path: 要扫描的目录路径；默认使用本包所在目录。
            传入自定义路径时，将直接从该路径加载模块文件。

    Returns:
        成功加载的模块名列表。
    """
    package_path = Path(package_path) if package_path else Path(__file__).parent
    package_path = Path(package_path)
    loaded: list[str] = []

    is_default = package_path == Path(__file__).parent

    for _, module_name, ispkg in pkgutil.iter_modules([str(package_path)]):
        if ispkg or module_name.startswith("_"):
            continue
        try:
            if is_default:
                # 默认场景：作为本包子模块导入
                importlib.import_module(f"{__name__}.{module_name}")
            else:
                # 测试/自定义场景：从文件路径加载
                module_path = package_path / f"{module_name}.py"
                spec = importlib.util.spec_from_file_location(
                    f"{__name__}.{module_name}", module_path
                )
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            loaded.append(module_name)
        except Exception:  # noqa: BLE001 - 单个插件失败不应影响整体
            import structlog

            logger = structlog.get_logger("evaluator_plugins")
            logger.warning(
                "插件加载失败",
                plugin=module_name,
                package=__name__,
            )

    return loaded
