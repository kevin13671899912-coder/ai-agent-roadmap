# Day41–60 学习路线图 — Memory / Context Engineering / Planning / Capstone

> 制定日期：2026-10-23。**当前状态：Day40 已通过阶段验收，正在复习；尚未开始 Day41。** 本文件是后续计划，不代表已经完成。
>
> 前置材料：[Day31–40 阶段总结](./DAY31-40_SUMMARY.md) · [Day31–40 名词 FAQ](./DAY31-40_GLOSSARY_FAQ.md) · [Day40 Agent 项目](../day40/agent_graph.py) · [Day40 测试](../day40/test_agent.py)

## 一、总目标与课程原则

在 Day1–40 的 LangGraph、RAG、工具可靠性、Policy Gate、Human Approval、Checkpoint、Idempotency 基础上，完成一个**可持久恢复、上下文可控、可计划多步任务、可评估和审计**的综合 Agent 项目。

- **不从零重复造 Mock**：以 Day40 Banking Operations Agent 为工程安全基座，逐步抽象到通用多步骤业务 Agent。为避免影响已通过的验收，Day40 原目录保持基线，新阶段在独立目录演进，必要时复用代码。
- **LLM 负责不确定性，代码负责不能错的事情。** 任何资金类写操作依然要遵守授权、审批绑定、重新校验、幂等和事务原子性。
- 每天有理论重点、可提交的代码或实验、明确验收。**一个功能可跨多天完善，不强求每天新建工程。**
- 不将 Notebook 运行截图或“打印 PASS”当作充分证据：同时核查断言、持久化数据、错误路径和进程边界。
- 学习按用户明确指令推进。**当前仍在 Day40 复习，只有用户说“开始 Day41”才进入新阶段。**

## 二、阶段划分

| 阶段 | 天数 | 交付目标 |
|---|---|---|
| Memory Foundations | Day41–44 | 短期/长期记忆、持久化、隔离与生命周期 |
| Context Engineering | Day45–47 | 上下文选择、截断/摘要、检索和 Token Budget |
| Memory Integration & Evaluation | Day48–50 | 记忆与 Tool Agent 集成，测试与评估 |
| Planning & Reasoning | Day51–54 | 任务分解、计划状态、依赖、重规划和审批 |
| Agent Reliability & Observability | Day55–57 | 失败恢复、Trace、审计、对抗与回归验证 |
| Capstone & Graduation | Day58–60 | 综合项目、演示、验收、总结 |

## 三、Day41–50：Memory & Context Engineering

| Day | 学习目标 | 实战交付物 | 最低验收标准 |
|---|---|---|---|
| **41** | 区分短期会话状态、长期记忆、业务真相 | 记忆架构图；定义 State、Checkpoint、Store、Business DB 边界 | 能证明 Checkpoint 不等于长期用户记忆；不能用“记忆”替代真实余额 |
| **42** | LangGraph 跨轮次短期记忆 | 多轮对话及 thread_id 隔离实验 | 同线程保持上下文，不同线程不会混淆；进程重启可恢复 |
| **43** | 长期记忆 Store 与命名空间 | 持久化 profile / preference 样例与读写接口 | 不同 user_id 数据隔离；重启后仍能读取 |
| **44** | 记忆生命周期、更新与删除 | Upsert、去重、修改、遗忘与权限测试 | 旧事实可被纠正、删除可验证；敏感信息默认不自动入记忆 |
| **45** | 上下文窗口与 Token Budget | Context Builder / 预算限制器 | 输入不超预算；保留系统规则、安全约束和当前任务关键事实 |
| **46** | 历史摘要与信息损失控制 | 摘要策略、关键实体保留测试 | 长对话压缩后保留未完成任务、交易 ID 和审批状态；不把摘要当授权 |
| **47** | 选择性检索与相关性排序 | 用户/会话记忆检索、来源标记 | 正确召回相关记忆，拒绝跨用户召回，能辨别记忆与实时业务数据 |
| **48** | Memory + Tool Calling + HITL 集成 | 在 Agent 中接入持久记忆与 Context Builder | 多轮指代可正确解析；记忆无法绕过 Policy Gate 或修改已批准参数 |
| **49** | Memory Evaluation | 测试集：召回准确性、过期信息、冲突事实、隐私隔离 | 自动断言包括错误信息不被应用、敏感用户信息不串线 |
| **50** | 阶段集成验收和技术债整理 | Day41–50 总结、FAQ、集成测试 | 核心正反用例通过；提交 `notes/DAY41-50_SUMMARY.md` 与 FAQ；标明尚未实现能力 |

**该阶段关键边界：** 记忆可以辅助理解“用户想做什么”，却不能证明身份、授权转账或替代真实业务事实。用户“常给 Alice 转账”的历史偏好不能成为免审批依据。

## 四、Day51–57：Planning / Multi-Step Agent / Reliability

| Day | 学习目标 | 实战交付物 | 最低验收标准 |
|---|---|---|---|
| **51** | Planning 基础与任务分解 | 显式 Plan Schema：step_id、依赖、状态、工具与成功条件 | 模型提出计划；代码验证工具白名单、参数 Schema 和依赖是否合法 |
| **52** | 执行器与依赖调度 | Planner–Executor 简版 LangGraph | 先后依赖正确；失败步骤不会错误标记为完成 |
| **53** | Replanning 与失败分支 | 可更新计划、重试/跳过/人工介入策略 | 重规划不会悄悄替换已审批交易的收款人、金额或稳定业务 ID |
| **54** | 多步骤 HITL / 暂停恢复 | 对写操作逐项审批，完整 ToolMessage 配对 | 跨进程恢复；拒绝/取消/异常均有对应结果，不遗留非法模型消息历史 |
| **55** | Reliability 综合 | 断线、超时、重试、并发、崩溃故障注入 | 重试不重复执行副作用；测试首次成功后再重试，验证 Ledger 仅一次 |
| **56** | Observability / Audit | 结构化日志、trace_id、operation_id、tool_call_id | 能串起单次用户请求、多个 Tool Calls、审批、Backend 事务结果；日志脱敏 |
| **57** | 安全回归与性能验证 | 多用户并发/竞态/越权/提示注入测试及验收报告 | 权限与数据隔离通过；不允许任意工具调用；有失败清单与改进计划 |

