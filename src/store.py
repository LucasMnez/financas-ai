import sqlite3
from enum import Enum
from pathlib import Path
import pandas as pd

DEFAULT_DB = Path(__file__).parent.parent / "data" / "transactions.db"


class UserStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    ADMIN = "admin"


SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    value REAL NOT NULL,
    date TEXT NOT NULL,
    chat_id INTEGER,
    source TEXT DEFAULT 'telegram',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER UNIQUE NOT NULL,
    status TEXT DEFAULT 'pending',
    username TEXT,
    registered_at TEXT DEFAULT (datetime('now')),
    activated_at TEXT
);
"""


class TransactionStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB):
        self.db_path = str(db_path)
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    def _conn(self):
        return sqlite3.connect(self.db_path)

    # ── Transactions ──────────────────────────────────────────────────────────

    def add_transaction(
        self, type: str, description: str, category: str,
        value: float, date: str, chat_id: int = 0,
    ) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO transactions (type, description, category, value, date, chat_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (type, description, category, value, date, chat_id),
            )
            return cur.lastrowid

    def get_transactions_df(self, year: int, month: int, type: str) -> pd.DataFrame:
        prefix = f"{year}-{month:02d}"
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT description, date, category, value FROM transactions "
                "WHERE type = ? AND date LIKE ?",
                (type, f"{prefix}%"),
            ).fetchall()
        if not rows:
            return pd.DataFrame(columns=["DESCRIÇÃO", "VENCIMENTO", "CATEGORIA", "VALOR"])
        df = pd.DataFrame(rows, columns=["DESCRIÇÃO", "VENCIMENTO", "CATEGORIA", "VALOR"])
        df["VENCIMENTO"] = pd.to_datetime(df["VENCIMENTO"])
        return df

    # ── Users ─────────────────────────────────────────────────────────────────

    def get_user(self, chat_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT chat_id, status, username, registered_at FROM users WHERE chat_id = ?",
                (chat_id,)
            ).fetchone()
        if not row:
            return None
        return dict(zip(["chat_id", "status", "username", "registered_at"], row))

    def upsert_user(self, chat_id: int, status: UserStatus, username: str = "") -> None:
        with self._conn() as conn:
            exists = conn.execute(
                "SELECT id FROM users WHERE chat_id = ?", (chat_id,)
            ).fetchone()
            if exists:
                if status == UserStatus.ACTIVE:
                    conn.execute(
                        "UPDATE users SET status = ?, activated_at = datetime('now') WHERE chat_id = ?",
                        (status, chat_id)
                    )
                else:
                    conn.execute(
                        "UPDATE users SET status = ? WHERE chat_id = ?", (status, chat_id)
                    )
            else:
                conn.execute(
                    "INSERT INTO users (chat_id, status, username) VALUES (?, ?, ?)",
                    (chat_id, status, username)
                )

    def list_pending_users(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT chat_id, username, registered_at FROM users WHERE status = 'pending'"
            ).fetchall()
        return [dict(zip(["chat_id", "username", "registered_at"], r)) for r in rows]
