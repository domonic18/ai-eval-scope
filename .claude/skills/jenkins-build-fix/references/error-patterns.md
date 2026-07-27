# 常见 Jenkins 构建错误模式与修复方案

本文档列出常见的构建失败模式、识别特征及对应的修复策略，供 AI 分析时参考。

## 1. Python 项目

### 1.1 ruff / black 格式检查失败

**识别特征**：
```
ruff check . --select E,W,F
Found 3 errors (2 fixed, 1 remaining)
E501 Line too long (120 > 88 characters)
F401 'typing.Optional' imported but unused
```

**修复策略**：
- 高置信度：运行 `ruff check . --fix` 或 `black .`
- 若 `--fix` 无法自动修复，AI 根据错误位置手动修改

### 1.2 mypy 类型检查失败

**识别特征**：
```
mypy src/
src/app/service.py:42: error: Incompatible types in assignment
src/app/models.py:15: error: Missing type parameters for generic type "dict"
```

**修复策略**：
- 中置信度：根据错误信息添加/修正类型注解
- 常见修复：
  - `dict` → `dict[str, Any]`
  - 函数返回值缺失 → 添加 `-> return_type`
  - `None` 返回值未声明 → 添加 `-> None`

### 1.3 pytest 测试失败

**识别特征**：
```
pytest backend/tests/
FAILED backend/tests/test_api.py::test_login - AssertionError: expected 200, got 401
FAILED backend/tests/test_models.py::test_user_create - KeyError: 'email'
```

**修复策略**：
- 低置信度（需人工判断）：
  - 若是实现代码 bug → 修复实现
  - 若是测试用例本身问题 → 修复测试
  - 若是环境依赖问题 → 调整测试环境配置
- **不自动修复测试用例断言逻辑**

### 1.4 缺失 import

**识别特征**：
```
ModuleNotFoundError: No module named 'pydantic'
ImportError: cannot import name 'BaseModel' from 'pydantic'
```

**修复策略**：
- 中置信度：添加缺失的 import 语句
- 注意：若缺失的是第三方包，仅提示用户安装，不修改 pyproject.toml/requirements.txt

### 1.5 Python 语法错误

**识别特征**：
```
  File "src/app/main.py", line 45
    def get_user(id: str) -> Optional[User]
                                           ^
SyntaxError: expected ':'
```

**修复策略**：
- 高置信度：补全缺失的冒号、括号等

---

## 2. TypeScript / JavaScript 项目

### 2.1 ESLint 检查失败

**识别特征**：
```
eslint src/ --ext .ts,.tsx
error  'React' is defined but never used  no-unused-vars
error  Expected indentation of 2 spaces but found 4  indent
```

**修复策略**：
- 高置信度：运行 `eslint --fix` 或手动删除未使用的 import

### 2.2 TypeScript 编译错误

**识别特征**：
```
tsc --noEmit
src/components/Button.tsx:15:23 - error TS2345: Argument of type 'string' is not assignable to parameter of type 'number'.
src/hooks/useAuth.ts:8:10 - error TS2304: Cannot find name 'useState'.
```

**修复策略**：
- 中置信度：根据 TS 错误信息修改类型
- 常见修复：
  - 缺失 React import → 添加 `import { useState } from 'react'`
  - 类型不匹配 → 调整类型注解或类型转换

### 2.3 Prettier 格式检查失败

**识别特征**：
```
prettier --check "src/**/*.{ts,tsx}"
[warn] src/components/App.tsx
```

**修复策略**：
- 高置信度：运行 `prettier --write`

### 2.4 npm 依赖安装失败

**识别特征**：
```
npm ci
npm ERR! code E404
npm ERR! 404 Not Found - GET https://registry.npmjs.org/xxx - Not found
```

**修复策略**：
- 低置信度：可能是包已废弃或版本不存在
- **不自动修改 package.json**，仅给出建议

---

## 3. 通用问题

### 3.1 文件权限不足

**识别特征**：
```
Permission denied: ./scripts/build.sh
EACCES: permission denied, mkdir '/opt/app'
```

**修复策略**：
- 低置信度：环境问题，建议检查 CI 环境配置或文件权限

### 3.2 磁盘空间不足

**识别特征**：
```
No space left on device
write error (disk full?)
```

**修复策略**：
- 低置信度：基础设施问题，需运维介入

### 3.3 网络连接超时

**识别特征**：
```
Connection timed out
Could not resolve host: registry.npmjs.org
```

**修复策略**：
- 低置信度：网络环境问题，建议重试或检查代理配置

### 3.4 Git 操作失败

**识别特征**：
```
fatal: could not read Username for 'https://github.com': terminal prompts disabled
error: failed to push some refs to
```

**修复策略**：
- 低置信度：CI 凭证配置问题，需检查 Jenkins 的 Git 凭证

---

## 4. 修复优先级指南

AI 根据错误类型判断修复优先级：

| 优先级 | 类型 | 自动修复 |
|--------|------|----------|
| P0 | 代码格式化（black/ruff/prettier） | 是，直接运行工具 |
| P1 | 简单语法错误（缺冒号/括号） | 是，AI 直接修改 |
| P2 | 缺失 import | 是，但需确认 |
| P3 | Lint 规则违反 | 视情况，部分可 auto-fix |
| P4 | 类型错误（mypy/tsc） | 建议修复方案，用户确认 |
| P5 | 测试失败 | 仅分析原因，不自动修复 |
| P6 | 环境问题（权限/磁盘/网络） | 仅给出排查建议 |