**该阶段关键边界：** Plan 不是权限。模型即使重规划，也必须复用原交易的稳定 `transaction_id`，重大业务参数变更必须走新的授权流程。

## 五、Day58–60：最终综合项目

**推荐毕业项目：Reliable Operations Agent**（以现有 Banking Operations Agent 为基础，扩展多轮记忆、计划执行和工程可观察性）。该名称为规划建议，具体业务范围以实现进度为准。

### Day58 — 核心功能集成

- 在同一工程中串联：会话/长期记忆 → Context Builder → Planner → Policy Gate → Approval → Revalidation → ToolNode → Backend → Ledger → Final Response。
- 最少支持只读查询和一类受审批的写操作；写操作保留稳定业务 ID。
- 清楚区分 Agent State、Checkpoint DB、Memory Store、Business DB / Ledger。
- 用配置切换模拟工具决策与真实 LLM；没有真实接入时应明确标注，不假称生产 LLM。

**验收：** 正常流程端到端通过，单条 Trace 可追踪。

### Day59 — 故障与安全验收

- 模拟进程中断后恢复、审批拒绝、余额变化、网络超时后重试和并发写入。
- 相同业务 ID 重试不能重复扣款；相同幂等键但不同业务参数必须拒绝。
- 原始 AIMessage 的所有 Tool Calls 必须最终有对应结果；未知工具默认拒绝。
- 运行自动化回归；保存真实执行结果，而非手工填入 PASS。

**验收：** 核心场景的状态、日志、余额、Ledger 和退出码可交叉验证。

### Day60 — 毕业验收

最终应提交：

1. 可复现的运行说明（环境变量示例、启动命令、测试命令）。
2. 系统架构图和数据流/权限边界说明。
3. 自动化测试及实际执行输出（含故障/并发场景）。
4. 已知限制、未实现能力、风险列表和下一步改进建议。
5. `notes/DAY51-60_SUMMARY.md`、术语 FAQ 或毕业复盘文档。

**通过标准：** 可以清楚演示端到端功能；解释每一个安全/可靠性边界；有可重复的测试证据；诚实区分“课程原型”与“生产就绪”。

## 六、从 Day40 带入后续阶段的技术债

按风险优先级逐步处理，不阻塞已有学习成果：

1. **稳定交易 ID：** Day40 在 `agent_node()` 中生成动态 UUID。改为业务入口创建一次、持久化至 State 与后端，重试/恢复原样复用。React + Spring Boot 场景下服务端可创建 operation/transaction ID，前端持有 ID 并查询状态；后端以唯一约束与事务保证幂等。
2. **幂等测试真实性：** 先成功扣款，再模拟重复请求，断言余额只减少一次、Ledger 仅一条；不要使用两次余额不足的结果相等证明幂等。
3. **审批安全：** 外部可信服务验证身份、权限、有效期，审批绑定 `tool_call_id + tool_name + args`；恢复后重新校验，不能信任自报 `approved=True`。
4. **结构化结果与多调用配对：** 不再靠最终回复中的字符串判断成功；多个 Tool Calls 都应有可追踪 ToolMessage，拒绝亦须配对。
5. **真实模型和真实服务边界：** Day40 仍是规则决策器。未来接入 LLM 或 Spring Boot API 时，重新验证 Tool Contract、并发、超时后提交、原子事务与审计，不能沿用模拟环境的安全假设。
6. **金额与并发：** 使用 Decimal/最小货币单位、正数检查、账户归属校验、后端事务内重读余额、唯一约束；必要时增加 `SELECT ... FOR UPDATE` 或条件更新。

## 七、每日导师工作流

1. 开始当天：先说明该日目标、为什么要做、与已完成代码的关系。
2. 用户写代码并提交 GitHub，说“已提交”：导师**直接查看仓库实际文件、测试与差异**，不要让用户重复贴链接或代码。
3. Review 分类为：**必须修复 / 推荐优化 / 后续技术债**；优先核查真实行为与断言，而不是形式问题。
4. 验收通过后记录日期、Commit、主要证据与遗留问题，再决定是否推进下一天。
5. 每十天阶段结束：将总结和名词 FAQ 存入 `notes/`；长期规划变更则更新本路线并说明原因。
6. 未经用户明确要求，不提前开始下一天；尤其**当前 Day41 尚未开始**。

## 八、新聊天的最小交接说明

> 我正在完成 60 天 AI Agent / LangGraph 工程学习计划。GitHub 仓库：`kevin13671899912-coder/ai-agent-roadmap`。请先阅读 `notes/DAY31-40_SUMMARY.md`、`notes/DAY31-40_GLOSSARY_FAQ.md`、`notes/DAY41-60_ROADMAP.md`，并参考 `day40/`。Day40 已验收，现阶段仍在复习；未经我明确说“开始 Day41”，不要推进。你是中文工程导师，以实际代码和测试为主，我说“已提交”时直接从 GitHub 拉取代码 Review。请严格按路线图和已知技术债衔接学习。
