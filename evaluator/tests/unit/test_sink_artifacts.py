"""sink 制品上传测试 — 按样本归属 + kind 分类 + contentType 语义化（产物修复）。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from agent_eval.observability.sink import ResultSink, _content_type_for


class _FakeClient:
    """记录 presign/upload 调用，返回确定 object_key。"""

    def __init__(self) -> None:
        self.uploads: list[tuple[str, str, str, str]] = []  # (sample_id, kind, ct, name)

    def presign_put(self, req: dict) -> dict:
        return {"object_key": f"obj/{req['kind']}/{req['name']}"}

    def upload_file(self, path: Path, presigned: dict, content_type: str) -> None:
        del path, presigned, content_type


def _make_sink(tmp_path: Path) -> tuple[ResultSink, _FakeClient]:
    client = _FakeClient()
    sink = ResultSink.__new__(ResultSink)  # 绕过 config/queue 初始化（只测上传方法）
    sink.cfg = SimpleNamespace(queue_replay_batch=10, batch_max_events=50)
    sink.log = SimpleNamespace(warning=lambda *a, **k: None, error=lambda *a, **k: None)
    sink.client = client
    sink.queue = SimpleNamespace(
        replay=lambda *a, **k: {"sent": 0},
    )

    # 拦截 _upload_artifact 的计数与真实上传，改走 FakeClient 记录
    def _fake_upload(
        local_path,
        *,
        external_run_id,
        external_sample_id,
        kind,
        content_type,
        original_name,
        report,
    ):
        client.uploads.append((external_sample_id, kind, content_type, original_name))
        report.artifacts_uploaded += 1
        return f"obj/{kind}/{original_name}"

    sink._upload_artifact = _fake_upload  # type: ignore[method-assign]
    del tmp_path
    return sink, client


def _make_pkg_set(tmp_path: Path, tasks: list[str]) -> Path:
    """构造包集合目录 packages/{task_id}/{包根 json + output/answer.md}。"""
    root = tmp_path / "packages"
    for t in tasks:
        pkg = root / t
        (pkg / "output").mkdir(parents=True)
        (pkg / "output" / "answer.md").write_text(f"# {t} 回答", encoding="utf-8")
        for name in ("manifest", "metadata", "metrics", "task", "trace"):
            (pkg / f"{name}.json").write_text(json.dumps({"t": t, "f": name}), encoding="utf-8")
        (pkg / "unrelated.txt").write_text("不应上传", encoding="utf-8")
    return root


def _samples(ids: list[str]) -> list[SimpleNamespace]:
    return [SimpleNamespace(sample_id=i) for i in ids]


class TestUploadPackageArtifacts:
    def test_multi_sample_each_gets_own_artifacts(self, tmp_path: Path) -> None:
        """包集合目录：3 样本各自获得自己的 output 产物 + 5 个技术文件。"""
        sink, client = _make_sink(tmp_path)
        root = _make_pkg_set(tmp_path, ["t_a", "t_b", "t_c"])
        events = sink._upload_package_artifacts(
            root,
            "r1",
            _samples(["t_a", "t_b", "t_c"]),
            SimpleNamespace(artifacts_uploaded=0, artifacts_failed=0),
        )

        by_sample: dict[str, list[tuple[str, str]]] = {}
        for sid, kind, ct, name in client.uploads:
            by_sample.setdefault(sid, []).append((kind, name))
        for sid in ("t_a", "t_b", "t_c"):
            kinds = by_sample.get(sid, [])
            outs = [n for k, n in kinds if k == "output"]
            traces = [n for k, n in kinds if k == "trace"]
            assert outs == ["answer.md"], f"{sid} output 应只有 answer.md，得到 {outs}"
            assert sorted(traces) == [
                "manifest.json",
                "metadata.json",
                "metrics.json",
                "task.json",
                "trace.json",
            ]
        # 事件侧同样按样本归属（3 样本 × 6 文件 = 18）
        assert len(events) == 18
        sids = {e["data"]["external_sample_id"] for e in events}
        assert sids == {"t_a", "t_b", "t_c"}

    def test_single_package_dir_goes_to_sole_sample(self, tmp_path: Path) -> None:
        """单包目录（含 manifest.json）：全部文件归唯一样本。"""
        sink, client = _make_sink(tmp_path)
        root = _make_pkg_set(tmp_path, ["solo"])
        events = sink._upload_package_artifacts(
            root / "solo",
            "r1",
            _samples(["solo"]),
            SimpleNamespace(artifacts_uploaded=0, artifacts_failed=0),
        )
        sids = {sid for sid, *_ in client.uploads}
        assert sids == {"solo"}
        assert len(events) == 6  # answer.md + 5 技术文件

    def test_kind_and_content_type_semantics(self, tmp_path: Path) -> None:
        """kind 分类（output/trace）与 contentType 按后缀（md/json）。"""
        sink, client = _make_sink(tmp_path)
        root = _make_pkg_set(tmp_path, ["t"])
        sink._upload_package_artifacts(
            root / "t",
            "r",
            _samples(["t"]),
            SimpleNamespace(artifacts_uploaded=0, artifacts_failed=0),
        )
        ct_map = {name: ct for _, kind, ct, name in client.uploads if kind == "trace"}
        assert all(ct == "application/json" for ct in ct_map.values())
        out_ct = [
            ct for sid, kind, ct, name in client.uploads if kind == "output" and name == "answer.md"
        ]
        assert out_ct == ["text/markdown"]


class TestContentTypeFor:
    def test_suffix_mapping(self, tmp_path: Path) -> None:
        del tmp_path
        assert _content_type_for(Path("a.html")) == "text/html"
        assert _content_type_for(Path("a.json")) == "application/json"
        assert _content_type_for(Path("a.md")) == "text/markdown"
        assert _content_type_for(Path("a.txt")) == "text/plain"
