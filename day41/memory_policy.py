import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger("MemoryPolicyGate")

# 定义系统白名单与约束
ALLOWED_KEYS = {"preferred_currency"}
ALLOWED_VALUES = {"CNY", "USD"}

def validate_memory_candidate(candidate: dict) -> bool:
    """
    Memory Policy Gate: 拦截并验证 LLM 提取的候选记忆，
    绝不允许 LLM 绕过代码自主决定敏感字段或伪造身份。
    """
    if not isinstance(candidate, dict):
        logger.warning("🛑 [Memory Policy] 拒绝：候选记忆必须是字典格式。")
        return False

    # 检查必要字段
    key = candidate.get("key")
    value = candidate.get("value")
    c_type = candidate.get("type")

    if not key or not value or c_type != "preference":
        logger.warning(f"🛑 [Memory Policy] 拒绝：缺少必要字段或类型错误 -> {candidate}")
        return False

    # 校验字段是否在白名单内
    if key not in ALLOWED_KEYS:
        logger.warning(f"🛑 [Memory Policy] 拒绝：非法的记忆 Key -> {key}")
        return False

    # 校验取值是否在允许范围内
    if value not in ALLOWED_VALUES:
        logger.warning(f"🛑 [Memory Policy] 拒绝：非法的记忆 Value -> {value}")
        return False

    # 严禁候选记忆自主决定或篡改 user_id
    if "user_id" in candidate:
        logger.warning("🛑 [Memory Policy] 拒绝：候选记忆试图自主指定或伪造 user_id！")
        return False

    logger.info(f"✅ [Memory Policy] 验证通过: key={key}, value={value}")
    return True