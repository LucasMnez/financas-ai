# Inline Categorization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add inline Telegram keyboard confirmation to every expense/income entry, allowing the user to validate or correct the category before saving, with corrections persisted in `data/category_mappings.json`.

**Architecture:** New `src/categorizer.py` manages the category list and JSON mappings. `BotHandler._handle_transaction()` returns `(text, ParsedMessage)` instead of saving immediately; `handle()` returns a 3-tuple `(str, bool, ParsedMessage | None)`. `bot.py` builds an inline keyboard with a UUID-based `pending_id` and registers the pending transaction; a new `CallbackQueryHandler` processes button clicks.

**Tech Stack:** Python 3.10, python-telegram-bot v20 (async, InlineKeyboardMarkup, CallbackQueryHandler), existing SQLite store.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `src/categorizer.py` | Create | Category lists + JSON mappings lookup/save |
| `tests/test_categorizer.py` | Create | Tests for ExpenseCategorizer |
| `src/parser.py` | Modify line 25 | Update SYSTEM_PROMPT category list |
| `src/bot_handler.py` | Modify | Pending state, new methods, `handle()` 3-tuple |
| `tests/test_bot_handler.py` | Modify | Update for 3-tuple, add pending flow tests |
| `bot.py` | Modify | Inline keyboard, CallbackQueryHandler |

---

## Task 1: ExpenseCategorizer

**Files:**
- Create: `src/categorizer.py`
- Create: `tests/test_categorizer.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_categorizer.py
import json
import pytest
from src.categorizer import ExpenseCategorizer
from src.parser import Intent

@pytest.fixture
def cat(tmp_path):
    return ExpenseCategorizer(mappings_path=tmp_path / "mappings.json")

def test_lookup_returns_none_when_no_mapping(cat):
    assert cat.lookup("mercado") is None

def test_save_and_lookup_round_trip(cat):
    cat.save("mercado", "Alimentação")
    assert cat.lookup("mercado") == "Alimentação"

def test_lookup_is_case_insensitive(cat):
    cat.save("Mercado", "Alimentação")
    assert cat.lookup("MERCADO") == "Alimentação"

def test_save_overwrites_existing(cat):
    cat.save("uber", "Transporte")
    cat.save("uber", "Outros")
    assert cat.lookup("uber") == "Outros"

def test_mappings_persisted_to_disk(tmp_path):
    path = tmp_path / "mappings.json"
    c1 = ExpenseCategorizer(mappings_path=path)
    c1.save("luz", "Moradia")
    c2 = ExpenseCategorizer(mappings_path=path)
    assert c2.lookup("luz") == "Moradia"

def test_categories_for_expense(cat):
    cats = cat.categories_for(Intent.EXPENSE)
    labels = [label for label, _ in cats]
    assert "🏠 Moradia" in labels
    assert "🍽️ Alimentação" in labels
    assert len(cats) == 10

def test_categories_for_income(cat):
    cats = cat.categories_for(Intent.INCOME)
    assert len(cats) == 3
    assert cats[0][1] == "Fixa mensal"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/python3 -m pytest tests/test_categorizer.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.categorizer'`

- [ ] **Step 3: Implement `src/categorizer.py`**

