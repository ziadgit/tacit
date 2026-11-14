"""`tacit gestures record x|figure8 [--sim]` (SPEC §13.2): the wearer's own examples.

Three examples of the gesture are cut out of the motion stream with the recogniser's
`Segmenter`, turned into shapes with `to_shape`, and saved to `data/gestures.json`, where the
bridge uses them alongside the built-in templates. With `--sim` the pretend band draws the
gesture itself (the same synthetic path as scripts/make_gesture_templates.py).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import gestures
from .config import Settings, require_band

EXAMPLES = 3
WAIT_S = 10.0
KEEP_PER_GESTURE = 9   # the newest examples kept per gesture
ROOT = Path(__file__).resolve().parents[2]


def user_path(settings: Settings) -> Path:
    return settings.tacit_data_dir / "gestures.json"


def save_examples(path: Path, name: str, shapes: list[gestures.Shape]) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    old = [s for s in data.get(name, []) if isinstance(s, list)]
    data[name] = (old + [[round(v, 4) for v in s] for s in shapes])[-KEEP_PER_GESTURE:]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)
    return data


def _synthetic(name: str, seconds: float) -> list[dict[str, float]]:
    spec = importlib.util.spec_from_file_location(
        "make_gesture_templates", ROOT / "scripts" / "make_gesture_templates.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("scripts/make_gesture_templates.py is missing")
    mk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mk)
    return [{k: v for k, v in s.items() if k != "t"} for s in mk.samples(name, seconds)]


async def record(settings: Settings, name: str, *, sim: bool,
                 echo: Callable[[str], None] = print, band: Any = None,
                 count: int = EXAMPLES, wait_s: float = WAIT_S) -> list[gestures.Shape]:
    if name not in gestures.GESTURES:
        raise ValueError(f"the gestures are {', '.join(gestures.GESTURES)}")
    number = require_band(settings)
    own = band is None
    if own:
        from .band import use_kit

        use_kit()
        from vexo_open import Band

        band = await (Band.connect(number, transport="sim") if sim else Band.connect(number))
    if band.number != number:
        raise RuntimeError("connected to the wrong band")
    seg = gestures.Segmenter()
    found: asyncio.Queue = asyncio.Queue()

    def on_motion(m: Any) -> None:
        g = seg.feed(m, now=getattr(m, "t", None))
        if g is not None:
            found.put_nowait(g)

    band.on("motion", on_motion)
    shapes: list[gestures.Shape] = []
    try:
        await band.set_motion(accel_range=8, gyro_range=1000)
        await band.configure(motion=100, sensors="both")
        word = "an X" if name == "x" else "a figure 8"
        while len(shapes) < count:
            echo(f"Draw {word} in the air now ({len(shapes) + 1} of {count}), then hold still.")
            if sim:
                band.transport.play_motion(_synthetic(name, 1.0 + 0.2 * len(shapes)))
            try:
                g = await asyncio.wait_for(found.get(), wait_s)
            except TimeoutError:
                echo("Nothing seen. Try again, a bit bigger.")
                continue
            shapes.append(gestures.to_shape(g))
            echo("Got it.")
    finally:
        band.off("motion", on_motion)
        if own:
            await band.disconnect()
    save_examples(user_path(settings), name, shapes)
    echo(f"Saved {len(shapes)} examples of {name} to {user_path(settings)}.")
    return shapes
