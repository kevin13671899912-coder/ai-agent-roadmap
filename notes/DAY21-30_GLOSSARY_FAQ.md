# Day21–30 名词解释 / 概念讲解 / 高频问答

这份文档用于复习 Day21–30。重点不是记 API，而是理解 **Agent Runtime 的可靠性边界、职责划分与常见问法**。

---

# 一、核心名词与中文解释

## Retry — 重试

失败后再次尝试同一个操作。

```text
503 / 网络抖动 / 临时 Timeout
→ 可能适合 Retry

400 / 权限错误 / 确定性业务错误
→ 通常不适合 Retry
```

---

## Retry Budget — 重试预算

一个逻辑请求最多允许 Retry 多少次。

```text
max_retries = 2
→ 首次调用 + 最多 2 次重试
→ 最多 3 次 attempt
```

---

## Exponential Backoff — 指数退避

失败后不立即 Retry，而是逐步延长等待时间。

```python
backoff = base_delay * (2 ** retry_count)
```

目的：减少对下游服务的持续压力。

---

## Jitter — 随机抖动

在 Backoff 上加入随机性，避免大量请求在同一时间点一起重试。

```text
Backoff = 晚点再试
Jitter = 不要大家同时再试
```

---

## Retry Storm — 重试风暴

大量失败请求同时快速 Retry，反而进一步把 downstream 压垮。

---

## Thundering Herd — 惊群效应

大量请求在同一时间被唤醒并争抢同一资源。

在 Retry 场景里，Jitter 就是常见缓解手段。

---

## Timeout — 超时

**单次操作**最多允许执行多久。

```text
单次 HTTP Call 最多 2 秒
```

---

## Deadline — 截止时间 / 整体时间预算

**整个 Workflow** 最晚什么时候必须结束。

Retry 前应考虑：

```python
required_budget = backoff + request_timeout + safety_margin
```

---

## Cancellation — 取消

请求已经不再有继续执行的意义。

例如：

```text
用户取消
上游任务结束
父任务失败
```

通常 Cancellation 应优先于 Retry。

---

## Idempotency — 幂等性

同一个逻辑操作重复执行，不应该产生重复副作用。

常见写操作：

```text
Payment
Order
Approval
Send Email
Database Write
```

---

## Idempotency Key — 幂等键

用于唯一标识同一个逻辑写操作。

关键原则：

> **同一个 Workflow 的所有 Retry 必须复用同一个 idempotency_key。**

不能每次 Retry 都重新生成。

---

## Circuit Breaker — 熔断器

共享的 downstream 健康保护机制。

```text
CLOSED
→ 正常放行

OPEN
→ Fast Fail，不调用 downstream

HALF_OPEN
→ 冷却后允许少量 Probe
```

---

## CLOSED — 熔断器关闭状态

表示服务当前可以正常接收请求。

注意：CLOSED 不是“服务关闭”，而是“熔断没有打开”。

---

## OPEN — 熔断器打开状态

服务被认为不健康，新请求直接快速失败。

---

## HALF_OPEN — 半开状态

Cooldown 后允许少量测试请求检查服务是否恢复。

---

## Probe — 探测请求

HALF_OPEN 状态下用来检查 downstream 是否恢复的特殊请求。

```text
Probe success → CLOSED
Probe failure → OPEN
```

通常 Probe 不应该进入普通多次 Retry。

---

## Cooldown — 冷却时间

Circuit Breaker OPEN 后等待一段时间，再进入 HALF_OPEN 的时间窗口。

---

## Fast Fail — 快速失败

明知道当前请求大概率不会成功时，直接返回失败，而不是继续占用资源。

例如：

```text
Circuit Breaker OPEN
→ Fast Fail
```

---

## Bulkhead — 舱壁隔离 / 并发隔离

限制某个 downstream 同时允许多少请求执行。

名称来源于船舱隔离：一个舱出问题，不应该拖垮整艘船。

