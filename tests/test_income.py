"""Tests for income (receitas) support added to analyzer and assistant."""
import io
from contextlib import redirect_stdout

import pandas as pd
import pytest

from src.analyzer import MonthlyReport, analyze_month
from src.assistant import _format_report_as_context


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_expenses_df() -> pd.DataFrame:
    """Minimal expenses DataFrame for March 2026."""
    return pd.DataFrame({
        "VENCIMENTO": pd.to_datetime(["2026-03-10", "2026-03-15", "2026-02-10"]),
        "CATEGORIA": ["Moradia", "Gastos Livres (Controle Total)", "Moradia"],
        "DESCRIÇÃO": ["Aluguel", "Lazer", "Aluguel"],
        "VALOR": [1500.0, 300.0, 1500.0],
    })


def _make_income_df() -> pd.DataFrame:
    """Income DataFrame with entries in Feb and March 2026."""
    return pd.DataFrame({
        "VENCIMENTO": pd.to_datetime(["2026-03-05", "2026-03-05", "2026-02-05"]),
        "CATEGORIA": ["Salário", "Freelance", "Salário"],
        "DESCRIÇÃO": ["Salário mensal", "Projeto X", "Salário mensal"],
        "VALOR": [5000.0, 800.0, 4800.0],
    })


# ---------------------------------------------------------------------------
# MonthlyReport dataclass fields
# ---------------------------------------------------------------------------

class TestMonthlyReportFields:
    def test_default_income_total_is_zero(self):
        report = MonthlyReport(
            year=2026, month=3, total=1800.0,
            by_category={"Moradia": 1500.0},
            installments=[], fixed_total=1500.0, free_total=300.0, other_total=0.0,
        )
        assert report.income_total == 0.0

    def test_default_income_by_category_is_empty_dict(self):
        report = MonthlyReport(
            year=2026, month=3, total=1800.0,
            by_category={}, installments=[],
            fixed_total=0.0, free_total=0.0, other_total=0.0,
        )
        assert report.income_by_category == {}

    def test_default_previous_income_total_is_none(self):
        report = MonthlyReport(
            year=2026, month=3, total=1800.0,
            by_category={}, installments=[],
            fixed_total=0.0, free_total=0.0, other_total=0.0,
        )
        assert report.previous_income_total is None

    def test_balance_property(self):
        report = MonthlyReport(
            year=2026, month=3, total=1800.0,
            by_category={}, installments=[],
            fixed_total=0.0, free_total=0.0, other_total=0.0,
            income_total=5800.0,
        )
        assert report.balance == pytest.approx(4000.0)

    def test_balance_when_no_income(self):
        report = MonthlyReport(
            year=2026, month=3, total=1800.0,
            by_category={}, installments=[],
            fixed_total=0.0, free_total=0.0, other_total=0.0,
        )
        assert report.balance == pytest.approx(-1800.0)

    def test_vs_previous_income_none_when_no_previous(self):
        report = MonthlyReport(
            year=2026, month=3, total=0.0,
            by_category={}, installments=[],
            fixed_total=0.0, free_total=0.0, other_total=0.0,
            income_total=5000.0, previous_income_total=None,
        )
        assert report.vs_previous_income is None

    def test_vs_previous_income_positive(self):
        report = MonthlyReport(
            year=2026, month=3, total=0.0,
            by_category={}, installments=[],
            fixed_total=0.0, free_total=0.0, other_total=0.0,
            income_total=5800.0, previous_income_total=4800.0,
        )
        assert report.vs_previous_income == pytest.approx(1000.0)

    def test_vs_previous_income_negative(self):
        report = MonthlyReport(
            year=2026, month=3, total=0.0,
            by_category={}, installments=[],
            fixed_total=0.0, free_total=0.0, other_total=0.0,
            income_total=4000.0, previous_income_total=5000.0,
        )
        assert report.vs_previous_income == pytest.approx(-1000.0)


# ---------------------------------------------------------------------------
# analyze_month() with income_df
# ---------------------------------------------------------------------------

