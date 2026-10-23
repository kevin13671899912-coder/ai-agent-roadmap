# Day31–40 阶段总结 — Multi-Tool Agent / Policy Gate / Human-in-the-Loop / Durable Execution

> 学习状态：Day31–40 已完成阶段实践与 Day40 集成验收（2026-10-23）。复习阶段，**先不进入 Day41**。
>
> 参考代码：[Day37](../day37/AgentRAG.ipynb) · [Day38](../day38/AgentRAG.ipynb) · [Day39](../day39/AgentRAG.ipynb) · [Day40 主项目](../day40/agent_graph.py) · [Day40 测试](../day40/test_agent.py)

## 一、阶段主线：从“可以调用 Tool”到“可以安全完成业务”

Day21–30 解决 Tool Runtime 可靠性：Retry、Timeout、Circuit Breaker、Bulkhead、错误归一化。Day31–40 在此前提下，进一步解决**谁可以调用什么工具、写操作何时批准、暂停如何恢复、执行后如何对账**。

```text
User Request
  ↓
Agent / Tool Selection           ← 语义选择，可能含不确定性
  ↓
Policy Gate                      ← 确定性的执行边界
  ├─ Read Tool ───────→ ToolNode ────────────┐
  ├─ Unknown / Disallowed → Rejected Result  │
  └─ Write Tool                             │
        ↓                                    │
    Human Approval / interrupt()            │
        ↓                                    │
    Durable Checkpoint                      │
        ↓                                    │
    Command(resume=...)                      │
        ↓                                    │
    Auth + Args + State Revalidation         │
        ├─ FAIL → ToolMessage(error)         │
        └─ PASS → ToolNode → Ledger          │
                        ↓                    │
                   ToolMessage               │
                        └────────────────────┤
                                             ↓
                                 Final Response / Audit
```

**本阶段主原则：LLM 负责不确定性，代码负责不能错的事情。** 例如模型可以推荐调用 `execute_transfer`，但不能仅凭一句自然语言批准就绕过 Policy Gate。

## 二、Day31–40 逐日复习地图

| 天数 | 核心复习主题 | 需要能回答的问题 |
|---|---|---|
| Day31 | Multi-Tool 安全边界 / 审批入口 | “模型选择工具”与“系统准许执行”是不是同一件事？ |
| Day32 | Tool Contract / 参数约束 | Tool 名称、参数 Schema、工具 ID 谁来校验？ |
| Day33 | Tool Calling 协议 | 一个 AIMessage 产生多个 Tool Call 后，结果如何一一对应？ |
| Day34 | 失败、恢复与中间态 | Workflow 暂停和 Workflow 失败有什么区别？ |
| Day35 | Policy / Decision Boundary | 未知工具、只读工具、副作用工具分别怎么处理？ |
| Day36 | 写操作安全：审批、确认、幂等、结果不确定 | Timeout-after-commit 为什么不能盲目重试？ |
| Day37 | LangGraph + Policy Gate + ToolNode | 如何只放行只读调用，把转账保留为 pending？ |
| Day38 | 真实 interrupt / resume | 为什么不能在 interrupt() 前执行不可逆副作用？ |
| Day39 | 官方 SQLite Checkpointer + 独立进程恢复 | 两个 Graph 实例与两个 OS 进程有什么区别？ |
| Day40 | Banking Operations Agent 集成 | 用户请求、审批、ToolMessage、最终答复、持久化如何闭环？ |

说明：Day31–36 的表格是知识主题回顾，不把重复练习包装成十项全新能力。**Day37–40 的实际 LangGraph 集成和跨进程验收**是这一阶段最实质的增量。

## 三、Tool Selection 与 Policy Gate

### 1. Tool Selection 不是 Authorization

```text
LLM: 我想调用 execute_transfer(amount=1000, recipient="Alice")
Policy: 这是 WRITE，有副作用 → 必须审批
Executor: 没有合法审批 → 绝不调用后端
```

推荐划分：

- Agent / LLM：理解用户意图、生成候选 Tool Calls。
- Policy Gate：白名单、参数校验、风险级别、拒绝与待审批分类。
- Approval 服务：验证审批人身份、权限、审批有效期；`resume` JSON 不能替代可信授权。
- ToolNode / Executor：只接收确定已放行的调用。
- Backend：再次校验业务约束、原子更新与幂等。

### 2. 默认拒绝未知工具

`evaluate_policy()` 至少区分：

```text
get_balance / get_transaction_history → READ_ONLY
execute_transfer                     → NEED_APPROVAL
未注册或不允许的 Tool               → REJECT
```

**不要默默丢弃**被拒绝的 Tool Call。必须记录拒绝原因，并维护 Tool Calling 消息协议。

### 3. 多笔副作用调用

Day40 演示中的 Policy Gate 只保存**第一笔**待审批写调用，其余写调用需明确拒绝或排队处理。生产流程不能静默忽略第二笔。

## 四、LangChain / LangGraph Tool Call 消息协议

重要三元组：

