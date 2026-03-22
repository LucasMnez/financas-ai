# Telegram Financial Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bot Telegram pessoal/multi-usuário que aceita lançamentos financeiros em linguagem natural, responde perguntas via IA e tem fluxo de cadastro com confirmação PIX manual — rodando em um único container Docker na VPS Hostinger.

**Architecture:** `python-telegram-bot` (v20, async) roda em polling mode, recebe mensagens e roteia para `BotHandler` que gerencia estados de usuário (SQLite), interpreta intenções com Claude Haiku, executa lógica financeira e retorna a resposta. Tudo em Python puro — sem Node.js, sem webhook, sem QR code.

**Tech Stack:** Python 3.10 · python-telegram-bot v20 · SQLite · Anthropic Claude API · Docker · python-dotenv

---

## Arquitetura de Arquivos

```
financas-ai/
  src/
    loader.py          # existente — sem mudanças
    analyzer.py        # modificar: aceitar income_df=None (Task 1)
    assistant.py       # existente — sem mudanças
    store.py           # NOVO: SQLite (transações + usuários por chat_id)
    parser.py          # NOVO: classifica mensagem → intent via Claude Haiku
    bot_handler.py     # NOVO: estados de usuário, lógica financeira, comandos admin
  bot.py               # NOVO: entry point Telegram (polling loop)
  Dockerfile           # NOVO: imagem Python única
  docker-compose.yml   # NOVO: serviço único
  .env                 # TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID, PIX_KEY, PIX_AMOUNT, ANTHROPIC_API_KEY
  .env.example         # NOVO
  main.py              # existente — CLI local continua funcionando
  data/                # existente — CSVs + transactions.db
  tests/
    test_store.py      # NOVO
    test_parser.py     # NOVO
    test_bot_handler.py  # NOVO
```

**Fluxo de dados:**
```
Telegram ← polling → python-telegram-bot (bot.py)
                          → BotHandler.handle(text, chat_id)
                               → store: usuário existe / qual status?
                               → parser: intent da mensagem
                               → store: salva transação
                               → analyzer + assistant: consultas IA
                          ← reply text
Telegram ← bot.py envia resposta
```

**Estados de usuário (por chat_id):**
```
DESCONHECIDO → /start → bot envia chave PIX → PENDENTE
PENDENTE → admin /ativar <chat_id> → ATIVO
ATIVO → todas as features
ADMIN → features + comandos administrativos
```

---

## Task 1: Adicionar suporte a receitas no analyzer

> **Pré-requisito de todas as outras tasks.**

**Files:**
- Modify: `src/analyzer.py`
- Modify: `src/assistant.py`
- Modify: `main.py`

- [ ] **Step 1: Adicionar campos ao `MonthlyReport` em `src/analyzer.py`**

Adicionar ao dataclass após `previous_by_category`:

```python
income_total: float = 0.0
income_by_category: dict[str, float] = field(default_factory=dict)
previous_income_total: float | None = None

@property
def balance(self) -> float:
    return round(self.income_total - self.total, 2)

@property
def vs_previous_income(self) -> float | None:
    if self.previous_income_total is None:
        return None
    return round(self.income_total - self.previous_income_total, 2)
```

- [ ] **Step 2: Atualizar `analyze_month()` com parâmetro `income_df`**

Alterar assinatura e adicionar bloco antes do `return MonthlyReport(...)`:

```python
def analyze_month(
    df: pd.DataFrame, year: int, month: int,
    income_df: pd.DataFrame | None = None,
) -> MonthlyReport:
    # ... código existente sem mudança até o bloco final ...

    income_total = 0.0
    income_by_category: dict[str, float] = {}
    previous_income_total: float | None = None

    if income_df is not None and not income_df.empty:
        curr_income = filter_by_month(income_df, year, month)
        prev_income = filter_by_month(income_df, prev_date.year, prev_date.month)
        income_by_category = (
            curr_income.groupby("CATEGORIA")["VALOR"].sum().round(2).to_dict()
            if not curr_income.empty else {}
        )
        income_total = round(curr_income["VALOR"].sum(), 2) if not curr_income.empty else 0.0
        previous_income_total = (
            round(prev_income["VALOR"].sum(), 2) if not prev_income.empty else None
        )

    # ATENÇÃO: o return MonthlyReport deve incluir TODOS os campos existentes.
    # Consultar o dataclass em src/analyzer.py para a lista completa.
    # Adicionar os 3 novos campos ao final do return existente:
    return MonthlyReport(
        year=year,
        month=month,
        total=round(current["VALOR"].sum(), 2),
        by_category=by_category,
        installments=installments,
        fixed_total=round(fixed_total, 2),
        free_total=round(free_total, 2),
        other_total=round(other_total, 2),
        previous_month_total=(
            round(previous["VALOR"].sum(), 2) if not previous.empty else None
        ),
        previous_by_category=prev_by_category,
        income_total=income_total,
        income_by_category=income_by_category,
        previous_income_total=previous_income_total,
    )
```