```python
# src/categorizer.py
import json
from pathlib import Path
from src.parser import Intent

DATA_DIR = Path(__file__).parent.parent / "data"

EXPENSE_CATEGORIES: list[tuple[str, str]] = [
    ("🏠 Moradia", "Moradia"),
    ("🚌 Transporte", "Transporte"),
    ("💳 Parcelamentos", "Parcelamentos"),
    ("👨‍👩‍👧‍👦 Família", "Família"),
    ("🍽️ Alimentação", "Alimentação"),
    ("📝 Assinaturas & Serviços", "Assinaturas & Serviços"),
    ("🏦 Empréstimo Itaú", "Empréstimo Itaú"),
    ("❤️ Saúde", "Saúde"),
    ("🎓 Educação - MBA", "Educação - MBA"),
    ("❓ Outros", "Outros"),
]

INCOME_CATEGORIES: list[tuple[str, str]] = [
    ("💰 Fixa mensal", "Fixa mensal"),
    ("📲 Pagamentos", "Pagamentos"),
    ("❓ Outros", "Outros"),
]


class ExpenseCategorizer:
    def __init__(self, mappings_path: Path = DATA_DIR / "category_mappings.json"):
        self.mappings_path = Path(mappings_path)
        self._mappings: dict[str, str] = {}
        if self.mappings_path.exists():
            self._mappings = json.loads(self.mappings_path.read_text(encoding="utf-8"))

    def lookup(self, description: str) -> str | None:
        return self._mappings.get(description.lower().strip())

    def save(self, description: str, category: str) -> None:
        self._mappings[description.lower().strip()] = category
        self.mappings_path.parent.mkdir(parents=True, exist_ok=True)
        self.mappings_path.write_text(
            json.dumps(self._mappings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def categories_for(self, intent: Intent) -> list[tuple[str, str]]:
        if intent == Intent.INCOME:
            return INCOME_CATEGORIES
        return EXPENSE_CATEGORIES
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
.venv/bin/python3 -m pytest tests/test_categorizer.py -v
```
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add src/categorizer.py tests/test_categorizer.py
git commit -m "feat: add ExpenseCategorizer with JSON mappings persistence"
```

---

## Task 2: Update Parser Category List

**Files:**
- Modify: `src/parser.py` line 25

- [ ] **Step 1: Update SYSTEM_PROMPT in `src/parser.py`**

Replace the `Categorias despesa` line (currently: `Alimentação, Moradia, Transporte, Saúde, Lazer, Assinaturas & Serviços, Família, Parcelamentos, Despesas Variáveis (pessoal), Outros`) with:

```python
SYSTEM_PROMPT = """Classifique mensagens financeiras pessoais. Responda APENAS com JSON válido, sem markdown.

Intents:
- EXPENSE: lançar despesa ("gastei", "paguei", "comprei")
- INCOME: lançar receita ("recebi", "entrou", "pix de")
- QUERY: consulta financeira ("como estou", "saldo", "resumo", "quanto gastei")
- HELP: ajuda ou comando desconhecido

Formato:
{"intent":"EXPENSE|INCOME|QUERY|HELP","amount":50.0,"description":"texto","category":"categoria","date":"YYYY-MM-DD ou null","query_month":null,"query_year":null}

Para QUERY: se a mensagem mencionar um mês específico (ex: "abril", "março de 2026", "mês que vem"), preencha query_month (1-12) e query_year (ex: 2026). Caso contrário, deixe null.

Categorias despesa: Moradia, Transporte, Parcelamentos, Família, Alimentação, Assinaturas & Serviços, Empréstimo Itaú, Saúde, Educação - MBA, Outros
Categorias receita: Fixa mensal, Pagamentos, Outros"""
```

- [ ] **Step 2: Run all existing tests**

```bash
.venv/bin/python3 -m pytest tests/ -v
```
Expected: all pass (parser tests mock the API, so the prompt change doesn't affect them)

- [ ] **Step 3: Commit**

```bash
git add src/parser.py
git commit -m "fix: align parser category list with inline keyboard categories"
```

---

## Task 3: BotHandler Pending State + New Methods

**Files:**
- Modify: `src/bot_handler.py`
- Modify: `tests/test_bot_handler.py`

This task changes `_handle_transaction` to return `tuple[str, ParsedMessage]` (no longer saves immediately), adds pending state infrastructure, and changes `handle()` to return a 3-tuple.

- [ ] **Step 1: Write failing tests for the new pending flow**

Add to `tests/test_bot_handler.py`:

```python
from datetime import datetime, timezone, timedelta
from src.bot_handler import BotHandler, PendingTransaction
from src.categorizer import ExpenseCategorizer

