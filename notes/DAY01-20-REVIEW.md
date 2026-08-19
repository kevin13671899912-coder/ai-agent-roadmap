# AI Agent 60 天学习路线：Day 1–20 阶段复习

> 用途：阶段复习、新会话交接、后续 Day 21–60 学习的上下文入口。

## 当前进度

- 已完成：Day 1–20
- 下一阶段：Day 21 Production Reliability
- 学习方式：少量理论 → 架构/场景题 → 自己回答 → 写代码 → 提交 GitHub → Code Review
- 当前重点：不是只会 LangGraph API，而是理解 Agent Runtime、Workflow、RAG、Memory 与企业可靠性设计。

---

## 一、Day 1–20 核心知识地图

```text
User
 ↓
LLM / Agent
 ↓
Graph / Runtime
 ↓
Router
 ├── Business API / Database
 ├── RAG / Retriever
 ├── Tool / Tool Node
 └── Human Approval
 ↓
State
 ↓
Checkpoint

Long-term Context:
Memory

Reliability:
Retry → Fallback → Idempotency
```

核心原则：

> LLM 处理不确定性；Graph 处理确定性；State 传递当前数据；Checkpoint 负责恢复；Tool 连接现实世界；Runtime / Policy 保证执行可靠和安全。

---

## 二、Agent / Tool / Graph

### LLM 与 Agent

LLM 主要负责自然语言理解、语义推理、判断需要什么能力、生成 Tool Call、综合结果。

Agent 不只是聊天模型，而是：

```text
LLM
+ Tools
+ State
+ Runtime / Graph
+ Control Logic
```

### Tool Call、Tool、Tool Node

三者不要混淆：

```text
Tool Call
→ LLM 产生的“调用什么工具、传什么参数”的请求

Tool
→ 真正的函数/外部能力，例如 query_employee()

Tool Node / Executor
→ Runtime 中真正负责执行 Tool Call 的节点
```

例如：

```text
LLM
→ ToolCall: query_weather(city="Shanghai")
→ Graph
→ Tool Node
→ query_weather()
→ Tool Result
→ LLM
```

### Graph 的职责

Graph 负责流程控制，而不是业务数据本身。

```text
Node   → 做业务步骤
Router → 根据 State 判断下一步
Graph  → 执行调度
```

企业关键流程不能只依赖 Prompt 让 LLM “记得按顺序执行”。

```text
Prompt Rule     = Soft Constraint
Graph Structure = Hard Constraint
```

---

## 三、State / Checkpoint / Memory / Business DB

这是目前最需要持续保持边界清晰的一组概念。

### State

State 保存**当前 Workflow 运行过程中需要传递的数据**。

例如：

```python
state = {
    "employee_id": "E1001",
    "employee": {...},
    "rag_query": "试用期员工年假规定",
    "knowledge": {...},
    "retry_count": 1,
    "idempotency_key": "leave_fix_001"
}
```

生命周期通常跟当前 Workflow / Thread 相关。

### Checkpoint

Checkpoint 是某个时间点的 Workflow 快照，用于中断恢复、故障恢复、Human-in-the-loop 等。

可以理解为：

```text
Checkpoint
≈ State Snapshot
+ Workflow execution position / next step
```

`thread_id` 用来识别一条 Workflow/会话执行链；`checkpoint_id` 更偏向某个具体恢复点。

### Memory

Memory 保存跨会话有价值的长期信息，例如：

```text
用户身份
长期偏好
习惯
稳定特征
```

例如：

```text
“我平时喜欢中文回答”
→ Long-term Memory
```

但：

```text
“这次请用英文回答”
→ 当前指令 / Context，不应直接当长期偏好
```

### Business Database / API

实时业务事实应该来自权威业务系统，而不是 Memory。

```text
E1001 当前是不是 probation
E1001 年假余额
ERP 项目当前负责人
审批单当前状态
```

应该来自 HR / ERP / CRM / Database / API。

重要区分：

```text
业务实时事实 → Business DB / API
企业制度知识 → RAG
长期用户偏好 → Memory
本次 Workflow 数据 → State
运行恢复快照 → Checkpoint
```

---

## 四、存储层理解

### Redis

适合低延迟、临时状态、缓存、热点数据等场景。

### PostgreSQL

适合结构化业务数据、持久化记录、事务数据、审计数据等。

### Vector DB

适合 Embedding 后的非结构化知识检索，例如 PDF、员工手册、制度文档等。

不是所有数据都应该放 Vector DB。

---

## 五、RAG / Retrieval

已经学习并实践：