- [ ] **Step 3: Atualizar `print_report()` com seção RECEITAS e SALDO**

Adicionar antes do `print(sep)` final:

```python
if report.income_total > 0:
    print(f"\n{'RECEITAS':}")
    for cat, val in sorted(report.income_by_category.items(), key=lambda x: x[1], reverse=True):
        print(f"  {cat:<38} R$ {val:>8.2f}")
    print(f"  {'TOTAL RECEITAS':.<38} R$ {report.income_total:>8.2f}")
    if report.vs_previous_income is not None:
        print(f"\n  vs mês anterior:  {report.vs_previous_income:+.2f}"
              f"  (mês ant.: R$ {report.previous_income_total:.2f})")
    print(f"\n{'SALDO DO MÊS':}")
    print(f"  {'Receitas - Despesas':.<38} R$ {report.balance:>8.2f}")
```

- [ ] **Step 4: Atualizar `_format_report_as_context()` em `src/assistant.py`**

Adicionar ao final da função antes do `return "\n".join(lines)`:

```python
if report.income_total > 0:
    lines += ["", "## Receitas do mês",
              f"- Total de receitas: R$ {report.income_total:.2f}"]
    if report.vs_previous_income is not None:
        sign = "+" if report.vs_previous_income >= 0 else ""
        lines.append(f"- vs mês anterior: {sign}R$ {report.vs_previous_income:.2f}")
    for cat, val in sorted(report.income_by_category.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"- {cat}: R$ {val:.2f}")
    lines += ["", "## Saldo",
              f"- Saldo do mês (receitas - despesas): R$ {report.balance:.2f}",
              "- Nota: 'total' refere-se a despesas; 'saldo' é o valor líquido."]
```

- [ ] **Step 5: Atualizar `main.py`**

```python
def find_latest_csv() -> Path:
    # ALTERAR: "*.csv" → "despesas-*.csv"
    csvs = sorted(DATA_DIR.glob("despesas-*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not csvs:
        print("Nenhum CSV de despesas encontrado em data/", file=sys.stderr)
        sys.exit(1)
    return csvs[0]

def find_latest_income_csv() -> Path | None:
    csvs = sorted(DATA_DIR.glob("receitas-*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    return csvs[0] if csvs else None
```

E no `main()`, após carregar `df`:

```python
parser.add_argument("--receitas", type=Path, default=None)
# ...
income_path = args.receitas or find_latest_income_csv()
income_df = load_csv(income_path) if income_path else None
report = analyze_month(df, year, month, income_df=income_df)
```

- [ ] **Step 6: Testar CLI**

```bash
.venv/bin/python3 main.py --mes 3 --ano 2026 --resumo
# Esperado: seções RECEITAS e SALDO aparecem no relatório
```

- [ ] **Step 7: Commit**

```bash
git add src/analyzer.py src/assistant.py main.py
git commit -m "feat: add income support to analyzer and assistant context"
```

---

## Task 2: SQLite store — transações e usuários

**Files:**
- Create: `src/store.py`
- Create: `tests/test_store.py`

- [ ] **Step 1: Escrever testes**

