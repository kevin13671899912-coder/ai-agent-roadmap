import sqlite3
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger("BankingBackend")

class ProductionBankingBackend:
    def __init__(self, db_path: str = "banking_ledger.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS accounts (id TEXT PRIMARY KEY, balance REAL);")
            conn.execute("CREATE TABLE IF NOT EXISTS ledger (idempotency_key TEXT PRIMARY KEY, result_json TEXT);")
            conn.execute("CREATE TABLE IF NOT EXISTS transactions (tx_id TEXT PRIMARY KEY, detail TEXT);")
            
            cursor = conn.execute("SELECT balance FROM accounts WHERE id = 'main'")
            if not cursor.fetchone():
                conn.execute("INSERT INTO accounts (id, balance) VALUES ('main', 5000.0)")
                conn.execute("INSERT INTO transactions (tx_id, detail) VALUES ('tx-001', 'Initial Deposit: 5000.0')")
                conn.commit()

    def get_balance(self) -> float:
        self._init_db()  # 确保表和初始数据存在
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT balance FROM accounts WHERE id = 'main'")
            row = cursor.fetchone()
            return row[0] if row else 0.0

    def get_transaction_history(self) -> list:
        self._init_db()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT tx_id, detail FROM transactions")
            return [{"tx_id": r[0], "detail": r[1]} for r in cursor.fetchall()]

    def execute_transfer(self, amount: float, recipient: str, idempotency_key: str) -> dict:
        self._init_db()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                cursor = conn.execute("SELECT result_json FROM ledger WHERE idempotency_key = ?", (idempotency_key,))
                row = cursor.fetchone()
                if row:
                    logger.info(f"🛡️ [Idempotency] 命中持久化键: {idempotency_key}")
                    return json.loads(row[0])

                cursor = conn.execute("SELECT balance FROM accounts WHERE id = 'main'")
                current_balance = cursor.fetchone()[0]

                if amount > current_balance:
                    return {"success": False, "reason": "INSUFFICIENT_FUNDS"}

                new_balance = current_balance - amount
                conn.execute("UPDATE accounts SET balance = ? WHERE id = 'main'", (new_balance,))
                
                result = {"success": True, "remaining_balance": new_balance, "transferred": amount, "recipient": recipient}
                conn.execute("INSERT INTO ledger (idempotency_key, result_json) VALUES (?, ?)", (idempotency_key, json.dumps(result)))
                conn.execute("INSERT INTO transactions (tx_id, detail) VALUES (?, ?)", (f"tx-{idempotency_key[-6:]}", f"Transferred {amount} to {recipient}"))
                
                conn.commit()
                return result
            except Exception as e:
                conn.rollback()
                raise e