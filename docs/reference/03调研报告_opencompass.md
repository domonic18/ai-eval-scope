# OpenCompass 对 Agent 评估体系的补充分析

> 本文档基于对 OpenCompass 开源评估系统（上海 AI Lab / 浦江实验室）的代码分析，梳理其评估维度、指标、方法，并指出对现有 Agent 评估资料的补充价值。

---

## 一、OpenCompass 概述

**OpenCompass** 是一个面向大语言模型的开源一站式评测平台，支持 100+ 个数据集，覆盖从基础能力到专业领域的多维度评测。其核心设计特点是：

- **模块化**：Evaluator、Dataset、Model 完全解耦，可灵活组合
- **可扩展**：通过 Registry 机制支持自定义评估器、数据集、模型
- **多后端**：支持 HuggingFace、vLLM、LMDeploy、API 等多种推理后端
- **混合评估**：原生支持 Rule-based + LLM-as-judge 的级联评估模式

---

## 二、OpenCompass 的评估维度分类

从 `dataset-index.yml` 中提取，OpenCompass 将评测数据集分为以下 **主维度**（按数据集数量排序）：


| 维度                   | 数据集数 | 说明                 | 对 Agent 评估的启示       |
| -------------------- | ---- | ------------------ | ------------------- |
| **Reasoning**        | 26   | 逻辑推理、数学推理、多步推理     | Agent 的核心认知能力       |
| **Understanding**    | 23   | 阅读理解、文本理解、语义理解     | Agent 处理用户输入的基础能力   |
| **Code**             | 19   | 代码生成、代码补全、编程能力     | Code Agent 的核心评估域   |
| **Math**             | 13   | 数学问题求解             | Agent 的精确计算能力       |
| **Knowledge**        | 13   | 学科知识、常识知识          | Agent 的知识储备广度       |
| **Long Context**     | 12   | 长文本理解、长上下文记忆       | **Agent 长程任务的关键能力** |
| **Language**         | 10   | 语言能力、语言学任务         | 多语言 Agent 的基础能力     |
| **Safety**           | 9    | 安全性、有害性、偏见检测       | **Agent 安全风控的关键维度** |
| **Examination**      | 6    | 考试评测（高考、公务员考试等）    | Agent 综合能力的标准化检验    |
| **Tool Utilization** | 2    | 工具使用能力             | **直接对应 Agent 能力**   |
| **Subjective**       | 8+   | 主观评测（对齐、指令遵循、多轮对话） | **Agent 体验质量评估**    |
| **Science**          | 4    | 科学领域专业评测           | 垂直领域 Agent 评估       |


### 2.1 对现有资料的补充

现有 Agent 评估资料主要覆盖了 **任务完成度、规划、工具使用、推理、记忆、指令遵循** 等维度。OpenCompass 的维度体系补充了以下**缺失或薄弱**的维度：


| 新增/强化维度                         | 重要性   | 说明                                                                                |
| ------------------------------- | ----- | --------------------------------------------------------------------------------- |
| **长上下文 (Long Context)**         | ⭐⭐⭐⭐⭐ | Agent 处理长对话、长文档、长历史记录的能力；OpenCompass 有 12 个数据集（NeedleBench、RULER、LongBench 等）专门评测 |
| **安全性 (Safety)**                | ⭐⭐⭐⭐⭐ | Agent 在实际部署中的风险控制；包括毒性、偏见、有害输出检测                                                  |
| **主观对齐 (Subjective Alignment)** | ⭐⭐⭐⭐  | Agent 输出的人类偏好对齐度；包括 AlpacaEval、Arena-Hard、MT-Bench 等                              |
| **多轮对话 (Multi-Round)**          | ⭐⭐⭐⭐  | Agent 在多轮交互中的上下文保持和策略调整能力                                                         |
| **语言能力 (Language)**             | ⭐⭐⭐   | 多语言 Agent 的语言理解和生成质量                                                              |
| **考试评测 (Examination)**          | ⭐⭐⭐   | 标准化的综合能力检验，如 AGIEval、C-Eval、MMLU                                                  |


---

## 三、OpenCompass 的评估指标体系

OpenCompass 的指标分布在多个 Evaluator 实现中，形成了丰富的指标库。以下逐一详述各指标的具体计算方法。

---

### 3.1 通用指标

#### 3.1.1 Accuracy（准确率）

**适用场景**：分类任务（单选题、判断题等）。

