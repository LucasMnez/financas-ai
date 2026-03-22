import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from src.loader import load_csv
from src.analyzer import analyze_month, print_report
from src.assistant import run_cli

DATA_DIR = Path(__file__).parent / "data"


def find_latest_csv() -> Path:
    csvs = sorted(DATA_DIR.glob("despesas-*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not csvs:
        print("Nenhum CSV encontrado em data/", file=sys.stderr)
        sys.exit(1)
    return csvs[0]


def find_latest_income_csv() -> Path | None:
    csvs = sorted(DATA_DIR.glob("receitas-*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    return csvs[0] if csvs else None


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Assistente financeiro pessoal")
    parser.add_argument("--csv", type=Path, help="Caminho para o CSV (padrão: mais recente em data/)")
    parser.add_argument("--ano", type=int, default=None, help="Ano do relatório (padrão: ano do CSV mais recente)")
    parser.add_argument("--mes", type=int, default=None, help="Mês do relatório (padrão: mês mais recente com dados)")
    parser.add_argument("--resumo", action="store_true", help="Exibe apenas o resumo, sem iniciar o chat")
    parser.add_argument("--receitas", type=Path, default=None)
    args = parser.parse_args()

    csv_path = args.csv or find_latest_csv()
    print(f"Carregando {csv_path.name}...")
    df = load_csv(csv_path)

    # Default to the most recent month with data
    if args.ano and args.mes:
        year, month = args.ano, args.mes
    else:
        latest = df["VENCIMENTO"].dropna().max()
        year, month = latest.year, latest.month

    income_path = args.receitas or find_latest_income_csv()
    income_df = load_csv(income_path) if income_path else None
    report = analyze_month(df, year, month, income_df=income_df)
    print_report(report)

    if not args.resumo:
        run_cli(report)


if __name__ == "__main__":
    main()
