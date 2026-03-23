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