- `AIMessage.tool_calls`：候选调用，包含 `id`、`name`、`args`。
- `ToolNode`：执行被授权的调用。
- `ToolMessage(tool_call_id=...)`：返回调用结果，必须和原始调用 ID 对齐。

例子：

```python
AIMessage(
    content="",
    tool_calls=[
        {"id": "bal_01", "name": "get_balance", "args": {}},
        {"id": "tx_01", "name": "execute_transfer",
         "args": {"amount": 1000, "recipient": "Alice", "idempotency_key": "tx-123"}},
    ],
)
# 执行 bal_01 → ToolMessage(tool_call_id="bal_01")
# tx_01 暂停待审批 → 不允许此时把未完成调用的消息发回 LLM
# 审批后执行或拒绝 → ToolMessage(tool_call_id="tx_01")
```

允许 Graph 在中断时暂存**协议尚未完整的中间态**，但不能把未配对的调用消息直接作为下一轮模型输入。最终每个原始调用应有可追踪结果（成功、拒绝、失败或取消）。

Day37 的关键技巧：给 ToolNode 单独传 `filtered_ai_message`，**只执行已放行调用**；但必须确保主对话历史与原始 `tool_call_id` 的配对关系仍然一致。

## 五、Day36–38：副作用边界 + Human-in-the-Loop

### 1. 为什么要 `interrupt()`

它不是普通的 `input()`，而是在持久化的 Graph 执行过程中发出中断，等待外部系统稍后恢复。

```python
from langgraph.types import interrupt, Command

def approval_node(state):
    decision = interrupt({
        "tool_call_id": state["pending_call"]["tool_call_id"],
        "tool_name": state["pending_call"]["tool_name"],
        "args": state["pending_call"]["args"],
    })
    return {"approval_result": decision}

config = {"configurable": {"thread_id": "transfer-123"}}
graph.invoke(initial_state, config=config)  # 到 interrupt 暂停
graph.invoke(Command(resume=approved_payload), config=config)
```

**核心陷阱**：恢复时包含 `interrupt()` 的节点可能从开头重新执行。所以不要在 `interrupt()` 前写数据库、发送转账、发邮件等不可逆操作。把写操作放在独立的审批后节点。

### 2. 审批绑定的最小要素

```text
approved == True
AND tool_call_id 精确匹配
AND tool_name 精确匹配
AND args 精确匹配
AND 审批者身份 / 权限 / 有效期已由可信服务核验
AND 当前业务状态重新校验通过
```

**参数匹配 ≠ 审批身份鉴权。** 任何调用者自造 `{"approved": true}` 都不应自动获得权限。

### 3. 恢复后重新校验（TOCTOU）

暂停前余额 5000，拟转账 1000。暂停期间另一操作把余额降至 800：

```text
approved = True + 参数匹配
≠ 一定可以执行

恢复后查询最新余额 800
→ INSUFFICIENT_FUNDS
→ ToolMessage(error)
→ 不扣款
```

余额检查不能仅使用审批前缓存的状态。真正扣款还应在同一数据库事务中重新检查，防止校验与写入之间发生并发变化。

## 六、Day39：Checkpoint / Durable Execution / Business Ledger

要分清三种存储：

| 对象 | 存什么 | 典型实现 |
|---|---|---|
| Agent State / Checkpoint | 消息、pending_call、执行位置、恢复点 | `SqliteSaver` / Postgres Checkpointer |
| Business DB | 实时账户余额、交易历史、业务状态 | SQLite / PostgreSQL / API |
| Idempotency Ledger | 同一逻辑写操作是否已完成，以及首次结果 | 带唯一键的事务表 |

**Checkpoint 成功写入，不代表银行扣款事务已完成。** 两者不能互相替代。

### 官方 SqliteSaver

Day39 最后采用：

```python
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver

conn = sqlite3.connect("official_checkpoints.db", check_same_thread=False)
graph = builder.compile(checkpointer=SqliteSaver(conn))
# graph.invoke(...) / graph.get_state(...) / graph.invoke(Command(resume=...), ...)
conn.close()
```

对应依赖：`pip install langgraph-checkpoint-sqlite`。

不要自己重新实现完整 Checkpointer 协议：此前 `CustomSqliteSaver.put_writes() = pass` 的写法缺少 pending writes 的持久化语义，有真实恢复风险。

### 如何证明“跨进程”

```python
import subprocess, sys

subprocess.run([sys.executable, "run_process_a.py"], check=True)
subprocess.run([sys.executable, "run_process_b.py"], check=True)
```

A 运行到 `interrupt()` 后退出；B 使用相同数据库文件和相同 `thread_id` 加载待审批调用并恢复。只 `del graph_a` 再 `graph_b = build_graph()`，不算两个独立 Python 进程。

### 后端扣款和 Ledger 必须原子化

```text
BEGIN IMMEDIATE
→ 根据 idempotency_key 查询已完成记录
→ 同一事务中读取余额
→ 余额不足则拒绝
→ 扣款
→ 插入 Ledger 首次结果
→ COMMIT
```

相同 `idempotency_key` 重试只返回已完成结果。不同交易使用不同键；同一逻辑交易**即使进程重启**也必须使用同一个稳定键。

