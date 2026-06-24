"""KnowledgeAuditor — misconception pattern 质量审计与精确清理。

识别并删除「无有效锚定」的 misconception pattern，从数据层消除全文子串匹配的
误报根因；保留带有效锚定的、长裸词的、概念辨析的，以及错别字 / 拼音 / 用字
纠正类 pattern（真阳检测）。

「无有效锚定」涵盖两类（根因相同：pattern 仅靠短字面子串匹配，正常教学文本
讨论 / 使用这些字眼即误报）：
1. 超短裸词——概念名词（理想 / 信念 / 滞后性 / 价值观）。
2. 弱锚定通配——`.*` 仅连接短片段，无字符类 / 分组 / 定位等结构约束：
   - 片段全为功能词（因为.*所以 / 不是.*而是 / 是.*也）→ 匹配语法结构；
   - 恰好两单字通配（购.*买 / 翦.*剪）→ 古今字 / 通假字裸对，任意共现即匹配。

与 KnowledgeMerger 的差异：Merger 做增量合并（`yaml.safe_dump` 重写整文件，
丢失注释与格式）；Auditor 做 **格式保留的行级删除**——只摘除命中的 `- pattern:`
整块，保留注释、其它 section 与既有缩进 / 引号风格。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from agent_eval.config.paths import paths

# 全部正则元字符——pattern 不含任一即为裸词
_REGEX_META = set(".^$*+?()[]{}|\\")
# 「有效锚定」结构字符——出现任一则 pattern 能定位上下文（字符类 / 分组 / 定位 /
# 转义 / 量词范围），不视为弱锚定。
_EFFECTIVE_ANCHOR_CHARS = set("[](){}^$\\")

# 错别字 / 拼音 / 用字纠正标记——correct 命中则视为真阳检测（保留）。
# 收紧：仅匹配明确的「写法纠正」措辞，排除「应使用 / 的正确」等宽泛措辞（后者
# 常出现在概念辨析条目，如「习气」「绿沉沉」实为合法词，属误报源）。
_MISSPELLING_MARKERS = re.compile(
    r"应为|应作|应写作|写为|写成|写作|正确写法|错别字|误写|同音字|形近字"
)

# 汉语功能词（连词 / 介词 / 助词 / 结构词）。弱锚定通配 pattern 若片段全为此类，
# 说明它匹配的是语法结构（正确文本正常使用即命中）→ 误报源。
_FUNC_WORDS = frozenset(
    {
        "因为",
        "所以",
        "由于",
        "因此",
        "因而",
        "于是",
        "虽然",
        "但是",
        "尽管",
        "可是",
        "然而",
        "不仅",
        "而且",
        "并且",
        "乃至",
        "甚至",
        "既然",
        "就",
        "如果",
        "那么",
        "只要",
        "只有",
        "才",
        "无论",
        "不管",
        "都",
        "也",
        "还",
        "既",
        "又",
        "一边",
        "一面",
        "不是",
        "而是",
        "和",
        "与",
        "或",
        "及",
        "并",
        "或者",
        "还是",
        "以及",
        "至",
        "于",
        "为",
        "被",
        "把",
        "将",
        "的",
        "了",
        "吗",
        "呢",
        "吧",
        "啊",
        "着",
        "过",
        "是",
        "在",
        "有",
        "这",
        "那",
        "其",
        "之",
        "以",
        "如",
        "若",
        "则",
        "爲",
        "於",
    }
)

# 顶层 section 起始（col 0 的 `misconceptions:`）
_SECTION_START = re.compile(r"^misconceptions:\s*(?:#.*)?$")
# 一个 misconception 列表项：捕获缩进 + pattern 值
_ITEM_START = re.compile(r"^(\s*)-\s+pattern:\s*(.+?)\s*(?:#.*)?$")


def is_bare_word(pattern: str) -> bool:
    """pattern 是否为裸词（不含任何正则元字符）。"""
    return not (_REGEX_META & set(pattern))


def has_effective_anchor(pattern: str) -> bool:
    """pattern 是否带有效锚定（字符类 / 分组 / 定位 / 转义 / 量词范围）。"""
    return bool(_EFFECTIVE_ANCHOR_CHARS & set(pattern))


def literal_runs(pattern: str) -> list[str]:
    """拆出 pattern 的连续字面子串片段（按正则元字符切分，丢弃空串）。"""
    return [s for s in re.split(r"[.^$*+?()\[\]{}|\\]+", pattern) if s]


def is_misspelling(correct: str) -> bool:
    """correct 是否指示错别字 / 用字纠正（真阳检测，应保留）。"""
    return bool(_MISSPELLING_MARKERS.search(correct or ""))


@dataclass
class PatternVerdict:
    """单条 pattern 的审计结论。"""

    pattern: str
    decision: str  # "remove" | "keep"
    reason: str


def classify(
    pattern: str,
    correct: str,
    *,
    max_len: int = 4,
    keep_misspellings: bool = True,
    weak_anchored: bool = True,
) -> PatternVerdict:
    """判定单条 misconception pattern 的去留。

    判定顺序（先命中先返回）：
    1. 有效锚定（字符类 / 分组 / 定位 / 转义）→ keep
    2. 错别字 / 用字纠正（真阳）→ keep
    3. 裸词：长度 ≤ max_len → remove（概念名词）；否则 keep
    4. 弱锚定通配（weak_anchored=True 时）：片段全为功能词，或恰好两单字 → remove；
       否则 keep（含内容词的概念辨析）

    Args:
        pattern: misconception 的 pattern 值。
        correct: 对应的 correct 字段（识别错别字真阳）。
        max_len: 「超短」阈值（裸词字符数 ≤ max_len 视为超短）。
        keep_misspellings: 是否保留错别字 / 用字纠正类 pattern。
        weak_anchored: 是否清理弱锚定通配 pattern（功能词 / 双单字）。
    """
    if has_effective_anchor(pattern):
        return PatternVerdict(pattern, "keep", "带有效锚定（字符类/分组/定位）")
    if keep_misspellings and is_misspelling(correct):
        return PatternVerdict(pattern, "keep", "错别字/用字纠正（真阳）")
    if is_bare_word(pattern):
        if len(pattern) <= max_len:
            return PatternVerdict(pattern, "remove", "超短无锚定裸词（概念名词，误报源）")
        return PatternVerdict(pattern, "keep", f"长度 {len(pattern)} > {max_len}")
    # 弱锚定通配：仅 .* / .+ / + 等连接短字面子串，无结构约束
    if weak_anchored:
        frags = literal_runs(pattern)
        if frags and all(f in _FUNC_WORDS for f in frags):
            return PatternVerdict(pattern, "remove", "弱锚定：片段全为功能词（匹配语法结构）")
        if len(frags) == 2 and all(len(f) <= 1 for f in frags):
            return PatternVerdict(pattern, "remove", "弱锚定：双单字通配（古今字/通假字裸对）")
    return PatternVerdict(pattern, "keep", "弱锚定但含内容词（概念辨析）")


@dataclass
class AuditReport:
    """单文件的审计报告。"""

    subject: str
    removed: list[str] = field(default_factory=list)
    kept_misspelling: int = 0
    kept_anchored_or_long: int = 0

    @property
    def removed_count(self) -> int:
        return len(self.removed)


def _unquote(val: str) -> str:
    """去除 YAML 行内值的首尾引号。"""
    val = val.strip()
    if len(val) >= 2 and val[0] in "\"'" and val[-1] == val[0]:
        return val[1:-1]
    return val


def _read_block(lines: list[str], start: int, indent: str) -> tuple[list[str], int]:
    """读取一个 `- pattern:` 列表项的完整块（含其 correct/description/severity/source 续行）。

    续行定义为：比 `- ` 行缩进更深的行。遇到空行 / 同级新 item / 更外层结构则停止。
    """
    block = [lines[start]]
    indent_len = len(indent)
    i = start + 1
    while i < len(lines):
        ln = lines[i]
        if ln.strip() == "":
            break  # 空行结束（保留空行由主循环处理）
        lead = len(re.match(r"[ \t]*", ln).group())
        if lead <= indent_len:
            break  # 同级新 item 或更外层 section
        block.append(ln)
        i += 1
    return block, i


def _field_in_block(block: list[str], field_name: str) -> str:
    """从列表项块中提取某字段值（如 correct）。"""
    pat = re.compile(rf"^\s*{field_name}:\s*(.+?)\s*(?:#.*)?$")
    for ln in block[1:]:
        m = pat.match(ln)
        if m:
            return _unquote(m.group(1))
    return ""


def audit_text(
    text: str,
    *,
    max_len: int = 4,
    keep_misspellings: bool = True,
    weak_anchored: bool = True,
    apply: bool = False,
) -> tuple[str, list[str], int, int]:
    """审计并（可选）清理单个 knowledge yaml 文本。

    Returns:
        (new_text, removed_patterns, removed_count, kept_count)
        apply=False 时 new_text == text（不改动），removed_* 仍反映「若删除将命中」。
    """
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    removed: list[str] = []
    kept = 0
    in_misconceptions = False
    i = 0
    while i < len(lines):
        line = lines[i]
        # 进入 misconceptions section
        if _SECTION_START.match(line):
            in_misconceptions = True
            out.append(line)
            i += 1
            continue
        # 离开 section：遇到新的顶层 key（col 0、非列表项、非注释、含冒号）
        if (
            in_misconceptions
            and line
            and not line[0].isspace()
            and not line.startswith(("-", "#"))
            and ":" in line
        ):
            in_misconceptions = False
            out.append(line)
            i += 1
            continue
        m_item = _ITEM_START.match(line)
        if in_misconceptions and m_item:
            indent, raw_val = m_item.group(1), m_item.group(2)
            pattern_val = _unquote(raw_val)
            block, next_i = _read_block(lines, i, indent)
            correct_val = _field_in_block(block, "correct")
            verdict = classify(
                pattern_val,
                correct_val,
                max_len=max_len,
                keep_misspellings=keep_misspellings,
                weak_anchored=weak_anchored,
            )
            if verdict.decision == "remove":
                removed.append(pattern_val)
                i = next_i  # 整块跳过
                continue
            kept += 1
            out.extend(block)
            i = next_i
            continue
        out.append(line)
        i += 1

    new_text = "".join(out) if apply else text
    return new_text, removed, len(removed), kept


def knowledge_dir() -> Path:
    """knowledge 资源目录。"""
    return paths.assets_dir / "knowledge"


def audit_all(
    *,
    max_len: int = 4,
    keep_misspellings: bool = True,
    weak_anchored: bool = True,
    apply: bool = False,
    subjects: list[str] | None = None,
) -> list[tuple[str, Path, AuditReport]]:
    """审计（可选清理）全部或指定学科的 knowledge yaml。

    Returns:
        [(subject, path, report), ...]
    """
    reports: list[tuple[str, Path, AuditReport]] = []
    for yaml_path in sorted(knowledge_dir().glob("*.yaml")):
        subject = yaml_path.stem
        if subjects and subject not in subjects:
            continue
        if subject == "_defaults":
            continue  # 通用高质量规则，不参与批量清理
        text = yaml_path.read_text(encoding="utf-8")
        new_text, removed, _, kept = audit_text(
            text,
            max_len=max_len,
            keep_misspellings=keep_misspellings,
            weak_anchored=weak_anchored,
            apply=apply,
        )
        if apply and removed:
            yaml_path.write_text(new_text, encoding="utf-8")
        reports.append((subject, yaml_path, AuditReport(subject, removed, 0, kept)))
    return reports
