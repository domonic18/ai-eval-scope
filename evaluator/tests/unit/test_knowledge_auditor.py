"""KnowledgeAuditor 测试 — classify 判定 + 格式保留的行级删除。"""

from __future__ import annotations

import yaml

from agent_eval.knowledge.auditor import (
    audit_text,
    classify,
    is_bare_word,
    is_misspelling,
)

# ─── classify 单元 ───


def test_anchored_pattern_is_kept() -> None:
    """带正则元字符的 pattern 一律保留（有锚定，能定位上下文）。"""
    v = classify("祖冲之.*(?:唐朝|宋代)", "祖冲之是南北朝人")
    assert v.decision == "keep"
    assert "锚定" in v.reason


def test_long_bare_word_is_kept() -> None:
    """长裸词（>max_len）足够特异，误报率低，保留。"""
    v = classify("人民代表大会制度", "...", max_len=4)
    assert v.decision == "keep"


def test_ultra_short_concept_noun_is_removed() -> None:
    """超短无锚定的概念名词（理想/信念/滞后性）→ 删除（误报源）。"""
    for pat, correct in [
        ("理想", "理想是对未来的期望与坚定的信仰态度"),
        ("滞后性", "市场调节的滞后性是指事后调节存在时间差"),
        ("价值观", "价值观是评价标准，不等同于信念"),
    ]:
        v = classify(pat, correct, max_len=4)
        assert v.decision == "remove", pat
        assert is_bare_word(pat)


def test_misspelling_pattern_is_kept() -> None:
    """超短裸词但属错别字/用字纠正（真阳）→ 保留，避免漏报。"""
    v = classify("急燥", "应为'急躁'，'躁'指性情急", max_len=4)
    assert v.decision == "keep"
    assert is_misspelling("应为'急躁'") is True


def test_misspelling_disabled_removes_all_ultra_short_bare() -> None:
    """keep_misspellings=False 时，错别字裸词也一并删除。"""
    v = classify("急燥", "应为'急躁'", max_len=4, keep_misspellings=False)
    assert v.decision == "remove"


def test_marker_specificity_excludes_concept_words() -> None:
    """「习气」「绿沉沉」是合法词（概念辨析），correct 措辞非错别字纠正 → 删除。"""
    # correct 含「应使用」（宽泛措辞），不应被当作错别字标记
    assert is_misspelling("此处应使用中性词'习惯'") is False
    v = classify("习气", "此处应使用中性词'习惯'", max_len=4)
    assert v.decision == "remove"


# ─── 弱锚定通配 classify ───


def test_func_word_wildcard_is_removed() -> None:
    """功能词通配（因为.*所以 / 不是.*而是 / 是.*也）匹配语法结构 → 删除。"""
    for pat, correct in [
        ("因为.*所以", "因果复句中'之所以…是因为…'强调原因在前"),
        ("不是.*而是", "'不是…而是…'表示并列选择关系"),
        ("是.*也", "古汉语'是'常作指示代词，非判断句系词"),
    ]:
        v = classify(pat, correct)
        assert v.decision == "remove", pat
        assert "弱锚定" in v.reason


def test_two_single_glyph_wildcard_is_removed() -> None:
    """双单字通配（购.*买 / 翦.*剪 古今字裸对）任意共现即匹配 → 删除。"""
    for pat in ["购.*买", "翦.*剪", "反.*返"]:
        v = classify(pat, "...古今字关系...")
        assert v.decision == "remove", pat


def test_content_conjunction_wildcard_is_kept() -> None:
    """含内容词的弱锚定（三英.*赵云 / 宣纸.*材质）编码概念辨析 → 保留（不漏报）。"""
    for pat, correct in [
        ("三英.*赵云", "'三英战吕布'的三英指刘备关羽张飞"),
        ("宣纸.*材质", "宣纸得名于产地安徽宣城，而非材质"),
        ("妈祖.*安徽", "妈祖文化盛行于福建台湾沿海"),
    ]:
        v = classify(pat, correct)
        assert v.decision == "keep", pat


def test_multi_fragment_specific_wildcard_is_kept() -> None:
    """多片段特定序列（负.*负.*得.*负）虽全单字，但序列特异 → 保留。"""
    v = classify("负.*负.*得.*负", "负负得正，两负数相乘得正数")
    assert v.decision == "keep"


def test_charclass_pattern_is_kept() -> None:
    """带字符类的 pattern（0.*[是无没有].*偶数）有有效锚定 → 保留。"""
    v = classify("0.*[是无没有].*偶数", "0是偶数")
    assert v.decision == "keep"


def test_weak_anchored_disabled_keeps_wildcard_patterns() -> None:
    """weak_anchored=False 时仅清裸词，弱锚定通配全部保留。"""
    v = classify("因为.*所以", "...", weak_anchored=False)
    assert v.decision == "keep"


# ─── audit_text 行级删除（格式保留）───


SAMPLE_0INDENT = """\
subject: morality
description: 测试
misconceptions:
- pattern: 理想
  correct: 理想是对未来的期望
  description: 误将理想等同于信念
  severity: error
- pattern: 急燥
  correct: 应为'急躁'
  description: 错别字
  severity: error
- pattern: 祖冲之.*(?:唐朝|宋代)
  correct: 祖冲之是南北朝人
  severity: warning
constants:
- name: x
  value: 1
"""

SAMPLE_2INDENT = """\
subject: _defaults
misconceptions:
  - pattern: "太阳从西边升起"
    correct: "太阳从东方升起"
    severity: "error"
  - pattern: 神
    correct: 希腊哲学主题转向了人本身
    severity: error
"""


def test_audit_text_removes_concept_noun_keeps_rest_0indent() -> None:
    new_text, removed, n_rem, n_kept = audit_text(SAMPLE_0INDENT, apply=True)
    # 仅「理想」被删；错别字「急燥」与锚定 pattern 保留
    assert removed == ["理想"]
    assert n_rem == 1 and n_kept == 2
    assert "急燥" in new_text and "祖冲之" in new_text
    assert "理想" not in new_text
    # constants section 不受影响
    assert "constants:" in new_text and "name: x" in new_text


def test_audit_text_preserves_2indent_and_quotes() -> None:
    """_defaults 的 2 空格缩进 + 引号风格必须保留；「神」被删。"""
    new_text, removed, _, _ = audit_text(SAMPLE_2INDENT, apply=True)
    assert removed == ["神"]
    assert "太阳从西边升起" in new_text  # 带引号 + 锚定（无元字符但长度 7>4）保留
    assert '"太阳从西边升起"' in new_text  # 引号风格保留
    assert "  - pattern:" in new_text  # 2 空格缩进保留
    assert "神" not in new_text.split("constants")[0]


def test_audit_text_dry_run_does_not_modify() -> None:
    """apply=False 时返回原文，removed 仍反映命中。"""
    new_text, removed, _, _ = audit_text(SAMPLE_0INDENT, apply=False)
    assert new_text == SAMPLE_0INDENT
    assert removed == ["理想"]


def test_audit_text_result_is_valid_yaml() -> None:
    """删除后剩余文本仍是合法 YAML，且 misconceptions 仅剩保留项。"""
    new_text, _, _, _ = audit_text(SAMPLE_0INDENT, apply=True)
    data = yaml.safe_load(new_text)
    pats = [m["pattern"] for m in data["misconceptions"]]
    assert pats == ["急燥", "祖冲之.*(?:唐朝|宋代)"]
    assert data["constants"] == [{"name": "x", "value": 1}]
