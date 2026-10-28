import sys
import os
from conversation_graph import build_conversation_graph
from langgraph.types import Command
from langchain_core.messages import HumanMessage

def main():
    mode = sys.argv[1] # "suspend" or "resume"
    thread_id = sys.argv[2]
    thread_config = {"configurable": {"thread_id": thread_id}}
    
    graph, conn = build_conversation_graph("day42_checkpoints.db")
    
    if mode == "suspend":
        print("Worker [Process A]: 启动并触发转账审批中断...")
        graph.invoke({"messages": [HumanMessage(content="请帮我转账 1000 元给 Alice")]}, config=thread_config)
        snapshot = graph.get_state(thread_config)
        print(f"Worker [Process A]: 挂起节点 -> {snapshot.next}")
        assert "approval_node" in snapshot.next
        
    elif mode == "resume":
        print("Worker [Process B]: 从 DB 恢复检查点并继续审批...")
        snapshot = graph.get_state(thread_config)
        print(f"Worker [Process B]: 读取到挂起节点 -> {snapshot.next}")
        assert "approval_node" in snapshot.next
        
        # 使用 Command(resume=...) 注入可信批准决策
        resume_cmd = Command(resume={"approved": True})
        res = graph.invoke(resume_cmd, config=thread_config)
        print("Worker [Process B]: 恢复执行完成，最终答复:", res["messages"][-1].content)
        
    conn.close()

if __name__ == "__main__":
    main()