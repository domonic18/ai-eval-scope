"""PackageManager — 场景包解析入口。

按 ``scenario/package:version_or_label`` 解析出 :class:`ResolvedPackage`。
解析优先级：精确版本 > 标签（latest/production/staging）> 最高版本。
"""

from __future__ import annotations

from agent_eval.core.exceptions import ScenarioPackageNotFoundError
from agent_eval.packages.manifest import ResolvedPackage
from agent_eval.packages.store import PackageStore

RESERVED_LABELS = frozenset({"latest", "production", "staging"})


def _semver_key(pkg: ResolvedPackage) -> tuple[int, ...]:
    """把 ``"1.2.3"`` 解析为可比较的整数元组；非数字段按 0 处理。"""
    parts: list[int] = []
    for chunk in pkg.manifest.version.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


class PackageManager:
    """场景包解析器。

    Args:
        store: 包仓库（默认 :class:`PackageStore` 默认实例）。
    """

    def __init__(self, store: PackageStore | None = None) -> None:
        self.store = store or PackageStore()

    def list(self, *, source: str | None = None) -> list[ResolvedPackage]:
        """列出全部包；``source`` 可选 builtin/local/project 过滤。"""
        if source == "builtin":
            return self.store.list_builtin()
        if source == "local":
            return self.store.list_local()
        if source == "project":
            return self.store.list_project()
        return self.store.list_all()

    def resolve(
        self,
        scenario: str,
        package_id: str | None = None,
        version_or_label: str | None = None,
    ) -> ResolvedPackage:
        """解析单个场景包。

        Args:
            scenario: 场景 ID。
            package_id: 包 ID（一个场景下可有多个包）；缺省取该场景全部包。
            version_or_label: 版本号或标签（latest/production/staging 或清单自定义标签）。
                缺省取最高版本。
        """
        candidates = self.store.find(scenario, package_id)
        ref = f"{scenario}/{package_id or '*'}:{version_or_label or 'latest'}"
        if not candidates:
            raise ScenarioPackageNotFoundError(ref)

        if version_or_label is None or version_or_label == "latest":
            return max(candidates, key=_semver_key)

        # 标签：命中任一候选的 labels，或为保留字
        is_label = version_or_label in RESERVED_LABELS or any(
            version_or_label in c.manifest.labels for c in candidates
        )
        if is_label:
            labeled = [c for c in candidates if version_or_label in c.manifest.labels]
            pool = labeled or candidates  # 保留字但无显式标注 → 回退全部取最高
            return max(pool, key=_semver_key)

        # 否则按精确版本
        exact = [c for c in candidates if c.manifest.version == version_or_label]
        if exact:
            return exact[0]
        raise ScenarioPackageNotFoundError(ref)

    def resolve_ref(self, ref: str) -> ResolvedPackage:
        """解析 ``scenario/package:version_or_label`` 或 ``scenario/package`` 串。"""
        scenario, package_id, version_or_label = parse_ref(ref)
        return self.resolve(scenario, package_id, version_or_label)


def parse_ref(ref: str) -> tuple[str, str | None, str | None]:
    """拆分 ``scenario/package:version_or_label`` → (scenario, package, ver_or_label)。

    - ``courseware`` → ("courseware", None, None)
    - ``courseware/quality`` → ("courseware", "quality", None)
    - ``courseware/quality:production`` → ("courseware", "quality", "production")
    - ``courseware:1.0.0`` → ("courseware", None, "1.0.0")
    """
    version: str | None = None
    if ":" in ref:
        ref, version = ref.split(":", 1)
        version = version or None
    if "/" in ref:
        scenario, package_id = ref.split("/", 1)
        return scenario, package_id or None, version
    return ref, None, version
