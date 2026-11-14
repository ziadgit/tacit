from datetime import timedelta

from fastapi.testclient import TestClient

from tacit.app import create_app
from tacit.bridge_api import token_hash
from tacit.domain import Moment, now
from tacit.store import Store
from tacit.testing import make_settings, onboard


def setup(tmp_path):
    store = Store(tmp_path / "t.db")
    s = make_settings(public_base_url="https://tacit.example")
    app = create_app(s, store=store)
    pwa = TestClient(app, base_url="https://tacit.example")
    me = onboard(pwa)
    bridge = TestClient(app, base_url="https://tacit.example")
    return store, app, pwa, bridge, me["id"]


def paired(tmp_path, band=74):
    store, app, pwa, bridge, uid = setup(tmp_path)
    r = pwa.post("/api/band/pair", json={"band": band})
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    bridge.headers["authorization"] = f"Bearer {token}"
    return store, app, pwa, bridge, uid, token


def test_pairing_team_bands_only_and_token_once(tmp_path):
    store, app, pwa, bridge, uid = setup(tmp_path)
    assert pwa.post("/api/band/pair", json={"band": 42}).status_code == 422
    assert pwa.post("/api/band/pair", json={"band": 7}).status_code == 422
    r = pwa.post("/api/band/pair", json={"band": 16})
    out = r.json()
    token = out["token"]
    assert out["env"][0] == f"TACIT_BRIDGE_TOKEN={token}"
    assert out["env"][1] == "TACIT_SERVER_URL=https://tacit.example"
    dev = store.device_for_user(uid)
    assert dev.band == 16 and dev.token_sha256 == token_hash(token)
    assert token.encode() not in (tmp_path / "t.db").read_bytes()
    band = pwa.get("/api/band").json()
    assert band["band"]["band"] == 16 and "token" not in band["band"]
    assert band["bands"] == [16, 74]
    # another person can't take band 16
    other = TestClient(app, base_url="https://tacit.example")
    onboard(other, phone="+14155550101", name="Ana")
    assert other.post("/api/band/pair", json={"band": 16}).status_code == 409
    # re-pairing replaces the token
    r2 = pwa.post("/api/band/pair", json={"band": 74})
    assert store.device_by_token(token_hash(token)) is None
    assert store.device_for_user(uid).band == 74 and r2.json()["token"] != token
    assert store.device_by_band(16) is None


def test_bridge_needs_token(tmp_path):
    store, app, pwa, bridge, uid, token = paired(tmp_path)
    anon = TestClient(app)
    assert anon.get("/api/bridge/commands").status_code == 401
    assert anon.get("/api/bridge/commands",
                    headers={"authorization": "Bearer nope"}).status_code == 401
    assert bridge.get("/api/bridge/commands").status_code == 200


def test_state_and_listening(tmp_path):
    store, app, pwa, bridge, uid, token = paired(tmp_path)
    assert pwa.get("/api/band").json()["band"]["listening"] is False
    bridge.post("/api/bridge/state", json={"connected": True, "listening": True, "muted": False,
                                           "battery": 80, "buffer_mb": 0})
    b = pwa.get("/api/band").json()["band"]
    assert b["listening"] is True and b["battery"] == 80 and b["online"] is True
    bridge.post("/api/bridge/state", json={"connected": True, "listening": False, "muted": True})
    b = pwa.get("/api/band").json()["band"]
    assert b["listening"] is False and b["muted"] is True


def test_pwa_mute_command_reaches_bridge(tmp_path):
    store, app, pwa, bridge, uid, token = paired(tmp_path)
    assert bridge.get("/api/bridge/commands").json() == {"muted": False, "changed": False}
    pwa.post("/api/band/mute", json={"muted": True})
    # a state report from before the poll doesn't undo the waiting command
    bridge.post("/api/bridge/state", json={"connected": True, "listening": True, "muted": False})
    assert bridge.get("/api/bridge/commands").json() == {"muted": True, "changed": True}
    assert bridge.get("/api/bridge/commands").json() == {"muted": True, "changed": False}
    bridge.post("/api/bridge/state", json={"connected": True, "muted": True})
    pwa.post("/api/band/mute", json={"muted": False})
    assert bridge.get("/api/bridge/commands").json() == {"muted": False, "changed": True}