**计算方法**：

$$
\text{Accuracy} = \frac{\text{预测正确的样本数}}{\text{总样本数}} = \frac{TP + TN}{TP + TN + FP + FN}
$$

其中：

- $TP$（True Positive）：真正例
- $TN$（True Negative）：真负例
- $FP$（False Positive）：假正例
- $FN$（False Negative）：假负例

**在 OpenCompass 中的实现**：调用 HuggingFace `evaluate` 库的 `accuracy` 指标，通常配合 `Exact Match` 使用，即模型输出与标准答案完全匹配才算正确。

---

#### 3.1.2 F1 Score

**适用场景**：不平衡分类任务、序列标注任务。

**计算方法**：

先计算精确率（Precision）和召回率（Recall）：

$$
\text{Precision} = \frac{TP}{TP + FP}, \quad \text{Recall} = \frac{TP}{TP + FN}
$$

F1 是两者的调和平均：

$$
\text{F1} = 2 \times \frac{\text{Precision} \times \text{Recall}}{\text{Precision} + \text{Recall}} = \frac{2 \cdot TP}{2 \cdot TP + FP + FN}
$$

**变体**：

- **Macro-F1**：对每个类别单独计算 F1，然后取算术平均
- **Micro-F1**：全局计算 TP/FP/FN，再算 F1
- ##### **Weighted-F1**：按各类别样本数加权平均

---

#### 3.1.3 BLEU（Bilingual Evaluation Understudy）

**适用场景**：文本生成质量评估（机器翻译、摘要等）。

**核心思想**：衡量候选文本与参考文本之间的 n-gram 重叠程度。

**计算方法**：

$$
\text{BLEU-N} = \text{BP} \times \exp\left(\sum_{n=1}^{N} w_n \log p_n\right)
$$

其中：

1. **修正的 n-gram 精确率** $p_n$：

$$
p_n = \frac{\sum_{C \in \text{Candidates}} \sum_{\text{n-gram} \in C} \text{Count}_{\text{clip}}(\text{n-gram})}{\sum_{C \in \text{Candidates}} \sum_{\text{n-gram} \in C} \text{Count}(\text{n-gram})}
$$

$\text{Count}_{\text{clip}}$ 表示 n-gram 出现次数被裁剪到参考文本中该 n-gram 的最大出现次数（防止重复生成同一词获得高分）。

1. **简短惩罚因子 BP**（Brevity Penalty）：

$$
\text{BP} = \begin{cases} 1 & \text{if } c > r \\ e^{(1-r/c)} & \text{if } c \leq r \end{cases}
$$

- $c$：候选文本长度
- $r$：参考文本长度（取最接近候选长度的参考）

**BLEU-4**：通常取 $N=4$，权重 $w_n = 1/4$。

---

#### 3.1.4 ROUGE（Recall-Oriented Understudy for Gisting Evaluation）

**适用场景**：摘要、文本生成质量。

**主要变体**：

**A. ROUGE-N**（基于 n-gram 召回率）：

$$
\text{ROUGE-N} = \frac{\sum_{S \in \text{Reference}} \sum_{\text{n-gram} \in S} \text{Count}_{\text{match}}(\text{n-gram})}{\sum_{S \in \text{Reference}} \sum_{\text{n-gram} \in S} \text{Count}(\text{n-gram})}
$$

- **ROUGE-1**：unigram（单词级别）重叠
- **ROUGE-2**：bigram（二元组）重叠

**B. ROUGE-L**（基于最长公共子序列，LCS）：

$$
\text{ROUGE-L} = \frac{(1 + \beta^2) \cdot R_{\text{lcs}} \cdot P_{\text{lcs}}}{R_{\text{lcs}} + \beta^2 \cdot P_{\text{lcs}}}
$$

其中：

- $R_{\text{lcs}} = \frac{LCS(X, Y)}{m}$（召回率，$m$ 为参考文本长度）
- $P_{\text{lcs}} = \frac{LCS(X, Y)}{n}$（精确率，$n$ 为候选文本长度）
- $\beta$ 通常设为极大值（近似于只考虑召回率）

**C. ROUGE-SU**：考虑 skip-bigram + unigram

---

#### 3.1.5 BERTScore

**适用场景**：需要语义理解的文本相似度评估。

**核心思想**：用预训练语言模型（如 BERT）将文本编码为上下文嵌入向量，计算语义相似度，而非表面的字符串匹配。

