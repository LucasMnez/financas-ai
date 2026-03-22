import os
import anthropic

from src.analyzer import MonthlyReport

MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 4096


def _format_report_as_context(report: MonthlyReport) -> str:
    lines = [
        f"=== RESUMO FINANCEIRO — {report.period_label} ===",
        "",
        "## Distribuição geral",
        f"- Total do mês: R$ {report.total:.2f}",
        f"- Despesas fixas (moradia, assinaturas, parcelamentos, empréstimo): R$ {report.fixed_total:.2f}",
        f"- Gastos livres (controle total): R$ {report.free_total:.2f}",
        f"- Demais (variáveis, família, transporte, alimentação, etc.): R$ {report.other_total:.2f}",
    ]

    if report.vs_previous_total is not None:
        sign = "+" if report.vs_previous_total >= 0 else ""
        pct = f" ({sign}{report.vs_previous_total / report.previous_month_total * 100:.1f}%)" if report.previous_month_total else ""
        lines += [
            "",
            "## Comparação com mês anterior",
            f"- Mês anterior: R$ {report.previous_month_total:.2f}",
            f"- Variação: {sign}R$ {report.vs_previous_total:.2f}{pct}",
        ]

    lines += ["", "## Gastos por categoria"]
    for cat, val in sorted(report.by_category.items(), key=lambda x: x[1], reverse=True):
        delta = report.category_delta(cat)
        delta_str = f"  (vs mês ant.: {delta:+.2f})" if delta is not None else ""
        lines.append(f"- {cat}: R$ {val:.2f}{delta_str}")

    if report.installments:
        active = [i for i in report.installments if i.remaining_installments > 0]
        lines += [
            "",
            f"## Parcelamentos ativos ({len(active)} itens)",
            f"- Total pago este mês em parcelas: R$ {report.installments_total:.2f}",
            f"- Compromisso futuro total: R$ {report.total_remaining_installments_value:.2f}",
            "",
        ]
        for inst in sorted(active, key=lambda x: x.remaining_value, reverse=True):
            lines.append(
                f"- {inst.description}: parcela {inst.current}/{inst.total}"
                f" — R$ {inst.monthly_value:.2f}/mês"
                f" — restam {inst.remaining_installments}x (R$ {inst.remaining_value:.2f})"
            )

    if report.income_total > 0:
        lines += ["", "## Receitas do mês",
                  f"- Total de receitas: R$ {report.income_total:.2f}"]
        if report.vs_previous_income is not None:
            sign = "+" if report.vs_previous_income >= 0 else ""
            lines.append(f"- vs mês anterior: {sign}R$ {report.vs_previous_income:.2f}")
        for cat, val in sorted(report.income_by_category.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"- {cat}: R$ {val:.2f}")
        lines += ["", "## Saldo",
                  f"- Saldo do mês (receitas - despesas): R$ {report.balance:.2f}",
                  "- Nota: 'total' refere-se a despesas; 'saldo' é o valor líquido."]

    return "\n".join(lines)


def _build_system_prompt(report: MonthlyReport) -> str:
    context = _format_report_as_context(report)
    return f"""Você é um assistente financeiro pessoal inteligente e direto.
Você tem acesso ao resumo financeiro detalhado do usuário referente ao período {report.period_label}.

Use esses dados como base para responder perguntas, identificar padrões, alertar sobre gastos excessivos
e sugerir melhorias. Seja objetivo e use os números reais disponíveis.
Quando o usuário perguntar algo que não esteja nos dados, diga claramente que não tem essa informação.

{context}
"""


class FinancialAssistant:
    def __init__(self, report: MonthlyReport, api_key: str | None = None):
        self.report = report
        self.client = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self.system = _build_system_prompt(report)
        self.history: list[dict] = []

    def chat(self, user_message: str) -> str:
        self.history.append({"role": "user", "content": user_message})

        full_response = ""
        with self.client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=self.system,
            messages=self.history,
        ) as stream:
            for text in stream.text_stream:
                print(text, end="", flush=True)
                full_response += text

        print()  # newline after streamed response
        self.history.append({"role": "assistant", "content": full_response})
        return full_response

    def reset(self) -> None:
        self.history.clear()


def run_cli(report: MonthlyReport, api_key: str | None = None) -> None:
    assistant = FinancialAssistant(report, api_key=api_key)

    print(f"\nAssistente financeiro pronto — período {report.period_label}")
    print("Digite sua pergunta ou 'sair' para encerrar.\n")

    while True:
        try:
            user_input = input("Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nEncerrando.")
            break

        if not user_input:
            continue
        if user_input.lower() in {"sair", "exit", "quit"}:
            print("Até logo!")
            break

        print("Assistente: ", end="", flush=True)
        assistant.chat(user_input)
        print()
