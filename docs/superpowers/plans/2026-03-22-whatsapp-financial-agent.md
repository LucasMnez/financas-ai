# WhatsApp Financial Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bot WhatsApp pessoal/multi-usuário que aceita lançamentos financeiros em linguagem natural, responde perguntas via IA e tem fluxo de cadastro via PIX manual — rodando em Docker na VPS Hostinger.

**Architecture:** Baileys (Node.js) cuida da conexão WhatsApp e repassa mensagens via HTTP para a API Python (FastAPI). A API Python gerencia usuários (whitelist + estado de cadastro), interpreta mensagens com Claude, executa lógica financeira e retorna a resposta. Tudo orquestrado por Docker Compose.

**Tech Stack:** Python 3.10 · FastAPI · Baileys (@whiskeysockets/baileys) · Node.js 20 · SQLite · Anthropic Claude API · Docker Compose

---

## Arquitetura de Arquivos

```
financas-ai/
  src/
    loader.py              # existente — sem mudanças
    analyzer.py            # modificar: aceitar income_df=None
    assistant.py           # existente — sem mudanças
    store.py               # NOVO: SQLite (transações + usuários)
    parser.py              # NOVO: classifica mensagem → intent
    whatsapp_handler.py    # NOVO: orquestra estados, parser, financeiro
  bot/
    index.js               # NOVO: Baileys WhatsApp client
    package.json           # NOVO
    Dockerfile             # NOVO
  server.py                # NOVO: FastAPI com POST /process
  Dockerfile               # NOVO: imagem Python
  docker-compose.yml       # NOVO: orquestra python-api + baileys-bot
  .env                     # adicionar ADMIN_PHONE, PIX_KEY, PIX_AMOUNT
  .env.example             # NOVO: template sem segredos
  main.py                  # existente — CLI local continua funcionando
  data/                    # existente — CSVs + transactions.db
  tests/
    test_store.py          # NOVO
    test_parser.py         # NOVO
    test_whatsapp_handler.py # NOVO
```

**Fluxo de dados:**
```
WhatsApp ← Baileys (Node.js) → POST /process → FastAPI (Python)
                                                    → whatsapp_handler
                                                        → store (usuário existe?)
                                                        → parser (intent)
                                                        → store (salva transação)
                                                        → analyzer + assistant (queries)
                                                    ← { reply: "..." }
              Baileys ← resposta ← FastAPI
WhatsApp ← Baileys
```

**Estados de usuário:**
```
DESCONHECIDO → bot envia chave PIX → PENDENTE
PENDENTE → admin /ativar NÚMERO → ATIVO
ATIVO → todas as features financeiras
ADMIN → features + comandos administrativos
```

---

## Task 1: Adicionar suporte a receitas no analyzer

> **Pré-requisito de todas as outras tasks.** Implementa o spec `2026-03-22-receitas-design.md`.

**Files:**
- Modify: `src/analyzer.py`
- Modify: `src/assistant.py`
- Modify: `main.py`

- [ ] **Step 1: Adicionar campos ao `MonthlyReport`**

Em `src/analyzer.py`, adicionar ao dataclass após `previous_by_category`:

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

- [ ] **Step 2: Atualizar `analyze_month()`**

Alterar assinatura e adicionar bloco de receitas antes do `return`:

```python
def analyze_month(
    df: pd.DataFrame, year: int, month: int,
    income_df: pd.DataFrame | None = None
) -> MonthlyReport:
    # ... código existente sem mudança até o return ...

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
        previous_income_total = round(prev_income["VALOR"].sum(), 2) if not prev_income.empty else None

    return MonthlyReport(
        # todos os campos existentes,
        income_total=income_total,
        income_by_category=income_by_category,
        previous_income_total=previous_income_total,
    )
```

- [ ] **Step 3: Atualizar `print_report()` com RECEITAS e SALDO**

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

- [ ] **Step 4: Atualizar `_format_report_as_context()` em `assistant.py`**

Adicionar ao final da função, antes do `return`:

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
    ...

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
    store.upsert_user("+5511999999999", status=UserStatus.PENDING)
    user = store.get_user("+5511999999999")
    assert user["status"] == UserStatus.PENDING

    store.upsert_user("+5511999999999", status=UserStatus.ACTIVE)
    user = store.get_user("+5511999999999")
    assert user["status"] == UserStatus.ACTIVE

