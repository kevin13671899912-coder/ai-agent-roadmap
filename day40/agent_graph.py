import os
import sqlite3
import re
import uuid
from typing import TypedDict, Optional, Annotated
from langchain_core.messages import AIMessage, ToolMessage, BaseMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langgraph.graph.message import add_messages
from langgraph.types import interrupt, Command
from langgraph.checkpoint.sqlite import SqliteSaver

from banking_backend import ProductionBankingBackend
from policy import evaluate_policy, validate_approval

backend = ProductionBankingBackend()

@tool
def get_balance() -> dict:
    """查询当前账户余额"""
    return {"balance": backend.get_balance()}

@tool
def get_transaction_history() -> dict:
    """查询账户最近的交易历史流水"""
    return {"history": backend.get_transaction_history()}

@tool
def execute_transfer(amount: float, recipient: str, idempotency_key: str) -> dict:
    """执行向指定收款人转账的副作用操作"""
    return backend.execute_transfer(amount, recipient, idempotency_key)

tools = [get_balance, get_transaction_history, execute_transfer]
tool_node_executor = ToolNode(tools)

class PendingCallInfo(TypedDict):
    tool_call_id: str
    tool_name: str
    args: dict

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    pending_call: Optional[PendingCallInfo]
    approval_result: Optional[dict]
    filtered_ai_message: Optional[AIMessage]

def agent_node(state: AgentState) -> AgentState:
    messages = state["messages"]
    last_msg = messages[-1].content if messages else ""
    
    tool_calls = []
    if "历史" in last_msg or "流水" in last_msg:
        tool_calls.append({"id": "call_hist_01", "name": "get_transaction_history", "args": {}})
    elif "转账" in last_msg:
        # 动态解析用户请求中的转账金额
        match = re.search(r'(\d+)\s*元', last_msg)
        amount = float(match.group(1)) if match else 1000.0
        
        # 动态派生唯一交易 ID 与幂等键
        tx_id = f"txn-day40-{uuid.uuid4().hex[:6]}"
        idempotency_key = f"idempotency-{tx_id}"
        
        tool_calls.append({"id": "call_bal_02", "name": "get_balance", "args": {}})
        tool_calls.append({"id": "call_trans_01", "name": "execute_transfer", "args": {"amount": amount, "recipient": "Alice", "idempotency_key": idempotency_key}})
    else:
        tool_calls.append({"id": "call_bal_01", "name": "get_balance", "args": {}})

    ai_msg = AIMessage(content="根据您的请求，我将为您执行相应操作。", tool_calls=tool_calls)
    return {"messages": [ai_msg]}

def policy_gate_node(state: AgentState) -> AgentState:
    ai_msgs = [m for m in state["messages"] if isinstance(m, AIMessage)]
    if not ai_msgs:
        return {}
    last_ai = ai_msgs[-1]
    
    readonly_calls, pending = evaluate_policy(last_ai.tool_calls)
    
    dropped_messages = []
    for tc in last_ai.tool_calls:
        if tc not in readonly_calls and (not pending or tc["id"] != pending["tool_call_id"]):
            dropped_messages.append(ToolMessage(content="ERROR: POLICY_GATE_REJECTED", tool_call_id=tc["id"]))

    filtered_ai = AIMessage(content=last_ai.content, tool_calls=readonly_calls)
    
    updates = {
        "filtered_ai_message": filtered_ai,
        "pending_call": pending
    }
    if dropped_messages:
        updates["messages"] = dropped_messages
    return updates

def tool_execution_router(state: AgentState) -> str:
    filtered_ai = state.get("filtered_ai_message")
    if filtered_ai and len(filtered_ai.tool_calls) > 0:
        return "run_readonly_tools"
    if state.get("pending_call"):
        return "go_to_approval"
    return "final_response"

def readonly_tool_node(state: AgentState) -> AgentState:
    filtered_ai = state["filtered_ai_message"]
    res = tool_node_executor.invoke({"messages": [filtered_ai]})
    return {"messages": res["messages"]}

