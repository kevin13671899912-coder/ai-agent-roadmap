# Day 21–30 Summary — Agent Runtime Reliability & LangGraph Integration

这一阶段的核心目标，是把一个“能调用 Tool 的 Agent”逐步升级成一个**具备生产级可靠性边界的 Agent Runtime**。

从 Day21 开始，我们不再只关注 LangGraph 的图结构，而是开始处理真实系统里更麻烦的问题：重试风暴、截止时间、熔断、并发隔离、错误归一化、统一结果协议、策略决策，以及最后如何把这些能力重新接回 LangGraph。

最终形成的核心原则是：

> **LangGraph 负责 Workflow / 业务编排，ToolRuntime 负责 Tool 执行生命周期。**

---

## 1. 总体架构演进

最开始的 Agent 很容易写成：

```text
LangGraph Node
↓
直接调用 API / Tool
↓
自己判断 503 / Retry / Timeout / Fallback
```

问题是：一旦 Tool 越来越多，Node 会不断塞入 Retry、Breaker、Bulkhead、Timeout、Deadline 等逻辑，导致业务编排和可靠性策略强耦合。

Day21–30 逐步演进成：

```text
Agent / LangGraph
        ↓
     Tool Node
        ↓
    ToolRuntime
        ↓
 ┌─────────────────────┐
 │ Tool Registry       │
 │ Retry / Backoff     │
 │ Deadline / Timeout  │
 │ Circuit Breaker     │
 │ Bulkhead            │
 │ Error Normalizer    │
 │ Policy Engine       │
 │ Idempotency         │
 └─────────────────────┘
        ↓
     Real Tool / API
        ↓
     ToolResult
```

核心设计思想：

```text
高内聚：
Runtime 内聚 Tool 执行与可靠性策略

低耦合：
Graph 不理解 HTTP 503、429、Breaker OPEN、Bulkhead FULL 等底层细节
```

---

# Day21 — Exponential Backoff + Jitter

Retry 不等于失败后立刻再试。大量请求同时失败并同步重试，会产生 Retry Storm / Thundering Herd。

指数退避：

```python
backoff = base_delay * (2 ** retry_count)
```

Jitter 用来打散重试时间：

```python
delay = random.uniform(0, max_backoff)
```

核心理解：

```text
Retry = 要不要再试
Backoff = 什么时候再试
Jitter = 不要大家同一时间再试
```

工程上应注入 `random_fn`、`sleep_fn`，方便 deterministic test。

---

# Day22 — Timeout / Deadline / Cancellation

三个概念：

```text
Timeout = 单次操作最长执行多久
Deadline = 整个 Workflow 最晚什么时候结束
Cancellation = 当前请求已经没有继续执行的意义
```

典型 Retry 决策顺序：

```text
Call failed
↓
cancelled?
├ YES → CANCELLED
↓
retryable?
├ NO → FATAL_ERROR
↓
retry budget?
├ NO → FALLBACK
↓
enough deadline budget?
├ NO → DEADLINE_EXCEEDED
↓
Backoff + Jitter
↓
Retry
```

Deadline 预算应至少包含：

```python
required_budget = backoff + request_timeout + safety_margin
```

写操作 Timeout 时可能已经在服务端成功，因此 Retry 必须保留相同 `idempotency_key`。

---

# Day23 — Circuit Breaker

Retry 是 request-level；Circuit Breaker 是 shared service-level protection。

```text
CLOSED
  ↓ failures threshold
OPEN
  ↓ cooldown
HALF_OPEN
  ├ success → CLOSED
  └ failure → OPEN
```

Breaker 应是共享 Runtime / Service State，而不是每个 AgentState 一份。

HALF_OPEN 通常只允许一个或少量 Probe，生产环境需要 semaphore / lock / Redis atomic primitive。

---

# Day24 — Retry + Deadline + Circuit Breaker Composition

这一课最重要的是策略所有权。

**Circuit Breaker 只负责新 Workflow 的 admission gate。**

```text
START
↓
Circuit Breaker Gate
↓
Workflow admitted
```

如果一个 Workflow 在 Breaker CLOSED 时已经进入，第一次调用失败并把 Breaker 打成 OPEN，这个已经被允许进入的 Workflow 仍可以继续自己的 Retry Policy。

新的 Workflow 则：

```text
Breaker OPEN
→ FAST_FAIL / FALLBACK
```

核心：

> **Breaker OPEN ≠ 当前已经进入的 Workflow 必须立即停止。**

Retry 路径不能重新进入 Breaker Gate：

```text
Breaker Gate
↓
call API
↓
Policy
↓
Retry Wait
↓
call API
```