**计算方法**：

**步骤 1：Token 嵌入**

- 将参考文本 $x$ 和候选文本 $\hat{x}$ 分别输入 BERT，得到 token 级别的上下文嵌入：
  - 参考文本：$\mathbf{x} = x_1, x_2, ..., x_m$
  - 候选文本：$\hat{\mathbf{x}} = \hat{x}_1, \hat{x}_2, ..., \hat{x}_n$

**步骤 2：计算余弦相似度矩阵**

$$
\mathbf{S}_{ij} = \cos(\mathbf{x}_i, \hat{\mathbf{x}}_j) = \frac{\mathbf{x}_i \cdot \hat{\mathbf{x}}_j}{\|\mathbf{x}_i\| \|\hat{\mathbf{x}}_j\|}
$$

**步骤 3：计算召回率、精确率、F1**

- **召回率**（参考文本的 token 被覆盖的程度）：

$$
R_{\text{BERT}} = \frac{1}{m} \sum_{i=1}^{m} \max_{j} \mathbf{S}_{ij}
$$

- **精确率**（候选文本的 token 有多少是相关的）：

$$
P_{\text{BERT}} = \frac{1}{n} \sum_{j=1}^{n} \max_{i} \mathbf{S}_{ij}
$$

- **F1**：

$$
\text{F1}_{\text{BERT}} = 2 \times \frac{P_{\text{BERT}} \times R_{\text{BERT}}}{P_{\text{BERT}} + R_{\text{BERT}}}
$$

**特点**：能捕捉同义词、语义等价等 BLEU/ROUGE 无法识别的相似性。

---

#### 3.1.6 AUC-ROC

**适用场景**：二分类任务的概率评估。

**计算方法**：

1. 将模型输出的概率值按从高到低排序
2. 以每个不同的概率值作为阈值，计算对应的 **真正例率 TPR** 和 **假正例率 FPR**：

$$
\text{TPR} = \frac{TP}{TP + FN}, \quad \text{FPR} = \frac{FP}{FP + TN}
$$

1. 以 FPR 为横轴、TPR 为纵轴绘制 ROC 曲线
2. **AUC** = ROC 曲线下面积

**取值范围**：$[0, 1]$，越接近 1 表示分类器性能越好。

---

### 3.2 代码/数学专用指标

#### 3.2.1 Pass@k

**适用场景**：代码生成任务。

**核心思想**：对同一个问题，让模型生成 $k$ 个候选代码，只要有一个能通过测试就算成功。

**计算方法**：

对于单个问题：

$$
\text{Pass@1} = \begin{cases} 1 & \text{if 第 1 个候选通过测试} \\ 0 & \text{otherwise} \end{cases}
$$

$$
\text{Pass@k} = \begin{cases} 1 & \text{if } k \text{ 个候选中至少 1 个通过} \\ 0 & \text{otherwise} \end{cases}
$$

**在统计意义上的无偏估计**（当采样数 $n \geq k$ 时）：

$$
\text{Pass@k} = \mathbb{E}_{\text{Problems}}\left[1 - \frac{\binom{n-c}{k}}{\binom{n}{k}}\right]
$$

其中：

- $n$：总采样数（如 $n=200$）
- $c$：通过测试的样本数
- $k$：评估参数（通常取 1, 10, 100）

当 $n$ 很大时的近似：

$$
\text{Pass@k} \approx 1 - \left(1 - \frac{c}{n}\right)^k
$$

**注意**：文档中写的是 `100 * correct / total`，这是简化版本的实现。

---

#### 3.2.2 G-Pass@k（Generalized Pass@k）

**适用场景**：需要多阈值评估的代码生成。

**核心思想**：Pass@k 只有二元结果（通过/不通过），G-Pass@k 引入多个通过率阈值，衡量模型在不同严格程度下的表现。

**计算方法**：

设通过率阈值为 $T \in 0.0, 0.25, 0.5, 0.75, 1.0$：

$$
\text{G-Pass@k}(T) = \mathbb{1}\left[\frac{\text{通过数}}{k} \geq T\right]
$$

具体解释：

- **T = 0.0**：只要有一个通过就算成功（等价于传统 Pass@k）
- **T = 0.25**：$k$ 个候选中至少 25% 通过
- **T = 0.5**：至少一半通过
- **T = 0.75**：至少 75% 通过
- **T = 1.0**：全部通过

**示例**（$k=10$）：


