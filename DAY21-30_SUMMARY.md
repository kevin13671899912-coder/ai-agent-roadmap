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

## 核心问题

Retry 不是简单地“失败就立即再试”。

如果大量请求同时失败并立即重试，很容易产生：

```text
Retry Storm / Thundering Herd
```

例如 1000 个请求同时遇到 503：

```text
1000 requests fail
↓
immediate retry
↓
1000 requests again
↓
downstream 更加过载
```

## Backoff

指数退避：

```python
backoff = base_delay * (2 ** retry_count)
```

例如：

```text
retry 0 → 1s
retry 1 → 2s
retry 2 → 4s
retry 3 → 8s
```

## Jitter

如果大家都严格按照 1、2、4、8 秒重试，仍然会同步撞上 downstream。

因此加入随机抖动：

```python
delay = random.uniform(0, max_backoff)
```

核心理解：

```text
Retry = 要不要再试
Backoff = 什么时候再试
Jitter = 不要大家同一时间再试
```

## 工程原则

为了可测试性，应注入：

```python
random_fn
sleep_fn
```

避免测试真正 sleep，也避免随机值导致测试不稳定。

---

# Day22 — Timeout / Deadline / Cancellation

这一课开始区分三个经常混淆的概念。

## Timeout

单次操作最长允许执行多久。

```text
一次 HTTP 请求最多 2 秒
```

## Deadline

整个 Workflow 最晚什么时候必须结束。

```text
整个 Agent 请求最多 10 秒
```

## Cancellation

请求已经没有意义，需要停止继续执行。

例如：

```text
用户关闭页面
上游取消请求
业务任务被撤销
```

## Retry 判断顺序

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

Deadline 不能只判断当前还有没有时间，而要判断：

```python
required_budget = backoff + request_timeout + safety_margin

if remaining_budget < required_budget:
    return DEADLINE_EXCEEDED
```

因为 Retry 不只是 sleep，还必须给下一次实际请求预留时间。

## 写操作特别注意

如果 Tool 是写操作：

```text
Approve
Payment
Order
Send Email
```

请求 Timeout 并不代表服务器没有成功执行。

因此 Retry 时必须保留同一个：

```text
idempotency_key
```

---

# Day23 — Circuit Breaker

Retry 解决的是**当前请求**的问题。

Circuit Breaker 解决的是**整个 downstream 服务健康度**的问题。

## 三个状态

```text
CLOSED
  ↓ failures threshold
OPEN
  ↓ cooldown
HALF_OPEN
  ├ success → CLOSED
  └ failure → OPEN
```

### CLOSED

正常放行请求。

### OPEN

服务被认为不健康，新请求快速失败，不再继续压 downstream。

### HALF_OPEN

Cooldown 后允许少量 Probe 检查服务是否恢复。

## 关键设计

Breaker 是共享的 service/runtime state：

```text
HR API Breaker
Search API Breaker
Email API Breaker
```

不能放到单个 `AgentState` 中。

因为 Breaker 描述的是：

```text
“这个服务整体健康吗？”
```

而不是：

```text
“这个 Workflow 当前发生了什么？”
```

## HALF_OPEN Probe

HALF_OPEN 一般只允许一个或极少数 probe。

生产环境需要：

```text
lock / semaphore / Redis atomic operation
```

防止几百个请求一起成为 probe。

---

# Day24 — Retry + Deadline + Circuit Breaker Composition

Day24 最重要的不是新增组件，而是**确定策略所有权和执行顺序**。

## 最重要的架构决定

Circuit Breaker 只负责**新 Workflow 的 admission gate**。

```text
START
↓
Circuit Breaker Gate
↓
Workflow admitted
```

如果一个 Workflow 在 Breaker CLOSED 时已经进入：

```text
first call → 503
↓
这个失败让 Breaker OPEN
↓
当前 Workflow 仍然可以按自己的 Retry Policy 继续
```

但是此时新的 Workflow：

```text
new request
↓
Breaker OPEN
↓
FAST_FAIL / FALLBACK
```

