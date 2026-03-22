import re
from dataclasses import dataclass, field
from dateutil.relativedelta import relativedelta

import pandas as pd

from src.loader import filter_by_month

# Categories considered "fixed" expenses
FIXED_CATEGORIES = {
    "Despesas Fixas (programadas)",
    "Moradia",
    "Assinaturas & Serviços",
    "Empréstimo Itaú",
    "Parcelamentos",
}

# Category explicitly flagged as "free spending" in the app
FREE_CATEGORY = "Gastos Livres (Controle Total)"

_INSTALLMENT_RE = re.compile(r"(\d+)\s*/\s*(\d+)\s*$")


@dataclass
class Installment:
    description: str
    current: int
    total: int
    monthly_value: float

    @property
    def remaining_installments(self) -> int:
        return self.total - self.current

    @property
    def remaining_value(self) -> float:
        return self.remaining_installments * self.monthly_value


@dataclass
class MonthlyReport:
    year: int
    month: int
    total: float
    by_category: dict[str, float]
    installments: list[Installment]
    fixed_total: float
    free_total: float
    other_total: float
    previous_month_total: float | None = None
    previous_by_category: dict[str, float] = field(default_factory=dict)
    income_total: float = 0.0
    income_by_category: dict[str, float] = field(default_factory=dict)
    previous_income_total: float | None = None

    @property
    def balance(self) -> float:
        return round(self.income_total - self.total, 2)

    @property
    def vs_previous_income(self) -> float | None:
        if self.previous_income_total is None:
            return None
        return round(self.income_total - self.previous_income_total, 2)

    @property
    def period_label(self) -> str:
        return f"{self.year}-{self.month:02d}"

    @property
    def vs_previous_total(self) -> float | None:
        if self.previous_month_total is None:
            return None
        return self.total - self.previous_month_total

    @property
    def installments_total(self) -> float:
        return sum(i.monthly_value for i in self.installments)

    @property
    def total_remaining_installments_value(self) -> float:
        return sum(i.remaining_value for i in self.installments)

    def category_delta(self, category: str) -> float | None:
        if not self.previous_by_category:
            return None
        prev = self.previous_by_category.get(category, 0.0)
        curr = self.by_category.get(category, 0.0)
        return curr - prev


def _parse_installments(df: pd.DataFrame) -> list[Installment]:
    result = []
    for _, row in df.iterrows():
        desc = str(row.get("DESCRIÇÃO", ""))
        m = _INSTALLMENT_RE.search(desc)
        if m:
            current, total = int(m.group(1)), int(m.group(2))
            result.append(
                Installment(
                    description=desc.strip(),
                    current=current,
                    total=total,
                    monthly_value=float(row["VALOR"]),
                )
            )
    return result


def analyze_month(df: pd.DataFrame, year: int, month: int, income_df: pd.DataFrame | None = None) -> MonthlyReport:
    current = filter_by_month(df, year, month)

    # Previous month
    prev_date = pd.Timestamp(year=year, month=month, day=1) - relativedelta(months=1)
    previous = filter_by_month(df, prev_date.year, prev_date.month)

    by_category = (
        current.groupby("CATEGORIA")["VALOR"].sum().round(2).to_dict()
    )
    prev_by_category = (
        previous.groupby("CATEGORIA")["VALOR"].sum().round(2).to_dict()
        if not previous.empty
        else {}
    )

    fixed_total = sum(
        v for k, v in by_category.items() if k in FIXED_CATEGORIES
    )
    free_total = by_category.get(FREE_CATEGORY, 0.0)
    other_total = sum(
        v
        for k, v in by_category.items()
        if k not in FIXED_CATEGORIES and k != FREE_CATEGORY
    )

    installments = _parse_installments(current)

    income_total = 0.0
    income_by_category: dict[str, float] = {}
    previous_income_total: float | None = None

    if income_df is not None and not income_df.empty:
        curr_income = filter_by_month(income_df, year, month)
        prev_income = filter_by_month(income_df, prev_date.year, prev_date.month)
        income_by_category = (
            curr_income.groupby("CATEGORIA")["VALOR"].sum().round(2).to_dict()
            if not curr_income.empty else {}
        )
        income_total = round(curr_income["VALOR"].sum(), 2) if not curr_income.empty else 0.0
        previous_income_total = (
            round(prev_income["VALOR"].sum(), 2) if not prev_income.empty else None
        )

    return MonthlyReport(
        year=year,
        month=month,
        total=round(current["VALOR"].sum(), 2),
        by_category=by_category,
        installments=installments,
        fixed_total=round(fixed_total, 2),
        free_total=round(free_total, 2),
        other_total=round(other_total, 2),
        previous_month_total=(
            round(previous["VALOR"].sum(), 2) if not previous.empty else None
        ),
        previous_by_category=prev_by_category,
        income_total=income_total,
        income_by_category=income_by_category,
        previous_income_total=previous_income_total,
    )


