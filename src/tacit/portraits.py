"""Profile pictures with MiniMax, kept only as landing-page dot portraits (SPEC §17).

MiniMax makes up to 4 images (always base64, never URLs); each is turned into a 19 x 17 dot
map in memory and the images are dropped. A photo, when given, is passed straight through as a
data URL and is never written to disk, the DB or a log.
"""

from __future__ import annotations

import base64
import binascii
import io
import logging
import re
import statistics
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from PIL import Image
from pydantic import BaseModel

from tacit.auth import current_user, get_settings, get_store
from tacit.config import Settings, require
from tacit.domain import User
from tacit.store import Store

PROMPT_PREFIX = (
    "Head-and-shoulders portrait of one person, centred, facing the viewer, simple flat shapes, "
    "even soft light, plain solid pale lavender background (#E9E4F7), no text, no pattern, "
    "no other people. "
)
MAX_DESCRIPTION = 300
MAX_PROMPT = 1500
MAX_PHOTO_BYTES = 1_500_000
TIMEOUT_S = 60.0

ROWS, COLS = 19, 17
CHARS = frozenset("#.o-+ ")
# Template positions from FACES.maya in landing/landing.js (0-based).
EYE_ROW, EYE_COLS = 7, (5, 11)
MOUTH_ROW, MOUTH_COLS = 10, (7, 8, 9)
CLOTHES_ROWS = 5
BG_DELTA_E = 12.0

_TRY_DIFFERENT = "try different words"
_NOT_SET_UP = "image service isn't set up"
_GENERIC = "couldn't make a picture right now"
_STATUS_MAP: dict[int, tuple[int, str]] = {
    1026: (422, _TRY_DIFFERENT),
    1008: (503, "image credit is used up"),
    1002: (429, "too many picture requests, try again soon"),
    1004: (503, _NOT_SET_UP),
    2049: (503, _NOT_SET_UP),
}
_DATA_URL = re.compile(r"^data:image/[a-zA-Z0-9.+-]+;base64,([A-Za-z0-9+/=\s]+)$")