核心结论：

> **Breaker OPEN ≠ 当前已经进入的 Workflow 必须立即停止。**

## Retry 不重新经过 Breaker Gate

正确：

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

错误：

```text
Retry Wait
↓
Breaker Gate
↓
call API
```

否则 Breaker 会“吃掉”当前 Workflow 本来拥有的 Retry Policy。

## HALF_OPEN 例外

HALF_OPEN Probe 是特殊请求：

```text
Probe success → CLOSED
Probe failure → OPEN
```

通常不应该进入普通多次 Retry 循环。

---

# Day25 — Bulkhead / Concurrency Control

Breaker 解决不了一个情况：

```text
服务没有失败
只是变得很慢
```

例如：

```text
HR API 正常：100ms
现在：8s
```

如果同时来了 1000 个 Workflow：

```text
线程
连接池
内存
CPU
下游连接
```

都可能被拖死。

## Bulkhead

Bulkhead 限制同时允许多少请求进入某个 dependency。

```text
HR API Pool      max=10
Search API Pool  max=30
Email API Pool   max=5
```

区别：

```text
Circuit Breaker
= “这个服务健康吗？”

Bulkhead
= “即使它健康，我最多允许多少请求同时使用它？”
```

因此完全可能：

```text
Breaker = CLOSED
Bulkhead = FULL
```

## 顺序

```text
Circuit Breaker Gate
↓
Bulkhead Acquire
↓
Tool Call
```

如果 Breaker OPEN：

```text
直接 FAST_FAIL
```

不应该占着 Bulkhead slot 等待。

## Bulkhead Full 是否算 Breaker Failure？

答案：**不算。**

因为：

```text
没有真正调用 downstream
```

所以：

> **No actual downstream call => do not record downstream failure.**

## Retry 时 Bulkhead 的规则

每次 Attempt 都必须重新 acquire：

```text
attempt 1
acquire → call → release

backoff

attempt 2
acquire → call → release
```

绝对不要：

```text
acquire
↓
call fails
↓
backoff while holding slot
```

否则 Retry 会长期占用有限资源。

## Slot Leak

成功 acquire 后，无论：

```text
Success
HTTP Error
Exception
Timeout
Cancellation
```

都必须 release。

实际代码应使用：

```python
try:
    call_tool()
finally:
    bulkhead.release()
```

---

# Day26 — Tool Execution Runtime

Day21–25 的策略如果继续散落在 LangGraph Node 中，会严重重复。

因此 Day26 开始抽象：

```text
ToolRuntime
```

核心原则：

> **Node 负责业务编排，Runtime 负责 Tool 执行策略。**

## Tool Registry

不要写：

```python
if tool_name == "hr_tool":
    ...
elif tool_name == "search_tool":
    ...
```

而是：

```python
registry = {
    "hr_tool": ToolConfig(...),
    "search_tool": ToolConfig(...),
}
```

最终：

```text
Tool Name
↓
Registry
↓
ToolConfig
↓
ToolRuntime
```

## 每个 Tool 独立 Policy

```text
HR Tool
→ HR Breaker
→ HR Bulkhead
→ HR Retry Config

Search Tool
→ Search Breaker
→ Search Bulkhead
→ Search Retry Config
```

不能让 HR 挂掉导致 Search 一起被熔断。

这正是：

```text
高内聚 + 低耦合
```

## Read vs Write

Runtime 机制可以统一，但 Policy 不应该完全一样。

```text
Search Read
→ 通常更安全 Retry

HR Write
→ 有 Side Effect
→ 必须关注 Idempotency
```

重要：

```python
idempotency_key
```

必须在 `execute()` 开始时生成一次，然后所有 Retry 复用。

不能每次 retry：

```python
uuid.uuid4()
```

否则幂等失效。

---

# Day27 — Tool Error Taxonomy / Error Normalization

现实 Tool 的错误形式很乱：

```text
HTTP 503
HTTP 429
HTTP 400
TimeoutError
ConnectionError
RuntimeError
Bulkhead Full
```

