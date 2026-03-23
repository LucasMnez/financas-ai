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
