import sqlite3
import uuid
import json
from typing import TypedDict, Optional, Annotated
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.types import interrupt
from langgraph.checkpoint.sqlite import SqliteSaver

class ConversationState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    pending_call: Optional[dict]
    approval_result: Optional[dict]
    transaction_status: Optional[str]

def agent_node(state: ConversationState) -> ConversationState:
    messages = state["messages"]
    last_msg = messages[-1].content if messages else ""
    
    # 检查是否存在未完成的挂起操作（如故障恢复场景）
    pending = state.get("pending_call")
    if pending and not state.get("transaction_status"):
        tx_id = pending.get("transaction_id")
        if check_ledger_exists(tx_id):
            return {
                "messages": [AIMessage(content=f"恢复检测：交易 {tx_id} 此前已成功执行，已安全拦截重复扣款。")],
                "pending_call": None,
                "approval_result": None,
                "transaction_status": "COMPLETED"
            }

    if "转账" in last_msg:
        # 为每笔新业务生成唯一的稳定交易 ID 与幂等键
        tx_id = f"txn-day42-{uuid.uuid4().hex[:6]}"
        return {
            "messages": [AIMessage(content=f"已生成转账请求 (ID: {tx_id})，等待人工审批。")],
            "pending_call": {
                "tool_name": "execute_transfer",
                "amount": 1000,
                "recipient": "Alice",
                "transaction_id": tx_id,
                "idempotency_key": f"idempotency-{tx_id}"
            },
            "approval_result": None,
            "transaction_status": "PENDING_APPROVAL"
        }
    elif "余额" in last_msg or "查" in last_msg:
        return {
            "messages": [AIMessage(content="当前账户余额为 5000 元。")],
            "pending_call": None,
            "approval_result": None,
            "transaction_status": "IDLE"
        }
    else:
        return {
            "messages": [AIMessage(content=f"已收到您的消息: {last_msg}")],
            "pending_call": None,
            "approval_result": None,
            "transaction_status": "IDLE"
        }

def approval_node(state: ConversationState) -> ConversationState:
    p_call = state["pending_call"]
    # 使用 LangGraph interrupt() 挂起等待可信审批输入，而不是自动批准
    approval_data = interrupt({
        "transaction_id": p_call["transaction_id"],
        "amount": p_call["amount"],
        "recipient": p_call["recipient"],
        "question": f"请确认向 {p_call['recipient']} 转账 {p_call['amount']} 元？"
    })
    return {
        "approval_result": approval_data,
        "transaction_status": "APPROVED" if approval_data.get("approved") else "REJECTED"
    }

def execute_transfer_node(state: ConversationState) -> ConversationState:
    approval = state.get("approval_result", {})
    if not approval.get("approved"):
        return {
            "messages": [AIMessage(content="转账请求已被拒绝，未发生扣款。")],
            "pending_call": None,
            "approval_result": None,
            "transaction_status": "REJECTED"
        }

    pending = state.get("pending_call")
    if not pending:
        return {}
    
    tx_id = pending["transaction_id"]
    idempotency_key = pending["idempotency_key"]
    
    # 具备事务排他锁与 Ledger 结果缓存的安全执行
    with sqlite3.connect("day42_ledger.db") as conn:
        conn.execute("BEGIN IMMEDIATE;")
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS ledger (tx_id TEXT PRIMARY KEY, idempotency_key TEXT, details TEXT);")
            cursor = conn.execute("SELECT details FROM ledger WHERE tx_id = ?", (tx_id,))
            row = cursor.fetchone()
            
            if row:
                # 幂等命中：直接返回已有结果，绝不重复扣款
                result_msg = f"交易 {tx_id} 幂等重试成功（不重复扣款）。"
            else:
                # 首次执行：写入 Ledger 记录副作用
                details = json.dumps({"amount": pending["amount"], "recipient": pending["recipient"]})
                conn.execute("INSERT INTO ledger (tx_id, idempotency_key, details) VALUES (?, ?, ?)", (tx_id, idempotency_key, details))
                conn.commit()
                result_msg = f"转账 {pending['amount']} 元给 {pending['recipient']} 成功！(ID: {tx_id})"
        except Exception as e:
            conn.rollback()
            raise e

    # 终态清理：显式清空临时状态，防止 Stale State 污染下一轮对话
    return {
        "messages": [AIMessage(content=result_msg)],
        "pending_call": None,
        "approval_result": None,
        "transaction_status": "COMPLETED"
    }

def router_after_agent(state: ConversationState) -> str:
    if state.get("pending_call") and state.get("transaction_status") == "PENDING_APPROVAL":
        return "approval_node"
    return "finalize"

def router_after_approval(state: ConversationState) -> str:
    status = state.get("transaction_status")
    if status == "APPROVED":
        return "execute_transfer_node"
    return "finalize"

def check_ledger_exists(tx_id: str) -> bool:
    with sqlite3.connect("day42_ledger.db") as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS ledger (tx_id TEXT PRIMARY KEY, idempotency_key TEXT, details TEXT);")
        cursor = conn.execute("SELECT 1 FROM ledger WHERE tx_id = ?", (tx_id,))
        return cursor.fetchone() is not None

def get_ledger_count() -> int:
    with sqlite3.connect("day42_ledger.db") as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS ledger (tx_id TEXT PRIMARY KEY, idempotency_key TEXT, details TEXT);")
        cursor = conn.execute("SELECT COUNT(*) FROM ledger;")
        row = cursor.fetchone()
        return row[0] if row else 0

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
    builder.add_conditional_edges(
        "approval_node",
        router_after_approval,
        {
            "execute_transfer_node": "execute_transfer_node",
            "finalize": END
        }
    )
    builder.add_edge("execute_transfer_node", END)
    
    conn = sqlite3.connect(db_path, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    return builder.compile(checkpointer=checkpointer), conn