| 通过数  | T=0.0 | T=0.25 | T=0.5 | T=0.75 | T=1.0 |
| ---- | ----- | ------ | ----- | ------ | ----- |
| 3/10 | ✓     | ✓      | ✗     | ✗      | ✗     |
| 8/10 | ✓     | ✓      | ✓     | ✓      | ✗     |


---

#### 3.2.3 mG-Pass@k（median G-Pass@k）

**核心思想**：取 G-Pass@k 各阈值结果的中位数，减少阈值选择的敏感性。

**计算方法**：

$$
\text{mG-Pass@k} = \text{median}\left(\text{G-Pass@k}(0.0), \text{G-Pass@k}(0.25), \text{G-Pass@k}(0.5), \text{G-Pass@k}(0.75), \text{G-Pass@k}(1.0)\right)
$$

**优势**：对阈值不敏感，更稳定。

---

#### 3.2.4 Math Verification（数学表达式等价验证）

**适用场景**：数学问题求解。

**核心思想**：不比较字符串，而是比较数学表达式的**语义等价性**。

**计算流程**：

**步骤 1：解析**

- 使用 `latex2sympy2` 将 LaTeX 格式的答案转换为 SymPy 表达式
- 使用 `math_verify` 进行标准化和验证

```python
gold_parsed = parse(gold_answer, extraction_config=[
    LatexExtractionConfig(),      # 提取 LaTeX 表达式
    ExprExtractionConfig(),        # 提取纯数学表达式
])
```

**步骤 2：标准化**

- 化简表达式：$\frac{2}{4} \rightarrow \frac{1}{2}$
- 统一形式：$x^2 + 2x + 1 \rightarrow (x+1)^2$
- 处理等价变形：$\sin^2 x + \cos^2 x \rightarrow 1$

**步骤 3：验证等价**

```python
answer_correct = float(verify(answer_parsed, gold_parsed))
```

**验证方法**：

- **符号等价**：用 SymPy 的 `simplify(expr1 - expr2) == 0` 判断
- **数值等价**：在随机采样点上计算数值，比较是否足够接近
- **结构等价**：对矩阵、集合等特殊类型进行专门比较

**输出**：1.0（等价）或 0.0（不等价）

---

### 3.3 Agent 专用指标

#### 3.3.1 Pass Rate（通过率 / 拒绝检测率）

**适用场景**：检测 Agent 是否"摆烂"拒绝执行任务。

**计算方法**：

**步骤 1：关键词过滤**

```python
DEFAULT_FAIL_WORDS = ('sorry', 'apologize', 'apology', 'unfortunately', "couldn't")

def check_real_valid(answer):
    return not any(word in answer.lower() for word in fail_words)
```

**步骤 2：计算 Pass Rate**

$$
\text{Pass Rate} = \frac{\text{未拒绝的样本数}}{\text{总样本数}}
$$

其中，一个样本被判定为"拒绝"当且仅当：

$$
\text{isrefused} = \bigvee_{w \in \text{FailWords}} \left[w \in \text{answer.lower()}\right]
$$

**注意**：这是基于关键词的启发式方法，可能漏检或误检。更严格的版本可加入 LLM 复核。

---

#### 3.3.2 Win Rate（胜率）

**适用场景**：Agent A vs Agent B 的能力对比。

**核心思想**：四层递进式比较，从结果到效率到过程。

**计算方法**（四层判定逻辑）：

设两个 Agent 的输出为 $A$ 和 $B$，比较流程如下：

**L1：是否有答案**

$$
\text{Winner} = \begin{cases} A & \text{if } A \text{ 能提取答案} \land B \text{ 不能} \\ B & \text{if } B \text{ 能提取答案} \land A \text{ 不能} \\ \text{继续 L2} & \text{if 两者都能或都不能} \end{cases}
$$

**L2：答案是否正确**

通过 LLM 函数调用判断 `is_solved`：

$$
\text{Winner} = \begin{cases} A & \text{if } \text{is\_solved}(A) \land \neg\text{is\_solved}(B) \\ B & \text{if } \text{is\_solved}(B) \land \neg\text{is\_solved}(A) \\ \text{继续 L3} & \text{if 两者都正确} \end{cases}
$$

**L3：工具调用效率（步数）**

$$
\text{Winner} = \begin{cases} A & \text{if } \text{steps}(A) < \text{steps}(B) \\ B & \text{if } \text{steps}(B) < \text{steps}(A) \\ \text{继续 L4} & \text{if 步数相同} \end{cases}
$$