如果 Runtime 到处写 provider-specific 判断，会越来越难维护。

因此加入：

```text
Raw Error
↓
Error Normalizer
↓
ToolError
```

## ErrorKind

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

## ToolError

```python
@dataclass
class ToolError:
    kind: ErrorKind
    message: str
    retryable: bool
    status_code: int | None = None
    retry_after: float | None = None
```

## Mapping

```text
429
→ RATE_LIMITED

500 / 502 / 503 / 504
→ RETRYABLE

408 / TimeoutError
→ TIMEOUT

400 / 401 / 403 / 404 / 422
→ NON_RETRYABLE

Bulkhead Rejected
→ OVERLOADED

RuntimeError / unknown exception
→ INTERNAL
```

这里形成一个非常重要的区分：

```text
Error 是什么
≠
Policy 应该怎么处理
```

同时还留下一个后续优化：

```text
retryable
≠
affects_breaker
```

例如：

```text
400
→ 不可重试
→ 但通常也不代表 downstream 不健康
```

未来可以增加：

```python
affects_breaker: bool
```

---

# Day28 — Structured Tool Result / Result Envelope

虽然错误已经标准化，但如果 Runtime 仍然返回：

```text
SUCCESS
FAST_FAIL
BULKHEAD_REJECTED
FATAL_ERROR
MAX_RETRIES_EXCEEDED
DEADLINE_EXCEEDED
```

上层 Graph 仍然必须了解 Runtime 的大量内部状态。

于是引入统一返回协议：

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

成功：

```python
ToolResult(
    ok=True,
    tool_name="hr_tool",
    data=raw_result,
    error=None,
    attempts=2,
)
```

失败：

```python
ToolResult(
    ok=False,
    tool_name="hr_tool",
    error=tool_error,
    attempts=2,
)
```

## Runtime 不理解业务 Data

例如 HR：

```python
{"employee": {...}}
```

Search：

```python
{"items": [...]}
```

Runtime 只应该：

```python
data=raw_result
```

而不是：

```python
if hr_tool:
    employee = ...
if search_tool:
    items = ...
```

因为业务数据含义属于业务 Node。

核心原则：

> **ToolRuntime 对下屏蔽底层 Tool 差异，对上提供稳定协议。**

---

# Day29 — Policy Decision Object / Policy Engine

到了 Day28，Error 和 Result 已经结构化，但 Runtime 里面仍然充满：

```python
if not retryable:
    ...
if retry_count >= max_retries:
    ...
if deadline ...:
    ...
```

因此继续拆分：

```text
ToolError
↓
PolicyEngine
↓
PolicyDecision
↓
ToolRuntime 执行决定
```

## PolicyAction

```python
class PolicyAction(Enum):
    RETRY = "retry"
    FAIL = "fail"
    FALLBACK = "fallback"
    CANCEL = "cancel"
    RATE_LIMIT_WAIT = "rate_limit_wait"
    DEADLINE_EXCEEDED = "deadline_exceeded"
```

## PolicyDecision

```python
@dataclass
class PolicyDecision:
    action: PolicyAction
    delay: float = 0.0
    reason: str = ""
```

## 核心区分

```text
ToolError
= 发生了什么？

PolicyDecision
= 应该怎么办？

ToolRuntime
= 把这个决定执行掉
```

例如：

```text
503
↓
ToolError(RETRYABLE)
↓
PolicyEngine
↓
PolicyDecision(RETRY, delay=...)
```

429：

```text
RATE_LIMITED
↓
优先 retry_after
↓
RATE_LIMIT_WAIT
```

## Pure Policy

PolicyEngine 不应该：

```text
调用 Tool
Acquire Bulkhead
修改 Breaker
Sleep
修改 AgentState
```

它最好尽量接近纯函数：

```text
输入：Error + Policy Context
输出：Decision
```

这样非常容易单元测试。

后续优化：把 `random_fn` 也注入，做到 deterministic test。

---

# Day30 — LangGraph × ToolRuntime Integration

