"""评估器插件自动发现。

将自定义 Evaluator 的 .py 文件放入本目录，系统启动时会自动导入并触发
@registry.register("custom.xxx") 装饰器完成注册。
"""

from __future__ import annotations

import importlib.util
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


def load_package_entry_points(package_path: Path | str) -> list[str]:
    """加载场景包声明的 entry_points 评估器（manifest.entry_points.evaluators）。

    值为 ``"module"`` 或 ``"module:func"``：``importlib.import_module`` 导入模块（首次导入
    触发模块内 ``@registry.register`` 装饰器，Python 模块缓存保证幂等——重复加载不会二次注册）；
    有 ``:func`` 则调用（func 须幂等）。使场景包能携带自己的评估器（阶段 4），解除评估器固定
    courseware 一组的限制。无 manifest / 无 entry_points / 加载失败 → 空操作（不阻塞评估）。
    """
    root = Path(package_path)
    try:
        from agent_eval.packages.manifest import load_manifest

        manifest = load_manifest(root)
    except Exception:  # noqa: BLE001 - 无清单或解析失败 → 视作无 entry_points
        return []
    ep = (manifest.entry_points or {}).get("evaluators")
    if not ep:
        return []
    module_name, _, func_name = str(ep).partition(":")
    try:
        mod = importlib.import_module(module_name)
        if func_name:
            getattr(mod, func_name)()
        return [module_name]
    except Exception:  # noqa: BLE001 - 单个 entry_point 失败不应阻塞评估
        import structlog

        structlog.get_logger("evaluator_plugins").warning(
            "entry_points 加载失败", package=str(root), entry_point=ep
        )
        return []
