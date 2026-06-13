"""
data/loader.py — File discovery and loading utilities.
Supports CSV, TSV, JSON, Excel, Parquet, and SQLite files.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.table import Table

console = Console()

# ── Supported file extensions ──────────────────────────────────────────────────
SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".csv":     "CSV",
    ".tsv":     "TSV",
    ".json":    "JSON",
    ".xlsx":    "Excel",
    ".xls":     "Excel (legacy)",
    ".parquet": "Parquet",
    ".sqlite":  "SQLite",
}


# ── File Discovery ─────────────────────────────────────────────────────────────
def discover_files(folder: str) -> list[dict]:
    """
    Recursively scan *folder* for supported data files.

    Returns a list of dicts sorted by filename, each containing:
        path, name, ext, format, size_kb
    Raises FileNotFoundError if the folder does not exist.
    """
    base = Path(folder)
    if not base.exists():
        raise FileNotFoundError(f"Folder not found: {folder}")

    results: list[dict] = []
    for ext in SUPPORTED_EXTENSIONS:
        for file_path in base.rglob(f"*{ext}"):
            results.append(
                {
                    "path":    str(file_path),
                    "name":    file_path.name,
                    "ext":     ext,
                    "format":  SUPPORTED_EXTENSIONS[ext],
                    "size_kb": round(file_path.stat().st_size / 1024, 2),
                }
            )

    results.sort(key=lambda f: f["name"].lower())
    return results


# ── Display ────────────────────────────────────────────────────────────────────
def display_files(files: list[dict]) -> None:
    """Pretty-print a numbered table of discovered files with Rich."""
    if not files:
        console.print(
            "[yellow]⚠  No supported data files found in the specified folder.[/yellow]"
        )
        return

    table = Table(
        title="Discovered Data Files",
        show_header=True,
        header_style="bold magenta",
        border_style="bright_black",
    )
    table.add_column("#",           style="dim cyan",  justify="right", width=4)
    table.add_column("File Name",   style="bold white", min_width=20)
    table.add_column("Format",      style="green",      min_width=14)
    table.add_column("Size (KB)",   style="yellow",     justify="right", min_width=10)
    table.add_column("Path",        style="dim",        min_width=30)

    for i, f in enumerate(files, start=1):
        table.add_row(str(i), f["name"], f["format"], str(f["size_kb"]), f["path"])

    console.print(table)


# ── Single-file Loader ─────────────────────────────────────────────────────────
def load_file(file_info: dict) -> pd.DataFrame:
    """
    Load a single file into a DataFrame, dispatching on extension.
    Prints progress messages via Rich.
    """
    path: str = file_info["path"]
    ext:  str = file_info["ext"].lower()
    name: str = file_info["name"]

    console.print(f"[dim]  → Loading [italic]{name}[/italic] …[/dim]")

    df: pd.DataFrame

    if ext == ".csv":
        df = pd.read_csv(path)

    elif ext == ".tsv":
        df = pd.read_csv(path, sep="\t")

    elif ext == ".json":
        try:
            df = pd.read_json(path, orient="records")
        except Exception:
            df = pd.read_json(path, orient="columns")

    elif ext in (".xlsx", ".xls"):
        df = pd.read_excel(path)

    elif ext == ".parquet":
        df = pd.read_parquet(path)

    elif ext == ".sqlite":
        df = _load_sqlite(path)

    else:
        raise ValueError(f"Unsupported extension: {ext}")

    rows, cols = df.shape
    console.print(
        f"[green]  ✓ Loaded [bold]{name}[/bold] — "
        f"{rows:,} rows × {cols} columns[/green]"
    )
    return df


def _load_sqlite(path: str) -> pd.DataFrame:
    """Load a table from a SQLite database, prompting if multiple tables exist."""
    con = sqlite3.connect(path)
    cursor = con.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]

    if not tables:
        con.close()
        raise ValueError(f"SQLite database '{path}' contains no tables.")

    if len(tables) == 1:
        chosen = tables[0]
    else:
        console.print(
            f"[cyan]SQLite database contains {len(tables)} table(s):[/cyan]"
        )
        for i, t in enumerate(tables, start=1):
            console.print(f"  [bold]{i}.[/bold] {t}")

        raw = input("Enter table number to load: ").strip()
        try:
            idx = int(raw) - 1
            if not (0 <= idx < len(tables)):
                raise IndexError
            chosen = tables[idx]
        except (ValueError, IndexError):
            con.close()
            raise ValueError(f"Invalid table selection: '{raw}'")

    df = pd.read_sql_query(f"SELECT * FROM [{chosen}]", con)
    con.close()
    return df


# ── Multi-file Loader ──────────────────────────────────────────────────────────
def load_multiple(files: list[dict]) -> dict[str, pd.DataFrame]:
    """
    Load a list of file_info dicts and return a name→DataFrame mapping.
    Keys are the file stem (filename without extension).
    Errors are caught per-file; a red message is printed but loading continues.
    """
    dfs: dict[str, pd.DataFrame] = {}

    for file_info in files:
        stem = Path(file_info["path"]).stem
        try:
            dfs[stem] = load_file(file_info)
        except Exception as exc:
            console.print(
                f"[red]  ✗ Failed to load [bold]{file_info['name']}[/bold]: {exc}[/red]"
            )

    return dfs