例如：

```text
HR API max=10
Search API max=30
Email API max=5
```

---

## Concurrency Control — 并发控制

控制同时执行的请求数量，避免线程、连接池、内存或 downstream 被耗尽。

---

## Semaphore — 信号量

一种常见的并发控制原语。

生产 Bulkhead 常用：

```text
threading.Semaphore
asyncio.Semaphore
Redis / distributed semaphore
```

---

## Slot — 槽位

Bulkhead 中代表一个可用并发执行名额。

关键原则：

```text
每次 Attempt acquire
调用结束后 release
Backoff 期间不能持有 slot
```

---

## Slot Leak — 槽位泄漏

成功 acquire 后，因为异常路径没有 release，导致可用并发容量越来越少。

常见保护：

```python
try:
    call_tool()
finally:
    bulkhead.release()
```

---

## Admission Gate — 准入门

在真正执行请求前判断是否允许进入。

Day24 的 Circuit Breaker 就是新 Workflow 的 admission gate。

```text
new workflow
↓
breaker gate
↓
ALLOW / FAST_FAIL
```

---

## Dependency — 下游依赖

当前 Agent / Runtime 所依赖的外部服务。

例如：

```text
HR API
Search API
Database
LLM Provider
Payment API
```

---

## Downstream — 下游服务

当前服务调用的目标服务。

例如 Agent Runtime 调用 HR API，则 HR API 是 downstream。

---

## Tool Runtime — 工具执行运行时

统一负责 Tool 执行生命周期的基础设施层。

```text
LangGraph Node
↓
ToolRuntime
↓
Breaker / Bulkhead / Retry / Deadline / Error Normalize
↓
Real Tool
```

核心原则：

> **Node 负责业务编排，Runtime 负责 Tool 执行策略。**

---

## Tool Registry — 工具注册表

用于根据 `tool_name` 找到：

```text
Tool Function
ToolConfig
Breaker
Bulkhead
Retry Policy
Timeout
```

避免 Runtime 里写大量：

```python
if tool_name == ...
elif tool_name == ...
```

---

## ToolConfig — 工具配置

描述某个 Tool 独立的执行策略。

例如：

```text
max_retries
timeout
base_delay
idempotency_required
breaker
bulkhead
```

核心：

> **Runtime 统一机制，ToolConfig 决定策略。**

---

## Error Taxonomy — 错误分类体系

把各种底层错误统一映射成 Runtime 能理解的标准类型。

例如：

```text
429 → RATE_LIMITED
503 → RETRYABLE
400 → NON_RETRYABLE
TimeoutError → TIMEOUT
Bulkhead full → OVERLOADED
RuntimeError → INTERNAL
```

---

## Error Normalization — 错误归一化

把 provider-specific / Python exception / HTTP Status 转换成统一 `ToolError`。

```text
Raw Error
↓
normalize_error()
↓
ToolError
```

---

## ToolError — 标准工具错误

描述“发生了什么错误”。

典型字段：

```python
kind
message
retryable
status_code
retry_after
```

---

## ErrorKind — 错误类型

Day27 使用的统一错误枚举：

```text
RETRYABLE       可重试错误
NON_RETRYABLE   不可重试错误
RATE_LIMITED    被限流
TIMEOUT         超时
OVERLOADED      过载/容量不足
CANCELLED       已取消
INTERNAL        内部代码错误
```

---

## RATE_LIMITED — 被限流

常见对应：

```text
HTTP 429 Too Many Requests
```

通常优先遵守：

```text
Retry-After
```

而不是单纯使用普通指数退避。

---

## Retry-After — 建议重试等待时间

服务端告诉客户端：

```text
请等待多久以后再 Retry
```

常见于 429。

---

## OVERLOADED — 过载

表示当前无法接收更多请求。

可能来源：

```text
Bulkhead Full
Circuit Breaker OPEN（当前实现里可能统一映射）
```