def print_report(report: MonthlyReport) -> None:
    w = 52
    sep = "─" * w

    print(f"\n{'RESUMO FINANCEIRO':^{w}}")
    print(f"{'Período: ' + report.period_label:^{w}}")
    print(sep)

    # Fixed vs Free vs Other
    print(f"\n{'DISTRIBUIÇÃO':}")
    print(f"  Fixos (moradia, assinat., parcel.)  R$ {report.fixed_total:>10.2f}")
    print(f"  Gastos Livres                        R$ {report.free_total:>10.2f}")
    print(f"  Demais (variáveis, família, transp.) R$ {report.other_total:>10.2f}")
    print(f"  {'TOTAL':.<38} R$ {report.total:>10.2f}")

    # vs previous month
    if report.vs_previous_total is not None:
        print(f"\n  vs mês anterior:  {report.vs_previous_total:+.2f}"
              f"  (mês ant.: R$ {report.previous_month_total:.2f})")

    # By category
    print(f"\n{'POR CATEGORIA':}")
    sorted_cats = sorted(report.by_category.items(), key=lambda x: x[1], reverse=True)
    for cat, val in sorted_cats:
        delta = report.category_delta(cat)
        delta_str = ""
        if delta is not None:
            delta_str = f"  ({delta:+.2f})"
        print(f"  {cat:<38} R$ {val:>8.2f}{delta_str}")

    # Active installments
    if report.installments:
        print(f"\n{'PARCELAMENTOS ATIVOS ({} itens)'.format(len(report.installments)):}")
        for inst in sorted(report.installments, key=lambda x: x.remaining_value, reverse=True):
            print(
                f"  {inst.description[:36]:<36}"
                f"  {inst.current}/{inst.total}"
                f"  R$ {inst.monthly_value:>7.2f}/mês"
                f"  (restam {inst.remaining_installments}x = R$ {inst.remaining_value:.2f})"
            )
        print(f"  {'Total parcelamentos mês':.<38} R$ {report.installments_total:>8.2f}")
        print(f"  {'Total compromisso futuro':.<38} R$ {report.total_remaining_installments_value:>8.2f}")

    if report.income_total > 0:
        print(f"\n{'RECEITAS':}")
        for cat, val in sorted(report.income_by_category.items(), key=lambda x: x[1], reverse=True):
            print(f"  {cat:<38} R$ {val:>8.2f}")
        print(f"  {'TOTAL RECEITAS':.<38} R$ {report.income_total:>8.2f}")
        if report.vs_previous_income is not None:
            print(f"\n  vs mês anterior:  {report.vs_previous_income:+.2f}"
                  f"  (mês ant.: R$ {report.previous_income_total:.2f})")
        print(f"\n{'SALDO DO MÊS':}")
        print(f"  {'Receitas - Despesas':.<38} R$ {report.balance:>8.2f}")

    print(f"\n{sep}\n")
