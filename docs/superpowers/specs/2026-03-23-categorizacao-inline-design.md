# Design: Categorização com Confirmação Inline no Bot Telegram

**Data:** 2026-03-23
**Status:** Aprovado

## Contexto

O bot atualmente registra despesas e receitas automaticamente via Claude Haiku, que já sugere uma categoria. O objetivo é adicionar um fluxo de confirmação via botões inline do Telegram, permitindo ao usuário validar ou corrigir a categoria antes de salvar. Correções são persistidas em `data/category_mappings.json` e consultadas nas próximas mensagens.

## Fluxo do Usuário

```
Usuário: "gastei 50 no mercado"

Bot:
  💸 Despesa identificada
  Descrição: mercado
  Valor: R$ 50,00
  Categoria: 🍽️ Alimentação

  [✅ Confirmar]  [✏️ Alterar categoria]
```

Se confirmar → transação salva no SQLite, mensagem de confirmação simples.

Se alterar → bot edita a mensagem com teclado de categorias:

```
  Escolha a categoria:
  [🏠 Moradia]          [🚌 Transporte]
  [💳 Parcelamentos]    [👨‍👩‍👧‍👦 Família]
  [🍽️ Alimentação]      [📝 Assinaturas & Serviços]
  [🏦 Empréstimo Itaú]  [❤️ Saúde]
  [🎓 Educação - MBA]   [❓ Outros]
```

Após seleção → salva mapeamento + transação, confirma ao usuário.

O mesmo fluxo se aplica a receitas, com categorias: Fixa mensal, Pagamentos, Outros.

## Categorias

As categorias do bot substituem as do parser. `src/parser.py` SYSTEM_PROMPT será atualizado para usar exatamente esta lista:

**Despesas:**
| Índice | Label | Categoria |
|--------|-------|-----------|
| 0 | 🏠 Moradia | Moradia |
| 1 | 🚌 Transporte | Transporte |
| 2 | 💳 Parcelamentos | Parcelamentos |
| 3 | 👨‍👩‍👧‍👦 Família | Família |
| 4 | 🍽️ Alimentação | Alimentação |
| 5 | 📝 Assinaturas & Serviços | Assinaturas & Serviços |
| 6 | 🏦 Empréstimo Itaú | Empréstimo Itaú |
| 7 | ❤️ Saúde | Saúde |
| 8 | 🎓 Educação - MBA | Educação - MBA |
| 9 | ❓ Outros | Outros |

**Receitas:**
| Índice | Label | Categoria |
|--------|-------|-----------|
| 0 | 💰 Fixa mensal | Fixa mensal |
| 1 | 📲 Pagamentos | Pagamentos |
| 2 | ❓ Outros | Outros |

## Arquitetura

### `src/categorizer.py` (novo)

Responsabilidade única: consultar e persistir mapeamentos de descrição → categoria.

```python
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
    def __init__(self, mappings_path: Path = DATA_DIR / "category_mappings.json")
    def lookup(self, description: str) -> str | None
        # normaliza (lower().strip()), consulta mappings. Retorna None se não encontrado.
    def save(self, description: str, category: str) -> None
        # normaliza e salva/atualiza no JSON
    def categories_for(self, intent: Intent) -> list[tuple[str, str]]
        # retorna EXPENSE_CATEGORIES se EXPENSE, INCOME_CATEGORIES se INCOME
```

O arquivo JSON:
```json
{
  "mercado": "Alimentação",
  "uber": "Transporte"
}
```

Inicializado como `{}` se não existir.

### `src/bot_handler.py` (modificado)

**Estado pendente** — dict em memória com TTL de 10 minutos:
```python
from datetime import datetime, timedelta
PENDING_TTL = timedelta(minutes=10)

@dataclass
class PendingTransaction:
    parsed: ParsedMessage
    expires_at: datetime

self._pending: dict[str, PendingTransaction] = {}
```

**Nota sobre reinicialização:** o dict é in-memory. Se o bot reiniciar, todas as confirmações pendentes são perdidas. Os botões ainda aparecem no Telegram mas clicar retorna "Confirmação expirada." — comportamento esperado, não é bug.

**`register_pending(pending_id: str, parsed: ParsedMessage) -> None`**
Salva `PendingTransaction(parsed, datetime.now(tz=timezone.utc) + PENDING_TTL)` no dict.
Também executa limpeza de entradas expiradas (varre o dict e remove as vencidas).

**`confirm_transaction(pending_id: str, category_index: int | None = None) -> str | None`**
- Busca `_pending[pending_id]`. Se não encontrado ou expirado → retorna `None` (chamador trata).
- Remove a chave do dict imediatamente (idempotência: segunda chamada retorna `None` silenciosamente).
- Se `category_index` fornecido → resolve `category = categorizer.categories_for(intent)[category_index][1]` e chama `categorizer.save(description, category)`.
- Salva no SQLite via `store.add_transaction()`.
- Retorna mensagem de confirmação.

**`_handle_transaction(parsed, chat_id) -> tuple[str, ParsedMessage]`** — em vez de salvar imediatamente:
1. Consulta `categorizer.lookup(parsed.description)` → sobrescreve `parsed.category` se encontrado.
2. Retorna `(texto_confirmação, parsed)` com categoria já resolvida.

