# Day1–20 阶段总结 — LangGraph / Agent Workflow 基础到可靠性入口

这一阶段的目标，是从“会调用模型”进化到“会设计一个可控、可维护、可恢复的 Agent Workflow”。

核心主线可以概括为：

```text
LLM 调用
↓
State
↓
Node
↓
Router
↓
Graph
↓
Tool / RAG
↓
错误处理
↓
Retry / Fallback / Idempotency
```

最重要的设计思想始终是：

> **高内聚、低耦合：Node 负责单一职责，Router 只负责路由，State 只保存 Workflow 真正需要共享的数据。**

---

# 1. Day1–5：从 LLM 调用到 Graph 思维

前几天的核心不是 LangGraph API，而是理解：

```text
Agent ≠ 一个大函数
Agent = 一组节点 + 状态 + 路由 + 执行顺序
```

## State — 状态

State 是节点之间共享的数据协议。

例如：

```python
class AgentState(TypedDict):
    query: str
    context: str
    answer: str
```

它不是“什么都往里面塞”的全局变量。

正确原则：

```text
State 保存跨 Node 需要共享的信息
局部变量留在 Node 内部
基础设施共享状态不要塞进单个 Workflow State
```

## Node — 节点

Node 应该负责一个清晰任务：

```text
retrieve_node
llm_node
tool_node
validate_node
fallback_node
```

不要写成：

```text
一个 Node 里：
查数据
调模型
判断错误
重试
fallback
生成最终回答
```

否则维护和测试都会越来越困难。

## Edge — 边

Edge 表示固定的执行关系：

```text
A → B
```

## Conditional Edge — 条件边

根据 Router 的返回值决定下一步：

```text
Router
├ SUCCESS → answer
├ RETRY → retry
└ FAILURE → fallback
```

---

# 2. Day6–10：Router / Branch / Workflow 控制

这一阶段开始理解“Graph 真正的价值不是画流程图，而是显式控制流程”。

## Router — 路由器

Router 的职责：

```text
读取当前 State
↓
做判断
↓
返回 route key
```

例如：

```python
def router(state):
    if state["score"] >= 0.8:
        return "GOOD"
    return "RETRY"
```

Router 不应该顺便去执行 Tool 或修改一堆业务状态。

核心原则：

> **Router 负责决定去哪，不负责在那里做什么。**

## Graph 的可视化价值

当流程逐渐复杂：

```text
START
↓
retrieve
↓
quality_check
├ GOOD → answer
└ BAD → rewrite_query → retrieve
```

相比巨大的 `if / elif / while`，Graph 的流程边界更容易观察、测试和扩展。

---

# 3. Day11–15：Tool / RAG / Agent Workflow 组合

这一阶段开始把外部能力接进 Agent。

## Tool — 工具

Tool 是 Agent 能调用的外部能力，例如：

```text
Search API
HR API
Database
Calculator
Email Service
```

Agent 的核心价值不只是生成文本，而是：

```text
理解任务
↓
选择/调用能力
↓
读取结果
↓
继续决策
```

## RAG — Retrieval-Augmented Generation

中文：**检索增强生成**。

基本结构：

```text
User Query
↓
Retriever 检索资料
↓
Context
↓
LLM
↓
Answer
```

核心目的：

```text
让回答基于外部资料，而不只依赖模型参数记忆
```

RAG Workflow 常见节点：

```text
query
↓
retrieve
↓
check relevance
├ relevant → answer
└ irrelevant → rewrite / fallback
```

---

# 4. Day16–19：异常路径、恢复路径、状态设计

真正的 Agent 不只要设计 Happy Path。

还必须考虑：

```text
Tool 失败怎么办？
RAG 查不到怎么办？
LLM 输出不合法怎么办？
某个 Node 抛异常怎么办？
```

因此 Workflow 会逐渐从：

```text
START → A → B → END
```

升级为：

```text
START
↓
A
↓
B
├ SUCCESS → END
├ RETRY → A
└ FAILURE → FALLBACK → END
```

## Fallback — 降级 / 备用路径

Fallback 不是简单等于“报错”。

它表示：