**L4：失败质量（当两者都失败时）**

$$
\text{Quality Score} = \text{ToolSuccess} \times 10 + \text{ToolTypes} \times 5 - \text{Steps} \times \text{penalty}
$$

$$
\text{Winner} = \begin{cases} A & \text{if } \text{Score}(A) > \text{Score}(B) \\ B & \text{if } \text{Score}(B) > \text{Score}(A) \\ \text{Tie} & \text{otherwise} \end{cases}
$$

**最终 Win Rate**：

$$
\text{Win Rate}_A = \frac{\text{A 获胜的样本数}}{\text{总样本数}}
$$

---

#### 3.3.3 Tool Call Steps（工具调用步数）

**计算方法**：

$$
\text{Tool Call Steps} = \text{Agent 完成任务期间调用工具的次数}
$$

**用途**：

- 作为效率指标，步数越少通常表示 Agent 规划越高效
- 在 Win Rate 的 L3 层作为判定依据

---

#### 3.3.4 Tool Type Diversity（工具类型多样性）

**计算方法**：

$$
\text{Tool Type Diversity} = |\text{使用的不同工具类型}|
$$

即完成任务过程中使用了多少种**不同类别**的工具。

**用途**：

- 在 Win Rate 的 L4 层作为失败质量评分的一部分
- 反映 Agent 的工具使用丰富度

---

#### 3.3.5 Tool Call Success（工具调用成功次数）

**计算方法**：

$$
\text{Tool Call Success} = \sum_{i=1}^{n} \mathbb{1}[\text{第 } i \text{ 次工具调用成功}]
$$

**用途**：

- 在 Win Rate 的 L4 层作为失败质量评分的一部分（$\times 10$ 的权重）
- 反映 Agent 工具使用的可靠性

---

### 3.4 各指标计算复杂度对比


| 指标                | 计算类型         | 时间复杂度                  | 是否需要外部工具      |
| ----------------- | ------------ | ---------------------- | ------------- |
| Accuracy          | 字符串匹配        | $O(n)$                 | 否             |
| F1 Score          | 计数统计         | $O(n)$                 | 否             |
| BLEU              | n-gram 匹配    | $O(n \cdot k)$         | 否             |
| ROUGE             | LCS / n-gram | $O(n \cdot m)$         | 否             |
| BERTScore         | 向量相似度        | $O(n \cdot m \cdot d)$ | 需要 BERT 模型    |
| AUC-ROC           | 排序 + 积分      | $O(n \log n)$          | 否             |
| Pass@k            | 执行验证         | $O(k \cdot t)$         | 需要代码执行环境      |
| G-Pass@k          | 多阈值统计        | $O(k \cdot t)$         | 需要代码执行环境      |
| Math Verification | 符号/数值验证      | $O(d^3)$（符号）           | 需要 SymPy      |
| Pass Rate         | 关键词匹配        | $O(n \cdot w)$         | 否             |
| Win Rate          | 多层规则判定       | $O(n)$                 | 需要 LLM 判定 L2  |
| Tool 相关指标         | 计数           | $O(n)$                 | 需要 Agent 执行日志 |


> 其中 $n$=样本数, $m$=文本长度, $k$=采样数, $d$=维度, $t$=测试用例数, $w$=关键词数

### 3.4 对现有资料的补充

现有资料中的指标主要覆盖了 **DR、CPR、Reward、CondR、Time** 等。OpenCompass 补充了：

1. **多轮评估统计指标**：`G-Pass@k`、`mG-Pass@k` —— 对于需要多次采样评估的 Agent 任务非常有价值
2. **Agent 拒绝检测指标**：`Pass Rate` —— 现有资料未涉及 Agent 是否"拒绝回答"的评估
3. **Agent 对比指标**：`Win Rate` —— 现有资料缺少 Agent 间直接对比的指标
4. **数学验证指标**：基于表达式解析的等价验证，而非简单的字符串匹配

---

## 四、OpenCompass 的评估方法详解

OpenCompass 实现了多种评估方法，形成了一个完整的评估方法矩阵：

### 4.1 方法全景图