---

## INTERNAL — 内部错误

通常表示自己的 Tool / Runtime 代码异常。

例如：

```text
RuntimeError
KeyError
程序 Bug
```

和 HTTP 400 的区别：

```text
400 → 请求本身有问题
INTERNAL → 自己代码出问题
```

---

## ToolResult — 工具结果统一协议

ToolRuntime 对上层提供的稳定返回结构。

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

核心：

> Graph 不应该理解 Runtime 的所有内部状态，只应该消费稳定的 ToolResult。

---

## Result Envelope — 结果信封 / 统一结果包装

就是把不同 Tool 的成功和失败统一包进同一个协议。

```text
HR API 返回 employee
Search API 返回 items
```

Runtime 不需要理解业务含义，只统一包装进：

```text
ToolResult.data
```

---

## Policy — 策略

表示系统在某种情况下应该采取什么处理规则。

例如：

```text
503 是否 Retry
429 等多久
Retry 次数上限
Deadline 不够是否停止
```

---

## Policy Engine — 策略引擎

接收标准化 `ToolError + Context`，输出下一步动作。

```text
ToolError
↓
PolicyEngine
↓
PolicyDecision
```

它最好接近纯函数，不直接执行 Side Effect。

---

## PolicyDecision — 策略决策对象

描述“接下来应该做什么”。

```python
@dataclass
class PolicyDecision:
    action: PolicyAction
    delay: float = 0.0
    reason: str = ""
```

---

## PolicyAction — 策略动作

例如：

```text
RETRY               重试
FAIL                失败
FALLBACK            降级
CANCEL              取消
RATE_LIMIT_WAIT     限流等待
DEADLINE_EXCEEDED   超出截止时间
```

---

## Pure Function — 纯函数

相同输入产生相同输出，并且没有外部副作用。

PolicyEngine 理想上应接近纯函数：

```text
输入：Error + Context
输出：Decision
```

不要在里面：

```text
调真实 Tool
拿 Bulkhead Slot
修改 Breaker
sleep
```

---

## Side Effect — 副作用

函数除了返回结果，还改变了外部世界。

例如：

```text
写数据库
发 HTTP 请求
sleep
修改共享 Breaker
发送邮件
```

---

## Latency — 延迟

一次 Tool 执行耗费的时间。

常用：

```text
latency_ms
```

用于可观测性、性能分析和 SLO 评估。

---

## attempts — 尝试次数

实际调用 Tool 的次数。

例如：

```text
503 → retry → 200
attempts = 2
```

---

## Fallback — 降级

主路径不可用时切换到备用能力或备用路径。

```text
实时服务不可用
→ 缓存

主模型不可用
→ 备用模型
```

---

## Workflow — 工作流

LangGraph 中整个业务流程。

```text
START
↓
Node
↓
Router
↓
Next Node
↓
END
```

---

## Runtime — 运行时

执行 Tool 并负责可靠性策略的基础设施层。

```text
Workflow 决定业务怎么走
Runtime 决定 Tool 怎么可靠执行
```

---

# 二、最容易混淆的概念

## Retry vs Backoff vs Jitter

```text
Retry
= 要不要再试

Backoff
= 什么时候再试

Jitter
= 不要大家同一时间再试
```

---

## Timeout vs Deadline

```text
Timeout
= 单次调用时间限制

Deadline
= 整个 Workflow 时间限制
```

---

## Circuit Breaker vs Bulkhead

```text
Circuit Breaker
= 服务健康吗？

Bulkhead
= 即使服务健康，我最多允许多少并发？
```

所以完全可能：

```text
Breaker = CLOSED
Bulkhead = FULL
```

---

## Retry vs Circuit Breaker

```text
Retry
= request-level，请求级策略

Circuit Breaker
= service-level，共享服务级策略
```

---

## ToolError vs PolicyDecision