```text
Document
Chunk
Embedding
Vector Search
Metadata Filter
Top-K
Threshold
Reranker
Query Rewrite
NO_RELEVANT_KNOWLEDGE
```

### Metadata

Metadata 负责硬约束，例如：

```text
status = active
year = 2026
effective_date <= today
```

不能只靠相似度让旧制度和新制度竞争。

### Similarity / Threshold

Vector similarity 是相关性信号，不等于绝对正确。

Threshold 不应该凭感觉确定，应结合 Evaluation / 测试集调整。

如果最终结果都低于 Threshold：

```text
NO_RELEVANT_KNOWLEDGE
```

LLM 应明确表示没有足够证据，而不是自己编答案。

### Reranker

Retriever 找到多个候选后，可以用 Reranker 做更精确的软相关排序。

### Query Rewrite

用户原始问题不一定是最佳检索 Query。

例如：

```text
用户：
“我还没转正，为什么没有年假？”

业务数据：
status = probation

Rewrite：
“试用期员工年假规定”
```

Query Rewrite 可以由 LLM 完成，也可以在规则明确时使用普通代码。

原则：

```text
确定性规则 → 普通代码
语义理解 / 不确定性 → LLM
```

---

## 六、Tool Dependency / 串行与并行

判断是否能并行，不是看是不是两个 Tool，而是看**数据依赖**。

```text
A → B
```

如果 B 的输入依赖 A 的输出，必须串行。

例如：

```text
query_employee(E1001)
↓
status = probation
↓
search_company_knowledge("试用期员工年假规定")
```

而：

```text
查询上海天气
```

与员工年假查询没有数据依赖，可以并行。

### Day 17

通过 Prompt / LLM 实现：

```text
Employee → RAG
```

属于 Soft Constraint。

### Day 18

升级成 Graph Hard Constraint：

```text
START
 ↓
employee_node
 ↓
Router
 ├─ employee exists → build_rag_query → rag → final
 └─ employee None   → final
```

关键测试不仅要证明“应该走的路径能走”，还要证明“不应该走的路径走不了”。

E9999 测试验证了：员工不存在时不会进入 RAG。

---

## 七、Failure Handling（Day 19）

核心原则：

> 失败不是异常边缘情况，而是 Workflow 的正常状态之一。

### 错误分类

```text
Retryable Error
→ Timeout / 503 / 部分 429

Non-Retryable Error
→ 401 / 参数错误 / 权限错误等

Business Result
→ NOT_FOUND 等正常业务结果
```

例如：

```text
query_employee → Timeout
→ Retry
→ 超过上限 Fallback

query_employee → NOT_FOUND
→ 正常结束，不 Retry

401 Unauthorized
→ 不 Retry，不应通过 Fallback 绕过权限
```

### Retry

Retry = 同一个方案再试一次。

### Fallback

Fallback = 主方案失败后换方案。

例如：

```text
HR API
↓ 失败并超过 Retry
Redis / Cache
```

### Graph 可靠性结构

```text
employee_node
     ↓
   Router
  /   |    \
OK  Retry  Fatal
↓     ↓      ↓
RAG employee Final
       ↓
  超过上限
       ↓
   Fallback
```

Node 只报告发生了什么；Router 决定怎么办；Graph 执行决定。

---

## 八、Backoff / Jitter（已建立概念，Day 21 深入）

不能在服务故障时瞬间：

```text
Retry Retry Retry Retry
```

需要 Exponential Backoff，例如：

```text
1s → 2s → 4s → 8s
```

并加入 Jitter，避免大量客户端同时重试造成 Thundering Herd。

Day 21 将继续系统学习。

---

## 九、Idempotency（Day 20）

Read Tool 和 Write Tool 的 Retry 风险不同。

```text
query_employee()
→ Read
→ Retry 通常相对安全

create_request()
give_bonus()
transfer_money()
→ Write
→ Retry 必须考虑重复副作用
```

### Ambiguous Failure

危险场景：

```text
Backend 实际执行成功
↓
Response 在网络中丢失
↓
Client 看到 Timeout
```

Client 无法判断业务是否已经成功。

如果直接 Retry Write Tool，可能重复执行。

### idempotency_key

同一个业务 operation 必须使用同一个 key：

```text
prepare_operation
↓
key = ABC
↓
execute #1
↓ Timeout
↓
execute #2
↓
仍然 key = ABC
```

绝不能 Retry 时重新生成 key。

### Backend 行为

```text
key 不存在
→ 创建 operation / 执行业务

key = processing
→ 不重复执行
→ 等待 / 返回处理中 / 轮询

key = completed
→ 不重复执行
→ 直接返回第一次保存的结果

key = failed
→ 根据失败类型和业务规则决定是否允许继续
```

