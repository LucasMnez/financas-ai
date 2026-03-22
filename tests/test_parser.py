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
    assert r.category == "Alimentação"

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

def test_category_fallback_to_outros_when_null():
    with patch("src.parser._client") as m:
        m.messages.create.return_value = _mock(
            '{"intent":"QUERY","amount":null,"description":null,"category":null,"date":null}'
        )
        r = parse_message("como estou?")
    assert r.intent == Intent.QUERY
    assert r.category == "Outros"

def test_fallback_to_help_on_malformed_response():
    with patch("src.parser._client") as m:
        m.messages.create.return_value = _mock("não é json válido")
        r = parse_message("qualquer coisa")
    assert r.intent == Intent.HELP
    assert r.raw == "qualquer coisa"
