# financas-ai

Assistente financeiro pessoal com IA. Lê exportações CSV do app **Minhas Finanças**, analisa despesas e receitas do mês, e disponibiliza um agente de chat via CLI ou bot do Telegram.

## Funcionalidades

- Relatório mensal com totais por categoria (fixas, livres, parcelamentos)
- Comparação automática com o mês anterior por categoria
- Detecção e rastreamento de parcelamentos ativos (N/M na descrição)
- Suporte a CSV de receitas — calcula saldo líquido do mês
- Chat interativo via CLI com contexto financeiro completo e streaming
- Bot do Telegram: lança despesas/receitas em linguagem natural, consulta saldo
- Classificação de intenção por IA (Claude Haiku) — sem comandos fixos
- Confirmação de lançamentos com teclado inline + aprendizado de categorias
- Consultas por mês específico ("como fui em março?")
- Cadastro de usuários via PIX + aprovação manual pelo admin
- Histórico multi-turno por usuário no Telegram
- Deploy via Docker em qualquer VPS

---

## Fluxo — CLI

```
Usuário
  │
  ├─ main.py (entrada CLI)
  │    ├─ Encontra CSV mais recente em data/despesas-*.csv
  │    ├─ Encontra CSV de receitas em data/receitas-*.csv (opcional)
  │    └─ Aceita flags: --csv, --mes, --ano, --resumo, --receitas
  │
  ├─ loader.py → load_csv()
  │    ├─ Lê CSV separado por ";" com encoding UTF-8
  │    ├─ Faz parse das colunas de data (LANÇAMENTO, VENCIMENTO, EFETIVAÇÃO)
  │    └─ Auto-detecta formato decimal: "1.234,56" BR ou "421.90" dot
  │
  ├─ analyzer.py → analyze_month()
  │    ├─ Filtra registros pelo campo VENCIMENTO (mês/ano)
  │    ├─ Calcula mês anterior automaticamente (relativedelta)
  │    ├─ Agrupa gastos por CATEGORIA → totais e deltas vs mês anterior
  │    ├─ Separa em 3 buckets:
  │    │    ├─ Fixos: Moradia, Assinaturas, Parcelamentos, Empréstimo Itaú, etc.
  │    │    ├─ Livres: Gastos Livres (Controle Total)
  │    │    └─ Outros: demais categorias
  │    ├─ Detecta parcelamentos via regex "N/M" na coluna DESCRIÇÃO
  │    │    └─ Calcula parcela atual, restantes e compromisso futuro total
  │    ├─ Processa CSV de receitas (se fornecido) → income_total, balance
  │    └─ Retorna MonthlyReport (dataclass)
  │
  ├─ print_report() — imprime resumo no terminal
  │    ├─ Distribuição: fixos / livres / outros / total
  │    ├─ Variação vs mês anterior
  │    ├─ Tabela por categoria com deltas
  │    ├─ Parcelamentos ativos com restantes e compromisso futuro
  │    └─ Receitas e saldo líquido (se disponível)
  │
  └─ assistant.py → run_cli()  (omitido com --resumo)
       ├─ Serializa MonthlyReport em system prompt estruturado
       ├─ Instancia FinancialAssistant (Claude Sonnet via Anthropic API)
       ├─ Loop de chat multi-turno com streaming de texto
       └─ Encerra com "sair", "exit", "quit" ou Ctrl+C
```

---

## Fluxo — Bot Telegram

### Cadastro de usuário

```
Usuário envia /start
  │
  ├─ Usuário não existe no banco?
  │    └─ Cria registro com status PENDING
  │
  ├─ Exibe chave PIX + valor + chat_id do usuário
  │
  ├─ Admin envia /ativar <chat_id>
  │    └─ store.py atualiza status → ACTIVE + registra activated_at
  │
  └─ Usuário agora pode usar o bot normalmente
```

### Lançamento de despesa ou receita

```
Usuário: "gastei 45 no mercado"
         "recebi 2000 de salário"
  │
  ├─ bot_handler.py → handle()
  │    └─ Verifica status do usuário (PENDING bloqueia, ACTIVE/ADMIN prossegue)
  │
  ├─ parser.py → parse_message()  [Claude Haiku]
  │    ├─ Classifica intent: EXPENSE | INCOME | QUERY | HELP
  │    ├─ Extrai: valor, descrição, categoria sugerida, data
  │    └─ Retorna ParsedMessage (JSON estruturado)
  │
  ├─ categorizer.py → lookup()
  │    └─ Verifica se descrição já tem categoria aprendida anteriormente
  │
  ├─ bot_handler.py → _handle_transaction()
  │    └─ Monta preview: "💸 Despesa identificada — R$ 45,00 — Alimentação"
  │
  ├─ bot.py exibe teclado inline:
  │    [✅ Confirmar]  [✏️ Alterar]
  │    └─ Pendência registrada com TTL de 10 minutos
  │
  ├─ Usuário clica ✅ Confirmar
  │    ├─ confirm_transaction() salva no SQLite (transactions)
  │    └─ Exibe confirmação: "💸 Despesa lançada! Valor / Categoria / Data"
  │
  └─ Usuário clica ✏️ Alterar
       ├─ Exibe teclado de categorias disponíveis (10 despesa / 3 receita)
       ├─ Usuário seleciona categoria correta
       ├─ categorizer.py → save() aprende o mapeamento descrição→categoria
       └─ confirm_transaction() salva com categoria corrigida
```

### Consulta financeira

