import sys
import logging
import sqlite3
import os
import json
from typing import Dict, Any, Optional, Annotated
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langgraph.graph.message import add_messages
from langgraph.types import interrupt, Command
from langchain_core.messages import AIMessage, ToolMessage, BaseMessage
from langchain_core.tools import tool
from langgraph.checkpoint.sqlite import SqliteSaver

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger("DurableExecutionProduction")

LEDGER_DB = "banking_ledger.db"
CHECKPOINT_DB = "official_checkpoints.db"

class ProductionBankingBackend:
    def __init__(self, db_path: str = LEDGER_DB):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS accounts (id TEXT PRIMARY KEY, balance REAL);")
            conn.execute("CREATE TABLE IF NOT EXISTS ledger (idempotency_key TEXT PRIMARY KEY, result_json TEXT);")
            cursor = conn.execute("SELECT balance FROM accounts WHERE id = 'main'")
            if not cursor.fetchone():
                conn.execute("INSERT INTO accounts (id, balance) VALUES ('main', 5000.0)")

    def get_balance(self) -> float:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT balance FROM accounts WHERE id = 'main'")
            row = cursor.fetchone()
            return row[0] if row else 0.0

    def execute_transfer(self, amount: float, recipient: str, idempotency_key: str) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                cursor = conn.execute("SELECT result_json FROM ledger WHERE idempotency_key = ?", (idempotency_key,))
                row = cursor.fetchone()
                if row:
                    return json.loads(row[0])

                cursor = conn.execute("SELECT balance FROM accounts WHERE id = 'main'")
                current_balance = cursor.fetchone()[0]

                if amount > current_balance:
                    return {"success": False, "reason": "INSUFFICIENT_FUNDS"}

                new_balance = current_balance - amount
                conn.execute("UPDATE accounts SET balance = ? WHERE id = 'main'", (new_balance,))

                result = {"success": True, "remaining_balance": new_balance, "transferred": amount, "recipient": recipient}
                conn.execute("INSERT INTO ledger (idempotency_key, result_json) VALUES (?, ?)", (idempotency_key, json.dumps(result)))
                conn.commit()
                return result
            except Exception as e:
                conn.rollback()
                raise e

@tool
def get_balance() -> dict:
    """查询当前账户余额"""
    backend = ProductionBankingBackend()
    return {"balance": backend.get_balance()}

@tool
def execute_transfer(amount: float, recipient: str, idempotency_key: str) -> dict:
    """执行高危副作用转账工具"""
    backend = ProductionBankingBackend()
    return backend.execute_transfer(amount, recipient, idempotency_key)

tools = [get_balance, execute_transfer]
tool_node_executor = ToolNode(tools)

class PendingCallInfo(TypedDict):
    tool_call_id: str
    tool_name: str
    args: Dict[str, Any]

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    pending_call: Optional[PendingCallInfo]
    approval_result: Optional[Dict[str, Any]]
    filtered_ai_message: Optional[AIMessage]

def agent_node(state: AgentState) -> AgentState:
    ai_msg = AIMessage(
        content="请帮我查询余额并转账 1000 元给 Alice。",
        tool_calls=[
            {"id": "call_bal_01", "name": "get_balance", "args": {}},
            {"id": "call_trans_01", "name": "execute_transfer", "args": {"amount": 1000.0, "recipient": "Alice", "idempotency_key": "idempotency-txn-2026-9988"}}
        ]
    )
    return {"messages": [ai_msg]}

def policy_gate_node(state: AgentState) -> AgentState:
    last_message = [m for m in state["messages"] if isinstance(m, AIMessage)][-1]
    allowed_calls, pending = [], None
    for tc in last_message.tool_calls:
        if tc["name"] == "get_balance":
            allowed_calls.append(tc)
        elif tc["name"] == "execute_transfer":
            pending = {"tool_call_id": tc["id"], "tool_name": tc["name"], "args": tc["args"]}
    return {"filtered_ai_message": AIMessage(content=last_message.content, tool_calls=allowed_calls), "pending_call": pending}

def approval_node(state: AgentState) -> AgentState:
    p_call = state["pending_call"]
    approval_data = interrupt({"tool_call_id": p_call["tool_call_id"], "tool_name": p_call["tool_name"], "args": p_call["args"], "question": "是否批准这笔高危转账？"})
    return {"approval_result": approval_data}

def revalidate_node(state: AgentState) -> AgentState:
    approval = state.get("approval_result", {})
    p_call = state.get("pending_call")
    if not approval.get("approved", False):
        return {"messages": [ToolMessage(content="ERROR: USER_REJECTED_APPROVAL", tool_call_id=p_call["tool_call_id"])]}
    if approval.get("tool_call_id") != p_call["tool_call_id"] or approval.get("args") != p_call["args"]:
        return {"messages": [ToolMessage(content="ERROR: APPROVAL_PARAMETER_MISMATCH", tool_call_id=p_call["tool_call_id"])]}

    backend = ProductionBankingBackend()
    if p_call["args"]["amount"] > backend.get_balance():
        return {"messages": [ToolMessage(content="ERROR: CANCELLED_DUE_TO_BALANCE_DROPPED", tool_call_id=p_call["tool_call_id"])]}

    return {"filtered_ai_message": AIMessage(content="Authorized execution", tool_calls=[{"id": p_call["tool_call_id"], "name": p_call["tool_name"], "args": p_call["args"]}])}

def tool_execution_router(state: AgentState) -> str:
    return "run_readonly_tools" if state.get("filtered_ai_message") and state.get("filtered_ai_message").tool_calls and state.get("pending_call") else "go_to_approval"

def post_revalidation_router(state: AgentState) -> str:
    last_msg = state["messages"][-1] if state["messages"] else None
    return "skip_tools" if isinstance(last_msg, ToolMessage) and "ERROR" in str(last_msg.content) else "execute_via_tool_node"

def build_graph_with_official_sqlite(db_path: str = CHECKPOINT_DB):
    builder = StateGraph(AgentState)
    builder.add_node("agent", agent_node)
    builder.add_node("policy_gate", policy_gate_node)
    builder.add_node("readonly_tool_node", lambda s: {"messages": tool_node_executor.invoke({"messages": [s["filtered_ai_message"]]})["messages"]})
    builder.add_node("approval_node", approval_node)
    builder.add_node("revalidate_node", revalidate_node)
    builder.add_node("tool_node", lambda s: {"messages": tool_node_executor.invoke({"messages": [s["filtered_ai_message"]]})["messages"]})
    builder.add_node("skip_node", lambda s: {})

    builder.add_edge(START, "agent")
    builder.add_edge("agent", "policy_gate")
    builder.add_conditional_edges("policy_gate", tool_execution_router, {"run_readonly_tools": "readonly_tool_node", "go_to_approval": "approval_node"})
    builder.add_edge("readonly_tool_node", "approval_node")
    builder.add_edge("approval_node", "revalidate_node")
    builder.add_conditional_edges("revalidate_node", post_revalidation_router, {"execute_via_tool_node": "tool_node", "skip_tools": "skip_node"})
    builder.add_edge("tool_node", END)
    builder.add_edge("skip_node", END)

    conn = sqlite3.connect(db_path, check_same_thread=False)
    return builder.compile(checkpointer=SqliteSaver(conn)), conn
