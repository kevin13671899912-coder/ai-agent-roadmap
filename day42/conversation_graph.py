
import sqlite3
from typing import TypedDict, Optional, Annotated
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.sqlite import SqliteSaver

class ConversationState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    pending_call: Optional[dict]
    approval_result: Optional[dict]
    transaction_status: Optional[str]

def agent_node(state: ConversationState) -> ConversationState:
    messages = state["messages"]
    last_msg = messages[-1].content if messages else ""
    
    # 模拟故障恢复：如果恢复后发现有遗留的 pending_call，安全检查 Ledger
    pending = state.get("pending_call")
    if pending and not state.get("transaction_status"):
        tx_id = pending.get("transaction_id")
        # 检查后端 Ledger 是否已经执行过
        if check_ledger_exists(tx_id):
            return {
                "messages": [AIMessage(content=f"检测到恢复操作：交易 {tx_id} 此前已成功执行，已安全跳过重复扣款。")],
                "pending_call": None,
                "approval_result": None,
                "transaction_status": "COMPLETED"
            }

    if "转账" in last_msg:
        # 新增转账请求，初始化 pending_call
        return {
            "messages": [AIMessage(content="收到转账请求，请审批。")],
            "pending_call": {
                "tool_name": "execute_transfer",
                "amount": 1000,
                "recipient": "Alice",
                "transaction_id": "TX-1001"
            },
            "approval_result": None,
            "transaction_status": "PENDING_APPROVAL"
        }
    elif "余额" in last_msg or "查" in last_msg:
        return {
            "messages": [AIMessage(content="当前账户余额为 5000 元。")],
            # 确保只读请求不会继承或携带旧的 pending_call
            "pending_call": None,
            "approval_result": None
        }
    else:
        return {
            "messages": [AIMessage(content=f"已收到您的消息: {last_msg}")],
            "pending_call": None,
            "approval_result": None
        }

def approval_node(state: ConversationState) -> ConversationState:
    # 模拟用户审批批准
    return {
        "approval_result": {"approved": True},
        "transaction_status": "APPROVED"
    }

def execute_transfer_node(state: ConversationState) -> ConversationState:
    pending = state.get("pending_call")
    if not pending:
        return {}
    
    tx_id = pending["transaction_id"]
    
    # 幂等校验与执行
    if check_ledger_exists(tx_id):
        status = "COMPLETED"
    else:
        record_ledger(tx_id)
        status = "COMPLETED"

    # 关键机制：操作进入终态后，必须显式清空临时状态以防 Stale State 污染
    return {
        "messages": [AIMessage(content=f"转账 {pending['amount']} 元给 {pending['recipient']} 成功！")],
        "pending_call": None,       # 清理过期 pending_call
        "approval_result": None,    # 清理过期 approval_result
        "transaction_status": status
    }

def router_after_agent(state: ConversationState) -> str:
    if state.get("pending_call") and state.get("transaction_status") == "PENDING_APPROVAL":
        return "approval_node"
    return "finalize"

def router_after_approval(state: ConversationState) -> str:
    approval = state.get("approval_result")
    if approval and approval.get("approved"):
        return "execute_transfer_node"
    return "finalize"

def check_ledger_exists(tx_id: str) -> bool:
    with sqlite3.connect("day42_ledger.db") as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS ledger (tx_id TEXT PRIMARY KEY);")
        cursor = conn.execute("SELECT 1 FROM ledger WHERE tx_id = ?", (tx_id,))
        return cursor.fetchone() is not None

def record_ledger(tx_id: str):
    with sqlite3.connect("day42_ledger.db") as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS ledger (tx_id TEXT PRIMARY KEY);")
        conn.execute("INSERT OR IGNORE INTO ledger (tx_id) VALUES (?)", (tx_id,))
        conn.commit()

def build_conversation_graph(db_path: str = "day42_checkpoints.db"):
    builder = StateGraph(ConversationState)
    
    builder.add_node("agent", agent_node)
    builder.add_node("approval_node", approval_node)
    builder.add_node("execute_transfer_node", execute_transfer_node)
    builder.add_node("finalize", lambda s: s)
    
    builder.add_edge(START, "agent")
    builder.add_conditional_edges(
        "agent",
        router_after_agent,
        {
            "approval_node": "approval_node",
            "finalize": END
        }
    )
    builder.add_edge("approval_node", "execute_transfer_node")
    builder.add_edge("execute_transfer_node", END)
    
    conn = sqlite3.connect(db_path, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    return builder.compile(checkpointer=checkpointer), conn