# Update fixture to inject categorizer:
@pytest.fixture
def handler(tmp_path):
    return BotHandler(
        db_path=str(tmp_path / "test.db"),
        admin_chat_id=ADMIN_ID,
        pix_key="pix@email.com",
        pix_amount=29.90,
        categorizer=ExpenseCategorizer(mappings_path=tmp_path / "mappings.json"),
    )

def test_expense_returns_pending_not_saved(handler):
    """Transaction is NOT saved to DB until confirmed."""
    handler.store.upsert_user(USER_ID, UserStatus.ACTIVE)
    p = parsed(Intent.EXPENSE, amount=50.0, desc="mercado")
    with patch("src.bot_handler.parse_message", return_value=p):
        reply, use_markdown, pending = handler.handle("gastei 50 no mercado", chat_id=USER_ID)
    assert pending is not None
    assert "50" in reply
    # NOT saved yet
    df = handler.store.get_transactions_df(2026, 4, type="expense")
    assert len(df) == 0

def test_confirm_saves_transaction(handler):
    handler.store.upsert_user(USER_ID, UserStatus.ACTIVE)
    p = parsed(Intent.EXPENSE, amount=50.0, desc="mercado")
    with patch("src.bot_handler.parse_message", return_value=p):
        _, _, pending = handler.handle("gastei 50 no mercado", chat_id=USER_ID)
    handler.register_pending("pid:1", pending)
    result = handler.confirm_transaction("pid:1")
    assert result is not None
    assert "lançada" in result.lower() or "50" in result
    df = handler.store.get_transactions_df(2026, 4, type="expense")
    assert len(df) == 1

def test_confirm_idempotent(handler):
    """Second confirm on same pending_id returns None, no duplicate row."""
    handler.store.upsert_user(USER_ID, UserStatus.ACTIVE)
    p = parsed(Intent.EXPENSE, amount=50.0, desc="mercado")
    with patch("src.bot_handler.parse_message", return_value=p):
        _, _, pending = handler.handle("gastei 50 no mercado", chat_id=USER_ID)
    handler.register_pending("pid:2", pending)
    handler.confirm_transaction("pid:2")
    result2 = handler.confirm_transaction("pid:2")
    assert result2 is None
    df = handler.store.get_transactions_df(2026, 4, type="expense")
    assert len(df) == 1  # only one row

def test_confirm_with_category_override(handler):
    handler.store.upsert_user(USER_ID, UserStatus.ACTIVE)
    p = parsed(Intent.EXPENSE, amount=50.0, desc="mercado", cat="Alimentação")
    with patch("src.bot_handler.parse_message", return_value=p):
        _, _, pending = handler.handle("gastei 50 no mercado", chat_id=USER_ID)
    handler.register_pending("pid:3", pending)
    handler.confirm_transaction("pid:3", category_index=0)  # index 0 = Moradia
    df = handler.store.get_transactions_df(2026, 4, type="expense")
    assert df.iloc[0]["CATEGORIA"] == "Moradia"

def test_confirm_expired_returns_none(handler):
    handler.store.upsert_user(USER_ID, UserStatus.ACTIVE)
    p = parsed(Intent.EXPENSE, amount=50.0, desc="mercado")
    with patch("src.bot_handler.parse_message", return_value=p):
        _, _, pending = handler.handle("gastei 50 no mercado", chat_id=USER_ID)
    # manually inject expired entry
    from src.bot_handler import PendingTransaction
    handler._pending["pid:expired"] = PendingTransaction(
        parsed=pending,
        expires_at=datetime.now(tz=timezone.utc) - timedelta(minutes=1),
    )
    assert handler.confirm_transaction("pid:expired") is None

def test_get_pending_returns_none_when_missing(handler):
    assert handler.get_pending("nonexistent") is None

def test_categorizer_lookup_overrides_haiku_category(handler):
    handler.store.upsert_user(USER_ID, UserStatus.ACTIVE)
    handler.categorizer.save("mercado", "Outros")  # user previously corrected this
    p = parsed(Intent.EXPENSE, amount=50.0, desc="mercado", cat="Alimentação")
    with patch("src.bot_handler.parse_message", return_value=p):
        reply, _, pending = handler.handle("gastei 50 no mercado", chat_id=USER_ID)
    assert pending.category == "Outros"
