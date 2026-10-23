%%writefile policy.py
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger("PolicyGate")

def evaluate_policy(tool_calls: list) -> tuple:
    """
    统一 Policy Gate: 将工具调用拆分为安全只读与高危副作用（待审批）
    """
    readonly_calls = []
    pending_approval = None

    for tc in tool_calls:
        name = tc.get("name")
        if name in ["get_balance", "get_transaction_history"]:
            readonly_calls.append(tc)
        elif name == "execute_transfer":
            # 默认拦截第一个高危副作用工具作为审批对象
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
    """
    恢复后执行严格的安全重新校验 (Revalidation)
    """
    if not approval_result or not approval_result.get("approved", False):
        logger.warning("🛑 [Revalidation] 用户拒绝了审批或未批准。")
        return "USER_REJECTED"

    if not pending_call:
        return "NO_PENDING_CALL"

    # 参数防篡改校验
    if approval_result.get("tool_call_id") != pending_call["tool_call_id"] or \
       approval_result.get("args") != pending_call["args"]:
        logger.warning("🛑 [Revalidation] 审批参数与挂起载荷不匹配！")
        return "PARAMETER_MISMATCH"

    # 暂停期间余额是否下降不足
    required_amount = pending_call["args"].get("amount", 0.0)
    if required_amount > current_balance:
        logger.warning(f"🛑 [Revalidation] 余额不足: 当前余额 {current_balance} < 需要金额 {required_amount}")
        return "INSUFFICIENT_FUNDS"

    return "PASSED"