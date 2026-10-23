import sys
import os
from agent_graph import build_banking_graph
from langgraph.types import Command

def main():
    mode = sys.argv[1]
    thread_id = sys.argv[2]
    thread_config = {"configurable": {"thread_id": thread_id}}
    
    graph, conn = build_banking_graph("official_checkpoints.db")
    
    if mode == "suspend":
        print("Worker [Process A]: 启动并触发转账审批中断...")
        graph.invoke({"messages": [{"role": "user", "content": "请帮我查询余额并转账 1000 元给 Alice"}]}, config=thread_config)
        snapshot = graph.get_state(thread_config)
        print(f"Worker [Process A]: 挂起节点 -> {snapshot.next}")
        assert "approval_node" in snapshot.next
        
    elif mode == "resume":
        print("Worker [Process B]: 从 DB 恢复检查点并继续审批...")
        snapshot = graph.get_state(thread_config)
        print(f"Worker [Process B]: 读取到挂起节点 -> {snapshot.next}")
        assert "approval_node" in snapshot.next
        
        resume_cmd = Command(resume={
            "approved": True,
            "tool_call_id": "call_trans_01",
            "tool_name": "execute_transfer",
            "args": {"amount": 1000.0, "recipient": "Alice", "idempotency_key": "idempotency-txn-day40-9999"}
        })
        res = graph.invoke(resume_cmd, config=thread_config)
        print("Worker [Process B]: 恢复执行完成，最终答复:", res["messages"][-1].content)
        
    conn.close()

if __name__ == "__main__":
    main()