```

- [ ] **Step 2: Run new tests to confirm they fail**

```bash
.venv/bin/python3 -m pytest tests/test_bot_handler.py -v -k "pending or confirm or categorizer"
```
Expected: all fail with `ImportError` or `TypeError`

- [ ] **Step 3: Update `src/bot_handler.py`**

Replace the entire file with:

```python
import os
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
import pandas as pd

from src.parser import parse_message, Intent, ParsedMessage
from src.store import TransactionStore, UserStatus
from src.categorizer import ExpenseCategorizer

DATA_DIR = Path(__file__).parent.parent / "data"
PENDING_TTL = timedelta(minutes=10)

EMPTY_EXPENSES = pd.DataFrame(columns=["DESCRIÇÃO", "LANÇAMENTO", "VENCIMENTO", "EFETIVAÇÃO", "CATEGORIA", "SUBCATEGORIA", "CARTÃO", "CONTA", "VALOR", "OBSERVAÇÕES"])
EMPTY_INCOME = pd.DataFrame(columns=["DESCRIÇÃO", "LANÇAMENTO", "VENCIMENTO", "EFETIVAÇÃO", "CATEGORIA", "SUBCATEGORIA", "CONTA", "VALOR", "OBSERVAÇÕES"])

HELP_TEXT = """Assistente Financeiro 💰

Lançamentos:
• gastei 50 no mercado → despesa
• recebi 200 pix da raissa → receita
• paguei 150 de luz → despesa

Consultas:
• resumo — resumo do mês
• saldo — quanto sobra
• Qualquer pergunta livre para a IA

Comandos:
• /ajuda — este menu
• /start — cadastro inicial
"""


