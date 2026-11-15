"""Fly.io deploy files (SPEC §16). Files only: nothing here runs `fly`."""

import subprocess
import sys
import tomllib

from tacit.app import ROOT


def test_fly_toml():
    cfg = tomllib.loads((ROOT / "fly.toml").read_text())
    assert cfg["primary_region"] == "sjc"
    assert cfg["env"]["TACIT_DATA_DIR"] == "/data"
    assert cfg["env"]["PUBLIC_BASE_URL"].startswith("https://")
    http = cfg["http_service"]
    assert http["internal_port"] == 8000 and http["force_https"] is True
    assert http["auto_stop_machines"] == "off" and http["min_machines_running"] == 1
    checks = http["checks"]
    assert len(checks) == 1 and checks[0]["path"] == "/healthz" and checks[0]["method"] == "GET"
    mounts = cfg["mounts"]
    mounts = mounts if isinstance(mounts, list) else [mounts]
    assert len(mounts) == 1 and mounts[0]["destination"] == "/data"
    assert mounts[0]["source"] == "tacit_data"
    text = (ROOT / "fly.toml").read_text().lower()
    for word in ("secret", "api_key", "sk_test", "whsec"):
        assert word not in text


def test_dockerignore():
    lines = {line.strip() for line in (ROOT / ".dockerignore").read_text().splitlines()}
    for must in (".env", "vexo-open-kit", "data", ".venv", ".git", "deploy", "**/*_test.py"):
        assert must in lines, must


def test_dockerfile():
    df = (ROOT / "Dockerfile").read_text()
    assert df.startswith("#") and "FROM python:3.11-slim" in df
    assert "ghcr.io/astral-sh/uv:" in df and "ghcr.io/astral-sh/uv:latest" not in df
    assert "uv sync --frozen --no-dev" in df
    assert "COPY . ." not in df and "vexo-open-kit" not in df.replace("# ", "")
    for d in ("src/", "pwa/", "landing/", "design-system/"):
        assert f"COPY {d}" in df
    assert "\nUSER tacit" in df
    assert 'CMD ["/app/.venv/bin/tacit", "serve", "--host", "0.0.0.0", "--port", "8000"]' in df


def test_server_imports_without_the_kit():
    code = r"""
import sys, importlib.abc
sys.path = [p for p in sys.path if "vexo-open-kit" not in p]
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in ("vexo_open", "speech", "ai"):
            raise ImportError("the kit must not load in the server path")
        return None
sys.meta_path.insert(0, Block())
from fastapi.testclient import TestClient
from tacit.app import create_app
from tacit.config import Settings
with TestClient(create_app(Settings(_env_file=None))) as c:
    assert c.get("/healthz").json()["status"] == "ok"
import tacit.cli, tacit.network, tacit.payments, tacit.portraits, tacit.interview
assert not any("vexo-open-kit" in p for p in sys.path)
print("ok")
"""
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().endswith("ok")


def test_pi_service_file():
    svc = (ROOT / "deploy" / "pi" / "tacit-bridge.service").read_text()
    for line in ("Restart=always", "User=tacit", "WorkingDirectory=/opt/tacit",
                 "EnvironmentFile=/opt/tacit/.env"):
        assert f"\n{line}\n" in svc, line
    assert "ExecStart=/opt/tacit/.venv/bin/tacit bridge" in svc and "--sim" not in svc
    readme = (ROOT / "deploy" / "pi" / "README.md").read_text()
    for words in ("uv", "scripts/bootstrap.sh", "systemctl enable", "hostapd", "Bluetooth"):
        assert words in readme


def test_healthz_bridge_fields(tmp_path):
    import json
    import time

    from tacit.testing import client, make_settings

    s = make_settings(tacit_data_dir=tmp_path / "data")
    c = client(tmp_path, s)
    assert c.get("/healthz").json() == {"status": "ok"}
    (tmp_path / "data").mkdir()
    health = {"band_connected": True, "listening": False, "muted": True, "buffer_mb": 1.5,
              "last_sync": None, "at": time.time()}
    (tmp_path / "data" / "bridge-health.json").write_text(json.dumps(health))
    out = c.get("/healthz").json()
    assert out == {"status": "ok", "band_connected": True, "listening": False, "muted": True,
                   "buffer_mb": 1.5, "last_sync": None}
    health["at"] = time.time() - 120                   # stale: the bridge isn't running
    (tmp_path / "data" / "bridge-health.json").write_text(json.dumps(health))
    assert c.get("/healthz").json() == {"status": "ok"}