## 七、Day40 项目结构与结果

最终项目结构：

```text
day40/
  AgentRAG.ipynb        # 验收入口与输出
  agent_graph.py        # Agent / 路由 / Approval / ToolNode / Final
  policy.py             # Policy Gate 与审批检查
  banking_backend.py    # SQLite 余额、历史、幂等 Ledger
  test_agent.py         # 八类集成场景
  sub_process_worker.py # 独立 OS 进程暂停/恢复
```

支持的工具：`get_balance`、`get_transaction_history`、`execute_transfer`。

八个场景：查询余额、查询历史、转账触发暂停、用户拒绝、正常批准、余额下降拒绝、重复请求幂等、跨进程恢复。

**已证实的修复历程**：

1. Day38：从只检查 `approved`，修复为绑定 `tool_call_id + tool_name + args`；从直接调用 Backend，修复为通过 ToolNode。
2. Day38/39：修复只读工具与待审批调用同时存在时的路由问题。
3. Day39：从手写 Checkpointer 和同进程“双实例”，修复为官方 `SqliteSaver` + 真正的两个 Python 子进程。
4. Day40：补齐最终答复、拒绝结果与主要测试覆盖；余额下降场景最初误触发 `PARAMETER_MISMATCH`，后改为真正触发 `INSUFFICIENT_FUNDS`。
5. Day40：Windows GBK 终端曾因输出 emoji 导致 `UnicodeEncodeError`，改成纯 ASCII 的测试结束提示，最后 Notebook 保存 `PASS` 输出。

### 别把阶段验收误当生产就绪

Day40 的决策器仍是规则/模拟（例如从中文请求里解析金额），**不是实际接入 LLM 的完整 Tool Calling Agent**。审批身份真实性还需接入外部鉴权服务；复杂多笔调用需设计排队或逐笔审批；完整审计与真实生产故障恢复也未实现。

## 八、最值得记住的八条工程原则

1. **LLM 决定候选意图；Policy 决定能否执行。**
2. **只读可以直通，副作用必须受控；未知工具默认拒绝。**
3. **Tool Call 和 ToolMessage 通过 ID 一一对应。**
4. **interrupt 前不做不可逆副作用；恢复后重校验。**
5. **resume 数据不天然可信，审批身份由可信边界认证。**
6. **Checkpoint 管执行状态，Business DB 管业务事实，Ledger 管幂等。**
7. **一笔逻辑操作一个稳定幂等键；Retry / Resume 不换键。**
8. **测试必须验证失败原因和副作用结果，而不只看最后答复或“PASS”打印。**

## 九、仍需记住的技术债（不阻碍 Day40 学习验收）

- **Day40 场景 7 测试设计**：在余额被调到 800 后再尝试转账 1000，两次结果相等也可能只是两次 `INSUFFICIENT_FUNDS`。严谨测试要先成功扣款，再断言重复请求不再扣款，且 Ledger 只有一条。
- **交易 ID 稳定性**：Day40 使用 UUID 动态生成新交易 ID，解决“所有交易共用固定键”；但同一业务请求被重新生成 Tool Call 时，不能再生成新键。交易 ID 应由入口请求提供并保存到 State / Checkpoint。
- **金额与收款人**：简单 regex + 固定 Alice 仅适合课程模拟；真实业务需要严格参数解析、校验正数、货币与账户归属。
- **结果解析**：`final_response_node` 依赖字符串关键词判断成功，未来应改用结构化 ToolResult（而不是子字符串）。
- **消息协议完整性**：必须保证多调用、拒绝、未知工具、追加下一轮 LLM 前不会遗留未配对的 Tool Calls。
- **权限与审计**：审批人身份 / RBAC / 过期 / 撤销、审计日志及 trace 尚未落地。
- **并发与账本**：对真正支付场景须强化唯一约束、事务冲突处理、金融金额用 Decimal/最小货币单位，禁止负数扣款。

## 十、复习顺序（不新增知识点）

1. **15 分钟画图**：不看代码画出 Day40 的 read / write 两条路径，并说出每个安全门的责任。
2. **20 分钟追消息**：拿 `get_balance + execute_transfer` 两个 Tool Call，写下每个 `tool_call_id` 对应的 ToolMessage 在哪里产生。
3. **20 分钟追失败**：模拟拒绝审批、参数篡改、余额下降、Timeout-after-commit 四种情况，确定哪里拦截、余额变不变。
4. **20 分钟追重启**：从 A 暂停到 B 恢复，标出哪些信息存 Checkpoint、哪些存 Ledger。
5. **20 分钟复盘测试**：修正“失败结果相等 ≠ 幂等成功”这种假阳性断言。

复习检测题、参考答案和针对 Day40 的小型补强实验见 [DAY31-40_GLOSSARY_FAQ.md](./DAY31-40_GLOSSARY_FAQ.md)。

---

## 下一步（等完成复习再继续）

Day41–50 是 Memory / Context Engineering；**本文件仅作 Day31–40 阶段复习，不提前推进课程**。