```text
主路径不可用
↓
换一个成本更低 / 能力较弱 / 数据较旧但仍可用的方案
```

例如：

```text
实时 HR API 挂了
→ 返回缓存数据

外部 Search 挂了
→ 使用本地知识库

主模型不可用
→ 使用备用模型
```

核心思想：

> **失败不一定意味着整个 Workflow 必须崩溃。**

---

# 5. Day20：Retry / Fallback / Idempotency

Day20 是前 20 天从“Workflow 编排”迈向“Production Runtime”的入口。

## Retry — 重试

失败后再次尝试。

适合：

```text
503
网络抖动
临时 Timeout
```

不适合：

```text
400 参数错误
权限错误
确定性的业务错误
```

## Fallback — 降级

当 Retry 不值得继续或已经耗尽预算时：

```text
Retry exhausted
↓
Fallback
```

## Idempotency — 幂等性

同一个业务操作重复执行，不应该重复产生副作用。

尤其重要于：

```text
付款
创建订单
审批
发送邮件
写数据库
```

经典问题：

```text
客户端 Timeout
↓
服务器其实已经执行成功
↓
客户端 Retry
↓
重复执行
```

解决方法之一：

```text
Idempotency Key（幂等键）
```

同一个逻辑请求的所有 Retry 必须复用同一个 Key。

---

# 6. Day1–20 最重要的架构原则

## 原则 1：高内聚、低耦合

```text
Node 做一件事
Router 只路由
State 只保存需要共享的 Workflow 数据
```

## 原则 2：业务逻辑和基础设施逻辑分开

不要让每一个业务 Node 都自己实现：

```text
Retry
Timeout
Fallback
错误分类
```

Day21 以后正是进一步解决这个问题。

## 原则 3：Happy Path 不够

生产 Agent 必须设计：

```text
SUCCESS
FAILURE
RETRY
FALLBACK
CANCEL
TIMEOUT
```

## 原则 4：不要让 Router 变成万能函数

正确：

```text
Router = Decide Where
Node = Do Work
```

## 原则 5：Graph State 不是垃圾桶

不要把所有内部变量都放进 AgentState。

State 应该代表 Workflow 级数据，而不是所有组件的内部实现。

---

# 7. 高频自测题

### Q1：Node 和 Router 最大区别是什么？

**Node 做事情，Router 决定下一步去哪。**

### Q2：为什么不把整个 Agent 写成一个大函数？

因为会导致职责混杂、难测试、难扩展、难观察，也很难单独处理失败和恢复路径。

### Q3：State 是全局变量吗？

不是。State 是 Workflow 节点之间的数据契约。

### Q4：Fallback 和 Retry 有什么区别？

```text
Retry = 继续尝试同一个能力
Fallback = 换备用能力/备用路径
```

### Q5：什么错误适合 Retry？

通常是临时性错误，例如网络抖动、503、部分 Timeout。

### Q6：400 应该无限 Retry 吗？

不应该。400 通常代表请求本身有问题，重复同样请求通常不会成功。

### Q7：为什么写操作 Retry 要特别小心？

因为第一次调用可能已经在服务端成功，只是客户端没收到结果，Retry 会产生重复副作用。

### Q8：什么是 Idempotency Key？

用于标识同一个逻辑操作的唯一 Key，让服务端识别重复请求。

### Q9：Graph 的价值只是可视化吗？

不是。更重要的是把状态流转、分支、恢复路径和执行边界显式化。

### Q10：Day1–20 和 Day21–30 最大区别是什么？

```text
Day1–20：
重点是 Agent Workflow / LangGraph 编排

Day21–30：
重点是 Tool Runtime / Production Reliability
```

---

# 8. 从 Day20 到 Day21 的关键转折

Day20 以后问题从：

```text
“失败了要不要 Retry？”
```

升级成：

```text
什么时候 Retry？
Retry 等多久？
整个 Workflow 还有多少时间？
服务整体是否已经不健康？
并发是不是已经满了？
错误到底属于什么类型？
这些策略应该由谁负责？
```

这就是 Day21–30 Agent Runtime 阶段的起点。