```python
# tests/test_store.py
import pytest
from src.store import TransactionStore, UserStatus

@pytest.fixture
def store(tmp_path):
    return TransactionStore(str(tmp_path / "test.db"))

def test_add_and_get_expense(store):
    store.add_transaction(type="expense", description="Mercado",
                          category="Alimentação", value=150.0, date="2026-04-10")
    df = store.get_transactions_df(2026, 4, type="expense")
    assert len(df) == 1
    assert df.iloc[0]["VALOR"] == 150.0

def test_filter_by_month(store):
    store.add_transaction("expense", "A", "Cat", 10.0, "2026-04-01")
    store.add_transaction("expense", "B", "Cat", 20.0, "2026-05-01")
    assert len(store.get_transactions_df(2026, 4, "expense")) == 1

def test_user_registration_flow(store):
    store.upsert_user(111, status=UserStatus.PENDING)
    user = store.get_user(111)
    assert user["status"] == UserStatus.PENDING

    store.upsert_user(111, status=UserStatus.ACTIVE)
    assert store.get_user(111)["status"] == UserStatus.ACTIVE

def test_list_pending_users(store):
    store.upsert_user(111, status=UserStatus.PENDING)
    store.upsert_user(222, status=UserStatus.ACTIVE)
    pending = store.list_pending_users()
    assert len(pending) == 1
    assert pending[0]["chat_id"] == 111
```

- [ ] **Step 2: Rodar para confirmar falha**

```bash
.venv/bin/pytest tests/test_store.py -v
# Esperado: ImportError
```

- [ ] **Step 3: Implementar `src/store.py`**

```python
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
```

- [ ] **Step 4: Rodar testes**

```bash
.venv/bin/pytest tests/test_store.py -v
# Esperado: 4 passed
```

- [ ] **Step 5: Commit**

```bash
git add src/store.py tests/test_store.py
git commit -m "feat: add SQLite store for transactions and users"
```

---

## Task 3: Parser de mensagens com Claude Haiku

**Files:**
- Create: `src/parser.py`
- Create: `tests/test_parser.py`

- [ ] **Step 1: Escrever testes**

```python
# tests/test_parser.py
from unittest.mock import patch, MagicMock
from src.parser import parse_message, Intent

def _mock(json_str):
    m = MagicMock()
    m.content = [MagicMock(text=json_str)]
    return m

def test_parse_expense():
    with patch("src.parser._client") as m:
        m.messages.create.return_value = _mock(
            '{"intent":"EXPENSE","amount":50.0,"description":"mercado","category":"Alimentação","date":null}'
        )
        r = parse_message("gastei 50 no mercado")
    assert r.intent == Intent.EXPENSE
    assert r.amount == 50.0

def test_parse_income():
    with patch("src.parser._client") as m:
        m.messages.create.return_value = _mock(
            '{"intent":"INCOME","amount":7800.0,"description":"salário","category":"Fixa mensal","date":null}'
        )
        r = parse_message("recebi salário 7800")
    assert r.intent == Intent.INCOME

def test_parse_query():
    with patch("src.parser._client") as m:
        m.messages.create.return_value = _mock(
            '{"intent":"QUERY","amount":null,"description":null,"category":null,"date":null}'
        )
        r = parse_message("como estou esse mês?")
    assert r.intent == Intent.QUERY

def test_parse_help():
    with patch("src.parser._client") as m:
        m.messages.create.return_value = _mock(
            '{"intent":"HELP","amount":null,"description":null,"category":null,"date":null}'
        )
        r = parse_message("ajuda")
    assert r.intent == Intent.HELP
```

- [ ] **Step 2: Rodar para confirmar falha**

```bash
.venv/bin/pytest tests/test_parser.py -v
# Esperado: ImportError
```

- [ ] **Step 3: Implementar `src/parser.py`**

```python
import json, os
from dataclasses import dataclass
from enum import Enum
import anthropic
from dotenv import load_dotenv

load_dotenv()
_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
PARSER_MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """Classifique mensagens financeiras pessoais. Responda APENAS com JSON válido, sem markdown.

Intents:
- EXPENSE: lançar despesa ("gastei", "paguei", "comprei")
- INCOME: lançar receita ("recebi", "entrou", "pix de")
- QUERY: consulta financeira ("como estou", "saldo", "resumo", "quanto gastei")
- HELP: ajuda ou comando desconhecido

Formato:
{"intent":"EXPENSE|INCOME|QUERY|HELP","amount":50.0,"description":"texto","category":"categoria","date":"YYYY-MM-DD ou null"}

Categorias despesa: Alimentação, Moradia, Transporte, Saúde, Lazer, Assinaturas & Serviços, Família, Parcelamentos, Despesas Variáveis (pessoal), Outros
Categorias receita: Fixa mensal, Pagamentos, Outros"""


class Intent(str, Enum):
    EXPENSE = "EXPENSE"
    INCOME = "INCOME"
    QUERY = "QUERY"
    HELP = "HELP"


@dataclass
class ParsedMessage:
    intent: Intent
    amount: float | None
    description: str | None
    category: str | None
    date: str | None
    raw: str


def parse_message(text: str) -> ParsedMessage:
    resp = _client.messages.create(
        model=PARSER_MODEL, max_tokens=256,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}],
    )
    data = json.loads(resp.content[0].text)
    return ParsedMessage(
        intent=Intent(data["intent"]),
        amount=data.get("amount"),
        description=data.get("description"),
        category=data.get("category") or "Outros",
        date=data.get("date"),
        raw=text,
    )
```