def test_list_pending_users(store):
    store.upsert_user("+5511111111111", status=UserStatus.PENDING)
    store.upsert_user("+5522222222222", status=UserStatus.ACTIVE)
    pending = store.list_pending_users()
    assert len(pending) == 1
    assert pending[0]["phone"] == "+5511111111111"
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
    phone TEXT,
    source TEXT DEFAULT 'whatsapp',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT UNIQUE NOT NULL,
    status TEXT DEFAULT 'pending',
    name TEXT,
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

    def add_transaction(self, type: str, description: str, category: str,
                        value: float, date: str, phone: str = "",
                        source: str = "whatsapp") -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO transactions (type, description, category, value, date, phone, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (type, description, category, value, date, phone, source),
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

    def get_user(self, phone: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT phone, status, name, registered_at, activated_at FROM users WHERE phone = ?",
                (phone,)
            ).fetchone()
        if not row:
            return None
        return dict(zip(["phone", "status", "name", "registered_at", "activated_at"], row))

    def upsert_user(self, phone: str, status: UserStatus, name: str = "") -> None:
        with self._conn() as conn:
            existing = conn.execute("SELECT id FROM users WHERE phone = ?", (phone,)).fetchone()
            if existing:
                if status == UserStatus.ACTIVE:
                    conn.execute(
                        "UPDATE users SET status = ?, activated_at = datetime('now') WHERE phone = ?",
                        (status, phone)
                    )
                else:
                    conn.execute("UPDATE users SET status = ? WHERE phone = ?", (status, phone))
            else:
                conn.execute(
                    "INSERT INTO users (phone, status, name) VALUES (?, ?, ?)",
                    (phone, status, name or "")
                )

    def list_pending_users(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT phone, status, registered_at FROM users WHERE status = 'pending'"
            ).fetchall()
        return [dict(zip(["phone", "status", "registered_at"], r)) for r in rows]
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
import pytest
from unittest.mock import patch, MagicMock
from src.parser import parse_message, Intent, ParsedMessage

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
git commit -m "feat: add WhatsApp message parser using Claude Haiku"
```

---

## Task 4: WhatsApp handler — estados de usuário e lógica financeira

**Files:**
- Create: `src/whatsapp_handler.py`
- Create: `tests/test_whatsapp_handler.py`

- [ ] **Step 1: Escrever testes**

```python
# tests/test_whatsapp_handler.py
import pytest
from unittest.mock import patch, MagicMock
from src.whatsapp_handler import WhatsAppHandler
from src.parser import Intent, ParsedMessage
from src.store import UserStatus

@pytest.fixture
def handler(tmp_path):
    return WhatsAppHandler(
        db_path=str(tmp_path / "test.db"),
        admin_phone="+5511000000000",
        pix_key="pix@email.com",
        pix_amount=29.90,
    )

ADMIN = "+5511000000000"
USER = "+5511999999999"

def parsed(intent, amount=None, desc=None, cat="Alimentação", date="2026-04-10"):
    return ParsedMessage(intent=intent, amount=amount, description=desc,
                         category=cat, date=date, raw="")

def test_unknown_user_receives_pix_info(handler):
    with patch("src.whatsapp_handler.parse_message"):
        reply = handler.handle("oi", from_number=USER)
    assert "PIX" in reply or "pix" in reply.lower()
    assert handler.store.get_user(USER)["status"] == UserStatus.PENDING

def test_pending_user_receives_wait_message(handler):
    handler.store.upsert_user(USER, UserStatus.PENDING)
    with patch("src.whatsapp_handler.parse_message"):
        reply = handler.handle("oi", from_number=USER)
    assert "aguard" in reply.lower() or "pend" in reply.lower()

def test_admin_activates_user(handler):
    handler.store.upsert_user(USER, UserStatus.PENDING)
    reply = handler.handle(f"/ativar {USER}", from_number=ADMIN)
    assert "ativado" in reply.lower()
    assert handler.store.get_user(USER)["status"] == UserStatus.ACTIVE

def test_admin_lists_pending(handler):
    handler.store.upsert_user(USER, UserStatus.PENDING)
    reply = handler.handle("/pendentes", from_number=ADMIN)
    assert USER in reply

def test_active_user_expense(handler):
    handler.store.upsert_user(USER, UserStatus.ACTIVE)
    p = parsed(Intent.EXPENSE, amount=50.0, desc="mercado")
    with patch("src.whatsapp_handler.parse_message", return_value=p):
        reply = handler.handle("gastei 50 no mercado", from_number=USER)
    assert "50" in reply
    df = handler.store.get_transactions_df(2026, 4, type="expense")
    assert len(df) == 1

def test_active_user_help(handler):
    handler.store.upsert_user(USER, UserStatus.ACTIVE)
    p = parsed(Intent.HELP)
    with patch("src.whatsapp_handler.parse_message", return_value=p):
        reply = handler.handle("ajuda", from_number=USER)
    assert "gastei" in reply.lower()
```

- [ ] **Step 2: Rodar para confirmar falha**

```bash
.venv/bin/pytest tests/test_whatsapp_handler.py -v
# Esperado: ImportError
```

- [ ] **Step 3: Implementar `src/whatsapp_handler.py`**

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

*Outros:*
• _ajuda_ — este menu
"""


def _find_latest(pattern: str) -> Path | None:
    files = sorted(DATA_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


class WhatsAppHandler:
    def __init__(
        self,
        db_path: str | Path | None = None,
        admin_phone: str | None = None,
        pix_key: str | None = None,
        pix_amount: float = 0.0,
        api_key: str | None = None,
    ):
        self.store = TransactionStore(db_path) if db_path else TransactionStore()
        self.admin_phone = admin_phone or os.environ.get("ADMIN_PHONE", "")
        self.pix_key = pix_key or os.environ.get("PIX_KEY", "")
        self.pix_amount = pix_amount or float(os.environ.get("PIX_AMOUNT", "0"))
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._history: dict[str, list[dict]] = {}

    # ── Entry point ───────────────────────────────────────────────────────────

    def handle(self, text: str, from_number: str) -> str:
        text = text.strip()

        # Admin commands (any message from admin number)
        if from_number == self.admin_phone:
            admin_reply = self._handle_admin(text)
            if admin_reply is not None:
                return admin_reply

        # User state gate
        user = self.store.get_user(from_number)

        if user is None:
            self.store.upsert_user(from_number, UserStatus.PENDING)
            return self._registration_message()

        if user["status"] == UserStatus.PENDING:
            return "⏳ Seu cadastro está *pendente*. Aguarde a confirmação do pagamento."

        # Active user
        parsed = parse_message(text)

        if parsed.intent == Intent.HELP:
            return HELP_TEXT
        if parsed.intent in (Intent.EXPENSE, Intent.INCOME):
            return self._handle_transaction(parsed, from_number)
        return self._handle_query(text, from_number)

    # ── Admin ─────────────────────────────────────────────────────────────────

    def _handle_admin(self, text: str) -> str | None:
        parts = text.strip().split()
        cmd = parts[0].lower() if parts else ""

        if cmd == "/ativar" and len(parts) == 2:
            phone = parts[1]
            self.store.upsert_user(phone, UserStatus.ACTIVE)
            return f"✅ Usuário *{phone}* ativado com sucesso."

        if cmd == "/desativar" and len(parts) == 2:
            phone = parts[1]
            self.store.upsert_user(phone, UserStatus.PENDING)
            return f"🚫 Usuário *{phone}* desativado."

        if cmd == "/pendentes":
            pending = self.store.list_pending_users()
            if not pending:
                return "Nenhum usuário pendente."
            lines = ["*Usuários pendentes:*"] + [
                f"• {u['phone']} — desde {u['registered_at'][:10]}" for u in pending
            ]
            return "\n".join(lines)

        return None  # not an admin command, process normally as active user

    # ── Registration ──────────────────────────────────────────────────────────

    def _registration_message(self) -> str:
        valor = f"R$ {self.pix_amount:.2f}" if self.pix_amount else "o valor combinado"
        return (
            f"👋 Olá! Este é um assistente financeiro pessoal.\n\n"
            f"Para ter acesso, faça um PIX de *{valor}* para:\n"
            f"🔑 Chave: `{self.pix_key}`\n\n"
            f"Após o pagamento, seu acesso será liberado em breve. ✅"
        )

    # ── Transaction ───────────────────────────────────────────────────────────

    def _handle_transaction(self, parsed, from_number: str) -> str:
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
            phone=from_number,
        )

        emoji = "💸" if tx_type == "expense" else "💰"
        label = "Despesa" if tx_type == "expense" else "Receita"
        return (
            f"{emoji} *{label} lançada!*\n"
            f"Valor: R$ {parsed.amount:.2f}\n"
            f"Categoria: {parsed.category}\n"
            f"Descrição: {parsed.description}\n"
            f"Data: {tx_date}"
        )

    # ── AI Query ──────────────────────────────────────────────────────────────

    def _handle_query(self, text: str, from_number: str) -> str:
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
            income_df=income_df if not income_df.empty else None
        )

        if from_number not in self._history:
            self._history[from_number] = []

        assistant = FinancialAssistant(report, api_key=self.api_key)
        assistant.history = self._history[from_number]

        # chat() also prints to stdout — expected side effect in server context
        reply = assistant.chat(text)
        self._history[from_number] = assistant.history
        return reply
```

- [ ] **Step 4: Rodar testes**

```bash
.venv/bin/pytest tests/test_whatsapp_handler.py -v
# Esperado: 6 passed
```

- [ ] **Step 5: Commit**

```bash
git add src/whatsapp_handler.py tests/test_whatsapp_handler.py
git commit -m "feat: add WhatsApp handler with user state machine and admin commands"
```

---

## Task 5: FastAPI — endpoint /process

**Files:**
- Create: `server.py`

- [ ] **Step 1: Instalar dependências**

```bash
.venv/bin/pip install fastapi uvicorn
.venv/bin/pip freeze > requirements.txt
```

- [ ] **Step 2: Criar `server.py`**

```python
import os
from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from src.whatsapp_handler import WhatsAppHandler

app = FastAPI()
handler = WhatsAppHandler()


class MessageRequest(BaseModel):
    from_number: str  # ex: "+5511999999999"
    text: str


class MessageResponse(BaseModel):
    reply: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/process", response_model=MessageResponse)
def process(req: MessageRequest):
    reply = handler.handle(req.text, from_number=req.from_number)
    return MessageResponse(reply=reply)
```

- [ ] **Step 3: Testar localmente**

```bash
.venv/bin/uvicorn server:app --reload --port 8000

# Outro terminal — testar health:
curl http://localhost:8000/health

# Testar com número desconhecido (deve retornar mensagem PIX):
curl -X POST http://localhost:8000/process \
  -H "Content-Type: application/json" \
  -d '{"from_number": "+5511999999999", "text": "oi"}'
```

- [ ] **Step 4: Commit**

```bash
git add server.py requirements.txt
git commit -m "feat: add FastAPI /process endpoint"
```

---

## Task 6: Baileys bot (Node.js)

**Files:**
- Create: `bot/package.json`
- Create: `bot/index.js`
- Create: `bot/Dockerfile`

- [ ] **Step 1: Criar `bot/package.json`**

```json
{
  "name": "financas-bot",
  "version": "1.0.0",
  "main": "index.js",
  "dependencies": {
    "@whiskeysockets/baileys": "^6.7.0",
    "axios": "^1.6.0",
    "pino": "^8.0.0"
  }
}
```

- [ ] **Step 2: Criar `bot/index.js`**

```javascript
const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
} = require('@whiskeysockets/baileys')
const axios = require('axios')
const pino = require('pino')

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8000'
const logger = pino({ level: 'info' })

async function connectToWhatsApp() {
  const { state, saveCreds } = await useMultiFileAuthState('./session')
  const { version } = await fetchLatestBaileysVersion()

  const sock = makeWASocket({
    version,
    auth: state,
    printQRInTerminal: true,
    logger: pino({ level: 'silent' }),
  })

  sock.ev.on('creds.update', saveCreds)

  sock.ev.on('connection.update', ({ connection, lastDisconnect, qr }) => {
    if (connection === 'close') {
      const shouldReconnect =
        lastDisconnect?.error?.output?.statusCode !== DisconnectReason.loggedOut
      logger.info('Connection closed. Reconnecting:', shouldReconnect)
      if (shouldReconnect) connectToWhatsApp()
    } else if (connection === 'open') {
      logger.info('WhatsApp connected!')
    }
  })

  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return

    for (const msg of messages) {
      if (msg.key.fromMe || !msg.message) continue

      const from = msg.key.remoteJid
      if (!from || from.includes('@g.us')) continue  // ignorar grupos

      const text =
        msg.message.conversation ||
        msg.message.extendedTextMessage?.text ||
        ''

      if (!text.trim()) continue

      const fromNumber = '+' + from.replace('@s.whatsapp.net', '')
      logger.info({ from: fromNumber, text }, 'Message received')

      try {
        const { data } = await axios.post(`${PYTHON_API_URL}/process`, {
          from_number: fromNumber,
          text,
        })
        await sock.sendMessage(from, { text: data.reply })
      } catch (err) {
        logger.error({ err }, 'Error processing message')
        await sock.sendMessage(from, {
          text: '⚠️ Erro interno. Tente novamente em instantes.',
        })
      }
    }
  })

  return sock
}

connectToWhatsApp()
```

- [ ] **Step 3: Criar `bot/Dockerfile`**

```dockerfile
FROM node:20-slim
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY index.js .
CMD ["node", "index.js"]
```

- [ ] **Step 4: Testar bot localmente (com Python API rodando)**

```bash
cd bot
npm install
PYTHON_API_URL=http://localhost:8000 node index.js
# Escanear QR code com WhatsApp
# Enviar mensagem para o número conectado e verificar resposta
```

- [ ] **Step 5: Commit (incluir package-lock.json)**

```bash
# npm install no Step 4 já gerou package-lock.json — commitar junto:
git add bot/
git commit -m "feat: add Baileys WhatsApp bot service"
# npm ci no Dockerfile requer package-lock.json — sem ele o build falha
```

---

## Task 7: Docker Compose

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.env.example`

- [ ] **Step 1: Criar `Dockerfile` para Python API**

```dockerfile
FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
# workers=1 obrigatório: conversa histórico fica em memória do processo
```

- [ ] **Step 2: Criar `docker-compose.yml`**

```yaml
version: '3.8'

services:
  python-api:
    build: .
    restart: unless-stopped
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - ADMIN_PHONE=${ADMIN_PHONE}
      - PIX_KEY=${PIX_KEY}
      - PIX_AMOUNT=${PIX_AMOUNT}
    volumes:
      - ./data:/app/data
    expose:
      - "8000"

  baileys-bot:
    build: ./bot
    restart: unless-stopped
    depends_on:
      - python-api
    environment:
      - PYTHON_API_URL=http://python-api:8000
    volumes:
      - baileys_session:/app/session

volumes:
  baileys_session:
```

- [ ] **Step 3: Criar `.env.example`**

```env
ANTHROPIC_API_KEY=sk-ant-...
ADMIN_PHONE=+5511999999999
PIX_KEY=seu-email@email.com
PIX_AMOUNT=29.90
```

- [ ] **Step 4: Testar build local**

```bash
docker compose build
docker compose up
# Aguardar QR code aparecer nos logs do baileys-bot:
docker compose logs -f baileys-bot
# Escanear QR com WhatsApp
```

- [ ] **Step 5: Verificar que os serviços se comunicam**

```bash
# Python API respondendo:
docker compose exec python-api curl http://localhost:8000/health

# Enviar mensagem pelo WhatsApp e verificar logs:
docker compose logs -f python-api
```

- [ ] **Step 6: Commit**

```bash
git add Dockerfile docker-compose.yml .env.example
git commit -m "feat: add Docker Compose for python-api and baileys-bot"
```

---

## Task 8: Deploy na VPS Hostinger

**Files:** nenhum — configuração no servidor

- [ ] **Step 1: Conectar na VPS via SSH**

```bash
ssh root@<IP_DA_VPS>
```

- [ ] **Step 2: Verificar Docker instalado**

```bash
docker --version
docker compose version
# Se não tiver: apt update && apt install -y docker.io docker-compose-plugin
```

- [ ] **Step 3: Clonar repositório na VPS**

```bash
git clone <URL_DO_REPO> /opt/financas-ai
cd /opt/financas-ai
```

- [ ] **Step 4: Criar `.env` com valores reais**

```bash
cp .env.example .env
nano .env
# Preencher ANTHROPIC_API_KEY, ADMIN_PHONE, PIX_KEY, PIX_AMOUNT
```

- [ ] **Step 5: Subir os serviços**

```bash
docker compose up -d --build
```

- [ ] **Step 6: Escanear QR code (primeira vez)**

```bash
docker compose logs -f baileys-bot
# Aparece o QR no terminal — escanear com WhatsApp
# Após conexão: "WhatsApp connected!"
```

- [ ] **Step 7: Verificar que tudo está rodando**

```bash
docker compose ps
# Esperado: python-api e baileys-bot com status "running"

# Testar endpoint:
docker compose exec python-api curl http://localhost:8000/health
```

- [ ] **Step 8: Testar end-to-end pelo WhatsApp**

Enviar as mensagens e verificar respostas:

```
oi                          → mensagem de cadastro PIX
/ativar +5511999999999      → ativar seu próprio número (do ADMIN_PHONE)
gastei 50 no mercado        → 💸 Despesa lançada!
recebi 200 pix raissa       → 💰 Receita lançada!
como estou esse mês?        → resposta da IA com análise
/pendentes                  → lista usuários aguardando ativação
ajuda                       → menu de comandos
```

---

## Variáveis de ambiente completas

```env
ANTHROPIC_API_KEY=sk-ant-...
ADMIN_PHONE=+5511999999999      # seu número, formato internacional
PIX_KEY=seu-email@email.com     # chave PIX para cobrança
PIX_AMOUNT=29.90                # valor do cadastro (0 = gratuito)
```

---

## Ordem de execução

```
Task 1 (analyzer) → Task 2 (store) → Task 3 (parser) → Task 4 (handler)
→ Task 5 (FastAPI) → Task 6 (Baileys) → Task 7 (Docker) → Task 8 (VPS)
```
