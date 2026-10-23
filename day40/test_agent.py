import os
import subprocess
import sys

def run_integration_tests():
    print("=" * 70)
    print("🧪 Day 40 收官项目：Banking Operations Agent 自动化集成测试")
    print("=" * 70)

    for f in ["official_checkpoints.db", "banking_ledger.db"]:
        if os.path.exists(f):
            os.remove(f)

    thread_config = {"configurable": {"thread_id": "day40-prod-thread-001"}}

    # 测试场景 1：纯余额查询（自动执行，无审批）
    from agent_graph import build_banking_graph
    graph, conn = build_banking_graph()
    
    print("\n--- 场景 1: 查询余额 ---")
    res1 = graph.invoke({"messages": [{"role": "user", "content": "帮我查一下账户余额"}]}, config=thread_config)
    print("余额查询执行完成，消息记录数:", len(res1["messages"]))
    conn.close()

    # 清理并测试转账审批挂起与跨进程恢复
    for f in ["official_checkpoints.db", "banking_ledger.db"]:
        if os.path.exists(f):
            os.remove(f)

    print("\n--- 场景 2: 发起转账请求（应在审批节点中断挂起） ---")
    graph_a, conn_a = build_banking_graph()
    graph_a.invoke({"messages": [{"role": "user", "content": "请帮我查询余额并转账 1000 元给 Alice"}]}, config=thread_config)
    
    snapshot_a = graph_a.get_state(thread_config)
    print(f"进程 A 挂起节点: {snapshot_a.next}")
    assert "approval_node" in snapshot_a.next
    conn_a.close()
    print("✅ 进程 A 成功挂起并落盘")

    print("\n--- 场景 3: 模拟进程重启，加载 DB 并通过 Command(resume=...) 批准转账 ---")
    graph_b, conn_b = build_banking_graph()
    snapshot_b = graph_b.get_state(thread_config)
    print(f"进程 B 成功恢复节点: {snapshot_b.next}")
    
    # 模拟用户批准
    resume_cmd = Command(resume={
        "approved": True,
        "tool_call_id": "call_trans_01",
        "args": {"amount": 1000.0, "recipient": "Alice", "idempotency_key": "idempotency-txn-day40-01"}
    })
    
    graph_b.invoke(resume_cmd, config=thread_config)
    conn_b.close()
    
    from banking_backend import ProductionBankingBackend
    backend = ProductionBankingBackend()
    print(f"转账完成后的最终账户余额: {backend.get_balance()}")
    assert backend.get_balance() == 4000.0
    print("🎉 Day 40 收官集成测试全部顺利通过！")

if __name__ == "__main__":
    run_integration_tests()