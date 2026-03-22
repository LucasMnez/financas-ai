import json
import os
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
        model=PARSER_MODEL,
        max_tokens=256,
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