@dataclass
class PendingTransaction:
    parsed: ParsedMessage
    expires_at: datetime
    chat_id: int = 0


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
        categorizer: ExpenseCategorizer | None = None,
    ):
        self.store = TransactionStore(db_path) if db_path else TransactionStore()
        self.admin_chat_id = admin_chat_id or int(os.environ.get("ADMIN_CHAT_ID", "0"))
        if not self.admin_chat_id:
            raise ValueError("ADMIN_CHAT_ID must be set (env var or constructor param)")
        self.pix_key = pix_key or os.environ.get("PIX_KEY", "")
        self.pix_amount = pix_amount or float(os.environ.get("PIX_AMOUNT", "0"))
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.categorizer = categorizer or ExpenseCategorizer()
        self._history: dict[int, list[dict]] = {}
        self._pending: dict[str, PendingTransaction] = {}

        if self.admin_chat_id:
            user = self.store.get_user(self.admin_chat_id)
            if user is None or user["status"] != UserStatus.ADMIN:
                self.store.upsert_user(self.admin_chat_id, UserStatus.ADMIN)

    # ── Pending transaction management ────────────────────────────────────────

    def register_pending(self, pending_id: str, parsed: ParsedMessage, chat_id: int = 0) -> None:
        now = datetime.now(tz=timezone.utc)
        self._pending[pending_id] = PendingTransaction(
            parsed=parsed,
            expires_at=now + PENDING_TTL,
            chat_id=chat_id,
        )
        # Cleanup expired entries
        expired = [k for k, v in self._pending.items() if v.expires_at < now]
        for k in expired:
            del self._pending[k]

    def get_pending(self, pending_id: str) -> ParsedMessage | None:
        entry = self._pending.get(pending_id)
        if entry is None or entry.expires_at < datetime.now(tz=timezone.utc):
            return None
        return entry.parsed

    def confirm_transaction(self, pending_id: str, category_index: int | None = None) -> str | None:
        entry = self._pending.pop(pending_id, None)
        if entry is None or entry.expires_at < datetime.now(tz=timezone.utc):
            return None

        parsed = entry.parsed
        category = parsed.category or "Outros"

        if category_index is not None:
            categories = self.categorizer.categories_for(parsed.intent)
            if 0 <= category_index < len(categories):
                category = categories[category_index][1]
                self.categorizer.save(parsed.description or parsed.raw, category)

        tx_date = parsed.date or date.today().isoformat()
        tx_type = "expense" if parsed.intent == Intent.EXPENSE else "income"

        self.store.add_transaction(
            type=tx_type,
            description=parsed.description or parsed.raw,
            category=category,
            value=parsed.amount,
            date=tx_date,
            chat_id=entry.chat_id,
        )

        emoji = "💸" if tx_type == "expense" else "💰"
        label = "Despesa" if tx_type == "expense" else "Receita"
        return (
            f"{emoji} {label} lançada!\n"
            f"Valor: R$ {parsed.amount:.2f}\n"
            f"Categoria: {category}\n"
            f"Descrição: {parsed.description}\n"
            f"Data: {tx_date}"
        )

    # ── Main routing ──────────────────────────────────────────────────────────

    def handle(self, text: str, chat_id: int) -> tuple[str, bool, ParsedMessage | None]:
        """Returns (reply_text, use_markdown, pending_parsed_or_None)."""
        text = text.strip()

        if chat_id == self.admin_chat_id:
            admin_reply = self._handle_admin(text)
            if admin_reply is not None:
                return admin_reply, False, None

        if text.lower() == "/start":
            return self._handle_start(chat_id), False, None

        user = self.store.get_user(chat_id)
        if user is None:
            return self._handle_start(chat_id), False, None
        if user["status"] == UserStatus.PENDING:
            return "⏳ Seu cadastro está pendente. Aguarde a confirmação do pagamento.", False, None

        if text.lower() in ("/ajuda", "ajuda"):
            return HELP_TEXT, False, None

        parsed = parse_message(text)

        if parsed.intent == Intent.HELP:
            return HELP_TEXT, False, None
        if parsed.intent in (Intent.EXPENSE, Intent.INCOME):
            reply, pending = self._handle_transaction(parsed, chat_id)
            return reply, False, pending
        return self._handle_query(text, chat_id, parsed.query_year, parsed.query_month), True, None

    def _handle_start(self, chat_id: int) -> str:
        user = self.store.get_user(chat_id)
        if user and user["status"] in (UserStatus.ACTIVE, UserStatus.ADMIN):
            return "✅ Você já tem acesso! Envie /ajuda para ver os comandos disponíveis."
        if user is None:
            self.store.upsert_user(chat_id, UserStatus.PENDING)
        valor = f"R$ {self.pix_amount:.2f}" if self.pix_amount else "o valor combinado"
        return (
            f"👋 Olá! Este é um assistente financeiro pessoal.\n\n"
            f"Para ter acesso, faça um PIX de {valor} para:\n"
            f"🔑 Chave: {self.pix_key}\n\n"
            f"Informe seu chat_id ao administrador: {chat_id}\n\n"
            f"Após o pagamento, seu acesso será liberado. ✅"
        )

    def _handle_admin(self, text: str) -> str | None:
        parts = text.strip().split()
        cmd = parts[0].lower() if parts else ""

        if cmd == "/ativar" and len(parts) == 2:
            try:
                target_id = int(parts[1])
            except ValueError:
                return "Uso: /ativar <chat_id>"
            self.store.upsert_user(target_id, UserStatus.ACTIVE)
            return f"✅ Usuário {target_id} ativado."

        if cmd == "/desativar" and len(parts) == 2:
            try:
                target_id = int(parts[1])
            except ValueError:
                return "Uso: /desativar <chat_id>"
            self.store.upsert_user(target_id, UserStatus.PENDING)
            return f"🚫 Usuário {target_id} desativado."

        if cmd == "/pendentes":
            pending = self.store.list_pending_users()
            if not pending:
                return "Nenhum usuário pendente. ✅"
            lines = ["Usuários pendentes:"]
            for u in pending:
                name = u.get("username") or "sem username"
                lines.append(f"• {u['chat_id']} ({name}) — desde {u['registered_at'][:10]}")
            return "\n".join(lines)

        return None

    def _handle_transaction(self, parsed: ParsedMessage, chat_id: int) -> tuple[str, ParsedMessage | None]:
        if parsed.amount is None:
            return "Não entendi o valor. Tente: gastei 50 reais no mercado", None

        # Override category from learned mappings
        learned = self.categorizer.lookup(parsed.description or parsed.raw)
        if learned:
            parsed = ParsedMessage(
                intent=parsed.intent,
                amount=parsed.amount,
                description=parsed.description,
                category=learned,
                date=parsed.date,
                raw=parsed.raw,
                query_month=parsed.query_month,
                query_year=parsed.query_year,
            )

        emoji = "💸" if parsed.intent == Intent.EXPENSE else "💰"
        label = "Despesa" if parsed.intent == Intent.EXPENSE else "Receita"
        text = (
            f"{emoji} {label} identificada\n"
            f"Descrição: {parsed.description}\n"
            f"Valor: R$ {parsed.amount:.2f}\n"
            f"Categoria: {parsed.category}\n\n"
            f"A categoria está correta?"
        )
        return text, parsed

    def _handle_query(self, text: str, chat_id: int, query_year: int | None = None, query_month: int | None = None) -> str:
        from src.loader import load_csv
        from src.analyzer import analyze_month
        from src.assistant import FinancialAssistant

        today = date.today()
        year = query_year or today.year
        month = query_month or today.month

        expenses_path = _find_latest("despesas-*.csv")
        income_path = _find_latest("receitas-*.csv")

        expenses_df = load_csv(expenses_path) if expenses_path else EMPTY_EXPENSES.copy()
        income_df = load_csv(income_path) if income_path else EMPTY_INCOME.copy()

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
        reply = assistant.chat(text)
        self._history[chat_id] = assistant.history
        return reply
