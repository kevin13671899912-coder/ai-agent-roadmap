%%writefile agent_graph.py
import os
import sqlite3
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
    # 模拟真实 LLM 根据上下文动态选择工具（实际生产可挂载 ChatOpenAI / ChatAnthropic）
    last_msg = messages[-1].content if messages else ""
    
    tool_calls = []
    if "历史" in last_msg or "流水" in last_msg:
        tool_calls.append({"id": "call_hist_01", "name": "get_transaction_history", "args": {}})
    elif "转账" in last_msg:
        tool_calls.append({"id": "call_bal_02", "name": "get_balance", "args": {}})
        tool_calls.append({"id": "call_trans_01", "name": "execute_transfer", "args": {"amount": 1000.0, "recipient": "Alice", "idempotency_key": "idempotency-txn-day40-01"}})
    else:
        tool_calls.append({"id": "call_bal_01", "name": "get_balance", "args": {}})

    ai_msg = AIMessage(content=f"根据您的请求，我将为您执行相应操作。", tool_calls=tool_calls)
    return {"messages": [ai_msg]}

def policy_gate_node(state: AgentState) -> AgentState:
    last_ai = [m for m in state["messages"] if isinstance(m, AIMessage)][-1]
    readonly_calls, pending = evaluate_policy(last_ai.tool_calls)
    
    filtered_ai = AIMessage(content=last_ai.content, tool_calls=readonly_calls)
    return {
        "filtered_ai_message": filtered_ai,
        "pending_call": pending
    }

def tool_execution_router(state: AgentState) -> str:
    filtered_ai = state.get("filtered_ai_message")
    # 如果有只读工具优先执行
    if filtered_ai and len(filtered_ai.tool_calls) > 0:
        return "run_readonly_tools"
    # 如果存在待审批副作用工具，进入审批节点
    if state.get("pending_call"):
        return "go_to_approval"
    return "finish_agent"

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

    # 校验通过，构建合法的受信任 Tool Call 准备交由 ToolNode 执行
    authorized_ai = AIMessage(content="Authorized execution", tool_calls=[{
        "id": p_call["tool_call_id"],
        "name": p_call["tool_name"],
        "args": p_call["args"]
    }])
    return {"filtered_ai_message": authorized_ai}

def post_revalidation_router(state: AgentState) -> str:
    last_msg = state["messages"][-1] if state["messages"] else None
    if isinstance(last_msg, ToolMessage) and "ERROR" in str(last_msg.content):
        return "skip_tools"
    return "execute_via_tool_node"

def authorized_tool_node(state: AgentState) -> AgentState:
    filtered_ai = state["filtered_ai_message"]
    res = tool_node_executor.invoke({"messages": [filtered_ai]})
    return {"messages": res["messages"]}

def build_banking_graph(db_path: str = "official_checkpoints.db"):
    builder = StateGraph(AgentState)
    
    builder.add_node("agent", agent_node)
    builder.add_node("policy_gate", policy_gate_node)
    builder.add_node("readonly_tool_node", readonly_tool_node)
    builder.add_node("approval_node", approval_node)
    builder.add_node("revalidate_node", revalidate_node)
    builder.add_node("authorized_tool_node", authorized_tool_node)
    
    builder.add_edge(START, "agent")
    builder.add_edge("agent", "policy_gate")
    
    builder.add_conditional_edges(
        "policy_gate",
        tool_execution_router,
        {
            "run_readonly_tools": "readonly_tool_node",
            "go_to_approval": "approval_node",
            "finish_agent": END
        }
    )
    
    # 只读工具执行完后，若无高危操作则结束，若有则进审批
    builder.add_conditional_edges(
        "readonly_tool_node",
        lambda s: "go_to_approval" if s.get("pending_call") else "finish_agent",
        {
            "go_to_approval": "approval_node",
            "finish_agent": END
        }
    )
    
    builder.add_edge("approval_node", "revalidate_node")
    
    builder.add_conditional_edges(
        "revalidate_node",
        post_revalidation_router,
        {
            "execute_via_tool_node": "authorized_tool_node",
            "skip_tools": END
        }
    )
    
    builder.add_edge("authorized_tool_node", END)
    
    conn = sqlite3.connect(db_path, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    return builder.compile(checkpointer=checkpointer), conn