- [ ] **Step 4: Rodar testes**

```bash
.venv/bin/pytest tests/test_parser.py -v
# Esperado: 4 passed
```

- [ ] **Step 5: Commit**

```bash
git add src/parser.py tests/test_parser.py
git commit -m "feat: add message parser using Claude Haiku"
```

---

## Task 4: Bot handler — estados de usuário e lógica financeira

**Files:**
- Create: `src/bot_handler.py`
- Create: `tests/test_bot_handler.py`

- [ ] **Step 1: Escrever testes**

```python
# tests/test_bot_handler.py
import pytest
from unittest.mock import patch
from src.bot_handler import BotHandler
from src.parser import Intent, ParsedMessage
from src.store import UserStatus

ADMIN_ID = 111111111
USER_ID  = 999999999

@pytest.fixture
def handler(tmp_path):
    return BotHandler(
        db_path=str(tmp_path / "test.db"),
        admin_chat_id=ADMIN_ID,
        pix_key="pix@email.com",
        pix_amount=29.90,
    )

def parsed(intent, amount=None, desc=None, cat="Alimentação", date="2026-04-10"):
    return ParsedMessage(intent=intent, amount=amount, description=desc,
                         category=cat, date=date, raw="")

def test_unknown_user_receives_pix_info(handler):
    with patch("src.bot_handler.parse_message"):
        reply = handler.handle("/start", chat_id=USER_ID)
    assert "PIX" in reply or "pix" in reply.lower()
    assert handler.store.get_user(USER_ID)["status"] == UserStatus.PENDING

def test_pending_user_receives_wait_message(handler):
    handler.store.upsert_user(USER_ID, UserStatus.PENDING)
    with patch("src.bot_handler.parse_message"):
        reply = handler.handle("oi", chat_id=USER_ID)
    assert "aguard" in reply.lower() or "pend" in reply.lower()

def test_admin_activates_user(handler):
    handler.store.upsert_user(USER_ID, UserStatus.PENDING)
    reply = handler.handle(f"/ativar {USER_ID}", chat_id=ADMIN_ID)
    assert "ativado" in reply.lower()
    assert handler.store.get_user(USER_ID)["status"] == UserStatus.ACTIVE

def test_admin_lists_pending(handler):
    handler.store.upsert_user(USER_ID, UserStatus.PENDING)
    reply = handler.handle("/pendentes", chat_id=ADMIN_ID)
    assert str(USER_ID) in reply

def test_active_user_expense(handler):
    handler.store.upsert_user(USER_ID, UserStatus.ACTIVE)
    p = parsed(Intent.EXPENSE, amount=50.0, desc="mercado")
    with patch("src.bot_handler.parse_message", return_value=p):
        reply = handler.handle("gastei 50 no mercado", chat_id=USER_ID)
    assert "50" in reply
    df = handler.store.get_transactions_df(2026, 4, type="expense")
    assert len(df) == 1

def test_active_user_help(handler):
    handler.store.upsert_user(USER_ID, UserStatus.ACTIVE)
    p = parsed(Intent.HELP)
    with patch("src.bot_handler.parse_message", return_value=p):
        reply = handler.handle("/ajuda", chat_id=USER_ID)
    assert "gastei" in reply.lower()
```

- [ ] **Step 2: Rodar para confirmar falha**

```bash
.venv/bin/pytest tests/test_bot_handler.py -v
# Esperado: ImportError
```

- [ ] **Step 3: Implementar `src/bot_handler.py`**