```

- [ ] **Step 4: Update existing tests in `tests/test_bot_handler.py` for 3-tuple**

The following 6 functions use `reply, _ = handler.handle(...)` and must be updated to `reply, _, _ = handler.handle(...)`:
- `test_unknown_user_receives_pix_info` (line ~25)
- `test_pending_user_receives_wait_message` (line ~31)
- `test_admin_activates_user` (line ~36)
- `test_admin_lists_pending` (line ~42)
- `test_active_user_help` (line ~56)
- `test_non_admin_cannot_activate_users` (line ~70)

Also add this new test for the `amount is None` path:

```python
def test_expense_without_amount_returns_no_pending(handler):
    handler.store.upsert_user(USER_ID, UserStatus.ACTIVE)
    p = parsed(Intent.EXPENSE, amount=None, desc="mercado")
    with patch("src.bot_handler.parse_message", return_value=p):
        reply, _, pending = handler.handle("gastei no mercado", chat_id=USER_ID)
    assert pending is None
    assert "valor" in reply.lower()
```

Also update `test_active_user_expense` — it now checks pending, not DB:

```python
def test_active_user_expense(handler):
    handler.store.upsert_user(USER_ID, UserStatus.ACTIVE)
    p = parsed(Intent.EXPENSE, amount=50.0, desc="mercado")
    with patch("src.bot_handler.parse_message", return_value=p):
        reply, _, pending = handler.handle("gastei 50 no mercado", chat_id=USER_ID)
    assert "50" in reply
    assert pending is not None
    # Transaction not in DB until confirmed
    df = handler.store.get_transactions_df(2026, 4, type="expense")
    assert len(df) == 0
```

- [ ] **Step 5: Run all tests**

```bash
.venv/bin/python3 -m pytest tests/ -v
```
Expected: all pass (48+ tests)

- [ ] **Step 6: Commit**

```bash
git add src/bot_handler.py tests/test_bot_handler.py
git commit -m "feat: add pending transaction state to BotHandler, handle() returns 3-tuple"
```

---

## Task 4: Inline Keyboard in bot.py

**Files:**
- Modify: `bot.py`

- [ ] **Step 1: Replace `bot.py` with the updated version**

```python
import logging
import os
import uuid
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from dotenv import load_dotenv
from src.bot_handler import BotHandler

