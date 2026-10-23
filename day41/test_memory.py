
import sys
from memory_service import save_preference, get_preference

def run_tests():
    print("=" * 70)
    print("Day 41 Memory Engineering & Policy Gate Integration Tests")
    print("=" * 70)

    # ----------------------------------------------------
    # 场景 1: user_001 保存并读取合法的 CNY 偏好
    # ----------------------------------------------------
    print("\n[Test 1] user_001 saving valid CNY preference...")
    candidate_valid = {
        "type": "preference",
        "key": "preferred_currency",
        "value": "CNY"
    }
    success = save_preference("user_001", candidate_valid)
    assert success == True, "Valid preference should be saved successfully."
    
    val = get_preference("user_001", "preferred_currency")
    print(f"-> user_001 retrieved preference: {val}")
    assert val == "CNY"

    # ----------------------------------------------------
    # 场景 2: 验证数据隔离 (user_002 不能读取 user_001 的偏好)
    # ----------------------------------------------------
    print("\n[Test 2] Data isolation test between user_001 and user_002...")
    val_002 = get_preference("user_002", "preferred_currency")
    print(f"-> user_002 retrieved preference: {val_002}")
    assert val_002 is None, "Isolation broken! user_002 should not see user_001's preferences."

    # ----------------------------------------------------
    # 场景 3: 拒绝未经授权的字段 (例如 LLM 提出 account_balance)
    # ----------------------------------------------------
    print("\n[Test 3] Rejecting unauthorized field (account_balance)...")
    candidate_bad_key = {
        "type": "preference",
        "key": "account_balance",
        "value": "CNY"
    }
    success_bk = save_preference("user_001", candidate_bad_key)
    assert success_bk == False, "Policy Gate must reject unknown keys."

    # ----------------------------------------------------
    # 场景 4: 拒绝非法的取值 (例如非法币种 EUR)
    # ----------------------------------------------------
    print("\n[Test 4] Rejecting illegal value (EUR)...")
    candidate_bad_val = {
        "type": "preference",
        "key": "preferred_currency",
        "value": "EUR"
    }
    success_bv = save_preference("user_001", candidate_bad_val)
    assert success_bv == False, "Policy Gate must reject unsupported values."

    # ----------------------------------------------------
    # 场景 5: 拒绝候选记忆中伪造的 user_id
    # ----------------------------------------------------
    print("\n[Test 5] Rejecting candidate trying to forge user_id...")
    candidate_forgery = {
        "type": "preference",
        "key": "preferred_currency",
        "value": "USD",
        "user_id": "user_evil"
    }
    # 传入可信的 user_001，但候选内部携带 user_evil 企图注入
    success_forge = save_preference("user_001", candidate_forgery)
    assert success_forge == False, "Policy Gate must reject candidates containing user_id!"

    print("\n" + "=" * 70)
    print("PASS: Day41 Memory & Policy integration tests passed successfully.")
    print("=" * 70)

if __name__ == "__main__":
    run_tests()