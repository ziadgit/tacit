from datetime import timedelta
from types import SimpleNamespace

from tacit import scenarios as sc
from tacit.domain import BridgeDevice, Moment, Segment, Skill, User, now
from tacit.store import Store
from tacit.testing import make_settings


class FakeJev:
    def __init__(self, probs=None, giver="wearer", fail=False):
        self.probs = probs or {}
        self.giver = giver
        self.fail = fail
        self.calls = []

    async def system_one(self, *, state, questions):
        self.calls.append((state, questions))
        if self.fail:
            raise TimeoutError
        return SimpleNamespace(
            nouls={k: SimpleNamespace(noul=self.probs.get(k, 0.05)) for k in sc.JEV_KINDS},
            choices={"giver": SimpleNamespace(choice=self.giver)})


ADVICE = {"title": "Open an update with the number", "verdict": "Lead with the number.",
          "reason": "People remember the number.", "quote": "they remember forty percent",
          "giver": "wearer", "steps": []}


class FakeLLM:
    def __init__(self, answers=None):
        self.answers = answers or {}
        self.calls = []

    async def extract(self, text, *, name, schema, instructions):
        self.calls.append((name, text))
        return dict(self.answers.get(name, {}))


def world(tmp_path, jev=None, llm=None, **kw):
    store = Store(tmp_path / "t.db")
    user = store.add_user(User(name="Maya Lin", phone="+14155550100", consent_lookup=False,
                               consent_call=False))
    dev = store.add_device(BridgeDevice(user_id=user.id, band=74, token_sha256="x"))
    pipe = sc.Scenarios(store, make_settings(**kw), jev=jev, llm=llm)
    return store, user, dev, pipe


def seg(store, dev, ago_s, dur_s, speaker, text, level=None):
    t = now() - timedelta(seconds=ago_s)
    return store.add_segment(Segment(device_id=dev.id, user_id=dev.user_id, started_at=t,
                                     ended_at=t + timedelta(seconds=dur_s), speaker=speaker,
                                     text=text, level=level))


def test_wearer_by_level():
    def s(spk, lvl):
        t = now()
        return Segment(device_id="d", user_id="u", started_at=t, ended_at=t, speaker=spk,
                       text="x", level=lvl)
    assert sc.wearer_speaker([s(0, 15), s(0, 17), s(1, 30), s(1, 28)]) == 0
    assert sc.wearer_speaker([s(0, 25), s(1, 28)]) is None        # under 6 dB apart
    assert sc.wearer_speaker([s(0, 15)]) is None
    lines = sc.window_lines([s(0, 15), s(1, 30)], 0)
    assert lines.splitlines() == ["S0 (likely wearer): x", "S1: x"]


def test_quote_check_and_jaccard():
    t = now()
    segs = [Segment(device_id="d", user_id="u", started_at=t, ended_at=t, speaker=0,
                    text="People forget the story.  They REMEMBER forty percent.")]
    assert sc.quote_ok("they remember   forty percent", segs) == "they remember forty percent"
    assert sc.quote_ok("they remember fifty percent", segs) is None
    assert sc.quote_ok(None, segs) is None
    assert sc.jaccard("Open an update with the number", "open the update with a number") >= 0.4


def test_due_rules(tmp_path):
    store, user, dev, pipe = world(tmp_path)
    assert pipe.due(dev) is None
    seg(store, dev, 30, 5, 0, "short and recent")         # 25 s of silence after it
    assert [s.text for s in pipe.due(dev)] == ["short and recent"]
    store2, user2, dev2, pipe2 = world(tmp_path / "b")
    seg(store2, dev2, 5, 3, 0, "still talking")
    assert pipe2.due(dev2) is None                        # not 90 s, not 20 s of silence
    seg(store2, dev2, 120, 3, 0, "long ago")
    assert pipe2.due(dev2) is not None                    # 90 s of new speech


async def test_no_jev_no_detections(tmp_path):
    store, user, dev, pipe = world(tmp_path, jev=None, llm=FakeLLM({"advice": ADVICE}))
    seg(store, dev, 60, 5, 0, "Open the update with the number.", 15)
    seg(store, dev, 50, 5, 1, "ok", 30)
    out = await pipe.maybe_run(dev)
    assert [m.kind for m in out] == ["conversation"]
    assert pipe.llm.calls == []
    jev = FakeJev(fail=True)
    store2, user2, dev2, pipe2 = world(tmp_path / "b", jev=jev, llm=FakeLLM())
    seg(store2, dev2, 60, 5, 0, "words", 15)
    assert await pipe2.maybe_run(dev2) == []


