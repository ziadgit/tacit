import json

from typer.testing import CliRunner

from tacit import cli, gestures
from tacit.config import TEAM_BANDS
from tacit.gesture_record import record, save_examples, user_path
from tacit.testing import make_settings


async def test_record_three_examples_on_the_pretend_band(tmp_path):
    s = make_settings(tacit_band=TEAM_BANDS[0], tacit_data_dir=tmp_path / "data")
    lines = []
    shapes = await record(s, "figure8", sim=True, echo=lines.append, wait_s=8)
    assert len(shapes) == 3
    assert all(len(sh) == gestures.POINTS * len(gestures.AXES) for sh in shapes)
    saved = json.loads(user_path(s).read_text())
    assert len(saved["figure8"]) == 3
    merged = gestures.load_templates(user_path(s))
    builtin = gestures.load_templates(tmp_path / "none.json")
    assert len(merged["figure8"]) == len(builtin["figure8"]) + 3
    assert sum("Draw a figure 8" in line for line in lines) == 3


def test_save_keeps_the_newest(tmp_path):
    p = tmp_path / "g.json"
    one = [0.0] * (gestures.POINTS * len(gestures.AXES))
    for _ in range(4):
        save_examples(p, "x", [one, one, one])
    data = json.loads(p.read_text())
    assert len(data["x"]) == 9
    p.write_text("broken")
    assert len(save_examples(p, "x", [one])["x"]) == 1


def test_cli_checks_name_and_band():
    r = CliRunner().invoke(cli.app, ["gestures", "record", "circle", "--sim"])
    assert r.exit_code == 1 and "x, figure8" in r.output
    r = CliRunner().invoke(cli.app, ["gestures", "record", "x", "--sim"])
    assert r.exit_code == 1 and "TACIT_BAND" in r.output
