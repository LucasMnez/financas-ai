import os
from datetime import date
from pathlib import Path
import pandas as pd

from src.parser import parse_message, Intent
from src.store import TransactionStore, UserStatus

DATA_DIR = Path(__file__).parent.parent / "data"

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
        if not self.admin_chat_id:
            raise ValueError("ADMIN_CHAT_ID must be set (env var or constructor param)")
        self.pix_key = pix_key or os.environ.get("PIX_KEY", "")
        self.pix_amount = pix_amount or float(os.environ.get("PIX_AMOUNT", "0"))
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._history: dict[int, list[dict]] = {}

        # Ensure admin is always in DB as ADMIN status
        if self.admin_chat_id:
            user = self.store.get_user(self.admin_chat_id)
            if user is None or user["status"] != UserStatus.ADMIN:
                self.store.upsert_user(self.admin_chat_id, UserStatus.ADMIN)

    def handle(self, text: str, chat_id: int) -> tuple[str, bool]:
        """Returns (reply_text, use_markdown)."""
        text = text.strip()

        # Admin commands (only from admin chat_id)
        if chat_id == self.admin_chat_id:
            admin_reply = self._handle_admin(text)
            if admin_reply is not None:
                return admin_reply, False

        # /start always triggers registration flow
        if text.lower() == "/start":
            return self._handle_start(chat_id), False

        # State gate
        user = self.store.get_user(chat_id)
        if user is None:
            return self._handle_start(chat_id), False  # shows PIX info and saves PENDING
        if user["status"] == UserStatus.PENDING:
            return "⏳ Seu cadastro está pendente. Aguarde a confirmação do pagamento.", False

        # Active user
        if text.lower() in ("/ajuda", "ajuda"):
            return HELP_TEXT, False

        parsed = parse_message(text)

        if parsed.intent == Intent.HELP:
            return HELP_TEXT, False
        if parsed.intent in (Intent.EXPENSE, Intent.INCOME):
            return self._handle_transaction(parsed, chat_id), False
        return self._handle_query(text, chat_id), True

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

        return None  # not an admin command, process as active user

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

        emoji = "💸" if tx_type == "expense" else "💰"
        label = "Despesa" if tx_type == "expense" else "Receita"
        return (
            f"{emoji} *{label} lançada!*\n"
            f"Valor: R$ {parsed.amount:.2f}\n"
            f"Categoria: {parsed.category}\n"
            f"Descrição: {parsed.description}\n"
            f"Data: {tx_date}"
        )

    def _handle_query(self, text: str, chat_id: int) -> str:
        from src.loader import load_csv
        from src.analyzer import analyze_month
        from src.assistant import FinancialAssistant

        today = date.today()
        year, month = today.year, today.month

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

        # chat() also prints to stdout — expected side effect in container context
        reply = assistant.chat(text)
        self._history[chat_id] = assistant.history
        return reply
