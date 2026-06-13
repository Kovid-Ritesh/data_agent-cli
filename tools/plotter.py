"""
tools/plotter.py — Plotting utility helpers.

Provides convenience wrappers around matplotlib that the agent (or
user scripts in the sandbox) can call.  All functions save to disk
via savefig — plt.show() is never called.
"""

from __future__ import annotations

import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


DEFAULT_OUTPUT_DIR = "./output"


def save_plot(
    fig: plt.Figure,
    name: str,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    dpi: int = 150,
) -> str:
    """
    Save a matplotlib Figure to *output_dir*/*name*.png and close it.

    Parameters
    ----------
    fig : plt.Figure
        The figure to save.
    name : str
        Descriptive filename (without extension).
    output_dir : str
        Directory to write to (created if missing).
    dpi : int
        Resolution.

    Returns
    -------
    str
        Absolute path to the saved image.
    """
    os.makedirs(output_dir, exist_ok=True)
    filepath = str(Path(output_dir) / f"{name}.png")
    fig.savefig(filepath, bbox_inches="tight", dpi=dpi)
    plt.close(fig)
    return filepath


def quick_bar(
    df: pd.DataFrame,
    x: str,
    y: str,
    title: str = "",
    output_dir: str = DEFAULT_OUTPUT_DIR,
) -> str:
    """
    Create and save a simple bar chart.

    Returns the path to the saved PNG.
    """
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(df[x].astype(str), df[y])
    ax.set_xlabel(x)
    ax.set_ylabel(y)
    ax.set_title(title or f"{y} by {x}")
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    name = f"bar_{x}_{y}".replace(" ", "_").lower()
    return save_plot(fig, name, output_dir)


def quick_line(
    df: pd.DataFrame,
    x: str,
    y: str,
    title: str = "",
    output_dir: str = DEFAULT_OUTPUT_DIR,
) -> str:
    """
    Create and save a simple line chart.

    Returns the path to the saved PNG.
    """
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(df[x], df[y], marker="o", linewidth=1.5)
    ax.set_xlabel(x)
    ax.set_ylabel(y)
    ax.set_title(title or f"{y} over {x}")
    fig.tight_layout()
    name = f"line_{x}_{y}".replace(" ", "_").lower()
    return save_plot(fig, name, output_dir)


def quick_hist(
    df: pd.DataFrame,
    column: str,
    bins: int = 30,
    title: str = "",
    output_dir: str = DEFAULT_OUTPUT_DIR,
) -> str:
    """
    Create and save a histogram.

    Returns the path to the saved PNG.
    """
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.hist(df[column].dropna(), bins=bins, edgecolor="black", alpha=0.75)
    ax.set_xlabel(column)
    ax.set_ylabel("Frequency")
    ax.set_title(title or f"Distribution of {column}")
    fig.tight_layout()
    name = f"hist_{column}".replace(" ", "_").lower()
    return save_plot(fig, name, output_dir)
