import os
import sys
import subprocess
import sqlite3
from agent_graph import build_banking_graph
from banking_backend import ProductionBankingBackend
from langgraph.types import Command

def reset_dbs():
    for db in ["official_checkpoints.db", "banking_ledger.db"]:
        if os.path.exists(db):
            try:
                os.remove(db)
            except PermissionError:
                with sqlite3.connect(db) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                    for table in cursor.fetchall():
                        if table[0] != 'sqlite_sequence':
                            conn.execute(f"DELETE FROM {table[0]};")
                    conn.commit()

def run_all_scenarios():
    print("=" * 70)
    print("Day 40 Integration Tests: Banking Operations Agent")
    print("=" * 70)
    
    thread_config = {"configurable": {"thread_id": "day40-all-scenarios-001"}}

    # 场景 1 & 2: 查询余额 与 查询交易历史
    reset_dbs()
    print("\n[Scenario 1 & 2] Read-only automatic execution...")
    graph, conn = build_banking_graph()
    
    res_bal = graph.invoke({"messages": [{"role": "user", "content": "帮我查一下账户余额"}]}, config=thread_config)
    assert "余额" in res_bal["messages"][-1].content or "balance" in res_bal["messages"][-1].content
    
    res_hist = graph.invoke({"messages": [{"role": "user", "content": "请查看交易历史流水"}]}, config=thread_config)
    assert "history" in res_hist["messages"][-1].content or "交易历史" in res_hist["messages"][-1].content
    conn.close()

    # 场景 3 & 4: 请求转账 与 用户拒绝
    reset_dbs()
    print("\n[Scenario 3 & 4] Transfer suspend and user rejection...")
    graph_a, conn_a = build_banking_graph()
    graph_a.invoke({"messages": [{"role": "user", "content": "请帮我转账 1000 元给 Alice"}]}, config=thread_config)
    snap = graph_a.get_state(thread_config)
    assert "approval_node" in snap.next
    
    reject_cmd = Command(resume={"approved": False})
    res_rej = graph_a.invoke(reject_cmd, config=thread_config)
    assert "USER_REJECTED" in res_rej["messages"][-1].content
    backend = ProductionBankingBackend()
    assert backend.get_balance() == 5000.0, "Balance must not change on rejection!"
    conn_a.close()

    # 场景 5: 批准且余额充足
    reset_dbs()
    print("\n[Scenario 5] Approval with sufficient balance...")
    graph_b, conn_b = build_banking_graph()
    graph_b.invoke({"messages": [{"role": "user", "content": "请帮我转账 1000 元给 Alice"}]}, config=thread_config)
    
    snap_b = graph_b.get_state(thread_config)
    p_call_b = snap_b.values.get("pending_call")
    
    approve_cmd = Command(resume={
        "approved": True,
        "tool_call_id": p_call_b["tool_call_id"],
        "tool_name": p_call_b["tool_name"],
        "args": p_call_b["args"]
    })
    res_app = graph_b.invoke(approve_cmd, config=thread_config)
    assert "转账执行成功" in res_app["messages"][-1].content
    assert backend.get_balance() == 4000.0
    conn_b.close()

    # 场景 6: 批准期间余额下降（触发 INSUFFICIENT_FUNDS 拦截）
    reset_dbs()
    print("\n[Scenario 6] Balance drop during suspension intercept check...")
    graph_c, conn_c = build_banking_graph()
    graph_c.invoke({"messages": [{"role": "user", "content": "请帮我转账 1000 元给 Alice"}]}, config=thread_config)
    
    snap_c = graph_c.get_state(thread_config)
    p_call_c = snap_c.values.get("pending_call")
    
    # 暂停期间把余额篡改降到 800 元（小于 1000 元）
    with sqlite3.connect("banking_ledger.db") as conn_hack:
        conn_hack.execute("UPDATE accounts SET balance = 800.0 WHERE id = 'main'")
        conn_hack.commit()
        
    approve_cmd2 = Command(resume={
        "approved": True,
        "tool_call_id": p_call_c["tool_call_id"],
        "tool_name": p_call_c["tool_name"],
        "args": p_call_c["args"]
    })
    res_drop = graph_c.invoke(approve_cmd2, config=thread_config)
    print("-> Intercept response:", res_drop["messages"][-1].content)
    
    # 严格断言触发了 INSUFFICIENT_FUNDS 且余额保持在 800
    assert "INSUFFICIENT_FUNDS" in res_drop["messages"][-1].content
    assert backend.get_balance() == 800.0
    conn_c.close()

    # 场景 7: 相同交易重试（幂等防重）
    print("\n[Scenario 7] Idempotency duplicate submission test...")
    res_dup = backend.execute_transfer(amount=1000.0, recipient="Alice", idempotency_key="idempotency-txn-day40-test-dup")
    res_dup_again = backend.execute_transfer(amount=1000.0, recipient="Alice", idempotency_key="idempotency-txn-day40-test-dup")
    assert res_dup == res_dup_again

    # 场景 8: 真正的独立子进程重启与跨进程恢复
    reset_dbs()
    print("\n[Scenario 8] True multi-process subprocess checkpoint recovery...")
    sub_thread_id = "day40-subproc-thread-001"
    
    p1 = subprocess.run([sys.executable, "sub_process_worker.py", "suspend", sub_thread_id], capture_output=True, text=True)
    assert p1.returncode == 0, f"Subprocess A failed: {p1.stderr}"

    p2 = subprocess.run([sys.executable, "sub_process_worker.py", "resume", sub_thread_id], capture_output=True, text=True)
    assert p2.returncode == 0, f"Subprocess B failed: {p2.stderr}"
    assert backend.get_balance() == 4000.0

    print("\n" + "=" * 70)
    print("PASS: Day40 all integration tests passed successfully.")
    print("=" * 70)

if __name__ == "__main__":
    run_all_scenarios()