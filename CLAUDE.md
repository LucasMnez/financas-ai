# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

Python 3.10, virtualenv at `.venv/`. Always use `.venv/bin/python3` to run code.

```bash
source .venv/bin/activate        # activate venv
.venv/bin/pip install <pkg>      # install packages
```

Required env var: `ANTHROPIC_API_KEY` (store in `.env`, never commit it).

## Running the app

```bash
# Chat with the most recent CSV, most recent month
.venv/bin/python3 main.py

# Specify month/year
.venv/bin/python3 main.py --mes 1 --ano 2026

# Print report only, no chat
.venv/bin/python3 main.py --resumo

# Use a specific CSV
.venv/bin/python3 main.py --csv data/myfile.csv
```

## Architecture

The pipeline is strictly linear: **loader → analyzer → assistant**.

```
CSV (data/)
  └─ loader.py      load_csv() → pd.DataFrame
       └─ analyzer.py  analyze_month(df, year, month) → MonthlyReport
            └─ assistant.py  FinancialAssistant(report) → streaming chat
```

**`src/loader.py`** — Reads the Minhas Finanças CSV export (`;`-separated, UTF-8). Parses three date columns with `dayfirst=True`. Auto-detects decimal format: if values use comma as decimal separator (e.g. `1.234,56`), converts them; otherwise uses the dot format the app currently exports.

**`src/analyzer.py`** — Core domain logic. `analyze_month()` filters by `VENCIMENTO` (due date), computes totals by category, splits expenses into fixed/free/other buckets, and detects active installments via the `N/M` regex pattern in `DESCRIÇÃO`. Returns a `MonthlyReport` dataclass with computed properties (`vs_previous_total`, `installments_total`, `total_remaining_installments_value`, `category_delta()`). The previous month is computed automatically via `relativedelta`.

**`src/assistant.py`** — Serializes `MonthlyReport` into a structured system prompt and runs a stateful multi-turn conversation via the Anthropic API (`claude-sonnet-4-20250514`) with streaming. `FinancialAssistant.history` holds the full message list for multi-turn context.

**`main.py`** — CLI entry point. Finds the most recent CSV in `data/` if none specified, defaults to the latest month with data.

## Key domain knowledge

- **Fixed categories** (`FIXED_CATEGORIES` in analyzer.py): `Despesas Fixas (programadas)`, `Moradia`, `Assinaturas & Serviços`, `Empréstimo Itaú`, `Parcelamentos`
- **Free spending category**: `Gastos Livres (Controle Total)`
- **Installment detection**: regex `(\d+)\s*/\s*(\d+)\s*$` on `DESCRIÇÃO` column — matches patterns like `"Produto  3/12"`
- CSV data is filtered by **`VENCIMENTO`** (due date), not `EFETIVAÇÃO` (settlement date) or `LANÇAMENTO` (entry date)
