import os
import sqlite3
import subprocess
import sys
from conversation_graph import build_conversation_graph, get_ledger_count
from langchain_core.messages import HumanMessage
from langgraph.types import Command

def reset_dbs():
    for db in ["day42_checkpoints.db", "day42_ledger.db"]:
        if os.path.exists(db):
            try:
                # 优雅清空表数据，避免 Windows 文件句柄占用导致 os.remove 失败
                with sqlite3.connect(db) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                    for table in cursor.fetchall():
                        if table[0] != 'sqlite_sequence':
                            conn.execute(f"DROP TABLE IF EXISTS {table[0]};")
                    conn.commit()
            except Exception:
                pass
            try:
                os.remove(db)
            except Exception:
                pass

def run_tests():
    print("=" * 70)
    print("Day 42 Short-term Memory, State Lifecycle & Subprocess Recovery Tests")
    print("=" * 70)
    
    reset_dbs()
    
    # ----------------------------------------------------
    # 任务 A 验证 1: 同线程 (T001) 多轮对话连续性
    # ----------------------------------------------------
    print("\n[Test 1] Multi-turn conversation continuity on T001...")
    graph, conn = build_conversation_graph()
    config_t1 = {"configurable": {"thread_id": "T001"}}
    
    res1 = graph.invoke({"messages": [HumanMessage(content="你好，我叫Kevin")]}, config=config_t1)
    res2 = graph.invoke({"messages": [HumanMessage(content="帮我查一下余额")]}, config=config_t1)
    print(f"-> T001 total messages: {len(res2['messages'])}")
    assert len(res2["messages"]) >= 4, "T001 should retain previous conversation history."
    conn.close()

    # ----------------------------------------------------
    # 任务 A 验证 2: 跨线程 (T002) 隔离性
    # ----------------------------------------------------
    print("\n[Test 2] Cross-thread isolation (T002 should not see T001 history)...")
    graph_t2, conn_t2 = build_conversation_graph()
    config_t2 = {"configurable": {"thread_id": "T002"}}
    res_t2 = graph_t2.invoke({"messages": [HumanMessage(content="查余额")]}, config=config_t2)
    assert len(res_t2["messages"]) == 2, "T002 must be isolated and not inherit T001 messages."
    conn_t2.close()

    # ----------------------------------------------------
    # 任务 B 验证: State 生命周期与防 Stale State 污染（带 HITL 审批流）
    # ----------------------------------------------------
    print("\n[Test 3] State lifecycle, HITL approval & Stale State prevention...")
    graph_b, conn_b = build_conversation_graph()
    
    # 触发转账中断
    graph_b.invoke({"messages": [HumanMessage(content="请帮我转账 1000 元给 Alice")]}, config=config_t1)
    snap = graph_b.get_state(config_t1)
    assert "approval_node" in snap.next
    
    # 用户批准
    res_trans = graph_b.invoke(Command(resume={"approved": True}), config=config_t1)
    print(f"-> Transfer response: {res_trans['messages'][-1].content}")
    
    # 检查转账成功后，临时状态是否被显式清理
    state_after = graph_b.get_state(config_t1)
    assert state_after.values.get("pending_call") is None, "pending_call must be cleaned up."
    assert state_after.values.get("approval_result") is None, "approval_result must be cleaned up."
    
    # 随后在同一个 T001 中查询余额，验证不会因为旧 pending_call 误入审批流
    res_balance = graph_b.invoke({"messages": [HumanMessage(content="再帮我查一下余额")]}, config=config_t1)
    assert "余额" in res_balance['messages'][-1].content
    conn_b.close()

    # ----------------------------------------------------
    # 任务 C 验证: 真正的操作系统级子进程重启与 Ledger 幂等副作用安全
    # ----------------------------------------------------
    print("\n[Test 4] True multi-process subprocess checkpoint recovery & Ledger validation...")
    reset_dbs()  # 确保干净的数据库环境
    sub_thread_id = "day40-subproc-thread-001"
    
    # 进程 A：启动并挂起，随后进程彻底退出销毁
    p1 = subprocess.run([sys.executable, "sub_process_worker_day42.py", "suspend", sub_thread_id], capture_output=True, text=True)
    assert p1.returncode == 0, f"Subprocess A failed: {p1.stderr}"

    # 进程 B：全新独立进程加载 Checkpoint 并恢复执行
    p2 = subprocess.run([sys.executable, "sub_process_worker_day42.py", "resume", sub_thread_id], capture_output=True, text=True)
    assert p2.returncode == 0, f"Subprocess B failed: {p2.stderr}"
    
    # 验证 Ledger 确实记录了且仅记录了一条副作用
    ledger_cnt = get_ledger_count()
    print(f"-> Verified Ledger transaction count: {ledger_cnt}")
    assert ledger_cnt == 1, "Ledger must record exactly one transaction."

    print("\n" + "=" * 70)
    print("PASS: Day42 Short-term memory & subprocess recovery tests passed successfully.")
    print("=" * 70)

if __name__ == "__main__":
    run_tests()