# financas-ai

Assistente financeiro pessoal com IA. Lê exportações CSV do app **Minhas Finanças**, analisa despesas e receitas do mês, e disponibiliza um agente de chat via CLI ou bot do Telegram.

## Funcionalidades

- Relatório mensal com totais por categoria (fixas, livres, parcelamentos)
- Suporte a CSV de receitas — calcula saldo líquido do mês
- Chat interativo via CLI com contexto financeiro completo
- Bot do Telegram: lança despesas/receitas em linguagem natural, consulta saldo
- Cadastro de usuários via PIX + aprovação manual pelo admin
- Deploy via Docker em qualquer VPS

## Estrutura

```
main.py          # CLI: relatório + chat
bot.py           # Bot do Telegram (polling)
src/
  loader.py      # Leitura do CSV (Minhas Finanças)
  analyzer.py    # Análise mensal → MonthlyReport
  assistant.py   # Chat com Claude (CLI)
  parser.py      # Classifica mensagens com Claude Haiku
  store.py       # SQLite: transações e usuários
  bot_handler.py # Lógica do bot (estados, comandos admin)
data/            # CSVs e banco SQLite (não versionado)
```

## Uso — CLI

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Coloque o CSV exportado em data/
python main.py                        # mês mais recente
python main.py --mes 4 --ano 2026     # mês específico
python main.py --resumo               # só relatório, sem chat
python main.py --receitas data/receitas-*.csv
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

| Comando | Descrição |
|---------|-----------|
| `/start` | Cadastro + instruções de pagamento PIX |
| `/ajuda` | Lista de comandos |
| `/ativar <chat_id>` | Admin: ativa usuário após pagamento |
| `/desativar <chat_id>` | Admin: desativa usuário |
| `/pendentes` | Admin: lista usuários aguardando ativação |

Mensagens de texto livres são interpretadas como lançamentos ou perguntas:
> "gastei 45 no mercado"
> "quanto sobra esse mês?"

## Variáveis de Ambiente

Copie `.env.example` para `.env`:

```
ANTHROPIC_API_KEY=   # console.anthropic.com
TELEGRAM_BOT_TOKEN=  # @BotFather
ADMIN_CHAT_ID=       # seu chat_id no Telegram
PIX_KEY=             # chave PIX exibida no cadastro
PIX_AMOUNT=          # valor mensal da assinatura
```

## Deploy com Docker

```bash
git clone https://github.com/LucasMnez/financas-ai.git
cd financas-ai
cp .env.example .env && nano .env
docker compose up -d
docker compose logs -f
```

## Formato do CSV

Exportação do app **Minhas Finanças** (Android/iOS). Separado por `;`, UTF-8.

```
DESCRIÇÃO;LANÇAMENTO;VENCIMENTO;EFETIVAÇÃO;CATEGORIA;SUBCATEGORIA;CONTA;CARTÃO;VALOR;OBSERVAÇÕES
```

O CSV de receitas usa o mesmo formato sem a coluna `CARTÃO`.

Nomeie os arquivos como `despesas-*.csv` e `receitas-*.csv` dentro de `data/`.

## Testes

```bash
pytest tests/ -v
```
