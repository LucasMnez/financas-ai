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

## Arquitetura

### `src/categorizer.py` (novo)

Responsabilidade única: consultar e persistir mapeamentos de descrição → categoria.

```python
class ExpenseCategorizer:
    def __init__(self, mappings_path: Path = DATA_DIR / "category_mappings.json")
    def lookup(self, description: str) -> str | None
        # normaliza (lower, strip), consulta mappings. Retorna None se não encontrado.
    def save(self, description: str, category: str) -> None
        # normaliza e salva/atualiza no JSON
```

Normalização: `description.lower().strip()`. Sem remoção de acentos (desnecessário para lookup exato).

O arquivo JSON:
```json
{
  "mercado": "Alimentação",
  "uber": "Transporte"
}
```

### `src/bot_handler.py` (modificado)

**Estado pendente** — dict em memória:
```python
self._pending: dict[str, ParsedMessage] = {}
# chave: f"{chat_id}:{message_id}" gerado após envio da mensagem de confirmação
```

**`_handle_transaction(parsed, chat_id)`** — em vez de salvar imediatamente:
1. Consulta `categorizer.lookup(parsed.description)` → sobrescreve categoria se encontrado
2. Retorna mensagem de confirmação + `pending_id` para ser associado ao `message_id`

Como `handle()` precisa retornar o texto antes de saber o `message_id`, o fluxo muda:
- `handle()` retorna `(text, parse_mode, pending_parsed)` onde `pending_parsed` é o `ParsedMessage` a aguardar confirmação (ou `None` se não for transação)
- `bot.py` envia a mensagem, obtém o `message_id`, registra `_pending[f"{chat_id}:{message_id}"] = pending_parsed`

**`confirm_transaction(pending_id, category_override=None)`** — salva no SQLite com categoria final.

**`get_categories(intent)`** — retorna lista de `(label, category_str)` para o teclado inline.

### `bot.py` (modificado)

Adiciona `CallbackQueryHandler` para processar cliques:

Formato do `callback_data`:
- `confirm:{chat_id}:{message_id}` — confirmar com categoria atual
- `change:{chat_id}:{message_id}` — mostrar seletor de categorias
- `cat:{chat_id}:{message_id}:{category}` — categoria selecionada

O handler:
1. Faz parse do `callback_data`
2. Busca `_pending[f"{chat_id}:{message_id}"]`
3. Se `confirm` → `bot_handler.confirm_transaction(pending_id)`
4. Se `change` → edita mensagem com teclado de categorias
5. Se `cat` → `bot_handler.confirm_transaction(pending_id, category_override=category)` + `categorizer.save(description, category)`
6. Responde com `answer_callback_query()` para remover o spinner

### `data/category_mappings.json` (novo, criado automaticamente)

Inicializado como `{}` se não existir.

## Categorias

**Despesas:**
| Label | Categoria |
|-------|-----------|
| 🏠 Moradia | Moradia |
| 🚌 Transporte | Transporte |
| 💳 Parcelamentos | Parcelamentos |
| 👨‍👩‍👧‍👦 Família | Família |
| 🍽️ Alimentação | Alimentação |
| 📝 Assinaturas & Serviços | Assinaturas & Serviços |
| 🏦 Empréstimo Itaú | Empréstimo Itaú |
| ❤️ Saúde | Saúde |
| 🎓 Educação - MBA | Educação - MBA |
| ❓ Outros | Outros |

**Receitas:**
| Label | Categoria |
|-------|-----------|
| 💰 Fixa mensal | Fixa mensal |
| 📲 Pagamentos | Pagamentos |
| ❓ Outros | Outros |

## Mudanças na Interface de `handle()`

`handle()` passa de `tuple[str, bool]` para `tuple[str, bool, ParsedMessage | None]`.

Terceiro elemento é `None` para tudo exceto transações pendentes de confirmação.

`bot.py` atualiza o unpacking:
```python
reply, use_markdown, pending = _handler.handle(text, chat_id=chat_id)
msg = await update.message.reply_text(reply, reply_markup=keyboard, parse_mode=...)
if pending:
    _handler.register_pending(f"{chat_id}:{msg.message_id}", pending)
```

## O que NÃO muda

- Lógica de parsing (Claude Haiku continua sendo o categorizador primário)
- Fluxo de queries financeiras
- Comandos admin
- Estrutura do SQLite

## Critérios de Sucesso

- Toda despesa/receita lançada exibe botões de confirmação antes de salvar
- Correção de categoria salva em `category_mappings.json` e é usada nas próximas mensagens com a mesma descrição
- Se bot reiniciar durante confirmação pendente, transação é simplesmente perdida (sem crash)
- Testes cobrem: lookup, save, confirm, change e seleção de categoria
