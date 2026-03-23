import pytest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
from src.bot_handler import BotHandler, PendingTransaction
from src.parser import Intent, ParsedMessage
from src.store import UserStatus
from src.categorizer import ExpenseCategorizer

ADMIN_ID = 111111111
USER_ID  = 999999999

@pytest.fixture
def handler(tmp_path):
    return BotHandler(
        db_path=str(tmp_path / "test.db"),
        admin_chat_id=ADMIN_ID,
        pix_key="pix@email.com",
        pix_amount=29.90,
        categorizer=ExpenseCategorizer(mappings_path=tmp_path / "mappings.json"),
    )

def parsed(intent, amount=None, desc=None, cat="Alimentação", date="2026-04-10"):
    return ParsedMessage(intent=intent, amount=amount, description=desc,
                         category=cat, date=date, raw="")

def test_unknown_user_receives_pix_info(handler):
    with patch("src.bot_handler.parse_message"):
        reply, _, _ = handler.handle("/start", chat_id=USER_ID)
    assert "PIX" in reply or "pix" in reply.lower()
    assert handler.store.get_user(USER_ID)["status"] == UserStatus.PENDING

def test_pending_user_receives_wait_message(handler):
    handler.store.upsert_user(USER_ID, UserStatus.PENDING)
    with patch("src.bot_handler.parse_message"):
        reply, _, _ = handler.handle("oi", chat_id=USER_ID)
    assert "aguard" in reply.lower() or "pend" in reply.lower()

def test_admin_activates_user(handler):
    handler.store.upsert_user(USER_ID, UserStatus.PENDING)
    reply, _, _ = handler.handle(f"/ativar {USER_ID}", chat_id=ADMIN_ID)
    assert "ativado" in reply.lower()
    assert handler.store.get_user(USER_ID)["status"] == UserStatus.ACTIVE

def test_admin_lists_pending(handler):
    handler.store.upsert_user(USER_ID, UserStatus.PENDING)
    reply, _, _ = handler.handle("/pendentes", chat_id=ADMIN_ID)
    assert str(USER_ID) in reply

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

def test_active_user_help(handler):
    handler.store.upsert_user(USER_ID, UserStatus.ACTIVE)
    p = parsed(Intent.HELP)
    with patch("src.bot_handler.parse_message", return_value=p):
        reply, _, _ = handler.handle("/ajuda", chat_id=USER_ID)
    assert "gastei" in reply.lower()

def test_non_admin_cannot_activate_users(handler):
    handler.store.upsert_user(USER_ID, UserStatus.ACTIVE)
    other_user = 888888888
    handler.store.upsert_user(other_user, UserStatus.PENDING)
    # USER_ID (not admin) tries to activate other_user
    p = ParsedMessage(intent=Intent.HELP, amount=None, description=None,
                      category=None, date=None, raw=f"/ativar {other_user}")
    with patch("src.bot_handler.parse_message", return_value=p):
        reply, _, _ = handler.handle(f"/ativar {other_user}", chat_id=USER_ID)
    # Should NOT activate — other_user still PENDING
    assert handler.store.get_user(other_user)["status"] == UserStatus.PENDING


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
    assert "50" in result
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


def test_expense_without_amount_returns_no_pending(handler):
    handler.store.upsert_user(USER_ID, UserStatus.ACTIVE)
    p = parsed(Intent.EXPENSE, amount=None, desc="mercado")
    with patch("src.bot_handler.parse_message", return_value=p):
        reply, _, pending = handler.handle("gastei no mercado", chat_id=USER_ID)
    assert pending is None
    assert "valor" in reply.lower()
