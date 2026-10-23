# Day31–40 高频名词 / 易错点 FAQ / 自测练习

> 复习配套：[Day31–40 总结](./DAY31-40_SUMMARY.md) · [Day40 Agent Graph](../day40/agent_graph.py) · [Day40 测试](../day40/test_agent.py)
>
> 本文适用于已完成 Day40、暂不进入 Day41 的复习阶段。先尝试回答题目，再查看答案。

## 一、必会名词（中文释义 + 使用边界）

| 英文 | 中文 | 一句话解释 |
|---|---|---|
| Tool Calling | 工具调用 | 模型输出结构化调用意图，不等于已经执行 |
| Tool Call ID | 工具调用标识 | 关联 `AIMessage.tool_calls` 与 `ToolMessage` |
| ToolNode | 工具执行节点 | 在 LangGraph 中执行收到的具体 Tool Calls |
| Tool Contract | 工具契约 | 名称、参数、Schema、错误和结果约定 |
| Policy Gate | 策略准入门 | 执行前确定性判断放行 / 拒绝 / 等待审批 |
| Read-only | 只读操作 | 原则上不产生持久业务副作用 |
| Side Effect | 副作用 | 扣款、写库、发送邮件等改变外部世界的动作 |
| HITL | 人在回路中 | 人类参与审批或纠正执行流程 |
| interrupt | 图中断 | 保存待恢复执行位置，并对外发出审批请求 |
| Command(resume=...) | 恢复指令 | 使用相同线程恢复此前的中断 |
| Checkpointer | 检查点保存器 | 保存 Graph 的恢复状态与中间写入 |
| thread_id | 线程标识 | 定位一条独立的 Graph 执行 / 对话链 |
| Revalidation | 恢复后重新校验 | 执行前重新核对审批和最新业务事实 |
| TOCTOU | 检查与使用间竞态 | 检查通过后，真正使用时状态可能已变化 |
| Idempotency | 幂等 | 同一逻辑操作重复请求不重复产生副作用 |
| Idempotency Ledger | 幂等账本 | 原子保存首次已处理操作及结果 |
| Pending Writes | 待持久化写入 | Checkpointer 为恢复执行记录的中间节点写入 |
| Durable Execution | 持久执行 / 可恢复执行 | 进程退出后能从持久状态继续执行 |
| RBAC | 基于角色的访问控制 | 根据经过认证的身份和角色核准权限 |
| Fail Closed | 默认拒绝 | 信息缺失 / 未知工具 / 校验异常时不放行危险操作 |

## 二、最容易混淆的八组概念

### 1. Tool Selection vs Policy Authorization

- Selection：模型想用什么工具。
- Authorization：系统允许什么工具以何种参数、在何种条件下执行。

**选择不是授权；生成了 Tool Call 不是已经执行。**

### 2. `interrupt()` vs 普通 `return`

- `return`：节点完成并返回更新。
- `interrupt()`：暂停执行，等待外部使用 `Command(resume=...)` 恢复；同一节点可能在恢复时从头运行。

因此：`interrupt` 前不允许发生不能安全重复的业务副作用。

### 3. State vs Checkpoint vs Ledger

```text
State       = Workflow 当前数据
Checkpoint  = State + 恢复所需执行元信息
Ledger      = 某笔业务副作用是否发生过，以及首次结果
```

Checkpoint 不能充当真实银行数据库；Ledger 也不负责 Graph 走到哪一个 Node。

### 4. 两个 Graph 实例 vs 两个 OS 进程

```python
graph_a = build()
graph_b = build()   # 同一解释器，不能证明跨进程
```

真正跨进程必须退出 A，另一个 Python 解释器打开同一持久数据库，再恢复原 `thread_id`。推荐 `subprocess.run(..., check=True)`。

### 5. Approval Payload Match vs Approver Identity

```text
参数正确    → 证明审批载荷和待执行对象一致
身份可信    → 证明“谁”有权审批，且审批没有过期
```

两者都需要。不能信任前端直接传来的 `approved=True`。

### 6. Revalidation vs Backend Transaction

恢复时检查余额 5000 ≠ 后端执行时余额仍是 5000。Backend 必须在**同一个写事务**内再次检查余额，原子处理扣款与幂等记录。

### 7. 稳定交易 ID vs 每次调用生成 UUID

- 不同业务交易：不同 ID。
- 同一交易 Retry / Resume：相同 ID。

UUID 本身没有问题；**每次重试都重新生成 UUID**才是问题。

### 8. 测试通过 vs 测试真的覆盖

两次失败结果相等不意味着验证了成功写操作的幂等性；错误原因是 `PARAMETER_MISMATCH` 也不能充当 `INSUFFICIENT_FUNDS` 的测试。

**要同时验证：预期分支、数据库余额、Ledger 记录数与进程退出码。**

---

## 三、情景问答（先自己答，再看下面参考答案）

**Q1.** 模型生成 `execute_transfer(1000, "Alice")`，是否能直接交给 ToolNode？为什么？

**Q2.** 原始 AIMessage 有两个 Tool Calls：余额查询与转账。只读先执行，转账等待审批。中断期间哪些 ToolMessage 已有、哪些还没有？什么时候可以把消息历史重新发给 LLM？

**Q3.** 为什么不把 `backend.execute_transfer()` 放在 `approval_node` 的 `interrupt()` 之前？

**Q4.** 恢复数据里 `approved=True`，参数也匹配，能否据此证明是授权用户批准的？

**Q5.** 审批时余额 5000，恢复时余额 800，转账金额 1000。应该返回什么？是否调用转账工具？

**Q6.** 程序在扣款提交后、ToolMessage 写入前崩溃。重新恢复时怎么避免再次扣款？

