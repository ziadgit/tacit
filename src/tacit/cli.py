"""Tacit command line."""

import asyncio
import json

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
    settings = _settings()
    results = asyncio.run(doctor.run(settings))
    mark = {True: "OK  ", False: "FAIL", None: "--  "}
    for r in results:
        typer.echo(f"{mark[r.ok]}  {r.name:<15} {r.detail}")
    if any(r.ok is False for r in results):
        raise typer.Exit(1)


def _settings() -> Settings:
    try:
        return Settings()
    except ValidationError as e:
        for err in e.errors():
            typer.echo(f"FAIL  config          {err['loc'][0]}: {err['msg']}")
        raise typer.Exit(1) from None


@app.command("serve")
def serve_cmd(
    host: str = typer.Option("127.0.0.1", help="Address to bind."),
    port: int = typer.Option(8000, help="Port to bind."),
    proxy_headers: bool = typer.Option(
        True, "--proxy-headers/--no-proxy-headers",
        help="Trust X-Forwarded-* (Fly's proxy terminates TLS)."),
) -> None:
    """Run the tacit server: API, PWA, landing page and webhooks."""
    import uvicorn

    from .app import create_app

    settings = _settings()
    uvicorn.run(create_app(settings), host=host, port=port, proxy_headers=proxy_headers,
                forwarded_allow_ips="*" if proxy_headers else None, log_level="info")


@app.command("vapi-sync")
def vapi_sync_cmd(
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the body, secrets as ***."),
) -> None:
    """Create or update the Vapi interview assistant."""
    from .interview import VapiApi, VapiError, assistant_body, masked

    settings = _settings()
    body = assistant_body(settings)
    if dry_run:
        typer.echo(json.dumps(masked(body), indent=2))
        return
    if not settings.public_base_url:
        typer.echo("FAIL  PUBLIC_BASE_URL is not set: Vapi needs it for the webhook")
        raise typer.Exit(1)
    if settings.vapi_api_key is None:
        typer.echo("FAIL  VAPI_API_KEY is not set")
        raise typer.Exit(1)
    vapi = VapiApi(settings)
    try:
        if settings.vapi_assistant_id:
            asyncio.run(vapi.update_assistant(settings.vapi_assistant_id, body))
            typer.echo("OK    updated the tacit interview assistant")
        else:
            out = asyncio.run(vapi.create_assistant(body))
            typer.echo("OK    created the tacit interview assistant")
            typer.echo(f"Add VAPI_ASSISTANT_ID={out.get('id')} to .env")
    except VapiError as e:
        typer.echo(f"FAIL  {e}")
        raise typer.Exit(1) from None


@app.command("bridge")
def bridge_cmd(
    sim: bool = typer.Option(False, "--sim", help="Use the pretend band (no Bluetooth)."),
) -> None:
    """Run the band bridge for TACIT_BAND: streams, mute, uploads."""
    from .bridge import run_bridge

    settings = _settings()
    if settings.tacit_band is None:
        typer.echo("FAIL  TACIT_BAND is not set: put 16 or 74 in .env")
        raise typer.Exit(1)
    try:
        asyncio.run(run_bridge(settings, sim=sim, echo=typer.echo))
    except KeyboardInterrupt:
        typer.echo("tacit bridge: stopped")
