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
        self._last_period: dict[int, tuple[int, int]] = {}
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
        entry = self._pending.get(pending_id)
        if entry is None or entry.expires_at < datetime.now(tz=timezone.utc):
            self._pending.pop(pending_id, None)  # clean up if expired
            return None
        self._pending.pop(pending_id)  # idempotency: remove after first confirm

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
            f"Descrição: {parsed.description or parsed.raw}\n"
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
            f"Descrição: {parsed.description or parsed.raw}\n"
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

        # Reset history when the queried period changes to avoid contradictory context
        current_period = (year, month)
        if self._last_period.get(chat_id) != current_period:
            self._history[chat_id] = []
            self._last_period[chat_id] = current_period
        elif chat_id not in self._history:
            self._history[chat_id] = []

        assistant = FinancialAssistant(report, api_key=self.api_key)
        assistant.history = self._history[chat_id]
        reply = assistant.chat(text)
        self._history[chat_id] = assistant.history
        return reply