HALF_OPEN Probe 是例外，通常一次 Probe 即决定 CLOSED / OPEN，不走普通多 Retry。

---

# Day25 — Bulkhead / Concurrency Control

Circuit Breaker 无法解决“服务没失败，只是很慢”的资源占用问题。

Bulkhead 限制同时进入某个 dependency 的请求数量：

```text
HR API Pool      max=10
Search API Pool  max=30
Email API Pool   max=5
```

区别：

```text
Circuit Breaker = 这个服务健康吗？
Bulkhead = 即使健康，我允许多少请求同时使用它？
```

推荐顺序：

```text
Circuit Breaker Gate
↓
Bulkhead Acquire
↓
Tool Call
```

Bulkhead Full 不应记录为 Breaker Failure，因为根本没有实际调用 downstream。

每次 Retry 都重新 acquire / release：

```text
attempt 1: acquire → call → release
backoff
attempt 2: acquire → call → release
```

不要在 Backoff 期间占着 slot。

成功 acquire 后必须使用 `finally` release，防止 Slot Leak。

---

# Day26 — Tool Execution Runtime

Day21–25 的可靠性机制不应该散落在每个 LangGraph Node 中，于是抽象出统一 ToolRuntime。

核心原则：

> **Node 负责业务编排，Runtime 负责 Tool 执行策略。**

ToolRegistry：

```python
registry = {
    "hr_tool": ToolConfig(...),
    "search_tool": ToolConfig(...),
}
```

每个 Tool 有自己的独立 Policy：

```text
HR Tool → HR Breaker → HR Bulkhead → HR Retry
Search Tool → Search Breaker → Search Bulkhead → Search Retry
```

Read Tool 和 Write Tool 可以复用同一个 Runtime 机制，但策略不同。写操作必须重视 Idempotency。

`idempotency_key` 在一次 `execute()` 开始时生成一次，并在所有 Retry 中复用。

---

# Day27 — Tool Error Taxonomy / Error Normalization

底层 Tool 错误来源很多：

```text
503 / 429 / 400
TimeoutError
ConnectionError
RuntimeError
Bulkhead Full
```

通过 Error Normalizer 统一成 `ToolError`：

```python
class ErrorKind(Enum):
    RETRYABLE = "retryable"
    NON_RETRYABLE = "non_retryable"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    OVERLOADED = "overloaded"
    CANCELLED = "cancelled"
    INTERNAL = "internal"
```

```python
@dataclass
class ToolError:
    kind: ErrorKind
    message: str
    retryable: bool
    status_code: int | None = None
    retry_after: float | None = None
```

典型映射：

```text
429 → RATE_LIMITED
500/502/503/504 → RETRYABLE
408 / TimeoutError → TIMEOUT
400/401/403/404/422 → NON_RETRYABLE
Bulkhead Rejected → OVERLOADED
RuntimeError / unknown → INTERNAL
```

核心区别：

```text
Error 是什么
≠
Policy 应该怎么处理
```

还留下一个后续重点：

```text
retryable ≠ affects_breaker
```

例如 400 通常不应该影响 downstream health。

---

# Day28 — Structured Tool Result / Result Envelope

Runtime 不应该给 Graph 返回一堆不同 shape 的 dict，例如 SUCCESS / FAST_FAIL / BULKHEAD_REJECTED 等。

统一成：

```python
@dataclass
class ToolResult:
    ok: bool
    tool_name: str
    data: Any = None
    error: ToolError | None = None
    attempts: int = 0
    latency_ms: float = 0.0
```

成功和失败都使用同一个结果协议。

核心原则：

> **ToolRuntime 对下屏蔽底层 Tool 差异，对上提供稳定协议。**

业务 Node 自己解释 `data` 的业务含义，Runtime 不应知道 `employee`、`items` 等业务字段。

---

# Day29 — Policy Decision Object / Policy Engine

进一步把：

```text
发生了什么
```

和：

```text
应该怎么办
```

分离。

架构：

```text
ToolError
↓
PolicyEngine
↓
PolicyDecision
↓
ToolRuntime 执行动作
```

```python
class PolicyAction(Enum):
    RETRY = "retry"
    FAIL = "fail"
    FALLBACK = "fallback"
    CANCEL = "cancel"
    RATE_LIMIT_WAIT = "rate_limit_wait"
    DEADLINE_EXCEEDED = "deadline_exceeded"
```

```python
@dataclass
class PolicyDecision:
    action: PolicyAction
    delay: float = 0.0
    reason: str = ""
```

核心原则：

```text
ToolError = 发生了什么？
PolicyDecision = 应该怎么办？
ToolRuntime = 把决定执行掉
```

