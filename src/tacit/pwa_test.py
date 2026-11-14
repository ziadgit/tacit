"""The PWA, checked without a browser (SPEC §12)."""

import json
import re
import struct

from tacit.app import ROOT
from tacit.testing import client

PWA = ROOT / "pwa"


def own_js() -> dict[str, str]:
    return {p.name: p.read_text() for p in PWA.glob("*.js")}


def png_size(path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR"
    return struct.unpack(">II", data[16:24])


def test_manifest_fields_and_icons():
    m = json.loads((PWA / "manifest.webmanifest").read_text())
    assert m["name"] == "tacit" and m["short_name"] == "tacit"
    assert m["start_url"] == "/app/" and m["scope"] == "/app/" and m["display"] == "standalone"
    tokens = json.loads((ROOT / "design-system" / "tokens.json").read_text())
    colours = {t["value"].lower() for t in tokens["color"]["tokens"]}
    assert m["background_color"].lower() in colours and m["theme_color"].lower() in colours
    assert any(i.get("purpose") == "maskable" for i in m["icons"])
    for icon in m["icons"]:
        path = PWA / icon["src"].removeprefix("/app/")
        assert path.is_file(), icon["src"]
        if icon["type"] == "image/png":
            w, h = icon["sizes"].split("x")
            assert png_size(path) == (int(w), int(h))


def test_png_dimensions():
    assert png_size(PWA / "icons" / "icon-192.png") == (192, 192)
    assert png_size(PWA / "icons" / "icon-512.png") == (512, 512)
    assert png_size(PWA / "icons" / "maskable-512.png") == (512, 512)


def test_index_links_manifest_and_registers_sw():
    html = (PWA / "index.html").read_text()
    assert 'rel="manifest" href="/app/manifest.webmanifest"' in html
    assert 'data-sw="/app/sw.js"' in html and 'data-scope="/app/"' in html
    assert re.search(r'<script type="module" src="/app/app.js"', html)
    # the CSP allows no inline script, so the registration code lives in app.js
    assert "<script>" not in html
    app = own_js()["app.js"]
    assert "serviceWorker.register(me.dataset.sw, { scope: me.dataset.scope })" in app


def test_no_unsafe_js():
    for name, src in own_js().items():
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "eval(", "alert(",
                    "confirm(", "prompt(", "document.write", "new Function"):
            assert bad not in src, f"{bad} in {name}"
        assert not re.search(r"fetch\(\s*['\"`]https?:", src), f"external fetch in {name}"
        if name != "api.js":
            assert "fetch(" not in src or name == "sw.js", f"fetch outside api.js in {name}"


def test_vendor_is_a_copy_with_source_comment():
    for ext in ("css", "js"):
        copy = (PWA / "vendor" / f"bundle.{ext}").read_text()
        src = (ROOT / "design-system" / "components" / f"bundle.{ext}").read_text()
        first, rest = copy.split("\n", 1)
        assert "design-system/components/bundle" in first
        assert rest == src


def test_sw_never_caches_api():
    sw = (PWA / "sw.js").read_text()
    assert "tacit-shell-v1" in sw
    assert "'/api/'" in sw and "isApi(url)" in sw
    shell = re.search(r"const SHELL = \[(.*?)\];", sw, re.S).group(1)
    assert "/api/" not in shell
    for path in re.findall(r"'(/app/[^']*)'", shell):
        rel = path.removeprefix("/app/") or "index.html"
        assert (PWA / rel).is_file(), path
    assert "caches.delete" in sw  # old caches go on activate


def test_served(tmp_path):
    c = client(tmp_path)
    r = c.get("/app/")
    assert r.status_code == 200 and "tacit" in r.text
    assert "content-security-policy" in r.headers
    r = c.get("/app/sw.js")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
    r = c.get("/app/manifest.webmanifest")
    assert r.headers["content-type"].startswith("application/manifest+json")
    assert c.get("/app/vendor/bundle.js").status_code == 200
    assert c.get("/app/icons/icon-192.png").status_code == 200


def test_screens_and_words():
    html = (PWA / "index.html").read_text()
    for screen in ("start", "context", "call", "skills", "me"):
        assert f'data-screen="{screen}"' in html
    app = own_js()["app.js"]
    assert "Look me up on the web (Exa) so the interview starts from what's public" in app
    assert "tacit may call me at this number" in app
    assert "We don't keep the audio or the transcript." in app
    assert "looks specific" in app and "might be generic" in app
    assert re.search(r"\bmoves?\b", app.lower()) is None
    # consent boxes start unticked
    assert "name: 'consent_lookup', checked" not in app
    # blue means only "listening": the PWA's own CSS never uses it
    css = (PWA / "style.css").read_text().upper()
    assert "#1F5EFF" not in css and "--T-LISTEN" not in css


def test_p1_screens_people_feed():
    html = (PWA / "index.html").read_text()
    for screen in ("people", "person", "feed"):
        assert f'data-screen="{screen}"' in html
    for nav in ("#/feed", "#/people", "#/skills", "#/me"):
        assert f'href="{nav}"' in html
    app = own_js()["app.js"]
    assert "unlock followers-only skills for" in app
    assert "/checkout`" in app and "location.assign(url)" in app
    assert "only you see this" in app
    assert "'sketched'" in app
    assert "T.ring(" in app  # PersonRings come from the design system's ring()
    css = (PWA / "style.css").read_text()
    assert "--t-lit" in css  # orange only on a new pass
    assert css.count("--t-lit") == 2 and ".pass.lit" in css


def test_reduced_motion_and_offline_banner():
    css = (PWA / "style.css").read_text()
    assert "@media (prefers-reduced-motion: reduce)" in css
    html = (PWA / "index.html").read_text()
    assert 'id="offline"' in html and "you're offline" in html
    app = own_js()["app.js"]
    assert "addEventListener('offline'" in app and "navigator.onLine" in app


def test_portrait_in_the_pwa():
    face = (PWA / "vendor" / "face.js").read_text()
    assert "landing/landing.js" in face.split("\n", 1)[0]
    landing = (ROOT / "landing" / "landing.js").read_text()
    body = face[face.index("  function face(cv, rows) {"):face.index("  window.TacitFace")]
    assert body.strip() in landing  # a copy of face(), not an edit
    html = (PWA / "index.html").read_text()
    assert '/app/vendor/face.js' in html
    app = own_js()["app.js"]
    assert "capture: 'user'" in app and "accept: 'image/*'" in app
    assert ("This is a photo of me. Send it to MiniMax to make my picture. "
            "tacit doesn't keep the photo.") in app
    assert "photo_consent: true" in app or "body.photo_consent = true" in app
    assert "PHOTO_MAX_PX = 1024" in app and "localStorage.setItem(LAST_ROUTE" in app
    # the photo never reaches storage
    assert app.count("localStorage.setItem") == 1
    assert "personHeader.push" in app and "m.portrait ? portraitPatch" in app
