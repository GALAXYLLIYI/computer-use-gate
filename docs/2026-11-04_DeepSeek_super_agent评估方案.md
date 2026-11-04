# DeepSeek 官方 super-agent 落地评估（只评估，不落地）

## 1. 评估对象

DeepSeek 官方 super-agent 概念：统一模型 + 工具编排 + 记忆 + 权限/审计 + 多步任务执行。
本地方案：OpenCode/ZCode/DSH + AgentStation VS Code + agentctl + 记忆引擎。

## 2. 本地已有能力

- 多 Agent：OpenCode、ZCode、DSH、VS Code 扩展
- 工具/权限：agentctl 闸门、租约、急停、时间线
- 记忆：episodes/segments、subject 分仓、召回策略、备份/去重
- 训练：Qwen/Ollama teacher/judge、7B QLoRA 候选（受 8GB 显存约束）
- 观测：VS Code 训练页、体检、知识树、理论图谱

## 3. 缺口

| 能力 | 本地现状 | super-agent 要求 | 差距 |
|---|---|---|---|
| 统一任务协议 | 多套 MCP/CLI | 单一协议 | 中 |
| 长任务编排 | 循环 + harness | 原生 planner/executor | 大 |
| 记忆写入 | append-only + gate | 自动记忆/检索 | 小 |
| 权限/审计 | agentctl 强 | 内置 | 本地更强 |
| 多模型路由 | 手动/多入口 | 自动路由 | 中 |
| 回滚/沙箱 | 部分 | 原生 | 中 |

## 4. 三种落地形态

### A. 薄适配层（推荐先评估）
- 把 super-agent 当外部 planner，本地 harness 当 executor
- 保留 agentctl 权限/审计/记忆
- 风险低，改动小，能快速验证

### B. 双栈并行
- 官方栈跑新任务，本地栈跑存量
- 共享记忆/评测，不共享写权限
- 成本中，适合 2-3 个月

### C. 完全迁移
- 用官方 super-agent 替换本地编排
- 需要重做权限、记忆、审计、回滚
- 风险高，不建议现在做

## 5. 评估结论（建议）

- 现在**不做完全迁移**
- 先做 A：一个只读 planner 适配器 + 本地 executor
- 用 10 个真实任务对照：成功率、步数、成本、回滚、审计
- 通过后再考虑 B

## 6. 评估指标

- 任务成功率
- 平均步数/时延
- 工具调用错误率
- 记忆召回命中率/出处率
- 权限拦截率/误拦率
- 回滚成功率
- 单任务成本

## 7. 风险

- 官方协议与本地 MCP 不兼容
- 记忆格式/权限模型冲突
- 长任务失控/成本失控
- 审计链断裂
- 供应商锁定

## 8. 下一步（仅评估）

1. 收集官方 super-agent 协议/接口文档
2. 选 10 个本地真实任务做基线
3. 写一个只读 planner 适配器原型（不接生产）
4. 对照评估后再决定是否投入
