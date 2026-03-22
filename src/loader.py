import pandas as pd
from pathlib import Path


def load_csv(filepath: str | Path) -> pd.DataFrame:
    df = pd.read_csv(
        filepath,
        sep=";",
        encoding="utf-8",
        dtype=str,
    )

    # Normalize column names
    df.columns = df.columns.str.strip()

    # Parse date columns
    date_cols = ["LANÇAMENTO", "VENCIMENTO", "EFETIVAÇÃO"]
    for col in date_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce")

    # Convert VALOR to float
    # Handles both formats:
    #   - dot decimal:  "421.90"  (exported by Minhas Finanças app)
    #   - comma decimal: "1.234,56" (European/BR format with thousands separator)
    if "VALOR" in df.columns:
        sample = df["VALOR"].dropna().head(20)
        has_comma_decimal = sample.str.contains(r",\d{1,2}$").any()
        if has_comma_decimal:
            df["VALOR"] = (
                df["VALOR"]
                .str.replace(".", "", regex=False)   # remove thousands dot
                .str.replace(",", ".", regex=False)  # decimal comma → dot
            )
        df["VALOR"] = pd.to_numeric(df["VALOR"], errors="coerce")

    return df


def filter_by_month(df: pd.DataFrame, year: int, month: int, date_col: str = "VENCIMENTO") -> pd.DataFrame:
    mask = (df[date_col].dt.year == year) & (df[date_col].dt.month == month)
    return df[mask].copy()
