"""Tacit command line."""

import asyncio

import typer
from pydantic import ValidationError

from . import doctor
from .config import Settings

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """Tacit: a wristband that listens 24/7."""


@app.command("doctor")
def doctor_cmd() -> None:
    """Check the Vexo kit, the band number and every sponsor key."""
    try:
        settings = Settings()
    except ValidationError as e:
        for err in e.errors():
            typer.echo(f"FAIL  config          {err['loc'][0]}: {err['msg']}")
        raise typer.Exit(1) from None
    results = asyncio.run(doctor.run(settings))
    mark = {True: "OK  ", False: "FAIL", None: "--  "}
    for r in results:
        typer.echo(f"{mark[r.ok]}  {r.name:<15} {r.detail}")
    if any(r.ok is False for r in results):
        raise typer.Exit(1)
