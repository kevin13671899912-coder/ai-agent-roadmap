from langgraph.types import Command
from agent_core import build_graph_with_official_sqlite, ProductionBankingBackend, CHECKPOINT_DB, LEDGER_DB

def main():
    print("=== [Python Process B] 启动：全新独立进程 ===")
    thread_config = {"configurable": {"thread_id": "true-process-thread-888"}}

    graph, conn = build_graph_with_official_sqlite(CHECKPOINT_DB)
    snapshot = graph.get_state(thread_config)
    print(f"进程 B 读取到的挂起节点: {snapshot.next}")

    assert "approval_node" in snapshot.next

    resume_command = Command(resume={
        "approved": True,
        "tool_call_id": "call_trans_01",
        "tool_name": "execute_transfer",
        "args": {"amount": 1000.0, "recipient": "Alice", "idempotency_key": "idempotency-txn-2026-9988"}
    })

    graph.invoke(resume_command, config=thread_config)

    backend = ProductionBankingBackend(LEDGER_DB)
    print(f"进程 B 恢复执行后最终账户余额: {backend.get_balance()}")
    assert backend.get_balance() == 4000.0

    dup_res = backend.execute_transfer(amount=1000.0, recipient="Alice", idempotency_key="idempotency-txn-2026-9988")
    print(f"重复提交返回结果: {dup_res}")
    assert backend.get_balance() == 4000.0

    conn.close()
    print("=== [Python Process B] 成功完成恢复与防重验证！ ===")

if __name__ == "__main__":
    main()
