
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger("PolicyGate")

def evaluate_policy(tool_calls: list) -> tuple:
    readonly_calls = []
    pending_approval = None

    for tc in tool_calls:
        name = tc.get("name")
        if name in ["get_balance", "get_transaction_history"]:
            readonly_calls.append(tc)
        elif name == "execute_transfer":
            if not pending_approval:
                pending_approval = {
                    "tool_call_id": tc.get("id"),
                    "tool_name": name,
                    "args": tc.get("args")
                }
        else:
            logger.warning(f"🛑 [Policy Gate] 未知工具被拦截: {name}")

    return readonly_calls, pending_approval

def validate_approval(approval_result: dict, pending_call: dict, current_balance: float) -> str:
    if not approval_result or not approval_result.get("approved", False):
        logger.warning("🛑 [Revalidation] 用户拒绝了审批或未批准。")
        return "USER_REJECTED"

    if not pending_call:
        return "NO_PENDING_CALL"

    if approval_result.get("tool_call_id") != pending_call["tool_call_id"] or \
       approval_result.get("tool_name") != pending_call["tool_name"] or \
       approval_result.get("args") != pending_call["args"]:
        logger.warning("🛑 [Revalidation] 审批参数或工具名称与挂起载荷不匹配！")
        return "PARAMETER_MISMATCH"

    required_amount = pending_call["args"].get("amount", 0.0)
    if required_amount > current_balance:
        logger.warning(f"🛑 [Revalidation] 余额不足: 当前余额 {current_balance} < 需要金额 {required_amount}")
        return "INSUFFICIENT_FUNDS"

    return "PASSED"
