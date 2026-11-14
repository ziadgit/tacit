import base64
import io
import json

import httpx
import pytest
import respx
from PIL import Image, ImageDraw

from tacit.config import Settings
from tacit.portraits import (
    PROMPT_PREFIX,
    MiniMaxClient,
    PortraitError,
    build_prompt,
    decode_photo,
    to_dot_map,
    valid_map,
)

URL = "https://api.minimax.io/v1/image_generation"

# FACES.maya from landing/landing.js.
MAYA = [
    "     #######     ",
    "   ###########   ",
    "  #############  ",
    " ############### ",
    " ####.......#### ",
    " ###.........### ",
    " ##...........## ",
    " ##..o.....o..## ",
    " ##...........## ",
    " ##...........## ",
    " ###...---...### ",
    " ###.........### ",
    " ####.......#### ",
    "  ####.....####  ",
    "  ### ..... ###  ",
    "   ## +...+ ##   ",
    "  +++++...+++++  ",
    " +++++++++++++++ ",
    "+++++++++++++++++",
]

LAVENDER = (0xE9, 0xE4, 0xF7)
HAIR = (0x2A, 0x1E, 0x1A)
SKIN = (0xE8, 0xB8, 0x8C)
CLOTHES = (0x5C, 0x8F, 0xC8)
EYE = (0x20, 0x18, 0x18)
LIP = (0xC0, 0x60, 0x7A)


def _png(color=(10, 20, 30), size=(8, 8)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _figure(side: int = 323) -> bytes:
    """Paint MAYA cell by cell: dark hair on top, skin face, light-blue clothes, lavender ground."""
    img = Image.new("RGB", (side, side), LAVENDER)
    d = ImageDraw.Draw(img)
    cw, ch = side / 17, side / 19
    for r, row in enumerate(MAYA):
        for c, k in enumerate(row):
            color = {"#": HAIR, ".": SKIN, "o": EYE, "-": LIP, "+": CLOTHES}.get(k)
            if r >= 14 and k == "#":
                color = CLOTHES  # below the face, the figure's dark parts are clothes
            if color:
                box = (round(c * cw), round(r * ch), round((c + 1) * cw) - 1,
                       round((r + 1) * ch) - 1)
                d.rectangle(box, fill=color)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _ok(images: list[bytes], failed: int = 0) -> dict:
    return {
        "data": {"image_base64": [base64.b64encode(i).decode() for i in images]},
        "metadata": {"failed_count": str(failed), "success_count": str(len(images))},
        "base_resp": {"status_code": 0, "status_msg": "success"},
    }


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, minimax_api_key="test")


# ---- MiniMax client --------------------------------------------------------------------


@respx.mock
async def test_generate_words_request_and_decode(settings):
    pngs = [_png((i * 40, 0, 0)) for i in range(4)]
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=_ok(pngs)))
    out = await MiniMaxClient(settings).generate(build_prompt("short dark hair, green jumper"))
    assert out == pngs
    req = route.calls.last.request
    assert req.headers["authorization"] == "Bearer test"
    assert json.loads(req.content) == {
        "model": "image-01",
        "prompt": PROMPT_PREFIX + "short dark hair, green jumper",
        "aspect_ratio": "1:1",
        "response_format": "base64",
        "n": 4,
        "prompt_optimizer": False,
    }


@respx.mock
async def test_generate_photo_adds_subject_reference(settings):
    photo = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8fakejpeg").decode()
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=_ok([_png()] * 4)))
    async with httpx.AsyncClient() as http:
        out = await MiniMaxClient(settings, http).generate("p", photo)
    assert len(out) == 4
    body = json.loads(route.calls.last.request.content)
    assert body["subject_reference"] == [{"type": "character", "image_file": photo}]
    assert body["response_format"] == "base64"


@respx.mock
async def test_generate_fewer_candidates_ok(settings):
    respx.post(URL).mock(return_value=httpx.Response(200, json=_ok([_png()] * 2, failed=2)))
    assert len(await MiniMaxClient(settings).generate("p")) == 2


@respx.mock
async def test_generate_zero_images_is_try_different_words(settings):
    respx.post(URL).mock(return_value=httpx.Response(200, json=_ok([], failed=4)))
    with pytest.raises(PortraitError) as e:
        await MiniMaxClient(settings).generate("p")
    assert (e.value.status, e.value.detail) == (422, "try different words")