async def test_advice_given_and_received(tmp_path):
    jev = FakeJev({"advice": 0.9, "idea": 0.4}, giver="both")
    llm = FakeLLM({"advice": ADVICE})
    store, user, dev, pipe = world(tmp_path, jev=jev, llm=llm)
    seg(store, dev, 60, 5, 0, "Open the update with the number:", 15)
    seg(store, dev, 50, 5, 1, "Why?", 30)
    seg(store, dev, 40, 5, 0, "They forget the story, they remember forty percent.", 16)
    out = await pipe.maybe_run(dev)
    kinds = sorted(m.kind for m in out)
    assert kinds == ["advice_given", "advice_received", "conversation"]
    given = next(m for m in out if m.kind == "advice_given")
    received = next(m for m in out if m.kind == "advice_received")
    assert given.body["quote"] == "they remember forty percent"
    assert received.body["quote"] is None                 # never a bystander's words
    assert given.confidence == 0.9 and given.title == ADVICE["title"]
    state, questions = jev.calls[0]
    assert state["wearer"] == "S0" and "S0 (likely wearer): Open" in state["window"]
    assert set(questions) == {*sc.JEV_KINDS, "giver"}
    assert [n for n, _ in llm.calls] == ["advice"]        # idea under the threshold
    assert all(s.windowed for s in store.segments(dev.id))


async def test_invented_quote_is_dropped_and_dedup(tmp_path):
    jev = FakeJev({"advice": 0.8}, giver="wearer")
    llm = FakeLLM({"advice": {**ADVICE, "quote": "words nobody said"}})
    store, user, dev, pipe = world(tmp_path, jev=jev, llm=llm)
    seg(store, dev, 300, 5, 0, "Open the update with the number.", 15)
    first = await pipe.maybe_run(dev)
    m = next(x for x in first if x.kind == "advice_given")
    assert m.body["quote"] is None
    llm.answers["advice"] = {**ADVICE, "title": "Open the update with the number"}
    seg(store, dev, 60, 5, 0, "Again: open the update with the number.", 15)
    second = await pipe.maybe_run(dev)
    again = next(x for x in second if x.kind == "advice_given")
    assert again.id == m.id                               # merged into the earlier moment
    assert len(store.moments_for(user.id, kind="advice_given")) == 1


async def test_stop_request_sets_mute_and_rewinds(tmp_path):
    jev = FakeJev({"stop_request": 0.95, "advice": 0.9})
    store, user, dev, pipe = world(tmp_path, jev=jev, llm=FakeLLM({"advice": ADVICE}))
    seg(store, dev, 50, 5, 1, "Hey, can you not keep this?")
    out = await pipe.maybe_run(dev)
    assert out == []
    d = store.device_for_user(user.id)
    assert d.muted is True and d.last_state["pending"] is True
    assert store.segments(dev.id) == []                   # rewound 60 s
    assert store.moments_for(user.id) == []


async def test_demonstration_while_drawing_and_kinds_off(tmp_path):
    jev = FakeJev({"explanation": 0.9, "commitment": 0.9}, giver="wearer")
    llm = FakeLLM({"demonstration": {**ADVICE, "steps": ["draw the axis", "mark the number"]},
                   "commitment": {"what": "send the deck", "who": None, "when_text": "tomorrow"}})
    store, user, dev, pipe = world(tmp_path, jev=jev, llm=llm)
    store.update_user(user.id, kinds_off=["commitment"])
    t = now()
    store.add_moment(Moment(user_id=user.id, kind="whiteboard",
                            started_at=t - timedelta(minutes=10), ended_at=t, source="motion"))
    seg(store, dev, 60, 5, 0, "First draw the axis, then mark the number.", 15)
    out = await pipe.maybe_run(dev)
    assert [m.kind for m in out] == ["demonstration"]
    assert out[0].body["steps"] == ["draw the axis", "mark the number"]
    assert out[0].body["ranked_first"] is True


