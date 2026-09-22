"""数据集域工具单测（Sprint 14c，arch/15 v4.13 §6.11）。

工具直调（不经 LLM 面）：确认门槛/旁路拒绝/委托参数红线（无 output/token）/
本地状态配对/失败语义。DatasetManager 全程 monkeypatch（编排回归在
test_manager；下载器 SDK 调用在 test_downloader）——禁联网。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_eval.agent.workbench.datasets import DatasetToolServer
from agent_eval.datasets import list_datasets as registry_list


def _first_entry():
    return next(iter(registry_list().values()))


def _fake_manager(monkeypatch, tmp_path: Path, calls: dict, *, fail: Exception | None = None):
    """替换 DatasetManager 为记录调用的桩（源模块与 re-export 两处同打）。"""
    from agent_eval.datasets import manager as manager_mod

    class _FakeManager:
        def download(self, name, source=None, output=None, revision=None, token=None, force=False):
            calls["download"] = dict(
                name=name, source=source, output=output, revision=revision, token=token, force=force
            )
            if fail is not None:
                raise fail
            target = tmp_path / "datasets" / "fake-ds"
            target.mkdir(parents=True, exist_ok=True)
            (target / "_dataset_manifest.json").write_text(
                json.dumps(
                    {
                        "name": name,
                        "source": source or "modelscope",
                        "repo_id": "org/fake-ds",
                        "downloaded_at": "2026-09-21T00:00:00",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (target / "data.jsonl").write_text('{"q": "1"}\n', encoding="utf-8")
            return target

    monkeypatch.setattr(manager_mod, "DatasetManager", _FakeManager)
    monkeypatch.setattr("agent_eval.datasets.DatasetManager", _FakeManager)


def _server(answers: list[str] | None, **kw) -> tuple[DatasetToolServer, dict]:
    calls: dict = {"questions": []}
    answers_iter = iter(answers) if answers is not None else None

    async def ask_fn(question, *, options=None, secret=False):
        calls["questions"].append(question)
        return next(answers_iter, "")

    server = DatasetToolServer(ask_fn=ask_fn if answers is not None else None, **kw)
    return server, calls


class TestAssembly:
    def test_assembles_two_tools(self) -> None:
        server = DatasetToolServer()
        names = {t.name for t in server.to_langchain_tools()}
        assert (
            names
            == {s.name for s in DatasetToolServer.TOOL_SPECS}
            == {
                "list_datasets",
                "download_dataset",
            }
        )


class TestListDatasets:
    @pytest.mark.asyncio
    async def test_registry_paired_with_local_manifests(self, tmp_path: Path) -> None:
        entry = _first_entry()
        dir_name = (entry.get_id(entry.default_source) or entry.id).rsplit("/", 1)[-1]
        ds_dir = tmp_path / "datasets" / dir_name
        ds_dir.mkdir(parents=True)
        (ds_dir / "_dataset_manifest.json").write_text(
            json.dumps(
                {
                    "name": entry.id,
                    "repo_id": entry.get_id(entry.default_source),
                    "source": entry.default_source,
                    "downloaded_at": "2026-09-21T00:00:00",
                }
            ),
            encoding="utf-8",
        )
        server, _ = _server(None, workspace_root=tmp_path)
        result = await server.list_datasets()
        assert result["status"] == "done" and result["total"] >= 1
        hit = next(d for d in result["datasets"] if d["id"] == entry.id)
        assert hit["downloaded"] is True
        assert hit["downloaded_at"] == "2026-09-21T00:00:00"
        assert hit["local_path"] == str(ds_dir)
        others = [d for d in result["datasets"] if d["id"] != entry.id]
        assert all(d["downloaded"] is False for d in others)

    @pytest.mark.asyncio
    async def test_no_workspace_all_not_downloaded(self) -> None:
        server, _ = _server(None)
        result = await server.list_datasets()
        assert result["total"] >= 1
        assert all(d["downloaded"] is False for d in result["datasets"])


class TestDownloadGate:
    @pytest.mark.asyncio
    async def test_no_ask_fn_refused_manager_never_called(self, monkeypatch, tmp_path) -> None:
        calls: dict = {}
        _fake_manager(monkeypatch, tmp_path, calls)
        server = DatasetToolServer(ask_fn=None)
        result = await server.download_dataset("gsm8k")
        assert result["status"] == "refused"
        assert "download" not in calls  # 唯一旁路拒绝点：从未编排

    @pytest.mark.asyncio
    async def test_declined_shows_command_repo_target(self, monkeypatch, tmp_path) -> None:
        calls: dict = {}
        _fake_manager(monkeypatch, tmp_path, calls)
        server, svc_calls = _server(["取消"], workspace_root=tmp_path)
        result = await server.download_dataset("gsm8k", source="ms")
        assert result["status"] == "declined"
        assert "agent-eval dataset download gsm8k --source ms" in result["equivalent_command"]
        question = svc_calls["questions"][0]
        assert "落盘" in question and "datasets" in question  # 目标目录展示
        assert "download" not in calls  # 拒绝 → DatasetManager 从未被调用

    @pytest.mark.asyncio
    async def test_confirmed_delegates_without_output_token(self, monkeypatch, tmp_path) -> None:
        calls: dict = {}
        _fake_manager(monkeypatch, tmp_path, calls)
        server, _ = _server(["确认下载"], workspace_root=tmp_path)
        result = await server.download_dataset("gsm8k", source="ms", revision="main", force=True)
        assert result["status"] == "done"
        kwargs = calls["download"]
        assert kwargs["name"] == "gsm8k"
        assert kwargs["source"] == "ms" and kwargs["revision"] == "main" and kwargs["force"]
        # 红线（结构性保证的回归锚）：委托参数永不含 output/token
        assert kwargs["output"] is None and kwargs["token"] is None
        assert result["manifest_path"].endswith("_dataset_manifest.json")
        assert not any("token" in key for key in result)  # 回执键集不含 token 字段

    @pytest.mark.asyncio
    async def test_failure_returns_explainable_failed(self, monkeypatch, tmp_path) -> None:
        from agent_eval.core.exceptions import DatasetDownloadError

        calls: dict = {}
        _fake_manager(monkeypatch, tmp_path, calls, fail=DatasetDownloadError("网络不可达"))
        server, _ = _server(["确认下载"], workspace_root=tmp_path)
        result = await server.download_dataset("gsm8k")
        assert result["status"] == "failed"
        assert "网络不可达" in result["error"]
        assert result["dataset"] == "gsm8k"

    @pytest.mark.asyncio
    async def test_existing_target_noted_in_confirmation(self, monkeypatch, tmp_path) -> None:
        _fake_manager(monkeypatch, tmp_path, calls={})
        (tmp_path / "datasets" / "gsm8k").mkdir(parents=True)
        (tmp_path / "datasets" / "gsm8k" / "x.txt").write_text("n", encoding="utf-8")
        server, svc_calls = _server(["取消"], workspace_root=tmp_path)
        await server.download_dataset("gsm8k")
        assert "已存在" in svc_calls["questions"][0]  # 已存在跳过/force 语义如实告知