```
Usuário: "como estou esse mês?"
         "qual meu saldo?"
         "quanto gastei em março?"
  │
  ├─ parser.py classifica intent → QUERY
  │    └─ Extrai query_month / query_year se mês específico mencionado
  │
  ├─ bot_handler.py → _handle_query()
  │    ├─ Carrega CSV de despesas e receitas mais recentes (data/)
  │    ├─ Carrega transações lançadas pelo bot (SQLite) do mês consultado
  │    ├─ Mescla CSV + banco → DataFrame unificado
  │    └─ analyze_month() → MonthlyReport completo
  │
  ├─ FinancialAssistant (Claude Sonnet) com histórico do usuário
  │    ├─ System prompt contém resumo financeiro completo do período
  │    ├─ Histórico multi-turno mantido por chat_id (em memória)
  │    └─ Resposta formatada para Telegram (*negrito*, listas com •)
  │
  └─ Resposta enviada ao usuário com parse_mode=Markdown
```

### Comandos admin

```
Admin (ADMIN_CHAT_ID):
  /ativar <chat_id>    → ativa usuário após pagamento PIX
  /desativar <chat_id> → revoga acesso (volta para PENDING)
  /pendentes           → lista usuários aguardando ativação
```

---

## Estrutura de arquivos

```
main.py              CLI: relatório + chat
bot.py               Bot do Telegram (polling + inline keyboards)
src/
  loader.py          Leitura e normalização do CSV (Minhas Finanças)
  analyzer.py        Análise mensal → MonthlyReport (dataclass)
  assistant.py       Chat com Claude Sonnet (CLI e bot)
  parser.py          Classificação de intenção com Claude Haiku
  store.py           SQLite: tabelas transactions + users
  bot_handler.py     Lógica do bot: roteamento, pendências, admin
  categorizer.py     Mapeamento aprendido de descrição → categoria
data/                CSVs e banco SQLite (não versionados)
  despesas-*.csv
  receitas-*.csv
  transactions.db
  category_mappings.json
```

---

## Uso — CLI

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Coloque o CSV exportado em data/
python main.py                              # mês mais recente do CSV
python main.py --mes 4 --ano 2026          # mês específico
python main.py --resumo                    # só relatório, sem chat
python main.py --receitas data/receitas-abril.csv
python main.py --csv data/meuarquivo.csv   # CSV específico
```

## Uso — Bot Telegram

**Pré-requisitos:**
- Criar bot via [@BotFather](https://t.me/BotFather) → obter `TELEGRAM_BOT_TOKEN`
- Obter seu `ADMIN_CHAT_ID` via [@userinfobot](https://t.me/userinfobot)

```bash
cp .env.example .env
# Preencher .env com as variáveis abaixo
python bot.py
```

### Comandos disponíveis

| Comando | Quem pode usar | Descrição |
|---------|---------------|-----------|
| `/start` | Qualquer um | Cadastro + instruções de pagamento PIX |
| `/ajuda` | Usuário ativo | Lista de comandos e exemplos |
| `/ativar <chat_id>` | Admin | Ativa usuário após pagamento |
| `/desativar <chat_id>` | Admin | Revoga acesso do usuário |
| `/pendentes` | Admin | Lista usuários aguardando ativação |

Mensagens livres (texto sem comando) são interpretadas automaticamente pela IA:

```
gastei 45 no mercado          → lança despesa
recebi 200 pix da raissa      → lança receita
paguei 150 de luz             → lança despesa
como estou esse mês?          → consulta via IA
quanto sobra?                 → consulta saldo
como foi março?               → consulta mês específico
```

---

## Variáveis de Ambiente

Copie `.env.example` para `.env`:

```
ANTHROPIC_API_KEY=   # console.anthropic.com
TELEGRAM_BOT_TOKEN=  # @BotFather
ADMIN_CHAT_ID=       # seu chat_id no Telegram
PIX_KEY=             # chave PIX exibida no cadastro
PIX_AMOUNT=          # valor mensal da assinatura
```

---

## Deploy com Docker

```bash
git clone https://github.com/LucasMnez/financas-ai.git
cd financas-ai
cp .env.example .env && nano .env
docker compose up -d
docker compose logs -f
```

---

## Formato do CSV

Exportação do app **Minhas Finanças** (Android/iOS). Separado por `;`, UTF-8.

```
DESCRIÇÃO;LANÇAMENTO;VENCIMENTO;EFETIVAÇÃO;CATEGORIA;SUBCATEGORIA;CONTA;CARTÃO;VALOR;OBSERVAÇÕES
```

O CSV de receitas usa o mesmo formato sem a coluna `CARTÃO`.

Nomeie os arquivos como `despesas-*.csv` e `receitas-*.csv` dentro de `data/`.

O sistema auto-detecta o formato do campo `VALOR`:
- Formato BR com separador de milhar: `1.234,56`
- Formato dot decimal (exportação atual do app): `421.90`

---

## Domínio — Categorias

**Despesas fixas** (somadas no bucket "Fixos"):
- `Despesas Fixas (programadas)`, `Moradia`, `Assinaturas & Serviços`, `Empréstimo Itaú`, `Parcelamentos`

**Gastos livres:** `Gastos Livres (Controle Total)`

**Parcelamentos** são detectados automaticamente pelo padrão `N/M` no campo `DESCRIÇÃO` (ex: `Produto 3/12`), independente da categoria.

**Categorias disponíveis no bot (despesas):** Moradia, Transporte, Parcelamentos, Família, Alimentação, Assinaturas & Serviços, Empréstimo Itaú, Saúde, Educação - MBA, Outros

**Categorias disponíveis no bot (receitas):** Fixa mensal, Pagamentos, Outros

---

## Testes

```bash
pytest tests/ -v
```