class TestAnalyzeMonthIncome:
    def test_no_income_df_keeps_defaults(self):
        df = _make_expenses_df()
        report = analyze_month(df, 2026, 3)
        assert report.income_total == 0.0
        assert report.income_by_category == {}
        assert report.previous_income_total is None

    def test_income_df_none_explicitly(self):
        df = _make_expenses_df()
        report = analyze_month(df, 2026, 3, income_df=None)
        assert report.income_total == 0.0

    def test_income_total_computed(self):
        df = _make_expenses_df()
        income_df = _make_income_df()
        report = analyze_month(df, 2026, 3, income_df=income_df)
        # March income: 5000 + 800 = 5800
        assert report.income_total == pytest.approx(5800.0)

    def test_income_by_category(self):
        df = _make_expenses_df()
        income_df = _make_income_df()
        report = analyze_month(df, 2026, 3, income_df=income_df)
        assert report.income_by_category == {"Salário": 5000.0, "Freelance": 800.0}

    def test_previous_income_total(self):
        df = _make_expenses_df()
        income_df = _make_income_df()
        report = analyze_month(df, 2026, 3, income_df=income_df)
        # Feb income: 4800
        assert report.previous_income_total == pytest.approx(4800.0)

    def test_previous_income_none_when_no_prior_data(self):
        df = _make_expenses_df()
        # Income only in March, nothing in February
        income_df = pd.DataFrame({
            "VENCIMENTO": pd.to_datetime(["2026-03-05"]),
            "CATEGORIA": ["Salário"],
            "DESCRIÇÃO": ["Salário mensal"],
            "VALOR": [5000.0],
        })
        report = analyze_month(df, 2026, 3, income_df=income_df)
        assert report.previous_income_total is None

    def test_balance_computed_correctly(self):
        df = _make_expenses_df()
        income_df = _make_income_df()
        report = analyze_month(df, 2026, 3, income_df=income_df)
        # expenses = 1500 + 300 = 1800; income = 5800; balance = 4000
        assert report.balance == pytest.approx(4000.0)

    def test_existing_behavior_unchanged(self):
        """Expenses total and categories should not change when income_df provided."""
        df = _make_expenses_df()
        income_df = _make_income_df()
        report_no_income = analyze_month(df, 2026, 3)
        report_with_income = analyze_month(df, 2026, 3, income_df=income_df)
        assert report_no_income.total == report_with_income.total
        assert report_no_income.by_category == report_with_income.by_category

    def test_empty_income_df(self):
        df = _make_expenses_df()
        income_df = pd.DataFrame(columns=["VENCIMENTO", "CATEGORIA", "DESCRIÇÃO", "VALOR"])
        income_df["VENCIMENTO"] = pd.to_datetime(income_df["VENCIMENTO"])
        report = analyze_month(df, 2026, 3, income_df=income_df)
        assert report.income_total == 0.0
        assert report.income_by_category == {}


# ---------------------------------------------------------------------------
# print_report() output
# ---------------------------------------------------------------------------

class TestPrintReportIncome:
    def _capture(self, report) -> str:
        from src.analyzer import print_report
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_report(report)
        return buf.getvalue()

    def test_no_income_section_when_zero(self):
        report = MonthlyReport(
            year=2026, month=3, total=1800.0,
            by_category={"Moradia": 1800.0}, installments=[],
            fixed_total=1800.0, free_total=0.0, other_total=0.0,
        )
        output = self._capture(report)
        assert "RECEITAS" not in output
        assert "SALDO" not in output

    def test_income_section_present(self):
        report = MonthlyReport(
            year=2026, month=3, total=1800.0,
            by_category={"Moradia": 1800.0}, installments=[],
            fixed_total=1800.0, free_total=0.0, other_total=0.0,
            income_total=5800.0,
            income_by_category={"Salário": 5000.0, "Freelance": 800.0},
        )
        output = self._capture(report)
        assert "RECEITAS" in output
        assert "SALDO DO MÊS" in output
        assert "5800.00" in output
        assert "4000.00" in output  # balance

    def test_income_vs_previous_shown(self):
        report = MonthlyReport(
            year=2026, month=3, total=1800.0,
            by_category={}, installments=[],
            fixed_total=0.0, free_total=0.0, other_total=0.0,
            income_total=5800.0,
            income_by_category={"Salário": 5800.0},
            previous_income_total=4800.0,
        )
        output = self._capture(report)
        assert "vs mês anterior" in output
        assert "+1000.00" in output


# ---------------------------------------------------------------------------
# _format_report_as_context() — AI context
# ---------------------------------------------------------------------------

class TestFormatReportAsContext:
    def _make_report(self, **kwargs) -> MonthlyReport:
        defaults = dict(
            year=2026, month=3, total=1800.0,
            by_category={"Moradia": 1800.0}, installments=[],
            fixed_total=1800.0, free_total=0.0, other_total=0.0,
        )
        defaults.update(kwargs)
        return MonthlyReport(**defaults)

    def test_no_income_section_when_zero(self):
        report = self._make_report()
        ctx = _format_report_as_context(report)
        assert "Receitas" not in ctx
        assert "Saldo" not in ctx

    def test_income_section_present(self):
        report = self._make_report(
            income_total=5800.0,
            income_by_category={"Salário": 5000.0, "Freelance": 800.0},
        )
        ctx = _format_report_as_context(report)
        assert "Receitas do mês" in ctx
        assert "5800.00" in ctx
        assert "Saldo" in ctx
        assert "4000.00" in ctx

    def test_income_vs_previous_in_context(self):
        report = self._make_report(
            income_total=5800.0,
            income_by_category={"Salário": 5800.0},
            previous_income_total=4800.0,
        )
        ctx = _format_report_as_context(report)
        assert "vs mês anterior" in ctx
        assert "+R$ 1000.00" in ctx

    def test_note_about_total_vs_balance(self):
        report = self._make_report(income_total=5800.0, income_by_category={})
        ctx = _format_report_as_context(report)
        assert "despesas" in ctx.lower() or "saldo" in ctx.lower()
