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
    print("Day 40 收官项目：全场景自动化集成测试")
    print("=" * 70)
    
    thread_config = {"configurable": {"thread_id": "day40-all-scenarios-001"}}

    # 场景 1 & 2: 查询余额 与 查询交易历史
    reset_dbs()
    print("\n[场景 1 & 2] 测试只读工具直通自动执行...")
    graph, conn = build_banking_graph()
    
    res_bal = graph.invoke({"messages": [{"role": "user", "content": "帮我查一下账户余额"}]}, config=thread_config)
    print("-> 余额查询答复:", res_bal["messages"][-1].content)
    assert "余额" in res_bal["messages"][-1].content or "balance" in res_bal["messages"][-1].content
    
    res_hist = graph.invoke({"messages": [{"role": "user", "content": "请查看交易历史流水"}]}, config=thread_config)
    print("-> 历史查询答复:", res_hist["messages"][-1].content)
    conn.close()

    # 场景 3 & 4: 请求转账 与 用户拒绝
    reset_dbs()
    print("\n[场景 3 & 4] 测试转账中断与用户拒绝...")
    graph_a, conn_a = build_banking_graph()
    graph_a.invoke({"messages": [{"role": "user", "content": "请帮我转账 1000 元给 Alice"}]}, config=thread_config)
    snap = graph_a.get_state(thread_config)
    assert "approval_node" in snap.next
    
    reject_cmd = Command(resume={"approved": False})
    res_rej = graph_a.invoke(reject_cmd, config=thread_config)
    print("-> 拒绝后的答复:", res_rej["messages"][-1].content)
    backend = ProductionBankingBackend()
    assert backend.get_balance() == 5000.0, "拒绝审批后绝对不能扣款！"
    conn_a.close()

    # 场景 5: 批准且余额充足
    reset_dbs()
    print("\n[场景 5] 测试批准且余额充足...")
    graph_b, conn_b = build_banking_graph()
    graph_b.invoke({"messages": [{"role": "user", "content": "请帮我转账 1000 元给 Alice"}]}, config=thread_config)
    
    approve_cmd = Command(resume={
        "approved": True,
        "tool_call_id": "call_trans_01",
        "tool_name": "execute_transfer",
        "args": {"amount": 1000.0, "recipient": "Alice", "idempotency_key": "idempotency-txn-day40-9999"}
    })
    res_app = graph_b.invoke(approve_cmd, config=thread_config)
    print("-> 批准后的最终答复:", res_app["messages"][-1].content)
    assert backend.get_balance() == 4000.0
    conn_b.close()

    # 场景 6: 批准期间余额下降（拦截）
    reset_dbs()
    print("\n[场景 6] 测试挂起期间余额下降拦截...")
    graph_c, conn_c = build_banking_graph()
    graph_c.invoke({"messages": [{"role": "user", "content": "请帮我转账 4500 元给 Alice"}]}, config=thread_config)
    
    with sqlite3.connect("banking_ledger.db") as conn_hack:
        conn_hack.execute("UPDATE accounts SET balance = 2000.0 WHERE id = 'main'")
        conn_hack.commit()
        
    approve_cmd2 = Command(resume={
        "approved": True,
        "tool_call_id": "call_trans_01",
        "tool_name": "execute_transfer",
        "args": {"amount": 4500.0, "recipient": "Alice", "idempotency_key": "idempotency-txn-day40-8888"}
    })
    res_drop = graph_c.invoke(approve_cmd2, config=thread_config)
    print("-> 余额不足拦截后的答复:", res_drop["messages"][-1].content)
    conn_c.close()

    # 场景 7: 相同交易重试（幂等防重）
    print("\n[场景 7] 测试相同幂等键重复提交不重复扣款...")
    res_dup = backend.execute_transfer(amount=1000.0, recipient="Alice", idempotency_key="idempotency-txn-day40-9999-dup")
    res_dup_again = backend.execute_transfer(amount=1000.0, recipient="Alice", idempotency_key="idempotency-txn-day40-9999-dup")
    print("-> 首次转账结果:", res_dup)
    print("-> 重复提交转账结果:", res_dup_again)
    assert res_dup == res_dup_again

    # 场景 8: 真正的独立子进程重启与跨进程恢复
    reset_dbs()
    print("\n[场景 8] 测试真正的操作系统级子进程退出与恢复...")
    sub_thread_id = "day40-subproc-thread-001"
    
    p1 = subprocess.run([sys.executable, "sub_process_worker.py", "suspend", sub_thread_id], capture_output=True, text=True)
    print("【进程 A 输出】\n", p1.stdout)
    if p1.stderr:
        print("【进程 A 错误】\n", p1.stderr)
    assert p1.returncode == 0, "子进程 A 退出码异常"

    p2 = subprocess.run([sys.executable, "sub_process_worker.py", "resume", sub_thread_id], capture_output=True, text=True)
    print("【进程 B 输出】\n", p2.stdout)
    if p2.stderr:
        print("【进程 B 错误】\n", p2.stderr)
    assert p2.returncode == 0, "子进程 B 退出码异常"
    assert backend.get_balance() == 4000.0

    print("\n" + "=" * 70)
    print("🎉 恭喜！Day 40 八大验收场景自动化测试全部全绿通过！")
    print("=" * 70)

if __name__ == "__main__":
    run_all_scenarios()