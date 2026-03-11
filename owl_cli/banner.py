from __future__ import annotations

from rich.console import Console

from . import __version__


def print_banner(console: Console | None = None) -> None:
    """Print the Owl-CLI startup banner with owl ASCII art."""
    if console is None:
        console = Console(stderr=True)

    v = __version__

    console.print("[bold cyan] ██████╗ ██╗    ██╗██╗                ██████╗ ██╗      ██╗[/bold cyan]")
    console.print("[bold cyan]██╔═══██╗██║    ██║██║               ██╔════╝ ██║      ██║[/bold cyan]      [yellow],______,[/yellow]")
    console.print("[bold cyan]██║   ██║██║ █╗ ██║██║      ██████╗  ██║      ██║      ██║[/bold cyan]     [yellow]( O v O )[/yellow]")
    console.print("[bold cyan]██║   ██║██║███╗██║██║      ╚═════╝  ██║      ██║      ██║[/bold cyan]      [yellow]/  V  \\\\[/yellow]")
    console.print("[bold cyan]╚██████╔╝╚███╔███╔╝███████╗          ╚██████╗ ███████╗ ██║[/bold cyan]     [yellow]/(     )\\\\[/yellow]")
    console.print("[bold cyan] ╚═════╝  ╚══╝╚══╝ ╚══════╝           ╚═════╝ ╚══════╝ ╚═╝[/bold cyan]      [yellow]^^   ^^[/yellow]")
    console.print()
    console.print(f"   [bold cyan]Owl-CLI[/bold cyan] [dim]v{v}[/dim]  [dim]— Semantic Code Search[/dim] 🔍")
    console.print()


def print_download_banner(model_name: str, console: Console | None = None) -> None:
    """Print a banner when downloading the embedding model for the first time."""
    if console is None:
        console = Console(stderr=True)

    console.print()
    console.print("[bold cyan]  📥 Downloading embedding model...[/bold cyan]")
    console.print(f"     [dim]{model_name}[/dim]")
    console.print("     [dim]This may take a moment on first run.[/dim]")
    console.print()
