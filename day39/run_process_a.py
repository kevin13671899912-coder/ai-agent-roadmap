import os
from agent_core import build_graph_with_official_sqlite, ProductionBankingBackend, CHECKPOINT_DB, LEDGER_DB

def main():
    print("=== [Python Process A] 启动 ===")
    thread_config = {"configurable": {"thread_id": "true-process-thread-888"}}
    backend = ProductionBankingBackend(LEDGER_DB)

    graph, conn = build_graph_with_official_sqlite(CHECKPOINT_DB)
    graph.invoke({"messages": []}, config=thread_config)

    snapshot = graph.get_state(thread_config)
    print(f"进程 A 挂起节点: {snapshot.next}")
    print(f"进程 A 结束时后端余额: {backend.get_balance()}")

    assert "approval_node" in snapshot.next
    assert backend.get_balance() == 5000.0

    conn.close()
    print("=== [Python Process A] 正常退出，检查点已落盘 ===")

if __name__ == "__main__":
    main()