`handle()` usa esse retorno para construir o terceiro elemento da tupla:
```python
text, pending_parsed = self._handle_transaction(parsed, chat_id)
return text, False, pending_parsed
```

**Mudança na assinatura de `handle()`:**
```python
def handle(self, text: str, chat_id: int) -> tuple[str, bool, ParsedMessage | None]:
    """Returns (reply_text, use_markdown, pending_parsed_or_None)."""
```

- Terceiro elemento é `None` para tudo exceto transações aguardando confirmação.
- Para transações: terceiro elemento é o `ParsedMessage` com categoria já resolvida.
- `bot.py` é responsável por chamar `register_pending()` após obter o `message_id`.

**`BotHandler` passa a receber `categorizer`:**
```python
def __init__(self, ..., categorizer: ExpenseCategorizer | None = None):
    self.categorizer = categorizer or ExpenseCategorizer()
```

### `bot.py` (modificado)

**Unpacking atualizado:**
```python
reply, use_markdown, pending = _handler.handle(text, chat_id=chat_id)
parse_mode = "Markdown" if use_markdown else None
msg = await update.message.reply_text(reply, reply_markup=keyboard, parse_mode=parse_mode)
if pending:
    pending_id = f"{chat_id}:{msg.message_id}"
    _handler.register_pending(pending_id, pending)
```

**`keyboard`** para a mensagem de confirmação:
```python
InlineKeyboardMarkup([
    [
        InlineKeyboardButton("✅ Confirmar", callback_data=f"confirm:{chat_id}:{msg.message_id}"),
        InlineKeyboardButton("✏️ Alterar",   callback_data=f"change:{chat_id}:{msg.message_id}"),
    ]
])
```

**`callback_data` — formato e limite de bytes:**

Todos os `callback_data` usam índice numérico para a categoria (não o nome completo), evitando estouro do limite de 64 bytes do Telegram:

- `confirm:{chat_id}:{message_id}` — confirmar com categoria atual (máx. ~35 bytes)
- `change:{chat_id}:{message_id}` — mostrar seletor de categorias (máx. ~34 bytes)
- `cat:{chat_id}:{message_id}:{idx}` — selecionar categoria pelo índice (máx. ~37 bytes)

O índice `idx` é resolvido via `categorizer.categories_for(intent)[idx]` no handler de callback. O `intent` é recuperado do `PendingTransaction.parsed.intent`.

**`CallbackQueryHandler`:**
```python
async def _callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()  # remove spinner imediatamente
    parts = query.data.split(":")
    action = parts[0]
    chat_id = int(parts[1])
    message_id = int(parts[2])
    pending_id = f"{chat_id}:{message_id}"

    if action == "confirm":
        result = _handler.confirm_transaction(pending_id)
        if result is None:
            await query.edit_message_text("⚠️ Confirmação expirada. Envie a transação novamente.")
        else:
            await query.edit_message_text(result)

    elif action == "change":
        pending = _handler.get_pending(pending_id)
        if pending is None:
            await query.edit_message_text("⚠️ Confirmação expirada. Envie a transação novamente.")
            return
        categories = _handler.categorizer.categories_for(pending.intent)
        buttons = [
            [InlineKeyboardButton(label, callback_data=f"cat:{chat_id}:{message_id}:{i}")]
            for i, (label, _) in enumerate(categories)
        ]
        await query.edit_message_reply_markup(InlineKeyboardMarkup(buttons))

    elif action == "cat":
        idx = int(parts[3])
        result = _handler.confirm_transaction(pending_id, category_index=idx)
        if result is None:
            await query.edit_message_text("⚠️ Confirmação expirada. Envie a transação novamente.")
        else:
            await query.edit_message_text(result)
```

**Nota:** `confirm_transaction` recebe `category_index: int | None` (não o nome) e resolve internamente via `categorizer.categories_for(intent)[idx]`. Isso mantém `callback_data` dentro do limite de 64 bytes.

**`get_pending(pending_id: str) -> ParsedMessage | None`** — método público em `BotHandler`, listado junto com `register_pending` e `confirm_transaction`. Retorna `pending.parsed` se existir e não expirado, senão `None` (sem remover do dict).

## O que muda em `src/parser.py`

`SYSTEM_PROMPT` — atualizar a lista de categorias de despesa para:
```
Moradia, Transporte, Parcelamentos, Família, Alimentação, Assinaturas & Serviços, Empréstimo Itaú, Saúde, Educação - MBA, Outros
```

## O que NÃO muda

- Lógica de parsing (Claude Haiku continua sendo o categorizador primário)
- Fluxo de queries financeiras
- Comandos admin
- Estrutura do SQLite

## Critérios de Sucesso

- Toda despesa/receita lançada exibe botões de confirmação antes de salvar
- Correção de categoria salva em `category_mappings.json` e é usada nas próximas mensagens com a mesma descrição
- Pendências expiram após 10 minutos sem crash
- Duplo clique em confirmar não duplica a transação no SQLite
- Clicar em confirmação após expiração retorna mensagem amigável
- Testes cobrem: lookup, save, confirm, change, seleção de categoria, expiração e idempotência