PolicyEngine 应尽量接近纯函数：只接受错误和上下文，输出 Decision，不调用 Tool、不碰 Breaker、不 acquire Bulkhead。

---

# Day30 — LangGraph × ToolRuntime Integration

Day30 把 Runtime 真正接回 LangGraph，并验证职责边界。

推荐结构：

```text
START
↓
execute_tool
↓
route_tool_result
├ SUCCESS  → answer → END
├ FALLBACK → fallback → END
└ FAILURE  → error_handler → END
```

Tool Node 保持非常薄：

```python
def execute_tool_node(state):
    result = runtime.execute(
        tool_name=state["tool_name"],
        args=state["tool_args"],
        deadline=state["deadline"],
    )
    return {"tool_result": result}
```

最重要的边界：

如果 HR Tool：

```text
第一次 → 503
Runtime 自动 Retry
第二次 → 200
```

LangGraph 不应该看到第一次 503，也不应该负责 Retry。

Graph 最终只看到：

```python
ToolResult(
    ok=True,
    tool_name="hr_tool",
    attempts=2,
)
```

因此：

```text
503 / 429 / Retry / Timeout / Breaker / Bulkhead
= Runtime concern

SUCCESS / FALLBACK / FAILURE
= Workflow concern
```

最终职责边界：

```text
LangGraph
= Workflow / 业务编排

Tool Node
= 调用 Runtime

Router
= 根据最终 ToolResult 路由

ToolRuntime
= Tool 执行生命周期

PolicyEngine
= Retry / Deadline 等策略决策
```

---

# 2. Day21–30 最终架构

```text
User Request
    ↓
LangGraph / Agent Workflow
    ↓
Tool Node
    ↓
ToolRuntime.execute()
    ↓
┌──────────────────────────────────┐
│ Tool Registry                    │
│                                  │
│ Circuit Breaker Admission Gate   │
│          ↓                       │
│ Bulkhead Acquire                 │
│          ↓                       │
│ Real Tool Call                   │
│          ↓                       │
│ Bulkhead Release                 │
│          ↓                       │
│ Error Normalizer                 │
│          ↓                       │
│ ToolError                        │
│          ↓                       │
│ PolicyEngine                     │
│          ↓                       │
│ PolicyDecision                   │
│          ↓                       │
│ Retry / Wait / Fail              │
│                                  │
│ + Deadline                       │
│ + Timeout                        │
│ + Idempotency                    │
└──────────────────────────────────┘
    ↓
ToolResult
    ↓
LangGraph Router
    ├ SUCCESS
    ├ FALLBACK
    └ FAILURE
```

---

# 3. 最重要的工程原则

## ① 高内聚，低耦合

```text
Graph → Workflow
Runtime → Tool execution
PolicyEngine → Decision
Normalizer → Error translation
```

不要把所有逻辑堆在一个 Node / Runtime / Router 中。

## ② Retry 和 Breaker 是不同层级

```text
Retry = 当前请求还能不能再试
Breaker = downstream 整体还值不值得继续接新请求
```

## ③ 没调用 Downstream，不算 Downstream Failure

典型：

```text
Bulkhead Full
Circuit Breaker OPEN fast-fail
```

不能简单等同于实际 API failure。

## ④ 不要持有稀缺资源等待 Backoff

```text
Acquire → Call → Release → Backoff
```

而不是：

```text
Acquire → Call → Backoff → Release
```

## ⑤ 写操作 Retry 必须考虑幂等

```text
Timeout ≠ 服务端一定失败
```

因此同一逻辑操作的 Retry 必须复用同一个 Idempotency Key。

## ⑥ Graph 不负责 Tool Reliability

LangGraph 应关心：

```text
业务流程接下来去哪
```

而不是：

```text
HTTP 503 怎么 Retry
429 应该 Sleep 多久
Breaker 是否 OPEN
Bulkhead 是否满
```

---

# 4. 阶段结论

Day21–30 完成了从：

```text
“LangGraph Node 直接调用 Tool”
```

到：

```text
“LangGraph 负责 Agent Workflow，ToolRuntime 负责可靠的 Tool Execution”
```

的架构升级。

这一阶段最终建立的不是某一个框架技巧，而是一套 Agent Runtime 的职责边界：

> **让 LLM / Agent 决定业务意图，让 LangGraph 组织 Workflow，让 Runtime 管理可靠执行，让 Policy 管理工程约束。**

下一阶段可以开始进入 Multi-Tool Agent / Tool Selection，让 LLM 选择“调用哪个 Tool”，同时继续保持：

```text
LLM 可以决定 Tool
但不应该随意决定 Retry / Timeout / Breaker 等生产可靠性 Policy
```