```text
ToolError
= 发生了什么？

PolicyDecision
= 接下来怎么办？
```

---

## ToolRuntime vs LangGraph

```text
LangGraph
= Workflow / 业务编排

ToolRuntime
= Tool Execution / 可靠性执行
```

---

## retryable vs affects_breaker

这两个概念不是一回事。

```text
retryable
= 当前请求要不要重试

affects_breaker
= 这个错误是否说明 downstream 不健康
```

例如 HTTP 400：

```text
retryable = false
但通常也不应该让 breaker failure_count + 1
```

---

# 三、Day21–30 最重要的执行顺序

## Retry Policy 判断

```text
Cancellation
↓
错误是否可重试
↓
Retry Budget
↓
计算 Backoff / Retry-After
↓
Deadline Budget
↓
等待
↓
重新检查 Cancellation / Deadline
↓
Retry
```

## Breaker + Bulkhead + Tool

```text
Circuit Breaker Gate
↓
Bulkhead Acquire
↓
Tool Call
↓
Bulkhead Release
↓
Error Normalize
↓
Policy Decision
```

## Retry Attempt

```text
attempt 1:
Bulkhead acquire
→ Tool call
→ release

Backoff

attempt 2:
Bulkhead acquire
→ Tool call
→ release
```

注意：

> Backoff 期间不能占着 Bulkhead Slot。

---

# 四、高频问答 / 面试题

## Q1：为什么 Retry 不能立即执行？

因为下游可能正在过载，立即 Retry 会进一步增加压力，甚至形成 Retry Storm。

---

## Q2：为什么有 Backoff 还需要 Jitter？

因为如果所有请求使用相同 Backoff，它们仍然会在相同时间点重新发起请求。Jitter 用于打散请求。

---

## Q3：Timeout 和 Deadline 有什么区别？

Timeout 控制单次调用，Deadline 控制整个 Workflow。

---

## Q4：为什么 Retry 前要检查 `backoff + request_timeout`？

因为不能只保证“有时间 sleep”，还必须保证 sleep 后有足够时间执行下一次真实请求。

---

## Q5：为什么写操作 Retry 要使用 Idempotency Key？

因为 Timeout 不代表服务端没有成功。Retry 可能重复创建订单、付款、审批等副作用。

---

## Q6：Circuit Breaker 为什么不能放在 AgentState？

因为 Circuit Breaker 描述的是共享 downstream 的健康状态，不属于单个 Workflow。

---

## Q7：Breaker OPEN 后，当前已经进入的 Workflow 是否必须停止？

不一定。

Day24 的设计是：普通 Workflow 在 CLOSED 时已经通过准入后，可以继续自己的 Retry Policy；OPEN 主要阻止新的 Workflow。

---

## Q8：为什么普通 Retry 不应该重新经过 Breaker Gate？

否则当前 Workflow 第一次失败导致 Breaker OPEN 后，自己的 Retry 立刻被 Breaker 阻止，相当于 Breaker 把 Retry Policy 吃掉了。

---

## Q9：HALF_OPEN Probe 为什么特殊？

Probe 的任务就是测试服务是否恢复。

```text
成功 → CLOSED
失败 → OPEN
```

通常一次 Probe 就足够，不需要普通多次 Retry。

---

## Q10：Bulkhead Full 是否应该增加 Circuit Breaker failure_count？

不应该。

因为请求根本没有调用 downstream。

核心：

> **No actual downstream call => do not record downstream failure.**

---

## Q11：为什么 Retry 期间不能一直持有 Bulkhead Slot？

因为 Backoff 期间没有实际调用，却占用了稀缺并发资源，会导致其他正常请求也无法执行。

---

## Q12：为什么 `try/finally` 对 Bulkhead 很重要？

保证无论 Tool 成功、失败还是抛异常，Slot 都会释放，防止 Slot Leak。

---

## Q13：为什么不同 Tool 不应该共享同一个 Breaker？

