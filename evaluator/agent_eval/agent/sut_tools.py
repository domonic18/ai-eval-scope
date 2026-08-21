"""SUT Tools — SUT 交互工具集（arch/03 §四 v4.6）。

提供 invoke_http_sut、invoke_cli_sut、scan_directory、read_file、
collect_results、write_package、list_files 七个工具。v4.6 起 SUTToolServer
演进为**工具注册表**：工具实现为普通异步方法（可直接调用与测试，不依赖任何
Agent 框架），to_langchain_tools() 惰性加载 langchain_core 将其导出为
LangChain Tool 显式绑定给 DeepAgents；MCP 封装为可选能力（未在本期排期）。
"""

from __future__ import annotations

import asyncio
import functools
import json
import os
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from jinja2 import Template as JinjaTemplate

from agent_eval.core.exceptions import (
    AgentError,
    CollectionError,
    ToolExecutionError,
)
from agent_eval.execution.models import SUTToolsConfig
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


@dataclass(frozen=True)
class ToolSpec:
    """单个 SUT 工具的注册信息（名称/描述/方法名）。"""

    name: str
    description: str
    method: str


def _truncate(text: str, max_chars: int) -> str:
    """超长文本截断（尾部追加标记）。"""
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}...（已截断，共 {len(text)} 字符）"


def _extract_by_path(data: Any, path: str) -> Any:
    """按点分路径提取字段值（数字段表示列表下标），如 "choices.0.message.content"。"""
    current = data
    for segment in path.split("."):
        if isinstance(current, dict):
            current = current[segment]
        elif isinstance(current, list) and segment.lstrip("-").isdigit():
            current = current[int(segment)]
        else:
            raise ToolExecutionError(
                f"response_mapping 路径无法解析: {path!r}（当前节点类型 {type(current).__name__}）",
                details={"path": path, "segment": segment},
            )
    return current


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


class SUTToolServer:
    """SUT 交互工具注册表，为 ExecutionAgent 提供工具集。

    工具方法不依赖 deepagents/langchain，可独立调用与测试；
    to_langchain_tools() 在 Agent-Driven 模式下将其导出为 LangChain Tool。
    """

    def __init__(
        self,
        config: SUTToolsConfig | None = None,
        *,
        http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        """初始化 SUTToolServer。

        Args:
            config: SUT Tools 配置（超时/默认请求头/文件模式等）。
            http_client_factory: 注入自定义 httpx.AsyncClient（测试用 MockTransport）。
        """
        self.config = config or SUTToolsConfig()
        self._http_client_factory = http_client_factory

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
            body = JinjaTemplate(body_template).render(**(template_vars or {}))

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
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"命令执行超时（{timeout or self.config.cli_default_timeout}秒）",
            }

    # ─── 目录 / 文件 ───

    async def scan_directory(
        self,
        directory_path: str,
        file_patterns: list[str] | None = None,
    ) -> dict[str, Any]:
        """遍历目录树收集匹配文件，返回 DirectoryManifest 的 JSON 序列化结果。"""
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
        workspace_dir: str,
        task_id: str,
    ) -> dict[str, Any]:
        """将源文件/目录复制到 {workspace_dir}/{task_id}/output/。"""
        output_dir = Path(workspace_dir) / task_id / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

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
        workspace_dir: str,
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
        """
        run_id = generate_run_id()
        package_dir = Path(workspace_dir) / task_id
        package_dir.mkdir(parents=True, exist_ok=True)

        manifest = PackageManifest(
            package_id=f"pkg_{run_id}_{task_id}",
            created_at=datetime.now(UTC).isoformat(),
            task_id=task_id,
            sut_config_id="agent",
            status=PackageStatus.SUCCESS if success else PackageStatus.FAILED,
        )
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

    # ─── 工具注册表 ───

    def to_langchain_tools(self) -> list[Any]:
        """导出 LangChain Tool 列表供 DeepAgents 显式绑定（v4.6，惰性导入）。"""
        try:
            from langchain_core.tools import StructuredTool
        except ImportError:
            raise AgentError(
                "导出 LangChain Tool 需要 langchain-core。请执行: pip install 'agent-eval[agent]'",
                details={"missing_module": "langchain_core"},
            ) from None
        return [
            StructuredTool.from_function(
                coroutine=self._json_tool(getattr(self, spec.method)),
                name=spec.name,
                description=spec.description,
            )
            for spec in TOOL_SPECS
        ]

    def _json_tool(self, method: Any) -> Any:
        """包装工具方法：结果 JSON 序列化为字符串（dict/list 统一文本化）。

        functools.wraps 保留原方法签名（含类型注解与默认值），
        StructuredTool.from_function 由此推导参数 Schema。
        """

        @functools.wraps(method)
        async def run(*args: Any, **kwargs: Any) -> str:
            result = await method(*args, **kwargs)
            if isinstance(result, str):
                return result
            return json.dumps(result, ensure_ascii=False, default=str)

        return run

    def get_tool_names(self) -> list[str]:
        """返回所有注册的工具名称。"""
        return [spec.name for spec in TOOL_SPECS]

    def describe_tools(self) -> str:
        """返回工具描述清单，用于构建 System Prompt。"""
        lines = []
        for spec in TOOL_SPECS:
            method = getattr(self, spec.method)
            params = ", ".join(
                f"{name}: {annot.__name__ if hasattr(annot, '__name__') else annot}"
                for name, annot in getattr(method, "__annotations__", {}).items()
                if name != "return"
            )
            lines.append(f"- {spec.name}({params}): {spec.description}")
        return "\n".join(lines)

    def _resolve_url(self, url: str) -> str:
        """相对 URL 拼接配置的 http_base_url；无 base_url 的相对路径直接报错。"""
        if url.startswith(("http://", "https://")):
            return url
        if not self.config.http_base_url:
            raise ToolExecutionError(
                f"相对 URL 需要配置 http_base_url: {url!r}",
                details={"url": url},
            )
        return f"{self.config.http_base_url.rstrip('/')}/{url.lstrip('/')}"