**Q7.** `CustomSqliteSaver.put_writes()` 直接 `pass`，有什么风险？为什么推荐官方 `SqliteSaver`？

**Q8.** 一个 `thread_id` 在进程 A 的 Checkpoint DB 中暂停，如何用独立进程 B 恢复？

**Q9.** 用户 A 的交易金额 1000，用户 B 的交易金额 2000。两笔交易使用同一个 `idempotency_key` 会怎样？

**Q10.** “Day40 场景 7 两次请求的结果相等”足以证明成功转账的幂等性吗？

**Q11.** LLM 一次生成两个不同的转账 Tool Calls，Policy Gate 只保存第一笔，第二笔应如何处理？

**Q12.** Day40 中 `final_response_node` 通过 `"remaining_balance" in str(content)` 判定成功，有什么隐患？更合理的接口是什么？

### 参考答案

**A1.** 不能。Policy Gate 必须先做工具白名单、参数 / 风险校验；写操作还需可信审批及恢复后的业务校验。

**A2.** 余额查询对应的 ToolMessage 已有；转账仍 pending，尚无执行/拒绝 ToolMessage。直到待审批调用完成并产出对应结果、工具调用协议闭合后，才把完整历史提供给模型。

**A3.** `interrupt` 所在节点可能重新执行；此前副作用可能被重复触发。

**A4.** 不能。参数匹配不证明审批身份；可信服务还要检查会话、角色、授权对象、有效期及撤销状态等。

**A5.** `INSUFFICIENT_FUNDS`；不得扣款。正确处理是失败结果及用户可理解的取消答复。

**A6.** 使用持久化且原子写入的 Idempotency Ledger。恢复重试用同一个业务幂等键；后端发现已经完成，返回首次结果而不再次扣款。不能单靠 Checkpoint 保证外部副作用 exactly-once。

**A7.** 会损失未完成节点的中间写入与恢复语义，影响部分失败场景的可靠恢复。使用官方实现，避免误做半套 Checkpointer 协议。

**A8.** A 写入 SQLite 并退出；B 作为新的 Python 进程重新打开同一 Checkpoint DB，加载相同 `thread_id`，确认挂起节点，然后 `Command(resume=...)`。Backend Ledger 必须独立持久化。

**A9.** 可能把不同请求误当同一业务操作，返回错误的旧结果；若系统错误设计，还可能造成更加严重的数据一致性问题。

**A10.** 不足。如果第一次就因余额不足失败，两次结果也会相等。必须先成功扣款一次，再验证重试未第二次扣款，余额与 Ledger 都正确。

**A11.** 必须明确拒绝、排队或逐笔审批，并为第二个 Tool Call 生成对应的可追踪结果；绝不能默默丢弃。

**A12.** 字符串字段碰巧出现会误判；成功与失败应解析结构化 `ToolResult`，显式使用 `ok/status/error` 和 `data`。

---

## 四、复习实验（只补强 Day40，不进入新课程）

### 练习 A：真正验证成功写操作幂等

目标：避免“两个失败结果相等”的假阳性。

```python
backend = ProductionBankingBackend()  # 测试前请使用隔离的全新数据库
key = "tx-review-A-001"

balance_before = backend.get_balance()
assert balance_before == 5000.0

first = backend.execute_transfer(1000.0, "Alice", key)
assert first["success"] is True
assert backend.get_balance() == 4000.0

second = backend.execute_transfer(1000.0, "Alice", key)
assert second == first
assert backend.get_balance() == 4000.0

# 还应查询 Ledger，确认 key 唯一且仅一条记录。
```

### 练习 B：审批参数防篡改

暂停一笔 `amount=1000, recipient=Alice` 的转账，恢复时提交 `amount=2000, recipient=Bob`，必须返回 `PARAMETER_MISMATCH`，余额不变。

### 练习 C：余额下降的正确错误路径

暂停时余额 5000、金额 1000；暂停期间将余额降为 800；恢复的审批载荷**必须与 pending_call 完全匹配**，否则只会测到参数不匹配。正确断言：

```python
assert "INSUFFICIENT_FUNDS" in final_response
assert backend.get_balance() == 800.0
```

### 练习 D：稳定交易 ID

将 `transaction_id` 放在业务请求中并持久化到 State。测试：

```text
交易 T1 首次执行 → key = idempotency-T1
交易 T1 Retry    → key = idempotency-T1
交易 T2 执行      → key = idempotency-T2
```

不能每次生成 Tool Call 时重新随机生成 T1 的 ID。

### 练习 E：跨进程与真实退出码

```python
import subprocess, sys

subprocess.run([sys.executable, "sub_process_worker.py", "suspend", "review-T1"], check=True)
subprocess.run([sys.executable, "sub_process_worker.py", "resume", "review-T1"], check=True)
```

进程 B 验证：挂起节点正确、审批调用 ID 正确、结果正确、重复转账不扣第二次。

---

## 五、复习完成检查清单

- [ ] 能画出 Read Tool / Write Tool 的执行路径
- [ ] 能解释 Tool Selection / Policy / ToolNode 三个职责
- [ ] 能为两笔 Tool Calls 配对两笔 ToolMessage
- [ ] 能解释 `interrupt()` 节点为什么会重跑
- [ ] 能区别 `thread_id`、Checkpoint DB 与业务 Ledger
- [ ] 能解释为何 `resume` JSON 不等于可信授权
- [ ] 能解释为何需要恢复时重校验和 DB 事务再校验
- [ ] 能证明“成功执行一次 + 重试没有二次扣款”
- [ ] 能运行两个 OS 进程证明断点恢复
- [ ] 能说出 Day40 规则模拟器与真实 Tool-Calling LLM 的差距

复习结束后，可以再开始 Day41；本轮不自动推进。