Day30 把前面 9 天造出来的 Runtime 重新接回 LangGraph。

最终目标：

> **LangGraph 不再关心 Retry、503、429、Breaker、Bulkhead 等底层执行细节。**

Graph：

```text
START
  ↓
execute_tool
  ↓
route_tool_result
 ├ SUCCESS  → answer
 ├ FALLBACK → fallback
 └ FAILURE  → error_handler
                ↓
               END
```

Tool Node 应该非常薄：

```python
def execute_tool_node(state):
    result = runtime.execute(
        tool_name=state["tool_name"],
        args=state["tool_args"],
        deadline=state["deadline"],
    )

    return {
        "tool_result": result
    }
```

Router 只看最终 `ToolResult`：

```text
ToolResult.ok = True
→ SUCCESS

ToolResult.error = overloaded / timeout / etc.
→ FALLBACK

Non-retryable / terminal failure
→ FAILURE
```

## 最关键的例子

HR Tool：

```text
第一次 → 503
Runtime → Retry
第二次 → 200
```

LangGraph **不应该看到第一次 503**。

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
503
不是 Graph Event

最终 ToolResult
才是 Graph Event
```

---

# 2. Day21–30 最终职责边界

经过这一阶段，可以把系统责任划分成四层。

## LangGraph

负责：

```text
Workflow
业务流程
Tool 选择后的编排
Success / Fallback / Failure 路由
```

不负责：

```text
503 Retry
429 retry_after
Backoff
Jitter
Breaker internals
Bulkhead counters
HTTP-specific details
```

---

## Tool Node

负责：

```text
把 Graph State 转换成 Runtime 调用
把 ToolResult 写回 State
```

尽量薄。

---

## ToolRuntime

负责：

```text
Breaker Gate
Bulkhead Acquire / Release
Real Tool Call
Error Normalize
Policy Decision Execution
Retry Lifecycle
Deadline
Idempotency
Result Envelope
```

---

## PolicyEngine

负责：

```text
根据 ToolError + Policy Context
决定下一步动作
```

例如：

```text
RETRY
FAIL
RATE_LIMIT_WAIT
DEADLINE_EXCEEDED
```

不执行 Side Effect。

---

# 3. 最终执行流程

一个完整 Tool 调用现在可以表示为：

```text
LangGraph
↓
Tool Node
↓
ToolRuntime.execute()
↓
Circuit Breaker Gate
├ OPEN → ToolResult(Failure)
↓ ALLOW
Bulkhead Acquire
├ FULL → ToolResult(Overloaded)
↓ ACQUIRED
Real Tool Attempt
↓
Bulkhead Release
↓
Success?
├ YES → ToolResult(ok=True)
↓ NO
Normalize Error
↓
ToolError
↓
PolicyEngine.decide()
↓
PolicyDecision
├ FAIL → ToolResult(ok=False)
├ DEADLINE_EXCEEDED → ToolResult(ok=False)
├ RETRY
└ RATE_LIMIT_WAIT
      ↓
    Wait
      ↓
Bulkhead Acquire Again
      ↓