```python
import os
from datetime import date
from pathlib import Path
import pandas as pd

from src.parser import parse_message, Intent
from src.store import TransactionStore, UserStatus

DATA_DIR = Path(__file__).parent.parent / "data"

HELP_TEXT = """*Assistente Financeiro* 💰

*Lançamentos:*
• _gastei 50 no mercado_ → despesa
• _recebi 200 pix da raissa_ → receita
• _paguei 150 de luz_ → despesa

*Consultas:*
• _resumo_ — resumo do mês
• _saldo_ — quanto sobra
• Qualquer pergunta livre para a IA

*Comandos:*
• /ajuda — este menu
• /start — cadastro inicial
"""


def _find_latest(pattern: str) -> Path | None:
    files = sorted(DATA_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


class BotHandler:
    def __init__(
        self,
        db_path: str | Path | None = None,
        admin_chat_id: int | None = None,
        pix_key: str | None = None,
        pix_amount: float = 0.0,
        api_key: str | None = None,
    ):
        self.store = TransactionStore(db_path) if db_path else TransactionStore()
        self.admin_chat_id = admin_chat_id or int(os.environ.get("ADMIN_CHAT_ID", "0"))
        self.pix_key = pix_key or os.environ.get("PIX_KEY", "")
        self.pix_amount = pix_amount or float(os.environ.get("PIX_AMOUNT", "0"))
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._history: dict[int, list[dict]] = {}

        # Garantir que admin existe no DB como ADMIN
        if self.admin_chat_id:
            user = self.store.get_user(self.admin_chat_id)
            if user is None:
                self.store.upsert_user(self.admin_chat_id, UserStatus.ADMIN)

    # ── Entry point ───────────────────────────────────────────────────────────

    def handle(self, text: str, chat_id: int) -> str:
        text = text.strip()

        # Comandos admin (só do chat_id admin)
        if chat_id == self.admin_chat_id:
            admin_reply = self._handle_admin(text)
            if admin_reply is not None:
                return admin_reply

        # /start sempre vai para fluxo de cadastro
        if text.lower() == "/start":
            return self._handle_start(chat_id)

        # Gate de estado
        user = self.store.get_user(chat_id)
        if user is None or user["status"] == UserStatus.PENDING:
            if user is None:
                self.store.upsert_user(chat_id, UserStatus.PENDING)
            return "⏳ Seu cadastro está *pendente*. Aguarde a confirmação do pagamento."

        # Usuário ativo
        if text.lower() in ("/ajuda", "ajuda"):
            return HELP_TEXT

        parsed = parse_message(text)

        if parsed.intent == Intent.HELP:
            return HELP_TEXT
        if parsed.intent in (Intent.EXPENSE, Intent.INCOME):
            return self._handle_transaction(parsed, chat_id)
        return self._handle_query(text, chat_id)

    # ── Start / Cadastro ──────────────────────────────────────────────────────

    def _handle_start(self, chat_id: int) -> str:
        user = self.store.get_user(chat_id)
        if user and user["status"] in (UserStatus.ACTIVE, UserStatus.ADMIN):
            return "✅ Você já tem acesso! Envie _ajuda_ para ver os comandos disponíveis."
        if user is None:
            self.store.upsert_user(chat_id, UserStatus.PENDING)
        valor = f"R$ {self.pix_amount:.2f}" if self.pix_amount else "o valor combinado"
        return (
            f"👋 Olá! Este é um assistente financeiro pessoal.\n\n"
            f"Para ter acesso, faça um PIX de *{valor}* para:\n"
            f"🔑 Chave: `{self.pix_key}`\n\n"
            f"Envie seu *chat\\_id* no comprovante ou informe ao administrador:\n"
            f"`{chat_id}`\n\n"
            f"Após o pagamento, seu acesso será liberado. ✅"
        )

    # ── Admin ─────────────────────────────────────────────────────────────────

    def _handle_admin(self, text: str) -> str | None:
        parts = text.strip().split()
        cmd = parts[0].lower() if parts else ""

        if cmd == "/ativar" and len(parts) == 2:
            try:
                target_id = int(parts[1])
            except ValueError:
                return "Uso: /ativar <chat_id>"
            self.store.upsert_user(target_id, UserStatus.ACTIVE)
            return f"✅ Usuário *{target_id}* ativado."

        if cmd == "/desativar" and len(parts) == 2:
            try:
                target_id = int(parts[1])
            except ValueError:
                return "Uso: /desativar <chat_id>"
            self.store.upsert_user(target_id, UserStatus.PENDING)
            return f"🚫 Usuário *{target_id}* desativado."

        if cmd == "/pendentes":
            pending = self.store.list_pending_users()
            if not pending:
                return "Nenhum usuário pendente. ✅"
            lines = ["*Usuários pendentes:*"]
            for u in pending:
                name = u.get("username") or "sem username"
                lines.append(f"• `{u['chat_id']}` ({name}) — desde {u['registered_at'][:10]}")
            return "\n".join(lines)

        return None  # não é comando admin, processar normalmente

    # ── Transaction ───────────────────────────────────────────────────────────

    def _handle_transaction(self, parsed, chat_id: int) -> str:
        if parsed.amount is None:
            return "Não entendi o valor. Tente: _gastei 50 reais no mercado_"

        tx_date = parsed.date or date.today().isoformat()
        tx_type = "expense" if parsed.intent == Intent.EXPENSE else "income"

        self.store.add_transaction(
            type=tx_type,
            description=parsed.description or parsed.raw,
            category=parsed.category or "Outros",
            value=parsed.amount,
            date=tx_date,
            chat_id=chat_id,
        )

        from telegram.helpers import escape_markdown as esc
        emoji = "💸" if tx_type == "expense" else "💰"
        label = "Despesa" if tx_type == "expense" else "Receita"
        # Strings vindas do usuário/parser devem ser escapadas para MarkdownV2
        # Caso contrário Telegram lança BadRequest se a string contiver . - ( ) etc.
        return (
            f"{emoji} *{label} lançada\!*\n"
            f"Valor: R$ {parsed.amount:.2f}\n"
            f"Categoria: {esc(parsed.category or '', version=2)}\n"
            f"Descrição: {esc(parsed.description or '', version=2)}\n"
            f"Data: {tx_date}"
        )

    # ── AI Query ──────────────────────────────────────────────────────────────

    def _handle_query(self, text: str, chat_id: int) -> str:
        from src.loader import load_csv
        from src.analyzer import analyze_month
        from src.assistant import FinancialAssistant

        today = date.today()
        year, month = today.year, today.month

        expenses_path = _find_latest("despesas-*.csv")
        income_path = _find_latest("receitas-*.csv")

        expenses_df = load_csv(expenses_path) if expenses_path else pd.DataFrame()
        income_df = load_csv(income_path) if income_path else pd.DataFrame()

        wa_exp = self.store.get_transactions_df(year, month, type="expense")
        wa_inc = self.store.get_transactions_df(year, month, type="income")

        if not wa_exp.empty:
            expenses_df = pd.concat([expenses_df, wa_exp], ignore_index=True)
        if not wa_inc.empty:
            income_df = pd.concat([income_df, wa_inc], ignore_index=True)

        report = analyze_month(
            expenses_df, year, month,
            income_df=income_df if not income_df.empty else None,
        )

        if chat_id not in self._history:
            self._history[chat_id] = []

        assistant = FinancialAssistant(report, api_key=self.api_key)
        assistant.history = self._history[chat_id]

        # chat() faz print() para stdout — efeito colateral esperado no container
        reply = assistant.chat(text)
        self._history[chat_id] = assistant.history
        return reply
```

