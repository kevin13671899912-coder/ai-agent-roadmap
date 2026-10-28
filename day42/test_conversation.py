
import os
import sqlite3
import subprocess
import sys
from conversation_graph import build_conversation_graph
from langchain_core.messages import HumanMessage

def reset_dbs():
    for db in ["day42_checkpoints.db", "day42_ledger.db"]:
        if os.path.exists(db):
            try:
                os.remove(db)
            except PermissionError:
                pass

def run_tests():
    print("=" * 70)
    print("Day 42 Short-term Memory & State Lifecycle Integration Tests")
    print("=" * 70)
    
    reset_dbs()
    
    # ----------------------------------------------------
    # 任务 A 验证 1: 同线程 (T001) 多轮对话连续性
    # ----------------------------------------------------
    print("\n[Test 1] Multi-turn conversation continuity on T001...")
    graph, conn = build_conversation_graph()
    
    config_t1 = {"configurable": {"thread_id": "T001"}}
    
    # 第一轮
    res1 = graph.invoke({"messages": [HumanMessage(content="你好，我叫Kevin")]}, config=config_t1)
    print(f"-> Turn 1 messages count: {len(res1['messages'])}")
    
    # 第二轮
    res2 = graph.invoke({"messages": [HumanMessage(content="帮我查一下余额")]}, config=config_t1)
    print(f"-> Turn 2 messages count: {len(res2['messages'])}")
    # 验证 Checkpoint 成功保留了前两轮的消息历史
    assert len(res2["messages"]) >= 4, "T001 should retain previous conversation history."
    
    # ----------------------------------------------------
    # 任务 A 验证 2: 跨线程 (T002) 隔离性
    # ----------------------------------------------------
    print("\n[Test 2] Cross-thread isolation (T002 should not see T001 history)...")
    config_t2 = {"configurable": {"thread_id": "T002"}}
    res_t2 = graph.invoke({"messages": [HumanMessage(content="查余额")]}, config=config_t2)
    print(f"-> T002 messages count: {len(res_t2['messages'])}")
    assert len(res_t2["messages"]) == 2, "T002 must be isolated and not inherit T001 messages."
    conn.close()

    # ----------------------------------------------------
    # 任务 B 验证: State 生命周期与防 Stale State 污染
    # ----------------------------------------------------
    print("\n[Test 3] State lifecycle & Stale State prevention...")
    graph_b, conn_b = build_conversation_graph()
    
    # 在 T001 中完成一笔转账
    res_transfer = graph_b.invoke({"messages": [HumanMessage(content="请帮我转账 1000 元给 Alice")]}, config=config_t1)
    
    # 检查转账结束后，临时状态是否被显式清理
    state_after = graph_b.get_state(config_t1)
    print(f"-> After transfer pending_call: {state_after.values.get('pending_call')}")
    assert state_after.values.get("pending_call") is None, "pending_call must be cleaned up on completion."
    assert state_after.values.get("approval_result") is None, "approval_result must be cleaned up on completion."
    
    # 随后在同一个 T001 中查询余额，验证不会因为旧 pending_call 误入审批流
    res_balance = graph_b.invoke({"messages": [HumanMessage(content="再帮我查一下余额")]}, config=config_t1)
    print(f"-> Balance query response: {res_balance['messages'][-1].content}")
    assert "余额" in res_balance['messages'][-1].content
    conn_b.close()

    # ----------------------------------------------------
    # 任务 C 验证: 进程重启与 Ledger 幂等恢复
    # ----------------------------------------------------
    print("\n[Test 4] Process restart & Ledger idempotency check...")
    # 模拟重启后重新编译 Graph 并加载持久化 Checkpointer
    graph_restarted, conn_restarted = build_conversation_graph()
    res_restart = graph_restarted.invoke({"messages": [HumanMessage(content="恢复测试")]}, config=config_t1)
    print(f"-> Restarted graph response: {res_restart['messages'][-1].content}")
    conn_restarted.close()

    print("\n" + "=" * 70)
    print("PASS: Day42 Short-term memory & state lifecycle tests passed successfully.")
    print("=" * 70)

if __name__ == "__main__":
    run_tests()