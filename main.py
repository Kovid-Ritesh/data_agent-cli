#!/usr/bin/env python3
"""
main.py — CLI entry-point for the DataAgent.

Handles argument parsing, file discovery, interactive file selection,
data loading, and the REPL loop with special commands.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from data.loader import (
    SUPPORTED_EXTENSIONS,
    discover_files,
    display_files,
    load_file,
    load_multiple,
)
from agent.core import DataAgent

console = Console()

# ── ASCII banner ───────────────────────────────────────────────────────────────
BANNER = r"""
 ____        _          _                    _      ____ _     ___
|  _ \  __ _| |_ __ _  / \   __ _  ___ _ __ | |_   / ___| |   |_ _|
| | | |/ _` | __/ _` |/ _ \ / _` |/ _ \ '_ \| __| | |   | |    | |
| |_| | (_| | || (_| / ___ \ (_| |  __/ | | | |_  | |___| |___ | |
|____/ \__,_|\__\__,_/_/   \_\__, |\___|_| |_|\__|  \____|_____|___|
                              |___/
"""


# ── Argument parser ───────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="DataAgent CLI — interactive developer & data analysis agent powered by Google Gemini.",
    )
    parser.add_argument(
        "query",
        type=str,
        nargs="?",
        default=None,
        help="Optional single query to run. If provided, the agent executes this query and exits.",
    )
    parser.add_argument(
        "--folder",
        type=str,
        default=".",
        help="Directory to scan for data files (default: current directory).",
    )
    parser.add_argument(
        "--files",
        nargs="+",
        default=None,
        help="Specific filenames to load (optional, space-separated).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gemini-2.5-flash",
        help="Gemini model to use (default: gemini-2.5-flash).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="./output",
        help="Output directory for plots and artifacts (default: ./output).",
    )
    return parser


# ── Helpers ────────────────────────────────────────────────────────────────────
def print_help_commands() -> None:
    """Print the list of REPL special commands."""
    help_table = Table(
        title="Available Commands",
        show_header=True,
        header_style="bold cyan",
        border_style="bright_black",
    )
    help_table.add_column("Command", style="bold yellow", min_width=18)
    help_table.add_column("Description", style="white")

    help_table.add_row("help",           "Show this help message")
    help_table.add_row("files",          "List currently loaded datasets and their shapes")
    help_table.add_row("load <path>",    "Load an additional data file into the agent")
    help_table.add_row("unload/remove <name>", "Remove a loaded dataset from the agent's memory")
    help_table.add_row("clear",          "Clear conversation history")
    help_table.add_row("cls",            "Clear the terminal screen")
    help_table.add_row("exit / quit",    "Exit the application")
    help_table.add_row("<any query>",    "Ask the agent a question or request a task")

    console.print(help_table)


def print_loaded_files(dfs: dict) -> None:
    """Display a quick summary of loaded datasets."""
    table = Table(
        title="Loaded Datasets",
        show_header=True,
        header_style="bold cyan",
        border_style="bright_black",
    )
    table.add_column("Name", style="bold white", min_width=20)
    table.add_column("Rows", style="green", justify="right")
    table.add_column("Columns", style="green", justify="right")

    for name, df in dfs.items():
        rows, cols = df.shape
        table.add_row(name, f"{rows:,}", str(cols))

    console.print(table)


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # ── Banner ─────────────────────────────────────────────────────────────────
    if not args.query:
        console.print(Panel(BANNER, style="bold cyan", border_style="cyan"))
        console.print(f"[dim]Model:[/dim] [bold]{args.model}[/bold]")
        console.print()

    # ── Discover files ─────────────────────────────────────────────────────────
    try:
        discovered = discover_files(args.folder)
    except FileNotFoundError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        sys.exit(1)

    # ── File selection and loading ──────────────────────────────────────────────
    dfs = {}
    if discovered:
        if not args.query:
            display_files(discovered)

        if args.files:
            # Filter by supplied filenames
            selected = [f for f in discovered if f["name"] in args.files]
            if not selected:
                console.print(
                    f"[yellow]⚠ None of the specified --files matched discovered files in '{args.folder}'.[/yellow]"
                )
        else:
            # Default auto-load up to 10 discovered files
            selected = discovered[:10]
            if len(discovered) > 10 and not args.query:
                console.print(
                    f"[yellow]⚠ Found {len(discovered)} data files. Automatically loading the first 10. "
                    "You can load additional files manually using the 'load <path>' command.[/yellow]"
                )
        dfs = load_multiple(selected)
    else:
        if not args.query:
            console.print("[dim]No supported data files discovered in the workspace. Agent ready for general tasks.[/dim]")

    # ── Initialize agent ───────────────────────────────────────────────────────
    agent = DataAgent(dfs=dfs, model=args.model, output_dir=args.output)
    
    if args.query:
        # Single-shot execution mode
        try:
            agent.run_query(args.query)
        except Exception as exc:
            console.print(f"[red]✗ Error: {exc}[/red]")
            sys.exit(1)
        sys.exit(0)

    # Interactive REPL mode
    if dfs:
        console.print(
            f"\n[green]✓ Loaded {len(dfs)} dataset(s). Agent ready.[/green]"
        )
    else:
        console.print(
            "\n[green]✓ Agent ready. Feel free to ask general programming or system questions.[/green]"
        )
    print_help_commands()
    console.print()

    # ── REPL loop ──────────────────────────────────────────────────────────────
    while True:
        try:
            console.print("[bold cyan][DataAgent][/bold cyan] > ", end="")
            user_input = input("").strip()
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted. Type 'exit' to quit.[/yellow]")
            continue
        except EOFError:
            console.print("\n[dim]Goodbye.[/dim]")
            sys.exit(0)

        if not user_input:
            continue

        command = user_input.lower()

        # ── special commands ───────────────────────────────────────────────────
        if command in ("exit", "quit"):
            console.print("[dim]Goodbye.[/dim]")
            sys.exit(0)

        elif command == "clear":
            agent.reset_history()

        elif command in ("cls", "clear-screen", "clear_screen"):
            import os
            os.system("cls" if os.name == "nt" else "clear")

        elif command == "files":
            print_loaded_files(dfs)

        elif command == "help":
            print_help_commands()

        elif command.startswith("unload ") or command.startswith("remove "):
            target_name = user_input[7:].strip().strip("'\"")
            if not target_name:
                console.print("[red]✗ Please specify a dataset name to remove.[/red]")
                continue

            if target_name in dfs:
                dfs.pop(target_name)
                agent.reload_data(dfs)
                console.print(
                    f"[green]✓ Removed '{target_name}' and reloaded agent context.[/green]"
                )
            else:
                # Try finding case-insensitive match
                matched = [k for k in dfs.keys() if k.lower() == target_name.lower()]
                if matched:
                    name_to_del = matched[0]
                    dfs.pop(name_to_del)
                    agent.reload_data(dfs)
                    console.print(
                        f"[green]✓ Removed '{name_to_del}' and reloaded agent context.[/green]"
                    )
                else:
                    console.print(f"[red]✗ Dataset not found: {target_name}[/red]")
                    console.print(f"[dim]  Currently loaded datasets: {', '.join(dfs.keys()) or '(none)'}[/dim]")

        elif command.startswith("load "):
            file_path = user_input[5:].strip().strip("'\"")
            if not file_path:
                console.print("[red]✗ Please specify a file path to load.[/red]")
                continue

            p = Path(file_path)
            # Resolve relative to folder if not found directly
            if not p.exists():
                p_alt = Path(args.folder) / p
                if p_alt.exists():
                    p = p_alt

            if not p.exists():
                console.print(f"[red]✗ File not found: {file_path}[/red]")
                console.print("[dim]  Tried paths:[/dim]")
                console.print(f"[dim]  - {Path(file_path).resolve()}[/dim]")
                if args.folder != ".":
                    console.print(f"[dim]  - {(Path(args.folder) / Path(file_path)).resolve()}[/dim]")
                continue

            ext = p.suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                supported_str = ", ".join(SUPPORTED_EXTENSIONS.keys())
                console.print(f"[red]✗ Unsupported file type '{ext}'. Supported formats: {supported_str}[/red]")
                continue

            file_info = {
                "path": str(p),
                "name": p.name,
                "ext": ext,
                "format": SUPPORTED_EXTENSIONS[ext],
                "size_kb": round(p.stat().st_size / 1024, 2),
            }
            try:
                new_df = load_file(file_info)
                stem = p.stem
                dfs[stem] = new_df
                agent.reload_data(dfs)
                console.print(
                    f"[green]✓ Added '{stem}' and reloaded agent context.[/green]"
                )
            except Exception as exc:
                console.print(f"[red]✗ Failed to load file: {exc}[/red]")

        else:
            # ── data analysis query ────────────────────────────────────────────
            try:
                agent.run_query(user_input)
            except Exception as exc:
                console.print(f"[red]✗ Error: {exc}[/red]")


if __name__ == "__main__":
    main()
