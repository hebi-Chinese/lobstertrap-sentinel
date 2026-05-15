# Lobster Trap 项目笔记

源仓库: `./lobstertrap/`(clone 自 https://github.com/veeainc/lobstertrap)

---

## 是什么

Go 写的**反向代理**, 介于 AI Agent 和 OpenAI 兼容的 LLM 后端之间, 做 **DPI (Deep Prompt Inspection)** 双向检查.

```
[Agent / App] → [Lobster Trap] → [LLM Backend (OpenAI 兼容)]
                       ↓
                  [审计日志]
```

- **Ingress DPI**: 在请求到达模型**之前**检查 prompt
- **Egress DPI**: 在响应回到 Agent **之前**检查 LLM 输出
- **目标性能**: <1ms ingress DPI, <5ms 总开销, <50MB 内存

---

## Go 项目结构

```
cmd/
internal/
├── inspector/    # DPI 引擎(检测各种特征模式)
├── policy/       # 策略加载 + 规则解析(YAML)
├── pipeline/     # 请求处理管线
├── proxy/        # OpenAI 兼容反向代理
└── audit/        # 审计日志(JSON 行格式)
```

---

## 关键设计决策(来自 claude.md)

1. **反向代理形态** — 不改 Agent 不改 LLM
2. **亚毫秒级 ingress DPI** — 不能拖慢推理
3. **First-match-wins** — 规则优先级排序后首个命中即生效 (类似 iptables)
4. **Ingress / Egress 分离** — 输入和输出走独立规则集
5. **JSON 审计日志** — 每个请求一行 JSON, 便于流处理
6. **YAML 策略** — 人类可读, Ops 友好
7. **OpenAI 兼容** — 现成生态

---

## 8 个 Actions

| Action | 含义 | 状态 |
|--------|------|------|
| ALLOW | 放行 | 已实现 |
| DENY | 拦截 | 已实现 |
| LOG | 记录但放行 | 已实现 |
| HUMAN_REVIEW | 转人工审核 | 已实现 |
| QUARANTINE | 隔离 | 已实现 |
| RATE_LIMIT | 限流 | 已实现 |
| MODIFY | 修改请求/响应 | 保留位 |
| REDIRECT | 重定向到另一后端 | 保留位 |

**注**: MODIFY 和 REDIRECT 暂未实装, 在 LT 文档中标 reserved.

---

## 元数据字段 (Metadata Fields)

LT 在 DPI 阶段提取这些字段, 规则基于字段匹配:

| 字段 | 类型 | 说明 |
|------|------|------|
| `intent_category` | string | 意图分类(question / instruction / etc) |
| `risk_score` | float | 风险评分 |
| `contains_credentials` | bool | 含密钥? |
| `contains_pii` | bool | 含 PII? |
| `contains_injection_patterns` | bool | 含 prompt injection 特征? |
| `contains_sensitive_paths` | bool | 含敏感文件路径? |
| `target_paths` | list | 涉及的文件路径 |
| `target_domains` | list | 涉及的域名 |
| `target_commands` | list | 涉及的 shell 命令 |
| `token_count` | int | token 数 |

---

## Match Types (匹配类型)

| 类型 | 用法 |
|------|------|
| exact | 精确字符串 |
| prefix | 前缀 |
| glob | 通配符 |
| regex | 正则 |
| contains | 包含子串 |
| boolean | 布尔字段(配 bool 元数据) |
| threshold | 阈值(配数值元数据) |
| range | 范围 |

---

## `_lobstertrap` 字段(双向元数据)

Agent ↔ LT 之间通过 HTTP header 里的 `_lobstertrap` 字段交换元数据.

- **入站方向**: Agent 可在 header 里声明自己的 intent(declared intent)
- **出站方向**: LT 把 inspection report 塞回 header 给 Agent

---

## 默认策略概览 (configs/default_policy.yaml)

### Ingress Rules (12 条, 按优先级降序)

| Priority | Rule | Action |
|----------|------|--------|
| 100 | block_prompt_injection | DENY |
| 98 | block_harm_violence | DENY |
| 96 | block_malware_request | DENY |
| 94 | block_phishing_fraud | DENY |
| 92 | block_data_exfiltration | DENY |
| 90 | block_obfuscation_evasion | DENY |
| 86 | review_role_impersonation | HUMAN_REVIEW |
| 85 | block_sensitive_paths | DENY |
| 82 | block_pii_request | DENY |
| 80 | block_dangerous_commands | DENY |
| 70 | review_high_risk | HUMAN_REVIEW |
| 30 | log_code_execution | LOG |

### Egress Rules (2 条)

| Priority | Rule | Action |
|----------|------|--------|
| 100 | block_credential_leak | DENY |
| 90 | block_pii_leak | DENY |

### 其他规则段

- **rate_limits**: 120/min, 2000/hr, burst 30
- **network policy**: allowlist + denylist (域名)
- **filesystem policy**: denied_paths + allowed_paths

---

## LT 的盲点(可以在上层补的位置)

这是用户后续设计的切入点 —— 这些是 LT **没做** 的事:

1. **不理解 Agent 身份** — 只记录 agent_id, 不知道 Agent 是谁、什么角色、信任级别
2. **无 session / memory 概念** — 每个请求独立看, 没有"这个 Agent 最近一直在做坏事"的状态记忆
3. **无 Agent 关系图** — 不知道 Agent A 调 Agent B 的拓扑
4. **默认策略是单 Agent 视角** — 多 Agent 协同场景没有现成规则
5. **审计日志是 flat JSON** — 没有聚合 / 关联分析

---

## 模式库(从 internal/inspector/ 推断)

LT 内部维护几类正则/特征库:

- **credential patterns** — API key 格式、密码模式
- **PII patterns** — 邮箱、身份证、电话号码等
- **injection patterns** — prompt injection 经典话术("ignore previous instructions"等)
- **shell command patterns** — rm / curl / wget / nc 等危险命令
- **file path patterns** — /etc/passwd / ~/.ssh / windows 系统路径等
