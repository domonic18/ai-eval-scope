"""规则集管理器。

提供 RuleSet 的版本控制、差异对比、应用归档与回滚能力。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from agent_eval.config.loader import ConfigLoader
from agent_eval.rules.models import RuleSet, RuleSetChange, RuleSetDiff
from agent_eval.rules.validation import RuleSetValidator


class RuleSetManager:
    """RuleSet 版本管理、diff、apply、rollback。"""

    HISTORY_FILE = "rule_set_history.json"

    def __init__(self, rule_set_path: Path | str, history_dir: Path | str | None = None) -> None:
        self.rule_set_path = Path(rule_set_path)
        self.history_dir = (
            Path(history_dir) if history_dir else self.rule_set_path.parent / ".rule_history"
        )
        self.history_dir.mkdir(parents=True, exist_ok=True)

    # ─── 加载 ───

    def load(self, *, resolve_templates: bool = True) -> RuleSet:
        """从磁盘加载 RuleSet，可选择是否解析模板。"""
        return ConfigLoader.load_rule_set(
            self.rule_set_path,
            resolve_templates=resolve_templates,
        )

    # ─── 版本管理 ───

    def bump_version(
        self,
        change_type: str = "patch",
        description: str = "",
    ) -> str:
        """递增语义版本号并保存。

        Args:
            change_type: major|minor|patch。
            description: 变更说明。

        Returns:
            新版本号。
        """
        rule_set = self.load(resolve_templates=False)
        old_version = rule_set.meta.version or rule_set.version
        new_version = self._semver_bump(old_version, change_type)

        # 归档当前版本
        try:
            self._archive_version(rule_set)
        except Exception:  # noqa: BLE001
            pass

        rule_set.version = new_version
        rule_set.meta.version = new_version
        rule_set.meta.updated_at = datetime.now(UTC).isoformat()
        if not rule_set.meta.created_at:
            rule_set.meta.created_at = rule_set.meta.updated_at
        rule_set.meta.changelog.append(
            f"{new_version} ({rule_set.meta.updated_at}): {description}".strip()
        )

        self._save_rule_set(rule_set)
        self._record_change(
            RuleSetChange(
                version=new_version,
                timestamp=rule_set.meta.updated_at,
                change_type="version_bump",
                description=f"{old_version} -> {new_version}: {description}".strip(),
                diff={"old_version": old_version, "new_version": new_version},
            )
        )
        return new_version

    @staticmethod
    def _semver_bump(version: str, change_type: str) -> str:
        """简单的语义版本递增。"""
        parts = version.split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            return "1.0.0"
        major, minor, patch = map(int, parts)
        change_type = change_type.lower()
        if change_type == "major":
            return f"{major + 1}.0.0"
        if change_type == "minor":
            return f"{major}.{minor + 1}.0"
        return f"{major}.{minor}.{patch + 1}"

    # ─── 差异 ───

    def diff(
        self,
        version_a: str | None = None,
        version_b: str | None = None,
    ) -> RuleSetDiff:
        """对比两个版本（或当前与最新归档）。"""
        rs_a = self._load_version_or_current(version_a)
        rs_b = self._load_version_or_current(version_b)
        return self._compute_diff(rs_a, rs_b)

    def _load_version_or_current(self, version: str | None) -> RuleSet:
        """加载指定版本；若未指定或为当前磁盘版本，则从磁盘当前文件加载。"""
        if version is None:
            return self.load(resolve_templates=False)
        current = self.load(resolve_templates=False)
        if current.meta.version == version or current.version == version:
            return current
        return self._load_version(version)

    @staticmethod
    def _compute_diff(rs_a: RuleSet, rs_b: RuleSet) -> RuleSetDiff:
        """计算两个 RuleSet 的差异。"""
        rules_a = {r.id: r.model_dump() for r in rs_a.rules}
        rules_b = {r.id: r.model_dump() for r in rs_b.rules}

        added = [rules_b[r] for r in rules_b if r not in rules_a]
        removed = [rules_a[r] for r in rules_a if r not in rules_b]
        modified: list[dict[str, Any]] = []
        unchanged: list[str] = []

        for rid in rules_a:
            if rid not in rules_b:
                continue
            if rules_a[rid] != rules_b[rid]:
                modified.append(
                    {
                        "rule_id": rid,
                        "before": rules_a[rid],
                        "after": rules_b[rid],
                    }
                )
            else:
                unchanged.append(rid)

        return RuleSetDiff(
            version_from=rs_a.meta.version or rs_a.version,
            version_to=rs_b.meta.version or rs_b.version,
            added_rules=added,
            removed_rules=removed,
            modified_rules=modified,
            unchanged_rules=unchanged,
        )

    # ─── 应用与回滚 ───

    def apply(self, rule_set: RuleSet, commit_message: str = "") -> str:
        """应用新的 RuleSet，将当前版本归档后保存新版本。

        Args:
            rule_set: 要应用的 RuleSet。
            commit_message: 变更说明。

        Returns:
            应用的版本号。

        Raises:
            ValueError: 语义校验失败。
        """
        errors = RuleSetValidator().validate(rule_set)
        if errors:
            raise ValueError(f"RuleSet 语义校验失败: {errors}")

        # 归档当前版本
        try:
            current = self.load(resolve_templates=False)
            self._archive_version(current)
        except Exception:  # noqa: BLE001 - 当前无版本时可继续
            pass

        # 更新时间戳
        now = datetime.now(UTC).isoformat()
        rule_set.meta.updated_at = now
        if not rule_set.meta.created_at:
            rule_set.meta.created_at = now
        rule_set.version = rule_set.meta.version or rule_set.version

        self._save_rule_set(rule_set)
        self._record_change(
            RuleSetChange(
                version=rule_set.version,
                timestamp=now,
                change_type="apply",
                description=commit_message,
            )
        )
        return rule_set.version

    def rollback(self, version: str | None = None) -> RuleSet:
        """回滚到指定版本（默认最近归档版本）。"""
        if version is None:
            version = self._get_last_archived_version()

        archived_path = self.history_dir / f"rule_set_{version}.yaml"
        if not archived_path.exists():
            raise FileNotFoundError(f"未找到归档版本: {version}")

        rule_set = ConfigLoader.load_rule_set(archived_path, resolve_templates=False)
        self._save_rule_set(rule_set)

        now = datetime.now(UTC).isoformat()
        self._record_change(
            RuleSetChange(
                version=rule_set.version,
                timestamp=now,
                change_type="rollback",
                description=f"回滚到版本 {version}",
                diff={"restored_from": version},
            )
        )
        return rule_set

    # ─── 历史 ───

    def list_history(self) -> list[RuleSetChange]:
        """返回按时间顺序排列的变更历史。"""
        history_path = self.history_dir / self.HISTORY_FILE
        if not history_path.exists():
            return []
        data = json.loads(history_path.read_text(encoding="utf-8"))
        return [RuleSetChange.model_validate(c) for c in data]

    # ─── 内部辅助 ───

    def _save_rule_set(self, rule_set: RuleSet) -> None:
        data = rule_set.model_dump(by_alias=True, exclude_none=True)
        self.rule_set_path.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    def _archive_version(self, rule_set: RuleSet) -> Path:
        version = rule_set.meta.version or rule_set.version
        path = self.history_dir / f"rule_set_{version}.yaml"
        data = rule_set.model_dump(by_alias=True, exclude_none=True)
        path.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return path

    def _record_change(self, change: RuleSetChange) -> None:
        history_path = self.history_dir / self.HISTORY_FILE
        history: list[dict[str, Any]] = []
        if history_path.exists():
            history = json.loads(history_path.read_text(encoding="utf-8"))
        history.append(change.model_dump())
        history_path.write_text(
            json.dumps(history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_version(self, version: str) -> RuleSet:
        path = self.history_dir / f"rule_set_{version}.yaml"
        return ConfigLoader.load_rule_set(path, resolve_templates=False)

    def _load_last_saved(self) -> RuleSet:
        return ConfigLoader.load_rule_set(self.rule_set_path, resolve_templates=False)

    def _get_last_archived_version(self) -> str:
        archives = sorted(self.history_dir.glob("rule_set_*.yaml"))
        if not archives:
            raise FileNotFoundError("没有可回滚的归档版本")
        return archives[-1].stem.replace("rule_set_", "")
