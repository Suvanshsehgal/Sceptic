"""
Terminal presentation for the Sceptic CLI.

One place decides how output looks, so every command stays consistent:
- color is used only on an interactive terminal, and is off when NO_COLOR is set or --no-color is given
- symbols fall back to ASCII when the console cannot encode Unicode (older Windows consoles)
- status is always shown in words as well as color, so the output still reads correctly in plain logs
"""
import os
import sys
from typing import Iterable, Optional, Sequence, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

APP_NAME = "Sceptic"
APP_VERSION = "0.2.0"

_state = {"no_color": False}

ACCENT = "cyan"
SUCCESS = "green"
WARNING = "yellow"
DANGER = "red"
MUTED = "bright_black"


def set_no_color(value: bool) -> None:
    """Called from the --no-color option. Updates the shared consoles in place, so every module keeps its reference."""
    _state["no_color"] = bool(value)
    for shared in (console, err_console):
        shared.no_color = not _color_enabled()


def _color_enabled() -> bool:
    if _state["no_color"] or os.getenv("NO_COLOR") is not None:
        return False
    if os.getenv("TERM", "").lower() == "dumb":
        return False
    return sys.stdout.isatty()


def _unicode_ok() -> bool:
    encoding = (getattr(sys.stdout, "encoding", None) or "ascii").lower()
    return "utf" in encoding


def make_console(stderr: bool = False) -> Console:
    return Console(
        stderr=stderr,
        no_color=not _color_enabled(),
        highlight=False,
        soft_wrap=False,
        emoji=False,
    )


console = make_console()
err_console = make_console(stderr=True)


class Symbols:
    @staticmethod
    def _pick(unicode_symbol: str, ascii_symbol: str) -> str:
        return unicode_symbol if _unicode_ok() else ascii_symbol

    @property
    def ok(self) -> str:
        return self._pick("✔", "[ok]")

    @property
    def fail(self) -> str:
        return self._pick("✖", "[x]")

    @property
    def warn(self) -> str:
        return self._pick("▲", "[!]")

    @property
    def info(self) -> str:
        return self._pick("•", "-")

    @property
    def arrow(self) -> str:
        return self._pick("›", ">")

    @property
    def bullet(self) -> str:
        return self._pick("·", "-")


SYM = Symbols()


def header(subtitle: Optional[str] = None) -> None:
    """One-line brand bar used at the top of every screen."""
    line = Text()
    line.append(f" {APP_NAME} ", style=f"bold black on {ACCENT}")
    line.append(f"  v{APP_VERSION}", style=MUTED)
    if subtitle:
        line.append(f"   {subtitle}", style="bold")
    console.print(line)
    console.print()


def section(title: str) -> None:
    console.print()
    console.print(Text(title.upper(), style=f"bold {ACCENT}"))
    console.rule(style=MUTED)


def success(message: str) -> None:
    console.print(Text.assemble((f"{SYM.ok} ", f"bold {SUCCESS}"), (message, "")))


def warning(message: str) -> None:
    console.print(Text.assemble((f"{SYM.warn} ", f"bold {WARNING}"), (message, "")))


def info(message: str) -> None:
    console.print(Text.assemble((f"{SYM.info} ", MUTED), (message, "")))


def error(message: str, hint: Optional[str] = None, code: Optional[int] = None) -> None:
    """Writes an error to stderr with an optional next step. The exit code is printed only when given."""
    err_console.print(Text.assemble((f"{SYM.fail} Error: ", f"bold {DANGER}"), (message, "")))
    if hint:
        err_console.print(Text.assemble(("  hint  ", MUTED), (hint, "")))
    if code is not None:
        err_console.print(Text(f"  exit  {code}", style=MUTED))


def kv_table(rows: Iterable[Tuple[str, object]], title: Optional[str] = None) -> Table:
    table = Table(
        title=title,
        title_style=f"bold {ACCENT}",
        title_justify="left",
        box=box.SIMPLE_HEAVY,
        show_header=False,
        pad_edge=False,
        expand=False,
    )
    table.add_column("key", style=MUTED, no_wrap=True)
    table.add_column("value", style="", overflow="fold")
    for key, value in rows:
        table.add_row(key, value if isinstance(value, Text) else Text(str(value)))
    return table


def status_text(state: str) -> Text:
    """state is one of: ok, fail, warn, info. The word is always shown next to the symbol."""
    mapping = {
        "ok": (SYM.ok, SUCCESS, "OK"),
        "fail": (SYM.fail, DANGER, "FAIL"),
        "warn": (SYM.warn, WARNING, "WARN"),
        "info": (SYM.info, ACCENT, "INFO"),
    }
    symbol, color, word = mapping.get(state, mapping["info"])
    return Text(f"{symbol} {word}", style=f"bold {color}")


SEVERITY_STYLE = {
    "CRITICAL": ("bold white on red", "fail"),
    "HIGH": ("bold red", "fail"),
    "MEDIUM": ("bold yellow", "warn"),
    "LOW": ("cyan", "info"),
    "INFO": (MUTED, "info"),
}


def severity_text(severity: str) -> Text:
    key = (severity or "INFO").upper()
    style, _ = SEVERITY_STYLE.get(key, (MUTED, "info"))
    return Text(key, style=style)


def recommendation_text(value: Optional[str]) -> Text:
    if not value:
        return Text("NO VERDICT", style=f"bold {MUTED}")
    if value == "APPROVE":
        return Text("APPROVE", style=f"bold {SUCCESS}")
    if value == "REQUEST_CHANGES":
        return Text("REQUEST CHANGES", style=f"bold {WARNING}")
    return Text(value.replace("_", " "), style=f"bold {DANGER}")


def score_text(score: float) -> Text:
    color = SUCCESS if score >= 85 else WARNING if score >= 65 else DANGER
    return Text(f"{score:.1f}", style=f"bold {color}")


def verdict_panel(score: float, recommendation: str, summary: str, target: str) -> Panel:
    body = Text()
    body.append("Trust score   ", style=MUTED)
    body.append_text(score_text(score))
    body.append(" / 100\n", style=MUTED)
    body.append("Verdict       ", style=MUTED)
    body.append_text(recommendation_text(recommendation))
    body.append("\n\n")
    body.append(summary or "", style="")
    return Panel(
        body,
        title=Text(f" {target} ", style="bold"),
        title_align="left",
        border_style=SUCCESS if recommendation == "APPROVE" else WARNING if recommendation == "REQUEST_CHANGES" else DANGER,
        box=box.ROUNDED,
        padding=(1, 2),
    )


def table(title: Optional[str], columns: Sequence[Tuple[str, dict]]) -> Table:
    grid = Table(
        title=title,
        title_style=f"bold {ACCENT}",
        title_justify="left",
        box=box.SIMPLE_HEAVY,
        header_style=f"bold {MUTED}",
        border_style=MUTED,
        pad_edge=False,
        expand=False,
    )
    for name, options in columns:
        grid.add_column(name, **options)
    return grid


def legend_for_symbols() -> str:
    return f"{SYM.ok} passed   {SYM.fail} failed   {SYM.warn} warning   {SYM.info} information"
