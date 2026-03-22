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