```
┌─────────────────────────────────────────────────────────────────┐
│                    OpenCompass 评估方法矩阵                       │
├──────────────┬──────────────┬──────────────┬────────────────────┤
│  自动评估     │  执行验证     │  LLM 评判    │  混合/级联评估      │
├──────────────┼──────────────┼──────────────┼────────────────────┤
│ • Exact Match│ • 代码执行    │ • Point-wise │ • CascadeEvaluator │
│ • F1/Accuracy│ • SQL 执行    │ • Pair-wise  │ • Rule + LLM      │
│ • BLEU/ROUGE │ • 数学验证    │ • LLM 函数调用│ • 并行/串行模式    │
│ • BERTScore  │              │ • 多轮对话评判│                    │
└──────────────┴──────────────┴──────────────┴────────────────────┘
```

### 4.2 核心评估器详解

#### 4.2.1 CascadeEvaluator（级联评估器）⭐⭐⭐⭐⭐

**设计思想**：先用低成本方法（Rule）快速筛选，再用高成本方法（LLM）复核边界案例。

```python
class CascadeEvaluator(BaseEvaluator):
    """First uses rule-based method to judge predictions.
    If a sample is marked as incorrect by rule-based method,
    then uses an LLM judge to re-evaluate it.
    """
```

**两种工作模式**：


| 模式              | 逻辑                        | 适用场景            |
| --------------- | ------------------------- | --------------- |
| **Cascade 模式**  | Rule 判定为错误的样本 → LLM 复核    | 减少 LLM 调用量，降低成本 |
| **Parallel 模式** | 所有样本同时用 Rule 和 LLM 评估，取并集 | 最大化准确率，成本较高     |


**对 Agent 评估的启示**：

- 对于 Agent 评估，可以先用**规则检查**（如格式、约束满足）快速通过大部分样本
- 对规则判定失败的样本，再用 **LLM 评判** 进行语义层面的复核
- 这与 TripScore 的设计理念高度一致，但 CascadeEvaluator 提供了**更工程化**的实现框架

#### 4.2.2 GenericLLMEvaluator（通用 LLM 评判器）

**核心能力**：

- 支持任意 Prompt Template 定义评判标准
- 支持自定义 Judge LLM（默认 GPT-4o）
- 支持 Prediction Post-processor 和 Output Post-processor
- 支持结果缓存，避免重复评估

**对 Agent 评估的启示**：

- 提供了一套标准化的 LLM-as-judge 工程实现框架
- 可以通过配置化方式快速接入新的评估维度
- 支持温度设置为接近 0，确保评估可复现

#### 4.2.3 CodeEvaluator（代码评估器）

**设计特点**：

- 通过 **Gradio Client** 连接远程代码执行服务
- 自动提取 Markdown 代码块
- 支持多语言（Python、Java、C++ 等）
- 支持 Pass@k 计算（多次采样）

```python
def score(self, predictions, references, test_set):
    # 1. 提取代码
    processed = self._extract_code(comp)
    # 2. 发送到远程执行服务
    success, output = self._code_eval_service(test_cases)
    # 3. 返回 Pass@k
    return {'pass@k': 100 * correct / total}
```

**对 Agent 评估的启示**：

- Code Agent 的评估必须依赖**执行验证**，不能仅靠字符串匹配
- 远程执行服务的设计可以隔离安全风险
- 对于工具调用类 Agent，也可以设计类似的**远程工具执行验证**框架

#### 4.2.4 MATHEvaluator（数学评估器）

**核心创新**：

- 不比较字符串，而是比较**数学表达式的语义等价性**
- 使用 `math_verify` + `latex2sympy2` 解析 LaTeX 和数学表达式
- 支持复杂数学对象的等价判断（分数、积分、矩阵等）

```python
gold_parsed = parse(j_with_env, extraction_config=[
    LatexExtractionConfig(),
    ExprExtractionConfig(),
])
answer_parsed = parse(i, extraction_config=[
    LatexExtractionConfig(normalization_config=...),
])
answer_correct = float(verify(answer_parsed, gold_parsed))
```

**对 Agent 评估的启示**：

- 对于涉及数值计算、公式推导的 Agent 任务，**不能**用字符串匹配评估
- 需要引入领域专用的解析和验证工具
- 这一思路可以推广到其他专业领域（如化学分子式、法律条文等）

#### 4.2.5 Agent 专用评估器（icl_agent_evaluator.py）

这是 OpenCompass 中与 Agent 评估最直接相关的模块，实现了两个核心评估器：

**A. PassRateEvaluator（通过率评估器）**