Next Attempt
```

注意：普通 Retry **不会重新经过 Circuit Breaker Gate**。

---

# 4. 最重要的设计原则

这一阶段最值得保留的不是某个具体代码，而是下面这些架构原则。

### 1. Retry 和 Breaker 的职责不同

```text
Retry = 当前 Workflow 还能不能再试
Breaker = 新请求是否还应该进入这个 dependency
```

### 2. Deadline 是整个 Workflow 的预算

Retry 前必须考虑：

```text
Backoff + 下一次请求 Timeout + Safety Margin
```

### 3. Bulkhead 保护容量

```text
Breaker 健康
≠
无限并发
```

### 4. 没真正调用 downstream，就不应该记录 downstream failure

例如：

```text
Breaker OPEN
Bulkhead FULL
```

都不能直接当成实际 API Failure。

### 5. 每次 Retry 都重新 Acquire Bulkhead

不能在 Backoff 时长期占用 slot。

### 6. Idempotency Key 必须跨 Retry 保持一致

尤其是写操作。

### 7. Error 与 Action 分离

```text
ToolError = 事实
PolicyDecision = 动作
```

### 8. Runtime 与业务数据分离

Runtime 不理解：

```text
employee
items
order
payment
```

它只返回统一 `ToolResult.data`。

### 9. Graph 与 Reliability 分离

```text
Graph = Workflow
Runtime = Reliability
```

这是 Day21–30 最核心的结论。

---

# 5. 当前仍保留的工程债

这些不影响当前架构成立，但后续可以继续升级。

## 真正的 Request Timeout

当前很多实现里的 `timeout` 主要参与 Deadline Budget 计算。

生产环境还需要真正中断 Tool Call，例如：

```text
asyncio.wait_for
HTTP client timeout
future timeout
process isolation
```

## Deterministic Testing

建议注入：

```text
clock_fn
sleep_fn
random_fn
```

避免测试依赖真实时间和随机数。

## Breaker Failure Classification

未来可让：

```python
ToolError.affects_breaker
```

明确表示某种错误是否应该影响 Breaker Health。

例如：

```text
503 → true
400 → false
Bulkhead Full → false
```

## Circuit Open 与 Overloaded 分离

当前可以共用 `OVERLOADED`，但更成熟的 Error Taxonomy 可以进一步拆分：

```text
CIRCUIT_OPEN
OVERLOADED
```

这样 observability 和 routing 会更准确。

## Production Bulkhead

Notebook 的计数器适合理解概念，但生产环境需要原子并发控制：

```text
threading.Semaphore
asyncio.Semaphore
Redis distributed semaphore
```

---

# 6. Day21–30 一句话回顾

```text
Day21  Backoff + Jitter
       → Retry 不要制造 Retry Storm

Day22  Timeout / Deadline / Cancellation
       → Retry 受次数预算和时间预算约束

Day23  Circuit Breaker
       → 保护不健康的 dependency

Day24  Policy Composition
       → Breaker Gate 与 Workflow Retry 正确组合

Day25  Bulkhead
       → 保护并发容量，防止慢服务拖垮系统

Day26  Tool Runtime
       → 把 Reliability 从 Node 抽到统一 Runtime

Day27  Error Taxonomy
       → Raw Error 统一成 ToolError

Day28  ToolResult
       → Runtime 对上提供稳定返回协议

Day29  PolicyDecision
       → Error 与执行动作彻底解耦

Day30  LangGraph Integration
       → Graph 只负责 Workflow，Runtime 负责 Reliability
```

---

# 7. 阶段最终架构

```text
                ┌───────────────────┐
                │     LangGraph     │
                │ Workflow / Router │
                └─────────┬─────────┘
                          │
                          ▼
                ┌───────────────────┐
                │     Tool Node     │
                │ Thin Adapter      │
                └─────────┬─────────┘
                          │
                          ▼
                ┌───────────────────┐
                │    ToolRuntime    │
                ├───────────────────┤
                │ Registry          │
                │ Circuit Breaker   │
                │ Bulkhead          │
                │ Error Normalizer  │
                │ Policy Engine     │
                │ Retry / Backoff   │
                │ Deadline          │
                │ Idempotency       │
                └─────────┬─────────┘
                          │
                          ▼
                ┌───────────────────┐
                │ Real Tool / API   │
                └─────────┬─────────┘
                          │
                          ▼
                ┌───────────────────┐
                │    ToolResult     │
                │ ok/data/error/... │
                └───────────────────┘
```

最终得到的不是单纯一个 LangGraph Demo，而是一个已经开始具备 **Agent Runtime / Tool Execution Platform** 雏形的架构。

下一阶段可以自然进入：

```text
Multi-Tool Agent
↓
LLM Tool Selection
↓
ToolRuntime
↓
ToolResult
↓
Agent 根据结果继续推理
```

而 Reliability Policy 继续留在 Runtime 中，不交给 LLM 随意决定。