### State + Checkpoint

`idempotency_key` 应进入当前 State，并由 Checkpoint 持久化。

这样 Workflow 崩溃恢复以后仍然使用同一个 key。

### Day 20 实验

已经验证：

```text
第一次 give_bonus
→ BONUS_DB += 5000
→ Backend 保存 completed
→ Response Timeout

Graph Retry
→ 同一个 idempotency_key
→ Backend 命中 completed
→ 不再次 += 5000

最终 Bonus = 5000，而不是 10000
```

---

## 十、Security / 企业 Tool 执行边界

已经建立的安全意识包括：

```text
Authentication
Authorization
Least Privilege
参数校验
风险判断
Human Approval
Prompt Injection 防护
Audit
```

工资等敏感数据不能因为 LLM 收到一句自然语言命令就直接暴露。

Tool Result 也应该作为外部数据处理，不能盲目当成新的系统指令执行。

关键 Write Tool 应由 Runtime / Policy / Approval 约束，而不是只靠 Prompt。

---

## 十一、20 天后的职责模型

```text
LLM
→ 语义理解、推理、不确定性处理

Node
→ 完成一个具体业务步骤

Tool Node / Executor
→ 真正执行外部 Tool

Router
→ 根据 State 判断下一步

Graph
→ 调度和硬约束流程

State
→ 当前 Workflow 数据

Checkpoint
→ Workflow 快照、恢复点

Memory
→ 跨会话长期用户信息

RAG
→ 企业非结构化知识

Business API / DB
→ 实时权威业务事实

Retry
→ 临时故障恢复

Fallback
→ 主方案失败后的降级

Idempotency
→ Write Retry 不重复产生副作用
```

---

## 十二、阶段综合案例：HR Agent

用户：

> 我是 E1001，我今年为什么没有年假？如果确实是系统错误，帮我提交一个年假修正申请。

合理流程：

```text
START
 ↓
query_employee(E1001)
 ↓
employee exists?
 ├─ NO → Final / END
 └─ YES
      ↓
构造 RAG Query
      ↓
search_company_knowledge
      ↓
有可靠制度证据？
 ├─ NO → 明确无法判断 / END
 └─ YES
      ↓
比较“实时业务数据”和“公司制度”
      ↓
是否属于系统异常？
 ├─ NO → 解释原因 / END
 └─ YES
      ↓
必要的 Policy / Approval
      ↓
prepare_operation
      ↓
生成并保存 idempotency_key
      ↓
create_leave_correction
      ↓
成功 / Safe Retry / Fallback / Final
```

关键点：

```text
“没有年假” ≠ “系统错误”
```

必须先结合实时员工状态和公司制度判断，才能执行 Write Tool。

---

## 十三、目前需要继续强化的地方

### 1. State / Memory / Business DB 边界

容易混淆，继续用下面规则判断：

```text
当前 Workflow 临时数据？ → State
跨会话长期用户偏好？     → Memory
实时权威业务事实？       → Business DB / API
```

### 2. Node 与 Router 的边界

```text
Node
→ 得到事实 / 执行业务

Router
→ 根据事实决定去哪
```

例如：

```text
employee_node
→ 查询 employee

Router
→ employee is None ? Final : RAG
```

### 3. LLM 与普通代码的边界

```text
确定性业务规则
→ 普通代码 / Graph

语义不确定性
→ LLM
```

不要为了 Agent 而把所有逻辑交给 LLM。

---

## 十四、Day 1–20 阶段自测结论

阶段综合题已经覆盖：

- 数据归属
- Tool Dependency
- Node / Router / Graph 职责
- Failure Handling
- Retry / Fallback
- Write Tool Safe Retry
- Idempotency

整体已经达到继续进入 Production Agent 阶段的要求。

---

# 下一阶段：Day 21

## Production Reliability

下一课从以下内容继续：

```text
Timeout
Exponential Backoff
Jitter
Circuit Breaker
```

后续逐步进入：

```text
Observability
Tracing
Evaluation
Guardrails
MCP
Multi-Agent
Handoff
Planning
Enterprise Integration
完整项目
```

## 新 Chat 交接提示词

新开聊天后，可以直接让 ChatGPT 读取本文件，然后发送：

> 这是我的 Day 1–20 学习记录。我正在进行 AI Agent 60 天课程，请从 Day 21 继续。保持之前的学习方式：一点理论 → 提问让我回答 → 写代码 → 我提交 GitHub → 你做 Code Review。不要一次灌输太多内容，重点训练企业 Agent 架构思维。