async def test_question_matches_people_followed(tmp_path):
    jev = FakeJev({"question": 0.9}, giver="none")
    llm = FakeLLM({"question": {"question": "How do I open an update?", "topic": "updates number"}})
    store, user, dev, pipe = world(tmp_path, jev=jev, llm=llm)
    ana = store.add_user(User(name="Ana Ruiz", phone="+14155550101", consent_lookup=False,
                              consent_call=False))
    store.add_skill(Skill(owner_id=ana.id, title="Open an update with the number",
                          verdict="Lead with the number.", reason="r", status="published"))
    store.follow(user.id, ana.id)
    seg(store, dev, 60, 5, 0, "How do I open an update?", 15)
    out = await pipe.maybe_run(dev)
    q = next(m for m in out if m.kind == "question")
    assert q.body["matches"][0]["first_name"] == "Ana"


async def test_window_cap(tmp_path):
    jev = FakeJev({"idea": 0.9})
    store, user, dev, pipe = world(tmp_path, jev=jev, llm=FakeLLM({"idea": {"idea": "x"}}),
                                   windows_per_hour=1)
    seg(store, dev, 300, 5, 0, "one")
    assert await pipe.maybe_run(dev)
    seg(store, dev, 60, 5, 0, "two")
    assert await pipe.maybe_run(dev) == []                # over the cap
    assert len(jev.calls) == 1


async def test_kept_is_forced_and_records_what_was_found(tmp_path):
    jev = FakeJev({"idea": 0.9})
    store, user, dev, pipe = world(tmp_path, jev=jev, llm=FakeLLM({"idea": {"idea": "x"}}),
                                   windows_per_hour=0)
    seg(store, dev, 20, 5, 0, "what if we did it backwards")
    t = now()
    kept = store.add_moment(Moment(user_id=user.id, kind="kept",
                                   started_at=t - timedelta(seconds=60), ended_at=t,
                                   source="motion"))
    await pipe.on_kept(dev, kept)
    k = store.get_moment(kept.id)
    assert k.body["found"] == ["idea"] and len(k.segment_ids) == 1


async def test_retention(tmp_path):
    store, user, dev, pipe = world(tmp_path)
    seg(store, dev, 25 * 3600, 5, 0, "old")
    seg(store, dev, 10, 2, 0, "new")
    await pipe.tick(dev)
    assert [s.text for s in store.segments(dev.id)] == ["new"]


def test_bridge_upload_runs_the_pipeline(tmp_path):
    from fastapi.testclient import TestClient

    from tacit.app import create_app
    from tacit.testing import onboard

    store = Store(tmp_path / "t.db")
    s = make_settings()
    jev = FakeJev({"stop_request": 0.9})
    app = create_app(s, store=store, scenarios=sc.Scenarios(store, s, jev=jev, llm=FakeLLM()))
    pwa = TestClient(app, base_url="https://localhost")
    onboard(pwa)
    token = pwa.post("/api/band/pair", json={"band": 16}).json()["token"]
    bridge = TestClient(app, base_url="https://localhost",
                        headers={"authorization": f"Bearer {token}"})
    t = now() - timedelta(seconds=40)
    bridge.post("/api/bridge/segments", json={"segments": [
        {"started_at": t.isoformat(), "ended_at": (t + timedelta(seconds=3)).isoformat(),
         "speaker": 1, "text": "please don't keep any of this"}]})
    assert jev.calls                                   # ran after the upload (20 s of silence)
    assert bridge.get("/api/bridge/commands").json() == {"muted": True, "changed": True}


async def test_stop_request_cannot_be_switched_off(tmp_path):
    jev = FakeJev({"stop_request": 0.95})
    store, user, dev, pipe = world(tmp_path, jev=jev, llm=FakeLLM())
    store.update_user(user.id, kinds_off=["stop_request"])
    seg(store, dev, 50, 5, 1, "stop it")
    await pipe.maybe_run(dev)
    assert store.device_for_user(user.id).muted is True


def test_patch_me_never_turns_off_stop_request(tmp_path):
    from tacit.testing import client, onboard

    c = client(tmp_path)
    onboard(c)
    me = c.patch("/api/me", json={"kinds_off": ["stop_request", "typing", "nonsense"]}).json()
    assert me["kinds_off"] == ["typing"]