def test_gesture_mute_on_the_bridge_is_the_truth(tmp_path):
    store, app, pwa, bridge, uid, token = paired(tmp_path)
    bridge.post("/api/bridge/state", json={"connected": True, "muted": True})
    assert pwa.get("/api/band").json()["band"]["muted"] is True
    assert bridge.get("/api/bridge/commands").json() == {"muted": True, "changed": False}


def test_mute_without_band_404(tmp_path):
    store, app, pwa, bridge, uid = setup(tmp_path)
    assert pwa.post("/api/band/mute", json={"muted": True}).status_code == 404


def test_segments_and_rewind(tmp_path):
    store, app, pwa, bridge, uid, token = paired(tmp_path)
    t = now()
    segs = [
        {"started_at": (t - timedelta(seconds=120)).isoformat(),
         "ended_at": (t - timedelta(seconds=110)).isoformat(), "speaker": 0,
         "text": "old words", "level": 20},
        {"started_at": (t - timedelta(seconds=8)).timestamp(),
         "ended_at": (t - timedelta(seconds=5)).timestamp(), "speaker": 1,
         "text": "  secret   words  ", "level": 30},
        {"started_at": t.isoformat(), "ended_at": t.isoformat(), "text": "   "},
    ]
    assert bridge.post("/api/bridge/segments", json={"segments": segs}).json() == {"stored": 2}
    dev = store.device_for_user(uid)
    texts = [s.text for s in store.segments(dev.id)]
    assert texts == ["old words", "secret words"]
    recent = store.segments(dev.id)[1]
    m_only = store.add_moment(Moment(user_id=uid, kind="idea", started_at=t, ended_at=t,
                                     segment_ids=[recent.id]))
    m_mixed = store.add_moment(Moment(user_id=uid, kind="idea", started_at=t, ended_at=t,
                                      segment_ids=[recent.id, store.segments(dev.id)[0].id]))
    r = bridge.post("/api/bridge/rewind", json={"seconds": 15})
    assert r.json() == {"segments": 1, "moments": 1}
    assert [s.text for s in store.segments(dev.id)] == ["old words"]
    assert store.get_moment(m_only.id) is None and store.get_moment(m_mixed.id) is not None


def test_motion_moments_and_kinds_off(tmp_path):
    store, app, pwa, bridge, uid, token = paired(tmp_path)
    kept = []
    app.state.on_kept = lambda dev, m: kept.append(m)
    pwa.patch("/api/me", json={"kinds_off": ["typing"]})
    t = now()
    body = {"moments": [
        {"kind": "drawing", "started_at": (t - timedelta(minutes=25)).isoformat(),
         "ended_at": t.isoformat(), "confidence": 0.8},
        {"kind": "typing", "started_at": t.isoformat(), "ended_at": t.isoformat()},
        {"kind": "advice_given", "started_at": t.isoformat(), "ended_at": t.isoformat()},
        {"kind": "kept", "started_at": t.isoformat(), "ended_at": t.isoformat()},
    ]}
    assert bridge.post("/api/bridge/moments", json=body).json() == {"stored": 2}
    kinds = sorted(m.kind for m in store.moments_for(uid))
    assert kinds == ["drawing", "kept"]
    k = store.moments_for(uid, kind="kept")[0]
    assert (k.ended_at - k.started_at).total_seconds() == 60
    assert kept and kept[0].id == k.id


def test_delete_everything_removes_device(tmp_path):
    store, app, pwa, bridge, uid, token = paired(tmp_path)
    bridge.post("/api/bridge/segments", json={"segments": [
        {"started_at": now().isoformat(), "ended_at": now().isoformat(), "text": "hi"}]})
    pwa.delete("/api/me")
    assert store.device_by_token(token_hash(token)) is None
    assert bridge.get("/api/bridge/commands").status_code == 401