def approval_node(state: AgentState) -> AgentState:
    p_call = state["pending_call"]
    approval_data = interrupt({
        "tool_call_id": p_call["tool_call_id"],
        "tool_name": p_call["tool_name"],
        "args": p_call["args"],
        "question": f"请求向 {p_call['args'].get('recipient')} 转账 {p_call['args'].get('amount')} 元，是否批准？"
    })
    return {"approval_result": approval_data}

def revalidate_node(state: AgentState) -> AgentState:
    approval = state.get("approval_result", {})
    p_call = state.get("pending_call")
    current_balance = backend.get_balance()
    
    status = validate_approval(approval, p_call, current_balance)
    
    if status != "PASSED":
        err_msg = ToolMessage(content=f"ERROR: {status}", tool_call_id=p_call["tool_call_id"])
        return {"messages": [err_msg]}

    authorized_ai = AIMessage(content="Authorized execution", tool_calls=[{
        "id": p_call["tool_call_id"],
        "name": p_call["tool_name"],
        "args": p_call["args"]
    }])
    return {"filtered_ai_message": authorized_ai}

def post_revalidation_router(state: AgentState) -> str:
    last_msg = state["messages"][-1] if state["messages"] else None
    if isinstance(last_msg, ToolMessage) and "ERROR" in str(last_msg.content):
        return "final_response"
    return "execute_via_tool_node"

def authorized_tool_node(state: AgentState) -> AgentState:
    filtered_ai = state["filtered_ai_message"]
    res = tool_node_executor.invoke({"messages": [filtered_ai]})
    return {"messages": res["messages"]}

def final_response_node(state: AgentState) -> AgentState:
    messages = state["messages"]
    last_msg = messages[-1] if messages else None
    
    if isinstance(last_msg, ToolMessage):
        content_str = str(last_msg.content)
        if "ERROR" in content_str:
            reply = AIMessage(content=f"抱歉，您的请求未能完成，原因：{content_str}")
        elif "remaining_balance" in content_str or "transferred" in content_str:
            bal = backend.get_balance()
            reply = AIMessage(content=f"转账执行成功！当前账户余额为 {bal} 元。")
        elif "balance" in content_str:
            reply = AIMessage(content=f"查询成功，{content_str}")
        elif "history" in content_str:
            reply = AIMessage(content=f"交易历史查询成功：{content_str}")
        else:
            reply = AIMessage(content=f"操作已执行，结果：{content_str}")
    else:
        reply = AIMessage(content="您的请求已处理完毕。")
        
    return {"messages": [reply]}

def build_banking_graph(db_path: str = "official_checkpoints.db"):
    builder = StateGraph(AgentState)
    
    builder.add_node("agent", agent_node)
    builder.add_node("policy_gate", policy_gate_node)
    builder.add_node("readonly_tool_node", readonly_tool_node)
    builder.add_node("approval_node", approval_node)
    builder.add_node("revalidate_node", revalidate_node)
    builder.add_node("authorized_tool_node", authorized_tool_node)
    builder.add_node("final_response", final_response_node)
    
    builder.add_edge(START, "agent")
    builder.add_edge("agent", "policy_gate")
    
    builder.add_conditional_edges(
        "policy_gate",
        tool_execution_router,
        {
            "run_readonly_tools": "readonly_tool_node",
            "go_to_approval": "approval_node",
            "final_response": "final_response"
        }
    )
    
    builder.add_conditional_edges(
        "readonly_tool_node",
        lambda s: "go_to_approval" if s.get("pending_call") else "final_response",
        {
            "go_to_approval": "approval_node",
            "final_response": "final_response"
        }
    )
    
    builder.add_edge("approval_node", "revalidate_node")
    
    builder.add_conditional_edges(
        "revalidate_node",
        post_revalidation_router,
        {
            "execute_via_tool_node": "authorized_tool_node",
            "final_response": "final_response"
        }
    )
    
    builder.add_edge("authorized_tool_node", "final_response")
    builder.add_edge("final_response", END)
    
    conn = sqlite3.connect(db_path, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    return builder.compile(checkpointer=checkpointer), conn