@pytest.mark.parametrize(
    ("code", "status", "detail"),
    [
        (1026, 422, "try different words"),
        (1008, 503, "image credit is used up"),
        (1002, 429, "too many picture requests, try again soon"),
        (1004, 503, "image service isn't set up"),
        (2049, 503, "image service isn't set up"),
        (1000, 502, "couldn't make a picture right now"),
    ],
)
@respx.mock
async def test_generate_error_codes(settings, code, status, detail):
    body = {"data": None, "base_resp": {"status_code": code, "status_msg": "x"}}
    respx.post(URL).mock(return_value=httpx.Response(200, json=body))
    with pytest.raises(PortraitError) as e:
        await MiniMaxClient(settings).generate("p")
    assert (e.value.status, e.value.detail) == (status, detail)
    assert "test" not in str(e.value)


@respx.mock
async def test_generate_http_error_is_502(settings):
    respx.post(URL).mock(return_value=httpx.Response(500, text="boom"))
    with pytest.raises(PortraitError) as e:
        await MiniMaxClient(settings).generate("p")
    assert e.value.status == 502


@respx.mock
async def test_generate_timeout_is_502(settings):
    respx.post(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(PortraitError) as e:
        await MiniMaxClient(settings).generate("p")
    assert (e.value.status, e.value.detail) == (502, "couldn't make a picture right now")


async def test_generate_without_key_is_not_set_up():
    with pytest.raises(PortraitError) as e:
        await MiniMaxClient(Settings(_env_file=None)).generate("p")
    assert e.value.status == 503


# ---- dot conversion --------------------------------------------------------------------


def test_to_dot_map_figure():
    m = to_dot_map(_figure())
    assert valid_map(m)
    assert len(m) == 19 and all(len(r) == 17 for r in m)
    assert set("".join(m)) <= set("#.o-+ ")
    # Above the clothes rows the figure comes back exactly as FACES.maya.
    assert m[:14] == MAYA[:14]
    assert m[7][5] == "o" and m[7][11] == "o"
    assert m[10][7:10] == "---"
    assert m[7].count("o") == 2 and "".join(m).count("-") == 3
    # Bottom rows: clothes are '+', the neck stays face.
    for r in range(14, 19):
        for c in range(17):
            want = MAYA[r][c]
            if want == " ":
                assert m[r][c] == " "
            elif want == ".":
                assert m[r][c] == "."
            else:
                assert m[r][c] == "+"


def test_to_dot_map_background_is_spaces_and_crop():
    blank = _png(LAVENDER, (300, 200))  # not square: centre-cropped
    assert to_dot_map(blank) == [" " * 17] * 19


def test_to_dot_map_eyes_only_on_face():
    # A figure with no face (all hair) gets no eyes or mouth.
    m = to_dot_map(_png(HAIR, (100, 100)))
    assert valid_map(m)
    assert "o" not in "".join(m) and "-" not in "".join(m)


def test_valid_map():
    assert valid_map(MAYA)
    assert not valid_map(MAYA[:18])
    assert not valid_map([r + " " for r in MAYA])
    assert not valid_map(["x" * 17] * 19)
    assert not valid_map("#" * 323)
    assert not valid_map(None)


# ---- prompt and photo ------------------------------------------------------------------


def test_build_prompt():
    assert PROMPT_PREFIX.startswith("Head-and-shoulders portrait of one person, centred,")
    assert PROMPT_PREFIX.endswith("no text, no pattern, no other people. ")
    assert build_prompt("  curly red hair ") == PROMPT_PREFIX + "curly red hair"
    assert len(build_prompt("a" * 300)) <= 1500
    with pytest.raises(PortraitError) as e:
        build_prompt("a" * 301)
    assert e.value.status == 422
    with pytest.raises(PortraitError):
        build_prompt("   ")


def test_decode_photo():
    ok = "data:image/png;base64," + base64.b64encode(_png()).decode()
    assert decode_photo(ok) == ok
    big = "data:image/jpeg;base64," + "A" * 1_600_000
    with pytest.raises(PortraitError) as e:
        decode_photo(big)
    assert (e.value.status, e.value.detail) == (413, "that photo is too big")
    for bad in ("https://example.com/me.jpg", "data:text/plain;base64,aGk=", "data:image/png,xx"):
        with pytest.raises(PortraitError) as e:
            decode_photo(bad)
        assert e.value.status == 422


# ---- API -------------------------------------------------------------------------------------


class FakeMiniMax:
    def __init__(self, images=None, error=None):
        self.calls = []
        self.images = images
        self.error = error

    async def generate(self, prompt, photo_data_url=None):
        self.calls.append((prompt, photo_data_url))
        if self.error:
            raise self.error
        return list(self.images)


def figure_png() -> bytes:
    img = Image.new("RGB", (170, 190), (0xE9, 0xE4, 0xF7))
    d = ImageDraw.Draw(img)
    d.rectangle((40, 10, 130, 60), fill=(40, 30, 30))
    d.rectangle((40, 50, 130, 130), fill=(240, 200, 160))
    d.rectangle((0, 140, 170, 190), fill=(250, 250, 250))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def api_client(tmp_path, fake, **kw):
    from tacit.testing import client, make_settings, onboard

    c = client(tmp_path, make_settings(**kw), portraits=fake)
    onboard(c)
    return c


def test_api_words_returns_candidates_and_keeps_nothing(tmp_path):
    fake = FakeMiniMax(images=[figure_png(), figure_png(), b"not an image"])
    c = api_client(tmp_path, fake)
    assert c.get("/api/config").json()["portraits_enabled"] is True
    r = c.post("/api/portrait", json={"mode": "words", "description": "short curly hair"})
    assert r.status_code == 200, r.text
    cands = r.json()["candidates"]
    assert len(cands) == 2 and all(valid_map(m) for m in cands)
    assert fake.calls[0] == (PROMPT_PREFIX + "short curly hair", None)
    assert c.get("/api/me").json()["portrait"] is None  # nothing kept until PUT


def test_api_photo_needs_consent(tmp_path):
    fake = FakeMiniMax(images=[figure_png()])
    c = api_client(tmp_path, fake)
    photo = "data:image/jpeg;base64," + base64.b64encode(b"jpegbytes").decode()
    r = c.post("/api/portrait", json={"mode": "photo", "photo": photo})
    assert r.status_code == 403 and fake.calls == []
    r = c.post("/api/portrait", json={"mode": "photo", "photo": photo, "photo_consent": True})
    assert r.status_code == 200
    assert fake.calls[0][1] == photo
    big = "data:image/jpeg;base64," + "A" * 1_600_000
    r = c.post("/api/portrait", json={"mode": "photo", "photo": big, "photo_consent": True})
    assert r.status_code == 413


def test_api_photo_is_never_stored_or_logged(tmp_path, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    fake = FakeMiniMax(images=[figure_png()])
    c = api_client(tmp_path, fake)
    marker = base64.b64encode(b"UNIQUE-PHOTO-MARKER-123").decode()
    photo = "data:image/png;base64," + marker
    c.post("/api/portrait", json={"mode": "photo", "photo": photo, "photo_consent": True})
    assert marker not in caplog.text
    db = (tmp_path / "t.db").read_bytes()
    assert marker.encode() not in db
    for p in tmp_path.rglob("*"):
        if p.is_file():
            assert marker.encode() not in p.read_bytes()


def test_api_rate_limit_and_errors(tmp_path):
    fake = FakeMiniMax(images=[figure_png()])
    c = api_client(tmp_path, fake, portraits_per_user_per_day=2)
    assert c.post("/api/portrait", json={"description": ""}).status_code == 422
    assert c.post("/api/portrait", json={"description": "a"}).status_code == 200
    fake.error = PortraitError(503, "image credit is used up")
    r = c.post("/api/portrait", json={"description": "a"})
    assert r.status_code == 503 and r.json()["detail"] == "image credit is used up"
    assert c.post("/api/portrait", json={"description": "a"}).status_code == 429


def test_api_put_and_delete(tmp_path):
    c = api_client(tmp_path, FakeMiniMax(images=[]))
    assert c.put("/api/portrait", json={"map": ["x" * 17] * 19}).status_code == 422
    assert c.put("/api/portrait", json={"map": MAYA[:18]}).status_code == 422
    r = c.put("/api/portrait", json={"map": MAYA, "source": "photo"})
    assert r.status_code == 200
    me = c.get("/api/me").json()
    assert me["portrait"] == MAYA and me["portrait_source"] == "photo"
    assert c.get(f"/api/people/{me['id']}").json()["portrait"] == MAYA
    assert c.delete("/api/portrait").status_code == 204
    assert c.get("/api/me").json()["portrait"] is None


def test_api_not_set_up(tmp_path):
    from tacit.testing import client, onboard

    c = client(tmp_path)
    onboard(c)
    assert c.post("/api/portrait", json={"description": "a"}).status_code == 503