- [ ] **Step 4: Rodar testes**

```bash
.venv/bin/pytest tests/test_bot_handler.py -v
# Esperado: 6 passed
```

- [ ] **Step 5: Commit**

```bash
git add src/bot_handler.py tests/test_bot_handler.py
git commit -m "feat: add Telegram bot handler with user states and admin commands"
```

---

## Task 5: Entry point Telegram (bot.py)

**Files:**
- Create: `bot.py`

- [ ] **Step 1: Instalar dependência**

```bash
.venv/bin/pip install "python-telegram-bot==20.*"
.venv/bin/pip freeze > requirements.txt
```

- [ ] **Step 2: Criar `bot.py`**

```python
import logging
import os
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from dotenv import load_dotenv
from src.bot_handler import BotHandler

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_handler = BotHandler()


async def _reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = update.message.text or ""
    logger.info(f"[{chat_id}] {text[:60]}")
    reply = _handler.handle(text, chat_id=chat_id)
    await update.message.reply_text(reply, parse_mode="MarkdownV2")


def main() -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).build()

    # Comandos roteados para o mesmo handler
    for cmd in ["start", "ajuda", "ativar", "desativar", "pendentes"]:
        app.add_handler(CommandHandler(cmd, _reply))

    # Mensagens de texto livres
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _reply))

    logger.info("Bot iniciado. Aguardando mensagens...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Criar bot no Telegram via @BotFather**

```
1. Abrir Telegram → buscar @BotFather
2. Enviar /newbot
3. Escolher nome e username (ex: financas_lucas_bot)
4. Copiar o token gerado
5. Adicionar ao .env: TELEGRAM_BOT_TOKEN=<token>
```

- [ ] **Step 4: Descobrir seu chat_id**

```
1. Buscar @userinfobot no Telegram
2. Enviar /start — ele retorna seu chat_id numérico
3. Adicionar ao .env: ADMIN_CHAT_ID=<seu_chat_id>
```

- [ ] **Step 5: Testar bot localmente**

```bash
.venv/bin/python3 bot.py
# No Telegram: enviar /start para o bot
# Esperado: mensagem com chave PIX e seu chat_id
```

- [ ] **Step 6: Testar ativação admin**

```
No Telegram, envie para o bot:
  /ativar <SEU_CHAT_ID>
  → "✅ Usuário XXXXXX ativado."