```python
class PassRateEvaluator(BaseEvaluator):
    """Determine whether pred refuses to execute the task."""
    
    DEFAULT_FAIL_WORDS = (
        'sorry', 'apologize', 'apology', 'unfortunately', "couldn't"
    )
    
    def check_real_valid(self, answer):
        """Exclude response without real answer."""
        return not any(word in answer.lower() for word in self.fail_words)
```

**功能**：检测 Agent 是否以"抱歉，我无法..."等话术拒绝执行任务。

**对 Agent 评估的启示**：

- **现有资料缺失**：未涉及 Agent "拒绝执行"的检测
- 实际部署中，Agent 的"摆烂"行为是严重问题
- 可以通过关键词过滤 + LLM 复核的方式进行检测

**B. WinRateEvaluator（胜率评估器）**

```python
class WinRateEvaluator(BaseEvaluator):
    """Compare which call-tool process between pred and reference is better.
    
    1. Compare whether an answer can be extracted
    2. Compare whether the answer is correct
    3. Compare the number of tool calls (fewer wins)
    4. If both failed, consider tool success rate and variety
    """
```

**评估逻辑**（四层比较）：


| 层级  | 比较维度   | 判定标准                             |
| --- | ------ | -------------------------------- |
| L1  | 是否有答案  | 能提取答案 vs 不能 → 能者胜                |
| L2  | 答案是否正确 | LLM 函数调用判断 `is_solved`           |
| L3  | 工具调用效率 | 步数少者胜（同样正确时）                     |
| L4  | 失败质量   | 工具调用成功次数 × 10 + 工具类型数 × 5 - 步数惩罚 |


**对 Agent 评估的启示**：

- **现有资料缺失**：缺少 Agent 间直接对比的评估方法
- WinRate 提供了一套**多层级、多维度**的 Agent 对比框架
- 不仅比结果，还比过程（步数、工具多样性）
- 对于旅行规划 Agent，可以借鉴此框架设计"行程质量对比评估器"

---

## 五、OpenCompass 评估方法对现有资料的补充

### 5.1 现有资料 vs OpenCompass 对比


| 方面       | 现有资料覆盖                                             | OpenCompass 补充                                                                               |
| -------- | -------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| **评估维度** | 任务完成、规划、工具使用、推理、记忆、指令遵循、安全、效率                      | + **长上下文**、+ **主观对齐**、+ **多轮对话**、+ **语言能力**、+ **考试评测**                                       |
| **评估指标** | DR、CPR、Reward、CondR、Time、Success Rate、Accuracy     | + **G-Pass@k**、+ **Pass Rate**（拒绝检测）、+ **Win Rate**（对比胜率）、+ **Tool Diversity**、+ **表达式等价验证** |
| **评估方法** | Rule-based、LLM-as-judge、Execution-based、Human Eval | + **CascadeEvaluator**（级联评估）、+ **HuggingFace Metrics 集成**、+ **数学表达式解析验证**、+ **Agent 专用对比评估** |
| **工程实现** | 概念层面描述                                             | + **Registry 模块化架构**、+ **配置化评估流程**、+ **结果缓存机制**、+ **多后端推理支持**                                |


### 5.2 建议补充到现有资料的内容

#### 补充 1：级联评估方法（Cascade Evaluation）

```markdown
## 级联评估（Cascade Evaluation）

一种高效的混合评估模式：

1. **第一层**：Rule-based 快速筛选（低成本、高召回）
2. **第二层**：LLM-as-judge 复核边界案例（高精度、高成本）

两种模式：
- **串行模式（Cascade）**：仅对 Rule 失败样本调用 LLM，降低成本
- **并行模式（Parallel）**：所有样本同时用两种方法评估，取并集，最大化准确率

适用场景：大规模 Agent 评估、在线评估系统。
```

#### 补充 2：Agent 拒绝检测（Pass Rate）

```markdown
## Agent 拒绝检测（Refusal Detection）

评估 Agent 是否以"抱歉，我无法..."等话术逃避任务：

- **方法**：关键词过滤（sorry, apologize, unfortunately...）+ LLM 复核
- **指标**：Pass Rate = 未拒绝的样本比例
- **意义**：Agent 的"摆烂"行为会严重影响用户体验
```

#### 补充 3：Agent 对比评估（Win Rate）

