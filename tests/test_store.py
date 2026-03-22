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