Depois envie:
  gastei 50 no mercado
  → "💸 Despesa lançada!"

  como estou esse mês?
  → resposta da IA
```

- [ ] **Step 7: Commit**

```bash
git add bot.py requirements.txt
git commit -m "feat: add Telegram bot entry point with polling"
```

---

## Task 6: Docker e deploy na VPS

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.env.example`

- [ ] **Step 1: Criar `.dockerignore`**

```
.venv/
.env
data/*.db
data/*.csv
__pycache__/
*.pyc
.git/
```

- [ ] **Step 2: Criar `Dockerfile`**

```dockerfile
FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python3", "bot.py"]
```

- [ ] **Step 3: Criar `docker-compose.yml`**

```yaml
version: '3.8'

services:
  financas-bot:
    build: .
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./data:/app/data
```

- [ ] **Step 4: Criar `.env.example`**

```env
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=1234567890:AABBccDDeeFFggHHiiJJ...
ADMIN_CHAT_ID=123456789
PIX_KEY=seu-email@email.com
PIX_AMOUNT=29.90
```

- [ ] **Step 5: Testar build local**

```bash
docker compose build
docker compose up
# Esperado: "Bot iniciado. Aguardando mensagens..."
# Testar enviando mensagem pelo Telegram
```

- [ ] **Step 6: Deploy na VPS Hostinger**

```bash
# Conectar na VPS
ssh root@<IP_DA_VPS>

# Clonar repositório
git clone <URL_DO_REPO> /opt/financas-ai
cd /opt/financas-ai

# Criar .env com valores reais
cp .env.example .env
nano .env

# Subir o serviço
docker compose up -d --build

# Verificar logs
docker compose logs -f
# Esperado: "Bot iniciado. Aguardando mensagens..."
```

- [ ] **Step 7: Testar end-to-end na VPS**

```
/start                     → mensagem PIX com seu chat_id
/ativar <chat_id>          → ✅ ativado
gastei 50 no mercado       → 💸 Despesa lançada!
recebi 200 pix raissa      → 💰 Receita lançada!
como estou esse mês?       → resposta da IA
/pendentes                 → lista de usuários aguardando
/ajuda                     → menu de comandos
```

- [ ] **Step 8: Commit**

```bash
git add Dockerfile .dockerignore docker-compose.yml .env.example
git commit -m "feat: add Docker deploy config for VPS"
```

---

## Variáveis de ambiente

```env
ANTHROPIC_API_KEY=sk-ant-...         # chave da API Anthropic
TELEGRAM_BOT_TOKEN=...               # token do @BotFather
ADMIN_CHAT_ID=123456789              # seu chat_id numérico
PIX_KEY=seu-email@email.com          # chave PIX para cobrança
PIX_AMOUNT=29.90                     # 0 = gratuito
```

---

## Ordem de execução

```
Task 1 (analyzer) → Task 2 (store) → Task 3 (parser)
→ Task 4 (bot_handler) → Task 5 (bot.py + BotFather)
→ Task 6 (Docker + VPS)
```