load_dotenv()
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

_handler = BotHandler()


def _confirm_keyboard(pending_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirmar", callback_data=f"confirm:{pending_id}"),
        InlineKeyboardButton("✏️ Alterar", callback_data=f"change:{pending_id}"),
    ]])


def _category_keyboard(pending_id: str, categories: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(label, callback_data=f"cat:{pending_id}:{i}")]
        for i, (label, _) in enumerate(categories)
    ]
    return InlineKeyboardMarkup(buttons)


async def _reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return
    chat_id = update.effective_chat.id
    text = update.message.text or ""
    logger.info(f"[{chat_id}] {text[:60]}")
    try:
        reply, use_markdown, pending = _handler.handle(text, chat_id=chat_id)
        parse_mode = "Markdown" if use_markdown else None

        if pending is not None:
            pending_id = uuid.uuid4().hex[:12]
            keyboard = _confirm_keyboard(pending_id)
            await update.message.reply_text(reply, reply_markup=keyboard, parse_mode=parse_mode)
            _handler.register_pending(pending_id, pending, chat_id=chat_id)
        else:
            await update.message.reply_text(reply, parse_mode=parse_mode)

    except Exception as e:
        logger.error(f"Error handling message from {chat_id}: {e}")
        await update.message.reply_text("⚠️ Erro interno. Tente novamente em instantes.")


async def _callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()  # remove spinner

    if not query.data:
        return

    parts = query.data.split(":")
    action = parts[0]

    if action == "confirm":
        pending_id = parts[1]
        result = _handler.confirm_transaction(pending_id)
        if result is None:
            await query.edit_message_text("⚠️ Confirmação expirada. Envie a transação novamente.")
        else:
            await query.edit_message_text(result)

    elif action == "change":
        pending_id = parts[1]
        pending = _handler.get_pending(pending_id)
        if pending is None:
            await query.edit_message_text("⚠️ Confirmação expirada. Envie a transação novamente.")
            return
        categories = _handler.categorizer.categories_for(pending.intent)
        keyboard = _category_keyboard(pending_id, categories)
        await query.edit_message_reply_markup(keyboard)

    elif action == "cat":
        pending_id = parts[1]
        idx = int(parts[2])
        result = _handler.confirm_transaction(pending_id, category_index=idx)
        if result is None:
            await query.edit_message_text("⚠️ Confirmação expirada. Envie a transação novamente.")
        else:
            await query.edit_message_text(result)


def main() -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).build()

    for cmd in ["start", "ajuda", "ativar", "desativar", "pendentes"]:
        app.add_handler(CommandHandler(cmd, _reply))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _reply))
    app.add_handler(CallbackQueryHandler(_callback))

    logger.info("Bot started. Polling for messages...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run all tests**

```bash
.venv/bin/python3 -m pytest tests/ -v
```
Expected: all pass

- [ ] **Step 3: Commit**

```bash
git add bot.py
git commit -m "feat: add inline keyboard confirmation for expense/income entries"
```

---

## Task 5: Push and Deploy

- [ ] **Step 1: Push to GitHub** (run in Windows terminal)

```bash
git push
```

- [ ] **Step 2: Deploy to VPS**

```bash
cd /root/financas-ai
git pull
docker compose up --build -d
docker compose logs -f
```

- [ ] **Step 3: Smoke test**

Send "gastei 50 no mercado" to the bot. Expected:
```
💸 Despesa identificada
Descrição: mercado
Valor: R$ 50,00
Categoria: Alimentação

A categoria está correta?
[✅ Confirmar]  [✏️ Alterar]
```

Click ✅ — expected: "💸 Despesa lançada! ..."
Send same message again — expected: category is still Alimentação (no learned mapping yet)
Click ✏️ Alterar → select 🏠 Moradia → expected: lançada with Moradia
Send "gastei 50 no mercado" again → expected: category pre-filled as Moradia (learned mapping applied)
