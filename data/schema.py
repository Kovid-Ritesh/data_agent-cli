"""
data/schema.py — DataFrame schema extraction for LLM context.

Produces a detailed, human-readable (and LLM-readable) text schema
for one or more DataFrames, including column types, null counts,
type-specific statistics, and a sample of the first 3 rows.
"""

from __future__ import annotations

import pandas as pd
from tabulate import tabulate

# If a dataset has more columns than this, the schema is summarised
# to avoid filling the entire LLM context window.
MAX_COLUMNS_FULL_SCHEMA = 80


def extract_schema(name: str, df: pd.DataFrame) -> str:
    """
    Generate a comprehensive text schema for a single DataFrame.

    Parameters
    ----------
    name : str
        Logical name of the dataset (used as the dict key in dfs).
    df : pd.DataFrame
        The DataFrame to describe.

    Returns
    -------
    str
        A multi-line string describing the dataset schema and sample rows.
    """
    row_count, col_count = df.shape
    lines: list[str] = []

    lines.append(f"Dataset: {name} ({row_count:,} rows × {col_count} columns)")
    lines.append("")
    lines.append("Columns:")

    columns_to_describe = df.columns
    truncated = False
    if col_count > MAX_COLUMNS_FULL_SCHEMA:
        columns_to_describe = df.columns[:MAX_COLUMNS_FULL_SCHEMA]
        truncated = True

    for col in columns_to_describe:
        series = df[col]
        dtype = str(series.dtype)
        nulls = int(series.isna().sum())

        # ── type-specific stats ────────────────────────────────────────────────
        kind = series.dtype.kind  # 'i','u','f','b','M','O','U' etc.

        try:
            if kind in ("i", "u", "f"):  # integer / float
                non_null = series.dropna()
                if len(non_null) > 0:
                    stats = (
                        f"min={float(non_null.min()):.2f}, "
                        f"max={float(non_null.max()):.2f}, "
                        f"mean={float(non_null.mean()):.2f}, "
                        f"std={float(non_null.std()):.2f}"
                    )
                else:
                    stats = "min=N/A, max=N/A, mean=N/A, std=N/A"

            elif kind == "M":  # datetime
                non_null = series.dropna()
                if len(non_null) > 0:
                    stats = f"range: {non_null.min()} → {non_null.max()}"
                else:
                    stats = "range: N/A → N/A"

            elif kind == "b":  # boolean
                true_count = int(series.sum())
                false_count = int((~series).sum())
                stats = f"true={true_count}, false={false_count}"

            else:  # object / string / category / other
                nunique = series.nunique()
                top_vals = series.dropna().value_counts().head(3).index.tolist()
                top_str = str(top_vals)
                stats = f"unique={nunique}, top: {top_str}"

        except Exception:
            stats = "(stats unavailable)"

        lines.append(
            f"  - {col:<20} {dtype:<20} | nulls: {nulls:<6} | {stats}"
        )

    if truncated:
        remaining = col_count - MAX_COLUMNS_FULL_SCHEMA
        lines.append(f"  ... and {remaining} more columns (use dfs['{name}'].columns.tolist() to see all)")

    # ── sample rows ───────────────────────────────────────────────────────────
    lines.append("")
    lines.append("Sample rows (first 3):")
    sample = df.head(3)
    try:
        lines.append(tabulate(sample, headers="keys", tablefmt="simple", showindex=False))
    except Exception:
        lines.append(str(sample))

    return "\n".join(lines)


def extract_all_schemas(dfs: dict[str, pd.DataFrame]) -> str:
    """
    Generate schemas for every DataFrame in *dfs* and join them with a separator.

    Returns
    -------
    str
        All schemas concatenated with '\\n' + '='*60 + '\\n' as dividers.
    """
    separator = "\n" + "=" * 60 + "\n"
    parts = [extract_schema(name, df) for name, df in dfs.items()]
    return separator.join(parts)
