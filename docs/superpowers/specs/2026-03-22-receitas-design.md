# Design: Integração de Receitas ao financas-ai

**Data:** 2026-03-22
**Status:** Aprovado

## Contexto

O app atualmente processa apenas despesas (`despesas-*.csv`). O usuário exporta também um CSV de receitas (`receitas-*.csv`) com o mesmo formato (`;`-separado, UTF-8, mesmas colunas exceto `CARTÃO`). O objetivo é alimentar o agente com dados de receita para que ele possa responder perguntas sobre saldo disponível, como *"se eu gastar R$150 hoje, como fico em relação às contas de abril?"*

## Formato do CSV de Receitas

Idêntico ao de despesas, sem a coluna `CARTÃO`:

```
DESCRIÇÃO;LANÇAMENTO;VENCIMENTO;EFETIVAÇÃO;CATEGORIA;SUBCATEGORIA;CONTA;VALOR;OBSERVAÇÕES
```

Categorias observadas: `Fixa mensal` (Salário), `Pagamentos` (Pix recebidos, Vale alimentação), `Outros` (Ajustes).

## Arquitetura

Pipeline permanece linear: **loader → analyzer → assistant**. Nenhuma nova camada.

## Mudanças por Arquivo

### `src/analyzer.py`

**`MonthlyReport`** ganha 3 campos e 2 propriedades:

```python
income_total: float = 0.0
income_by_category: dict[str, float] = field(default_factory=dict)
previous_income_total: float | None = None

@property
def balance(self) -> float:
    # receitas - despesas. Nota: self.total continua sendo exclusivamente despesas.
    return round(self.income_total - self.total, 2)

@property
def vs_previous_income(self) -> float | None:
    if self.previous_income_total is None:
        return None
    return round(self.income_total - self.previous_income_total, 2)
```

**Nota de nomenclatura:** `MonthlyReport.total` mantém seu significado original (total de despesas). `balance` é o único campo líquido (receitas − despesas). Isso evita renomear `total` e quebrar todos os callsites existentes.

**`analyze_month(df, year, month, income_df=None)`** — novo parâmetro opcional. Quando fornecido, filtra o `income_df` pelo mês via `filter_by_month(income_df, year, month, date_col="VENCIMENTO")` (mesma coluna de data usada para despesas) e computa `income_by_category`, `income_total` e `previous_income_total`.

**`print_report()`** — ganha seção `RECEITAS` (por categoria, ordenadas por valor), comparação com mês anterior, e linha de saldo:

```
RECEITAS
  Fixa mensal (Salário)     R$   7.837,52
  Pagamentos                R$   1.197,82
  TOTAL RECEITAS...........  R$   9.035,34
  vs mês anterior:  +0.00  (mês ant.: R$ 9.035,34)

SALDO DO MÊS
  Receitas - Despesas......  R$   3.653,66
```

### `main.py`

- `find_latest_csv()` — **alterar glob de `*.csv` para `despesas-*.csv`** para evitar capturar o receitas CSV acidentalmente.
- `find_latest_income_csv()` — glob `receitas-*.csv` em `data/`, retorna o mais recente por mtime. Retorna `None` se não existir (receitas são opcionais).
- Argumento CLI `--receitas PATH` — permite especificar arquivo manualmente.
- `income_df = load_csv(income_path)` se encontrado, `None` caso contrário.
- Passa `income_df` para `analyze_month()`.

### `src/assistant.py`

`_format_report_as_context()` ganha seção de receitas e saldo:

```
## Receitas do mês
- Total de receitas: R$ 9.035,34
- vs mês anterior: +R$ 0,00
- Fixa mensal: R$ 7.837,52
- Pagamentos: R$ 1.197,82

## Saldo
- Saldo do mês (receitas - despesas): R$ 3.653,66
- Nota: "total" no relatório refere-se sempre a despesas; "saldo" é o valor líquido.
```

### `src/loader.py`

Nenhuma mudança — `load_csv()` já lida com o formato do CSV de receitas.

## O que NÃO muda

- Lógica de parcelamentos
- Detecção de mês padrão (baseada em despesas)
- Categorias fixas / livres
- Interface de chat

## Critérios de Sucesso

- `--resumo` exibe seção RECEITAS e SALDO quando receitas disponíveis
- O agente responde corretamente perguntas de saldo ("quanto sobra após pagar tudo?")
- Se não houver CSV de receitas, o app funciona normalmente sem erro