因为一个 dependency 出问题不应该拖累另一个无关 dependency。

```text
HR API 挂了
≠ Search API 也应该熔断
```

---

## Q14：为什么需要 ToolRegistry？

为了避免 Runtime 内部不断增加 `if tool_name == ...`，并让每个 Tool 独立配置自己的策略。

---

## Q15：Read Tool 和 Write Tool 的 Retry Policy 为什么不同？

因为 Write Tool 有副作用，存在重复执行风险；Read Tool 通常更安全。

---

## Q16：429 为什么单独定义 RATE_LIMITED？

因为它虽然可能重试，但通常有更特殊的处理方式，例如优先遵守 `Retry-After`。

---

## Q17：HTTP 400 和 RuntimeError 有什么区别？

```text
400
→ 请求/参数问题
→ NON_RETRYABLE

RuntimeError
→ 自己 Tool / 代码内部问题
→ INTERNAL
```

---

## Q18：为什么需要 Error Normalization？

因为不同 Tool 可能返回 HTTP Status、Python Exception、SDK Error。统一成 ToolError 后，Policy 不需要理解所有 provider-specific 错误。

---

## Q19：为什么需要 ToolResult？

为了让上层 Graph 不依赖 Runtime 的各种内部返回形式。

Graph 只需要稳定协议：

```text
ok
data
error
attempts
latency_ms
```

---

## Q20：ToolResult.data 应该由 Runtime 解释吗？

不应该。

Runtime 负责统一包装，业务 Node 负责理解 `employee`、`items` 等业务字段。

---

## Q21：PolicyEngine 的职责是什么？

把：

```text
发生了什么错误
```

转换成：

```text
下一步应该做什么
```

---

## Q22：为什么 PolicyEngine 最好接近纯函数？

因为容易测试、容易推理，也避免 Policy 层和真实 Tool/Bulkhead/Breaker 强耦合。

---

## Q23：PolicyEngine 可以直接 sleep 吗？

最好不要。

PolicyEngine 输出：

```text
PolicyDecision(delay=...)
```

然后由 Runtime 执行 sleep。

---

## Q24：LangGraph Router 应该负责 503 Retry 吗？

不应该。

```text
503 / 429 / Timeout / Retry Budget
→ Runtime Policy

SUCCESS / FALLBACK / FAILURE
→ Graph Router
```

---

## Q25：HR 第一次 503，第二次 200，Graph 应该看到什么？

Graph 应该只看到最终结果：

```python
ToolResult(
    ok=True,
    attempts=2,
)
```

而不应该自己参与第一次 503 的 Retry。

---

## Q26：为什么说 Day21–30 的核心不是 LangGraph Syntax？

因为真正难的是：

```text
策略归谁负责
共享状态放哪里
什么错误影响什么组件
什么顺序执行
哪些内部细节不能泄漏到 Graph
```

这是 Runtime / Distributed Systems / Reliability Design 问题。

---

# 五、一张图记住 Day21–30

```text
Agent / LangGraph
        ↓
     Tool Node
        ↓
    ToolRuntime
        ↓
 ┌─────────────────────────┐
 │ Tool Registry           │
 │ Circuit Breaker         │
 │ Bulkhead                │
 │ Timeout / Deadline      │
 │ Error Normalizer        │
 │ Policy Engine           │
 │ Retry / Backoff/Jitter  │
 │ Idempotency             │
 └─────────────────────────┘
        ↓
     Real Tool / API
        ↓
     ToolResult
        ↓
 LangGraph Router
 ├ SUCCESS
 ├ FALLBACK
 └ FAILURE
```

最后记住四句话：

```text
Error 描述事实，Decision 描述动作。

Graph 负责 Workflow，Runtime 负责 Tool Reliability。

Breaker 看健康度，Bulkhead 看容量。

Retry 是请求级，Breaker 是共享服务级。
```