class PortraitError(Exception):
    """A failure with the HTTP status and plain detail the API should answer."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def build_prompt(description: str) -> str:
    description = " ".join(description.split())
    if not description:
        raise PortraitError(422, "describe how you'd like to look")
    if len(description) > MAX_DESCRIPTION:
        raise PortraitError(422, f"keep it under {MAX_DESCRIPTION} characters")
    return (PROMPT_PREFIX + description)[:MAX_PROMPT]


def decode_photo(data_url: str) -> str:
    """Check a `data:image/...;base64,` URL and return it unchanged. Never stored anywhere."""
    if not isinstance(data_url, str):
        raise PortraitError(422, "that photo couldn't be read")
    if len(data_url) > MAX_PHOTO_BYTES:
        raise PortraitError(413, "that photo is too big")
    m = _DATA_URL.match(data_url)
    if not m:
        raise PortraitError(422, "that photo couldn't be read")
    try:
        raw = base64.b64decode(m.group(1), validate=False)
    except (binascii.Error, ValueError):
        raise PortraitError(422, "that photo couldn't be read") from None
    if not raw:
        raise PortraitError(422, "that photo couldn't be read")
    if len(raw) > MAX_PHOTO_BYTES:
        raise PortraitError(413, "that photo is too big")
    return data_url


class MiniMaxClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._http = http

    async def generate(self, prompt: str, photo_data_url: str | None = None) -> list[bytes]:
        if self._settings.minimax_api_key is None:
            raise PortraitError(503, _NOT_SET_UP)
        key = require(self._settings.minimax_api_key, "MINIMAX_API_KEY")
        body: dict = {
            "model": "image-01",
            "prompt": prompt[:MAX_PROMPT],
            "aspect_ratio": "1:1",
            "response_format": "base64",
            "n": 4,
            "prompt_optimizer": False,
        }
        if photo_data_url is not None:
            body["subject_reference"] = [
                {"type": "character", "image_file": decode_photo(photo_data_url)}
            ]
        url = self._settings.minimax_base_url.rstrip("/") + "/v1/image_generation"
        headers = {"Authorization": f"Bearer {key}"}
        try:
            if self._http is not None:
                resp = await self._http.post(url, json=body, headers=headers, timeout=TIMEOUT_S)
            else:
                async with httpx.AsyncClient(timeout=TIMEOUT_S) as http:
                    resp = await http.post(url, json=body, headers=headers)
        except httpx.HTTPError:
            raise PortraitError(502, _GENERIC) from None
        if resp.status_code != 200:
            raise PortraitError(502, _GENERIC)
        try:
            payload = resp.json()
        except ValueError:
            raise PortraitError(502, _GENERIC) from None
        if not isinstance(payload, dict):
            raise PortraitError(502, _GENERIC)
        code = (payload.get("base_resp") or {}).get("status_code", 0)
        if code != 0:
            raise PortraitError(*_STATUS_MAP.get(code, (502, _GENERIC)))
        items = (payload.get("data") or {}).get("image_base64") or []
        images: list[bytes] = []
        for item in items:
            if not isinstance(item, str):
                continue
            try:
                images.append(base64.b64decode(item, validate=False))
            except (binascii.Error, ValueError):
                continue
        images = [i for i in images if i]
        if not images:
            raise PortraitError(422, _TRY_DIFFERENT)
        return images


# ---- dot conversion ------------------------------------------------------------------------

Lab = tuple[float, float, float]


def _lin(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _f(t: float) -> float:
    return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116


def _lab(rgb: tuple[int, int, int]) -> Lab:
    r, g, b = (_lin(v) for v in rgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
    fx, fy, fz = _f(x), _f(y), _f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def _de(a: Lab, b: Lab) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def _mean(labs: list[Lab]) -> Lab:
    n = len(labs)
    return (sum(p[0] for p in labs) / n, sum(p[1] for p in labs) / n, sum(p[2] for p in labs) / n)


def _is_skin(p: Lab) -> bool:
    lum, a, b = p
    return 20 < lum < 97 and a > 2 and b > 6 and b > a * 0.5


def _two_means(values: list[float]) -> float:
    """Split 1-D values into two clusters; return the threshold between them."""
    lo, hi = min(values), max(values)
    t = (lo + hi) / 2
    for _ in range(20):
        dark = [v for v in values if v <= t]
        light = [v for v in values if v > t]
        if not dark or not light:
            break
        nt = (sum(dark) / len(dark) + sum(light) / len(light)) / 2
        if abs(nt - t) < 0.01:
            break
        t = nt
    return t


def to_dot_map(png_bytes: bytes) -> list[str]:
    """Turn a portrait image into a FACES-style dot map: 19 strings of 17 chars of `#.o-+ `."""
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    w, h = img.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    img = img.crop((left, top, left + side, top + side))

    # Corner median: the background colour. The bottom corners are usually shoulders in a
    # head-and-shoulders picture, so sample the top corners and the upper side edges.
    k = max(1, side // 20)
    mid = side // 3
    raw = b"".join(
        img.crop((x0, y0, x0 + k, y0 + k)).tobytes()
        for x0, y0 in ((0, 0), (side - k, 0), (0, mid), (side - k, mid))
    )
    bg = _lab(
        (
            int(statistics.median(raw[0::3])),
            int(statistics.median(raw[1::3])),
            int(statistics.median(raw[2::3])),
        )
    )

    # Each cell is a 4 x 4 block of a small resize; a cell is figure if most of its pixels are.
    sub = 4
    small = img.resize((COLS * sub, ROWS * sub), Image.Resampling.BOX)
    px = small.load()
    cells: list[list[Lab | None]] = []
    for r in range(ROWS):
        row: list[Lab | None] = []
        for c in range(COLS):
            fg: list[Lab] = []
            for dy in range(sub):
                for dx in range(sub):
                    p = _lab(px[c * sub + dx, r * sub + dy])
                    if _de(p, bg) > BG_DELTA_E:
                        fg.append(p)
            row.append(_mean(fg) if len(fg) * 2 > sub * sub else None)
        cells.append(row)

    grid = [[" "] * COLS for _ in range(ROWS)]
    upper = ROWS - CLOTHES_ROWS
    up_cells = [(r, c, cells[r][c]) for r in range(upper) for c in range(COLS) if cells[r][c]]

    face_cells: list[Lab] = []
    if up_cells:
        lums = [p[0] for _, _, p in up_cells]
        t = _two_means(lums)
        dark = [v for v in lums if v <= t]
        light = [v for v in lums if v > t]
        split = bool(dark and light) and (sum(light) / len(light) - sum(dark) / len(dark)) > 15
        for r, c, p in up_cells:
            is_face = (p[0] > t if split else True) and (_is_skin(p) or not split)
            grid[r][c] = "." if is_face else "#"
            if is_face:
                face_cells.append(p)
        # Dark marks inside the face (drawn eyes, brows, mouth) are face, not hair.
        for r in range(upper):
            dots = [c for c in range(COLS) if grid[r][c] == "."]
            if len(dots) >= 2:
                for c in range(dots[0] + 1, dots[-1]):
                    if grid[r][c] == "#":
                        grid[r][c] = "."

    face_ref = _mean(face_cells) if face_cells else None
    for r in range(upper, ROWS):
        for c in range(COLS):
            p = cells[r][c]
            if p is None:
                continue
            near_face = face_ref is not None and _is_skin(p) and _de(p, face_ref) < 15
            grid[r][c] = "." if near_face else "+"

    for c in EYE_COLS:
        if grid[EYE_ROW][c] == ".":
            grid[EYE_ROW][c] = "o"
    for c in MOUTH_COLS:
        if grid[MOUTH_ROW][c] == ".":
            grid[MOUTH_ROW][c] = "-"
    return ["".join(row) for row in grid]


def valid_map(m: object) -> bool:
    return (
        isinstance(m, list)
        and len(m) == ROWS
        and all(isinstance(s, str) and len(s) == COLS and set(s) <= CHARS for s in m)
    )


# ---- API (SPEC §17) ------------------------------------------------------------------------

log = logging.getLogger("tacit.portraits")
router = APIRouter()


class PortraitIn(BaseModel):
    mode: Literal["words", "photo"] = "words"
    description: str | None = None
    photo: str | None = None          # a data URL; never stored, never logged
    photo_consent: bool = False       # "This is a photo of me. Send it to MiniMax..."


class PortraitPut(BaseModel):
    map: list[str]
    source: Literal["words", "photo"] = "words"


def make_portraits(settings: Settings) -> MiniMaxClient | None:
    return MiniMaxClient(settings) if settings.minimax_api_key is not None else None


@router.post("/api/portrait")
async def make_portrait(body: PortraitIn, request: Request,
                        user: Annotated[User, Depends(current_user)],
                        store: Annotated[Store, Depends(get_store)],
                        settings: Annotated[Settings, Depends(get_settings)]
                        ) -> dict[str, list[list[str]]]:
    client = getattr(request.app.state, "portraits", None)
    if client is None:
        raise HTTPException(503, _NOT_SET_UP)
    photo: str | None = None
    try:
        if body.mode == "photo":
            if not body.photo_consent:
                raise PortraitError(403, "tick \"This is a photo of me\" first")
            photo = decode_photo(body.photo or "")
            prompt = build_prompt(body.description or "as in the photo")
        else:
            prompt = build_prompt(body.description or "")
    except PortraitError as e:
        raise HTTPException(e.status, e.detail) from None
    if not store.allow(user.id, "portrait", settings.portraits_per_user_per_day):
        raise HTTPException(429, "that's enough pictures for today")
    try:
        images = await client.generate(prompt, photo)
    except PortraitError as e:
        log.warning("minimax: %s", e.status)
        raise HTTPException(e.status, e.detail) from None
    finally:
        photo = None  # dropped once the request ends
        body.photo = None
    candidates = []
    for img in images[:4]:
        try:
            candidates.append(to_dot_map(img))
        except Exception:  # noqa: BLE001 - an unreadable image is just one candidate fewer
            continue
    images.clear()
    if not candidates:
        raise HTTPException(422, _TRY_DIFFERENT)
    log.info("portrait: %d candidates (%s)", len(candidates), body.mode)
    return {"candidates": candidates}


@router.put("/api/portrait")
def keep_portrait(body: PortraitPut, user: Annotated[User, Depends(current_user)],
                  store: Annotated[Store, Depends(get_store)]) -> dict[str, object]:
    if not valid_map(body.map):
        raise HTTPException(422, "a picture is 19 rows of 17 dots")
    store.update_user(user.id, portrait=body.map, portrait_source=body.source)
    return {"portrait": body.map, "portrait_source": body.source}


@router.delete("/api/portrait", status_code=204)
def delete_portrait(user: Annotated[User, Depends(current_user)],
                    store: Annotated[Store, Depends(get_store)]) -> Response:
    store.update_user(user.id, portrait=None, portrait_source=None)
    return Response(status_code=204)