```markdown
## Agent 对比评估（Win Rate）

通过多层级比较判定两个 Agent 的优劣：

1. **结果层**：是否有答案 → 答案是否正确
2. **效率层**：完成任务的工具调用步数（少者胜）
3. **过程层**：失败时的工具成功率和工具多样性

- **指标**：Win Rate = A 胜过 B 的样本比例
- **方法**：LLM 函数调用 + 规则评分结合
```

#### 补充 4：长上下文评估维度

```markdown
## 长上下文能力（Long Context）

Agent 在长对话、长文档、长历史记录中的表现：

- **大海捞针（Needle in a Haystack）**：在长文本中定位特定信息
- **多跳推理（Multi-hop Tracing）**：跨长距离的因果推理
- **信息聚合（Aggregation）**：从长文本中综合多个信息点
- **代表性基准**：NeedleBench、RULER、LongBench、BABILong
```

#### 补充 5：安全性评估维度

```markdown
## 安全性评估（Safety）

Agent 在实际部署中的风险控制能力：

- **有害内容生成**：毒性、偏见、歧视性输出
- **指令注入攻击**：抵抗恶意提示注入
- **越权操作**：防止执行危险操作（删除数据、越权访问）
- **隐私泄露**：防止泄露敏感信息
```

#### 补充 6：数学/专业领域验证方法

```markdown
## 专业领域验证（Domain-Specific Verification）

对于涉及精确计算的 Agent 任务，不能依赖字符串匹配：

- **数学**：使用 `math_verify` + `latex2sympy2` 进行表达式等价验证
- **代码**：远程执行 + 单元测试验证
- **SQL**：在数据库中执行并对比结果
- **化学**：分子式解析和等价判断
- **法律**：法条引用和逻辑推导验证
```

---

## 六、OpenCompass 的工程架构启示

OpenCompass 的工程实现对构建 Agent 评估系统有以下启示：

### 6.1 模块化设计

```python
# OpenCompass 的 Registry 机制
@ICL_EVALUATORS.register_module()
class MyEvaluator(BaseEvaluator):
    pass

# 配置化使用
evaluator = dict(type='MyEvaluator', param1=..., param2=...)
```

**启示**：Agent 评估系统应支持插件化 Evaluator，方便新增评估维度。

### 6.2 评估流程标准化

```
Dataset → Model Inference → Prediction → Evaluator → Metrics → Report
```

**启示**：将 Agent 评估流程标准化，支持不同 Agent 在相同流程下被公平比较。

### 6.3 结果缓存与复现

OpenCompass 支持：

- 评估结果自动保存（JSON 格式）
- 已评估样本自动跳过（避免重复调用 LLM）
- 固定随机种子（确保可复现）

**启示**：Agent 评估成本高（LLM 调用费、执行验证费），必须支持结果缓存。

### 6.4 多后端支持

```python
# 支持多种推理后端
model = dict(type='HuggingFaceModel', path='...')
model = dict(type='OpenAI', path='gpt-4', key='...')
model = dict(type='vLLM', path='...')
```

**启示**：Agent 评估系统应支持不同模型后端的统一接入。

---

## 七、总结：建议整合到现有资料的要点


| 优先级    | 补充内容                          | 理由                         |
| ------ | ----------------------------- | -------------------------- |
| **P0** | 级联评估方法（CascadeEvaluator）      | 工程化实现 Rule + LLM 混合评估的最佳实践 |
| **P0** | Agent 拒绝检测（PassRateEvaluator） | 现有资料完全缺失，实际部署中至关重要         |
| **P0** | Agent 对比评估（WinRateEvaluator）  | 现有资料缺少 Agent 间直接对比方法       |
| **P1** | 长上下文评估维度                      | Agent 处理长任务的核心能力           |
| **P1** | 安全性评估维度                       | Agent 部署前的必检项              |
| **P1** | 数学/代码执行验证                     | 精确任务不能依赖字符串匹配              |
| **P2** | G-Pass@k 等多轮评估指标              | 提升评估的统计可靠性                 |
| **P2** | HuggingFace Metrics 集成        | 复用成熟的 NLP 评估指标             |


---

## 参考

- OpenCompass GitHub: [https://github.com/open-compass/opencompass](https://github.com/open-compass/opencompass)
- OpenCompass 文档: [https://opencompass.readthedocs.io/](https://opencompass.readthedocs.io/)
- 现有 Agent 评估资料: `agent-evaluation-guide.md`
- TripScore 评估资料: `tripscore-evaluation-guide.md`

