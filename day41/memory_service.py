import logging
from langgraph.store.memory import InMemoryStore
from memory_policy import validate_memory_candidate

logger = logging.getLogger("MemoryService")

# 初始化 LangGraph 内存存储（生产环境可换成 PostgresStore 等持久化实现）
memory_store = InMemoryStore()

def save_preference(user_id: str, candidate: dict) -> bool:
    """
    保存用户偏好。
    注意：user_id 必须由可信的应用上下文中传入，绝不采信 LLM 生成的身份。
    """
    if not user_id:
        logger.error("🛑 [Memory Service] 拒绝保存：未提供有效的认证 user_id。")
        return False

    # 执行 Memory Policy Gate 校验
    if not validate_memory_candidate(candidate):
        return False

    # 构建严格隔离的命名空间：("users", user_id, "preferences")
    namespace = ("users", user_id, "preferences")
    key = candidate["key"]
    value_payload = {"value": candidate["value"]}

    # 调用 LangGraph Store API 写入
    memory_store.put(namespace, key, value_payload)
    logger.info(f"💾 [Memory Service] 成功写入长期记忆 -> Namespace: {namespace}, Key: {key}")
    return True

def get_preference(user_id: str, key: str):
    """
    安全读取指定用户的长期记忆。
    """
    if not user_id:
        return None

    namespace = ("users", user_id, "preferences")
    item = memory_store.get(namespace, key)
    
    if item and item.value:
        return item.value.get("value")
    return None