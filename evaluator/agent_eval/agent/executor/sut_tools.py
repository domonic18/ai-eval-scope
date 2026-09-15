"""SUT Tools — 执行域通用工具集。

工具实现为普通异步方法（可直接调用与测试，不依赖任何 Agent 框架），
ToolExporterMixin（agent/tools.py）惰性导出 LangChain Tool 显式绑定给
DeepAgents；MCP 封装为可选能力（未在本期排期）。

工具面白名单（v4.8 安全裁剪）：默认仅导出通用工具（DEFAULT_EXECUTION_TOOLS），
invoke_http_sut/invoke_cli_sut **退出 LLM 工具面**——SUT 交互唯一出口是通道
语义工具（agent_run 族 / sut_request）。实测 generic_http 任务中 LLM 借
invoke_cli_sut（任意 shell 无沙箱）cat 凭证与 .env，prompts 禁令拦不住，
结构性裁剪才有效。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from jinja2 import Template as JinjaTemplate

from agent_eval.agent.core.tools import TEMPLATE_SYNTAX_HINT, ToolExporterMixin, ToolSpec
from agent_eval.agent.core.tools import truncate as _truncate
from agent_eval.core.exceptions import CollectionError, ToolExecutionError
from agent_eval.execution.models import SUTToolsConfig
from agent_eval.execution.utils import extract_by_path as _extract_by_path
from agent_eval.storage.collector import DirectoryCollector
from agent_eval.storage.package import (
    PackageManifest,
    PackageMetadata,
    PackageStatus,
    generate_run_id,
)

# 工具输出截断上限（字节级上下文经济性保护，非业务阈值）
HTTP_RAW_MAX_CHARS = 4000
CLI_OUTPUT_MAX_CHARS = 20000

TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="invoke_http_sut",
        description="发送 HTTP 请求到被测 Agent 服务（支持 Jinja2 模板渲染与响应字段映射）",
        method="invoke_http_sut",
    ),
    ToolSpec(
        name="invoke_cli_sut",
        description="通过子进程执行 CLI 命令调用本地被测 Agent",
        method="invoke_cli_sut",
    ),
    ToolSpec(
        name="scan_directory",
        description="扫描目录结构，生成文件清单（模块/文件类型/层级深度）",
        method="scan_directory",
    ),
    ToolSpec(
        name="read_file",
        description="读取文件内容（文本）",
        method="read_file",
    ),
    ToolSpec(
        name="list_files",
        description="列出目录中匹配模式的文件",
        method="list_files",
    ),
    ToolSpec(
        name="collect_results",
        description="收集执行结果文件/目录到 workspace 的 output 目录",
        method="collect_results",
    ),
    ToolSpec(
        name="write_package",
        description="写入 ExecutionPackage（manifest/metadata/trace/metrics）到 workspace，任务结束时必须调用",
        method="write_package",
    ),
]

# 执行面默认工具集：裸调用工具（invoke_http_sut/invoke_cli_sut）不入选——
# 语义工具是唯一 SUT 出口，方法本体保留（服务端直调/测试/显式恢复可达）
DEFAULT_EXECUTION_TOOLS: tuple[str, ...] = (
    "scan_directory",
    "read_file",
    "list_files",
    "collect_results",
    "write_package",
)


def content_fingerprint(package_dir: Path) -> str:
    """聚合包内全部内容文件的 sha256（排序稳定，跳过 manifest 自身与隐藏文件）。

    write_package 时 answer/trace/metrics 尚未由 ExecutionAgent 物化，指纹只反映
    当时内容；物化完成后须由 ExecutionAgent 重算（见 _refresh_content_hash）。
    """
    import hashlib

    h = hashlib.sha256()
    files = sorted(
        p
        for p in package_dir.rglob("*")
        if p.is_file() and p.name != "manifest.json" and not p.name.startswith(".")
    )
    for f in files:
        h.update(f.relative_to(package_dir).as_posix().encode("utf-8"))
        h.update(b"\x00")
        h.update(f.read_bytes())
        h.update(b"\x00")
    return h.hexdigest()


class SUTToolServer(ToolExporterMixin):
    """SUT 交互工具注册表，为 ExecutionAgent 提供工具集。

    工具方法不依赖 deepagents/langchain，可独立调用与测试；
    to_langchain_tools()（ToolExporterMixin）在 Agent-Driven 模式下导出 LangChain Tool。
    """

    TOOL_SPECS = TOOL_SPECS

    def __init__(
        self,
        config: SUTToolsConfig | None = None,
        *,
        workspace_dir: str | Path | None = None,
        http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
        enabled_tools: Sequence[str] | None = None,
    ) -> None:
        """初始化 SUTToolServer。

        Args:
            config: SUT Tools 配置（超时/默认请求头/文件模式等）。
            workspace_dir: workspace 根目录（collect_results/write_package 落盘位置，
                同时是文件工具的读取边界）。目的地路径属执行器基础设施，不由 LLM
                决定——实测 LLM 会幻觉绝对路径（/workspace/...）导致 OS 错误击穿图执行。
            http_client_factory: 注入自定义 httpx.AsyncClient（测试用 MockTransport）。
            enabled_tools: 导出进 LLM 工具面的工具名白名单；None → 安全默认集
                （DEFAULT_EXECUTION_TOOLS，不含 invoke_* 裸调用工具）。
        """
        self.config = config or SUTToolsConfig()
        self.workspace_dir: Path | None = Path(workspace_dir) if workspace_dir else None
        # 任务配置允许的额外读取根（目录模式：task.directory_path 是任务作者
        # 配置的 SUT 产出目录，不在 workspace 内）——执行循环逐任务注入
        self.extra_allowed_roots: list[Path] = []
        self._http_client_factory = http_client_factory
        names = set(enabled_tools) if enabled_tools is not None else set(DEFAULT_EXECUTION_TOOLS)
        unknown = sorted(names - {spec.name for spec in TOOL_SPECS})
        if unknown:
            raise ToolExecutionError(
                f"enabled_tools 含未知工具名: {unknown}"
                f"（可用: {', '.join(spec.name for spec in TOOL_SPECS)}）",
                details={"unknown": unknown},
            )
        # 实例属性遮蔽类属性：工具面 100% 由 TOOL_SPECS 决定（to_langchain_tools/
        # describe_tools/get_tool_names 同源）。默认即安全——ExecutionAgent 的
        # 兜底构造（未显式装配的调用方）同样收窄，无需装配点记得传参
        self.TOOL_SPECS = [spec for spec in TOOL_SPECS if spec.name in names]

    def _package_root(self, task_id: str) -> Path:
        """校验 task_id 并解析包目录（workspace/{task_id}，防路径逃逸）。"""
        if self.workspace_dir is None:
            raise ToolExecutionError(
                "workspace_dir 未配置（SUTToolServer 构造时需传入或由 ExecutionAgent 注入）"
            )
        if not re.fullmatch(r"[A-Za-z0-9._-]+", task_id):
            raise ToolExecutionError(
                f"非法 task_id（仅允许字母/数字/./_/-）: {task_id!r}",
                details={"task_id": task_id},
            )
        return self.workspace_dir / task_id

    # ─── SUT 调用 ───

    async def invoke_http_sut(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body_template: str | None = None,
        template_vars: dict[str, Any] | None = None,
        response_mapping: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """发送 HTTP 请求到被测 Agent 服务。

        1. body_template + template_vars 时用 Jinja2 渲染请求体
        2. 发送请求（合并 SUTToolsConfig 默认请求头与超时）
        3. response_mapping 按点分路径提取输出字段
        """
        url = self._resolve_url(url)
        merged_headers = {**self.config.http_default_headers, **(headers or {})}
        body: str | None = None
        if body_template is not None:
            try:
                body = JinjaTemplate(body_template).render(**(template_vars or {}))
            except Exception as e:  # noqa: BLE001 — 模板错误转纠正提示（渲染 TypeError 等曾击穿会话）
                raise ToolExecutionError(
                    f"body_template 渲染失败（{e}）。{TEMPLATE_SYNTAX_HINT}",
                    details={"url": url},
                ) from e

        client_cm = (
            self._http_client_factory()
            if self._http_client_factory
            else httpx.AsyncClient(
                timeout=timeout or self.config.http_timeout, follow_redirects=True
            )
        )
        try:
            async with client_cm as client:
                response = await client.request(
                    method=method.upper(),
                    url=url,
                    headers=merged_headers or None,
                    content=body,
                )
        except httpx.HTTPError as e:
            raise ToolExecutionError(
                f"HTTP SUT 调用失败: {e}",
                details={"url": url, "method": method},
            ) from e

        result: dict[str, Any] = {
            "status_code": response.status_code,
            "raw": _truncate(response.text, HTTP_RAW_MAX_CHARS),
        }
        if response_mapping:
            try:
                parsed = response.json()
            except json.JSONDecodeError as e:
                raise ToolExecutionError(
                    f"响应不是合法 JSON，无法执行 response_mapping: {e}",
                    details={"url": url, "status_code": response.status_code},
                ) from e
            for target_field, source_path in response_mapping.items():
                result[target_field] = _extract_by_path(parsed, source_path)
        return result

    async def invoke_cli_sut(
        self,
        command: str,
        working_dir: str | None = None,
        env_vars: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """通过子进程执行 CLI 命令调用本地被测 Agent。

        超时不抛异常（返回 exit_code=-1 与超时说明），由 Agent 决策重试或降级。
        """
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir or self.config.cli_working_dir,
            env={**os.environ, **(env_vars or {})},
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout or self.config.cli_default_timeout
            )
            return {
                "exit_code": proc.returncode,
                "stdout": _truncate(stdout.decode(errors="replace"), CLI_OUTPUT_MAX_CHARS),
                "stderr": _truncate(stderr.decode(errors="replace"), CLI_OUTPUT_MAX_CHARS),
            }
        except TimeoutError:
            proc.kill()
            # kill 后必须 wait 回收：子进程 transport 若留到事件 loop 关闭后才被
            # GC，__del__ 里 close() 会撞 "Event loop is closed"（unraisable 告警源）
            try:
                await proc.wait()
            except Exception:
                pass
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"命令执行超时（{timeout or self.config.cli_default_timeout}秒）",
            }

    # ─── 目录 / 文件 ───

    def _within_workspace(self, path: Path) -> bool:
        """文件工具读取边界：路径 resolve 后须位于 workspace 子树或允许根内。

        纵深防御（v4.8）：裸调用工具裁撤后 read_file 是唯一的任意路径读取面——
        实测 LLM 曾读取 .secret/.env 与凭证文件并回流上下文。未设 workspace_dir
        不限制（纯方法级使用/测试兼容）。
        """
        if self.workspace_dir is None:
            return True
        resolved = path.resolve()
        for root in (self.workspace_dir, *self.extra_allowed_roots):
            try:
                resolved.relative_to(root.resolve())
            except ValueError:
                continue
            return True
        return False

    async def scan_directory(
        self,
        directory_path: str,
        file_patterns: list[str] | None = None,
    ) -> dict[str, Any]:
        """遍历目录树收集匹配文件，返回 DirectoryManifest 的 JSON 序列化结果。"""
        if not self._within_workspace(Path(directory_path)):
            raise ToolExecutionError(
                f"路径越界: {directory_path}——目录工具仅允许访问 workspace 内路径",
                details={"path": directory_path},
            )
        collector = DirectoryCollector(
            root_dir=directory_path,
            file_patterns=file_patterns or self.config.file_patterns,
        )
        try:
            manifest = collector.collect()
        except (FileNotFoundError, NotADirectoryError) as e:
            raise ToolExecutionError(f"目录扫描失败: {e}") from e
        return manifest.model_dump(mode="json")

    async def read_file(self, file_path: str, encoding: str = "utf-8") -> str:
        """读取指定文件的内容并返回。"""
        path = Path(file_path)
        if not self._within_workspace(path):
            raise ToolExecutionError(
                f"路径越界: {file_path}——read_file 仅允许访问 workspace 内路径",
                details={"path": file_path},
            )
        try:
            return path.read_text(encoding=encoding)
        except OSError as e:
            raise ToolExecutionError(f"文件读取失败: {e}", details={"path": file_path}) from e

    async def list_files(
        self,
        directory_path: str,
        pattern: str = "*",
        recursive: bool = False,
    ) -> list[str]:
        """列出目录中匹配指定模式的文件（recursive 时返回相对路径）。"""
        base = Path(directory_path)
        if not self._within_workspace(base):
            raise ToolExecutionError(
                f"路径越界: {directory_path}——目录工具仅允许访问 workspace 内路径",
                details={"path": directory_path},
            )
        if not base.is_dir():
            raise ToolExecutionError(f"不是目录: {directory_path}")
        try:
            if recursive:
                return [str(p.relative_to(base)) for p in base.rglob(pattern) if p.is_file()]
            return [str(p.name) for p in base.glob(pattern) if p.is_file()]
        except OSError as e:
            raise ToolExecutionError(f"目录遍历失败: {e}") from e

    async def collect_results(
        self,
        source_paths: list[str],
        task_id: str,
    ) -> dict[str, Any]:
        """将源文件/目录复制到 {workspace_dir}/{task_id}/output/（目的地由服务端持有）。"""
        output_dir = self._package_root(task_id) / "output"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ToolExecutionError(
                f"输出目录创建失败: {e}", details={"output_dir": str(output_dir)}
            ) from e

        collected: list[str] = []
        try:
            for source in source_paths:
                src = Path(source)
                if src.is_file():
                    dst = output_dir / src.name
                    shutil.copy2(src, dst)
                    collected.append(str(dst))
                elif src.is_dir():
                    dst = output_dir / src.name
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                    collected.append(str(dst))
                else:
                    raise CollectionError(f"源路径不存在: {source}", details={"path": source})
        except OSError as e:
            raise CollectionError(f"结果采集失败: {e}") from e
        return {"collected_files": collected, "output_dir": str(output_dir)}

    async def write_package(
        self,
        task_id: str,
        success: bool,
        output_files: list[str] | None = None,
        output_directory: str | None = None,
        metadata: dict[str, Any] | None = None,
        error: str | None = None,
        trace: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """将 ExecutionPackage 写入 workspace（manifest/metadata/trace/metrics）。

        写入布局与评估引擎（PipelineEngine）的 ExecutionPackage.load 对齐。
        目的地 workspace 由服务端持有，LLM 只传 task_id 与内容字段。
        """
        run_id = generate_run_id()
        package_dir = self._package_root(task_id)
        try:
            package_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ToolExecutionError(
                f"包目录创建失败: {e}", details={"package_dir": str(package_dir)}
            ) from e

        manifest = PackageManifest(
            package_id=f"pkg_{run_id}_{task_id}",
            created_at=datetime.now(UTC).isoformat(),
            task_id=task_id,
            sut_config_id="agent",
            status=PackageStatus.SUCCESS if success else PackageStatus.FAILED,
        )
        # 执行包内容指纹——先写内容文件再算 hash 回填 manifest，评估缓存键
        # 恢复内容维度（此前恒 null，包内容变化仍命中旧缓存）
        (package_dir / "manifest.json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )
        manifest.content_hash = self._content_fingerprint(package_dir)
        (package_dir / "manifest.json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )

        pkg_metadata = PackageMetadata(
            sut_name="agent",
            python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        ).model_dump()
        pkg_metadata.update(metadata or {})
        (package_dir / "metadata.json").write_text(
            json.dumps(pkg_metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        if trace is not None:
            (package_dir / "trace.json").write_text(
                json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        if metrics is not None:
            (package_dir / "metrics.json").write_text(
                json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        summary: dict[str, Any] = {
            "package_dir": str(package_dir),
            "success": success,
            "output_files": output_files or [],
        }
        if output_directory:
            summary["output_directory"] = output_directory
        if error:
            summary["error"] = error
        return summary

    def _content_fingerprint(self, package_dir: Path) -> str:
        """聚合 output/ + task/trace/metrics 内容的 sha256（排序稳定，跳过 manifest 自身）。"""
        return content_fingerprint(package_dir)

    def _resolve_url(self, url: str) -> str:
        """相对 URL 拼接配置的 http_base_url；无 base_url 的相对路径直接报错。

        绝对 URL 受 host 边界约束（allowed_hosts 非空时仅放行白名单，缺省不限
        制）：实测执行 Agent 曾在协议通道 404 后臆测 localhost:8000/8080 等地址
        乱试——LLM 只该打被测系统配置域，越界直接拒绝并指回语义工具。
        """
        if url.startswith(("http://", "https://")):
            allowed = {h.lower() for h in self.config.allowed_hosts if h}
            if allowed:
                host = (urlparse(url).hostname or "").lower()
                if host not in allowed:
                    raise ToolExecutionError(
                        f"URL 越界: {url}——仅允许访问被测系统配置域"
                        f"（{', '.join(sorted(allowed))}）。协议通道任务请用 agent_run 等"
                        "语义工具调用 SUT，不要自行构造 HTTP 地址",
                        details={"url": url, "host": host},
                    )
            return url
        if not self.config.http_base_url:
            raise ToolExecutionError(
                f"相对 URL 需要配置 http_base_url: {url!r}",
                details={"url": url},
            )
        return f"{self.config.http_base_url.rstrip('/')}/{url.lstrip('/')}"
