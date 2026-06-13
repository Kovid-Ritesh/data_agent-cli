"""
agent/executor.py — Sandboxed Python code executor.

Provides a persistent execution sandbox where LLM-generated code runs.
Variables persist across calls so follow-up queries can reference
previously computed results.
"""

from __future__ import annotations

import builtins
import contextlib
import io
import os
import re as re_module
import traceback
import math
import datetime
import json
from dataclasses import dataclass

import matplotlib
matplotlib.use("Agg")  # non-interactive backend — no plt.show() possible
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from tabulate import tabulate


@dataclass
class ExecutionResult:
    """Structured result from a single code execution."""

    stdout: str
    error: str | None
    success: bool


class Executor:
    """
    Persistent sandboxed Python executor.

    The sandbox_globals dict is shared across all run() calls within the
    same Executor instance, so variables defined in one execution are
    available in subsequent ones.
    """

    def __init__(
        self,
        dfs: dict[str, pd.DataFrame],
        output_dir: str = "./output",
    ) -> None:
        self.dfs = dfs
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

        # Import plotter helpers and bind them with output_dir pre-applied
        import tools.plotter as plotter
        import subprocess
        import sys
        from rich.console import Console
        from rich.panel import Panel

        # Write directly to the original un-redirected stdout stream so the user actually sees the requests.
        exec_console = Console(file=sys.__stdout__)

        def custom_save_plot(fig: plt.Figure, name: str, dpi: int = 150) -> str:
            return plotter.save_plot(fig, name, output_dir=self.output_dir, dpi=dpi)

        def custom_quick_bar(df: pd.DataFrame, x: str, y: str, title: str = "") -> str:
            return plotter.quick_bar(df, x, y, title=title, output_dir=self.output_dir)

        def custom_quick_line(df: pd.DataFrame, x: str, y: str, title: str = "") -> str:
            return plotter.quick_line(df, x, y, title=title, output_dir=self.output_dir)

        def custom_quick_hist(df: pd.DataFrame, column: str, bins: int = 30, title: str = "") -> str:
            return plotter.quick_hist(df, column, bins=bins, title=title, output_dir=self.output_dir)

        def custom_run_command(cmd: str) -> str:
            """Execute a terminal command with user permission and return stdout/stderr."""
            cmd = cmd.strip()
            exec_console.print()
            exec_console.print(Panel(
                f"[bold yellow]The agent wants to execute the following terminal command:[/bold yellow]\n\n"
                f"  [bold green]$ {cmd}[/bold green]",
                title="[bold red]Terminal Command Request[/bold red]",
                border_style="red"
            ))
            try:
                exec_console.print("[bold cyan]To grant permission type 'y' or 'n' [y/N]: [/bold cyan]", end="")
                confirm = input("").strip().lower()
            except (KeyboardInterrupt, EOFError):
                exec_console.print("\n[red]Execution cancelled by user.[/red]")
                raise PermissionError("User cancelled command execution request.")

            if confirm not in ("y", "yes"):
                exec_console.print("[yellow]⚠ Command execution denied by user.[/yellow]")
                raise PermissionError(f"User denied permission to execute command: {cmd}")

            exec_console.print("[dim]Executing command...[/dim]")
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True
            )
            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                output += result.stderr
            exec_console.print(f"[dim]Finished. Exit code: {result.returncode}[/dim]")
            return output

        self.sandbox_globals: dict = {
            "pd": pd,
            "np": np,
            "plt": plt,
            "dfs": self.dfs,
            "math": math,
            "datetime": datetime,
            "json": json,
            "re": re_module,
            "tabulate": tabulate,
            "__builtins__": builtins,
            "save_plot": custom_save_plot,
            "quick_bar": custom_quick_bar,
            "quick_line": custom_quick_line,
            "quick_hist": custom_quick_hist,
            "run_command": custom_run_command,
        }

    # ── public interface ───────────────────────────────────────────────────────
    def run(self, code: str) -> ExecutionResult:
        """
        Execute *code* inside the persistent sandbox.

        Returns an ExecutionResult with captured stdout and, on failure,
        the full Python traceback as a string.
        """
        code = self._strip_fences(code)

        stdout_buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout_buf):
                exec(code, self.sandbox_globals)  # noqa: S102
            return ExecutionResult(
                stdout=stdout_buf.getvalue(),
                error=None,
                success=True,
            )
        except Exception:
            tb = traceback.format_exc()
            return ExecutionResult(
                stdout=stdout_buf.getvalue(),
                error=tb,
                success=False,
            )

    # ── helpers ────────────────────────────────────────────────────────────────
    @staticmethod
    def _strip_fences(code: str) -> str:
        """Remove optional markdown code fences wrapping the code."""
        code = code.strip()
        # ```python … ```  or  ``` … ```
        if code.startswith("```"):
            first_newline = code.index("\n") if "\n" in code else len(code)
            code = code[first_newline + 1 :]
        if code.endswith("```"):
            code = code[: -3]
        return code.strip()
