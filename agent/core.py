"""
agent/core.py — DataAgent: the ReAct loop that ties LLM + Executor together.

Parses <execute> and <answer> tags from the LLM response, runs code,
feeds results back, and loops until a final answer is produced or the
maximum iteration count is reached.
"""

from __future__ import annotations

import re

import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from agent.llm import GeminiLLM, LLMError
from agent.executor import Executor
from agent.prompt import build_system_prompt

console = Console()

MAX_ITERATIONS = 8

# Maximum characters of execution output to feed back to the LLM.
# Prevents token overflow when the agent prints huge DataFrames.
MAX_OUTPUT_CHARS = 8000


# ── Response parser ────────────────────────────────────────────────────────────
def parse_response(response: str) -> tuple[list[str], str | None]:
    """
    Extract ``<execute>`` code blocks and an optional ``<answer>`` block
    from the LLM's response text.

    Returns
    -------
    tuple[list[str], str | None]
        (list_of_code_strings, answer_text_or_None)
    """
    execute_blocks: list[str] = re.findall(
        r"<execute>(.*?)</execute>", response, re.DOTALL
    )
    execute_blocks = [block.strip() for block in execute_blocks]

    answer_match = re.search(r"<answer>(.*?)</answer>", response, re.DOTALL)
    answer: str | None = answer_match.group(1).strip() if answer_match else None

    return execute_blocks, answer


def extract_thinking(response: str) -> str | None:
    """
    Extract the reasoning/thinking text outside of ``<execute>`` and
    ``<answer>`` tags.
    """
    text = re.sub(r"<execute>.*?</execute>", "", response, flags=re.DOTALL)
    text = re.sub(r"<answer>.*?</answer>", "", text, flags=re.DOTALL)
    text = text.strip()
    return text if text else None


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    """Truncate long output so it doesn't blow up the context window."""
    if len(text) <= limit:
        return text
    half = limit // 2
    return (
        text[:half]
        + f"\n\n... [truncated {len(text) - limit:,} chars] ...\n\n"
        + text[-half:]
    )


# ── DataAgent ──────────────────────────────────────────────────────────────────
class DataAgent:
    """
    Interactive data analysis agent.

    Maintains conversation history and a persistent code sandbox so that
    follow-up queries can reference variables computed in earlier turns.
    """

    def __init__(
        self,
        dfs: dict[str, pd.DataFrame],
        model: str = "gemini-2.5-flash",
        output_dir: str = "./output",
    ) -> None:
        self.dfs = dfs
        self.llm = GeminiLLM(model=model)
        self.executor = Executor(dfs=dfs, output_dir=output_dir)
        self.system_prompt: str = build_system_prompt(dfs, output_dir=output_dir)
        self.history: list[dict[str, str]] = []

    # ── query loop ─────────────────────────────────────────────────────────────
    def run_query(self, user_query: str) -> str:
        """
        Run a user query through the ReAct loop.

        The loop calls the LLM, executes any code blocks, feeds the
        execution output back, and repeats until an ``<answer>`` tag is
        produced or *MAX_ITERATIONS* is reached.

        Returns
        -------
        str
            The final answer text, or a timeout message.
        """
        self.history.append({"role": "user", "content": user_query})

        for _iteration in range(MAX_ITERATIONS):
            # a) LLM call with error handling
            try:
                with console.status("[bold green]Agent is thinking...[/bold green]", spinner="dots"):
                    response: str = self.llm.chat(self.history, self.system_prompt)
            except LLMError as exc:
                console.print(f"[red]✗ LLM Error: {exc}[/red]")
                if exc.original:
                    console.print(f"[dim]  Cause: {exc.original}[/dim]")
                return f"LLM Error: {exc}"

            # b) Record assistant turn
            self.history.append({"role": "assistant", "content": response})

            # c) Parse
            thinking = extract_thinking(response)
            if thinking:
                from rich.markdown import Markdown
                console.print(
                    Panel(Markdown(thinking), title="[bold yellow]Thinking[/bold yellow]", border_style="yellow")
                )

            execute_blocks, answer = parse_response(response)

            # d) Execute code blocks
            for code in execute_blocks:
                # Pretty-print the code being executed
                syntax = Syntax(code, "python", theme="monokai", line_numbers=True)
                console.print(
                    Panel(syntax, title="[bold cyan]Executing Code[/bold cyan]", border_style="cyan")
                )

                result = self.executor.run(code)

                # If failed, check for ModuleNotFoundError and try to install/retry
                if not result.success:
                    match = re.search(r"ModuleNotFoundError:\s*No\s*module\s*named\s*'([^']+)'", result.error or "")
                    if match:
                        missing_module = match.group(1)
                        console.print(f"[bold yellow]⚠ Code execution failed because module '{missing_module}' is not installed.[/bold yellow]")
                        try:
                            confirm = input(f"Would you like to run 'pip install {missing_module}'? To grant permission type 'y' or 'n' [y/N]: ").strip().lower()
                        except (KeyboardInterrupt, EOFError):
                            confirm = "no"
                        if confirm in ("y", "yes"):
                            console.print(f"[dim]Running: pip install {missing_module}...[/dim]")
                            import subprocess
                            import sys
                            install_result = subprocess.run(
                                [sys.executable, "-m", "pip", "install", missing_module],
                                capture_output=True,
                                text=True
                            )
                            if install_result.returncode == 0:
                                console.print(f"[green]✓ Successfully installed {missing_module}. Retrying execution...[/green]")
                                # Re-run the code!
                                result = self.executor.run(code)
                            else:
                                console.print(f"[red]✗ Failed to install {missing_module}:[/red]\n{install_result.stderr or install_result.stdout}")

                if result.success:
                    output_text = _truncate(result.stdout)
                    feedback = f"[EXECUTION RESULT]\n{output_text}"
                    if result.stdout.strip():
                        console.print(f"[dim]{result.stdout}[/dim]")
                    else:
                        console.print("[dim](no output)[/dim]")
                else:
                    error_text = _truncate(result.error or "")
                    feedback = f"[EXECUTION RESULT - ERROR]\n{error_text}"
                    if result.stdout.strip():
                        console.print(f"[dim]{result.stdout}[/dim]")
                    console.print(f"[red]{result.error}[/red]")

                self.history.append({"role": "user", "content": feedback})

            # e) If the LLM produced an answer, we're done
            if answer is not None:
                from rich.markdown import Markdown
                console.print(
                    Panel(Markdown(answer), title="[bold green]Answer[/bold green]", border_style="green")
                )
                return answer

            # f) If no code AND no answer — nudge the LLM
            if not execute_blocks and answer is None:
                self.history.append(
                    {
                        "role": "user",
                        "content": "Please provide your analysis result in <answer> tags.",
                    }
                )

        # Loop exhausted
        timeout_msg = (
            "Agent reached maximum iterations without completing. "
            "Try rephrasing your query."
        )
        console.print(f"[yellow]{timeout_msg}[/yellow]")
        return timeout_msg

    # ── session management ─────────────────────────────────────────────────────
    def reset_history(self) -> None:
        """Clear conversation history."""
        self.history = []
        console.print("[dim]Conversation history cleared.[/dim]")

    def reload_data(self, new_dfs: dict[str, pd.DataFrame]) -> None:
        """
        Hot-swap the loaded datasets, rebuild the system prompt,
        update the executor sandbox, and clear history.
        """
        self.dfs = new_dfs
        self.executor.dfs = new_dfs
        self.executor.sandbox_globals["dfs"] = new_dfs
        self.system_prompt = build_system_prompt(new_dfs, output_dir=self.executor.output_dir)
        self.reset_history()
