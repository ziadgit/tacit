from datetime import timedelta

from fastapi.testclient import TestClient

from tacit import scenarios as sc
from tacit.app import create_app
from tacit.domain import Moment, now
from tacit.moments import MomentHooks, find_passes, skill_from
from tacit.scenarios_test import ADVICE, FakeJev, FakeLLM
from tacit.store import Store
from tacit.testing import make_settings, onboard


def two_bands(tmp_path):
    """Maya on band 16 and Ana on band 74, each paired through the PWA (the test pair)."""
    store = Store(tmp_path / "t.db")
    s = make_settings()
    app = create_app(s, store=store)
    maya = TestClient(app, base_url="https://localhost")
    ana = TestClient(app, base_url="https://localhost")
    maya_id = onboard(maya, phone="+14155550100", name="Maya Lin")["id"]
    ana_id = onboard(ana, phone="+14155550101", name="Ana Ruiz")["id"]
    maya.post("/api/band/pair", json={"band": 16})
    ana.post("/api/band/pair", json={"band": 74})
    return store, s, maya, ana, maya_id, ana_id


def talk(store, dev, lines):
    """Segments on one device: (seconds ago, speaker, level, text)."""
    from tacit.domain import Segment

    for ago, spk, lvl, text in lines:
        t = now() - timedelta(seconds=ago)
        store.add_segment(Segment(device_id=dev.id, user_id=dev.user_id, started_at=t,
                                  ended_at=t + timedelta(seconds=8), speaker=spk, text=text,
                                  level=lvl))


CONVO = [(150, 0, 15, "When I report results I open the update with the number."),
         (120, 1, 30, "Why the number first?"),
         (90, 0, 15, "People forget the story, they remember forty percent."),
         (40, 1, 30, "I'll try that.")]


async def test_skill_draft_and_pass_between_16_and_74(tmp_path):
    store, s, maya, ana, maya_id, ana_id = two_bands(tmp_path)
    dev_m, dev_a = store.device_for_user(maya_id), store.device_for_user(ana_id)
    llm = FakeLLM({"advice": {**ADVICE, "quote": "they remember forty percent"}})
    judge_jev = FakeJev()

    async def jev_scores(*, state, questions):
        from types import SimpleNamespace
        if "specific" in questions:   # the §8 skill check
            return SimpleNamespace(nouls={"specific": SimpleNamespace(noul=0.8),
                                          "own": SimpleNamespace(noul=0.7)})
        return await judge_jev.system_one(state=state, questions=questions)

    class Jev:
        system_one = staticmethod(jev_scores)

    # Maya's band hears her give advice; Ana's band hears her receive it
    pipe_m = sc.Scenarios(store, s, jev=FakeJev({"advice": 0.9}, giver="wearer"), llm=llm)
    pipe_m.hooks.append(MomentHooks(store, s, Jev()))
    pipe_a = sc.Scenarios(store, s, jev=FakeJev({"advice": 0.9}, giver="other"), llm=llm)
    pipe_a.hooks.append(MomentHooks(store, s, Jev()))
    talk(store, dev_m, CONVO)
    talk(store, dev_a, [(a, 1 - spk, 45 - lvl, t) for a, spk, lvl, t in CONVO])
    out_m = await pipe_m.maybe_run(dev_m)
    given = next(m for m in out_m if m.kind == "advice_given")
    assert given.skill_id
    skill = store.get_skill(given.skill_id)
    assert skill.status == "draft" and skill.source == "conversation"
    assert skill.moment_id == given.id and skill.jev_specific == 0.8 and skill.jev_own == 0.7
    assert skill.quote == "they remember forty percent"

    out_a = await pipe_a.maybe_run(dev_a)
    received = next(m for m in out_a if m.kind == "advice_received")
    passes = store.passes_for(ana_id)
    assert len(passes) == 1
    p = passes[0]
    assert (p.giver_id, p.receiver_id, p.skill_id) == (maya_id, ana_id, skill.id)
    assert p.receiver_moment_id == received.id
    # no pass item and no name until Maya publishes the skill
    feed = ana.get("/api/feed").json()
    assert not [i for i in feed if i["type"] == "pass"]
    picked = next(i for i in feed if i["type"] == "picked_up")
    assert picked["giver"]["first_name"] == "someone you talked with"
    maya.patch(f"/api/skills/{skill.id}", json={"status": "published"})
    for client in (maya, ana):
        items = [i for i in client.get("/api/feed").json() if i["type"] == "pass"]
        assert items and items[0]["giver"]["first_name"] == "Maya"
        assert items[0]["receiver"]["first_name"] == "Ana"
    picked = next(i for i in ana.get("/api/feed").json() if i["type"] == "picked_up")
    assert picked["giver"]["first_name"] == "Maya"
    assert picked["body"]["quote"] == "they remember forty percent"
    # not made twice
    assert find_passes(store, store.get_moment(received.id)) == []


def test_no_pass_without_overlapping_conversations(tmp_path):
    store, s, maya, ana, maya_id, ana_id = two_bands(tmp_path)
    t = now()
    from tacit.domain import Skill

    sk = store.add_skill(Skill(owner_id=maya_id, title="Open an update with the number",
                               verdict="v", reason="r"))
    store.add_moment(Moment(user_id=maya_id, kind="conversation", started_at=t - timedelta(hours=2),
                            ended_at=t - timedelta(minutes=100)))
    store.add_moment(Moment(user_id=ana_id, kind="conversation",
                            started_at=t - timedelta(minutes=5), ended_at=t))
    store.add_moment(Moment(user_id=maya_id, kind="advice_given", started_at=t, ended_at=t,
                            title=sk.title, skill_id=sk.id))
    recv = store.add_moment(Moment(user_id=ana_id, kind="advice_received", started_at=t,
                                   ended_at=t, title=sk.title))
    assert find_passes(store, recv) == []


def test_skill_from_rules():
    t = now()

    def m(kind, **body):
        return Moment(user_id="u", kind=kind, started_at=t, ended_at=t, body=body)
    assert skill_from(m("advice_given", title="T", verdict="V", reason="R")).verdict == "V"
    demo = skill_from(m("demonstration", title="T", verdict="V", reason="R",
                        steps=["draw it", "mark it"], giver="wearer"))
    assert demo.verdict == "1. draw it; 2. mark it"
    assert skill_from(m("explanation", title="T", verdict="V", reason="R", giver="other")) is None
    assert skill_from(m("lesson", title="T", verdict="V")) is None   # no reason, no skill


def test_moments_api(tmp_path):
    store, s, maya, ana, maya_id, ana_id = two_bands(tmp_path)
    t = now()
    idea = store.add_moment(Moment(user_id=maya_id, kind="idea", started_at=t, ended_at=t,
                                   title="backwards", confidence=0.7))
    dec = store.add_moment(Moment(user_id=maya_id, kind="decision", started_at=t, ended_at=t))
    store.add_moment(Moment(user_id=maya_id, kind="demonstration", started_at=t, ended_at=t))
    store.add_moment(Moment(user_id=ana_id, kind="idea", started_at=t, ended_at=t))
    ms = maya.get("/api/moments").json()
    assert len(ms) == 3 and ms[0]["kind"] == "demonstration"   # ranked first in its hour
    assert "segment_ids" not in ms[0]
    assert maya.patch(f"/api/moments/{dec.id}", json={"status": "shared"}).status_code == 422
    assert maya.patch(f"/api/moments/{idea.id}", json={"status": "shared"}).json()["status"] == \
        "shared"
    assert ana.patch(f"/api/moments/{idea.id}", json={"status": "dismissed"}).status_code == 404
    assert maya.patch(f"/api/moments/{dec.id}", json={"status": "dismissed"}).status_code == 200
    ana.post(f"/api/follow/{maya_id}")
    posts = [i for i in ana.get("/api/feed").json() if i["type"] == "post"]
    assert posts and posts[0]["title"] == "backwards"


def test_transcript_is_private_live_and_deletable(tmp_path):
    from tacit.domain import Segment

    store, s, maya, ana, maya_id, ana_id = two_bands(tmp_path)
    dev_m, dev_a = store.device_for_user(maya_id), store.device_for_user(ana_id)
    t = now()

    def seg(dev, ago, spk, lvl, text):
        st = t - timedelta(seconds=ago)
        return store.add_segment(Segment(device_id=dev.id, user_id=dev.user_id, started_at=st,
                                         ended_at=st + timedelta(seconds=3), speaker=spk,
                                         text=text, level=lvl))

    seg(dev_m, 25 * 3600, 0, 15, "too old to show")
    seg(dev_m, 60, 0, 15, "Lead with the number.")
    seg(dev_m, 40, 1, 32, "Why?")
    seg(dev_a, 30, 0, 15, "Ana's own words")
    out = maya.get("/api/transcript").json()
    assert [x["text"] for x in out["segments"]] == ["Lead with the number.", "Why?"]
    assert [x["you"] for x in out["segments"]] == [True, False]   # loudest speaker by 6 dB+
    assert out["retention_hours"] == 24 and out["band"] == 16
    # incremental: only lines ending after `since`
    since = (t - timedelta(seconds=45)).isoformat()
    assert [x["text"] for x in maya.get("/api/transcript", params={"since": since})
            .json()["segments"]] == ["Why?"]
    # never another person's lines; never without a session
    assert [x["text"] for x in ana.get("/api/transcript").json()["segments"]] == \
        ["Ana's own words"]
    anon = TestClient(maya.app, base_url="https://localhost")
    assert anon.get("/api/transcript").status_code == 401
    assert maya.delete("/api/transcript").status_code == 204
    assert maya.get("/api/transcript").json()["segments"] == []
    assert ana.get("/api/transcript").json()["segments"]          # Ana's untouched


def test_moment_detail(tmp_path):
    from tacit.domain import Segment, Skill

    store, s, maya, ana, maya_id, ana_id = two_bands(tmp_path)
    dev = store.device_for_user(maya_id)
    t = now()
    segs = [store.add_segment(Segment(
        device_id=dev.id, user_id=maya_id, started_at=t - timedelta(seconds=a),
        ended_at=t - timedelta(seconds=a - 3), speaker=spk, text=txt, level=lvl))
        for a, spk, lvl, txt in [(30, 0, 15, "Lead with the number."), (20, 1, 33, "Why?")]]
    sk = store.add_skill(Skill(owner_id=maya_id, title="Lead with the number", verdict="v",
                               reason="r", source="conversation", jev_specific=0.8))
    m = store.add_moment(Moment(user_id=maya_id, kind="advice_given", started_at=segs[0].started_at,
                                ended_at=segs[1].ended_at, title="Lead with the number",
                                body={"verdict": "v", "reason": "r"}, confidence=0.9,
                                segment_ids=[x.id for x in segs], skill_id=sk.id))
    from tacit.domain import Pass
    store.add_pass(Pass(giver_id=maya_id, receiver_id=ana_id, skill_id=sk.id))
    d = maya.get(f"/api/moments/{m.id}").json()
    assert [(x["text"], x["you"]) for x in d["lines"]] == [("Lead with the number.", True),
                                                          ("Why?", False)]
    assert d["skill"]["title"] == "Lead with the number" and d["skill"]["jev_specific"] == 0.8
    assert d["passes"] == [{"giver": "Maya", "receiver": "Ana", "you_gave": True,
                            "at": d["passes"][0]["at"]}]
    assert d["seconds"] == 13 and d["lines_kept"] is True
    assert ana.get(f"/api/moments/{m.id}").status_code == 404      # only the wearer
    # after 24 h the words are gone, the moment stays
    store.delete_segments_for_user(maya_id)
    d = maya.get(f"/api/moments/{m.id}").json()
    assert d["lines"] == [] and d["lines_expected"] is True and d["moment"]["title"]


class FlakyLLM(FakeLLM):
    """Out of credit first, then fine."""

    def __init__(self, answers):
        super().__init__(answers)
        self.down = True

    async def extract(self, text, *, name, schema, instructions):
        self.calls.append((name, text))
        if self.down:
            raise RuntimeError("openai status 429")
        return dict(self.answers.get(name, {}))


async def test_failed_extraction_is_retried_and_becomes_a_skill(tmp_path):
    store, s, maya, ana, maya_id, ana_id = two_bands(tmp_path)
    dev = store.device_for_user(maya_id)
    llm = FlakyLLM({"advice": {**ADVICE, "giver": "other"}})   # the model's giver is ignored
    pipe = sc.Scenarios(store, s, jev=FakeJev({"advice": 0.9}, giver="wearer"), llm=llm)
    pipe.hooks.append(MomentHooks(store, s, None))
    talk(store, dev, CONVO)
    out = await pipe.maybe_run(dev)
    given = next(m for m in out if m.kind == "advice_given")
    assert given.body["title"] is None and not given.skill_id        # empty: the model was down
    feed = maya.get("/api/feed").json()
    heard = [i for i in feed if i["type"] == "heard"]
    assert heard and heard[0]["kind"] == "advice_given" and heard[0]["only_you"] is True
    assert not [i for i in ana.get("/api/feed").json() if i["type"] == "heard"]
    # still down: nothing changes, and it waits before the next try
    assert await pipe.retry_extraction(dev) == 0
    llm.down = False
    assert await pipe.retry_extraction(dev) == 0                       # waiting 5 minutes
    pipe._retry_at.clear()
    assert await pipe.retry_extraction(dev) >= 1
    fixed = store.get_moment(given.id)
    assert fixed.body["title"] == ADVICE["title"] and fixed.body["giver"] == "wearer"
    skill = store.get_skill(fixed.skill_id)
    assert skill.status == "draft" and skill.source == "conversation"
    line = next(i for i in maya.get("/api/feed").json() if i["id"] == f"heard:{given.id}")
    assert line["body"]["title"] == ADVICE["title"]
    # dismissed moments leave the feed
    maya.patch(f"/api/moments/{given.id}", json={"status": "dismissed"})
    assert not [i for i in maya.get("/api/feed").json() if i["id"] == f"heard:{given.id}"]


def test_ana_shares_advice_she_picked_up(tmp_path):
    from tacit.domain import Pass, Skill

    store, s, maya, ana, maya_id, ana_id = two_bands(tmp_path)
    maya.post(f"/api/follow/{ana_id}")
    t = now()
    got = store.add_moment(Moment(user_id=ana_id, kind="advice_received", started_at=t, ended_at=t,
                                  title="Test it yourself first",
                                  body={"title": "Test it yourself first",
                                        "verdict": "Try it alone.", "reason": "you see the gaps",
                                        "quote": "a stranger's words", "giver": "other",
                                        "steps": ["one"]}))
    # private until shared
    assert not [i for i in maya.get("/api/feed").json() if i["type"] == "post"]
    mine = next(i for i in ana.get("/api/feed").json() if i["type"] == "picked_up")
    assert mine["body"]["status"] == "new"
    assert ana.patch(f"/api/moments/{got.id}", json={"status": "shared"}).status_code == 200
    post = next(i for i in maya.get("/api/feed").json() if i["type"] == "post")
    assert post["kind"] == "advice_received" and post["person"]["first_name"] == "Ana"
    assert post["body"] == {"title": "Test it yourself first", "verdict": "Try it alone.",
                            "reason": "you see the gaps"}          # no quote, giver or steps
    # a matched giver (a published pass) gets the credit
    sk = store.add_skill(Skill(owner_id=maya_id, title="Test it yourself first", verdict="v",
                               reason="r", status="published"))
    store.add_pass(Pass(giver_id=maya_id, receiver_id=ana_id, skill_id=sk.id,
                        receiver_moment_id=got.id))
    post = next(i for i in maya.get("/api/feed").json() if i["type"] == "post")
    assert post["body"]["from"] == "Maya"


def test_share_a_skill_from_the_feed(tmp_path):
    from tacit.domain import Skill

    store, s, maya, ana, maya_id, ana_id = two_bands(tmp_path)
    maya.post(f"/api/follow/{ana_id}")
    t = now()
    sk = store.add_skill(Skill(owner_id=ana_id, title="Say the final task first", verdict="v",
                               reason="r", source="conversation"))
    m = store.add_moment(Moment(user_id=ana_id, kind="advice_given", started_at=t, ended_at=t,
                                title=sk.title, body={"title": sk.title, "verdict": "v",
                                                      "reason": "r"}, skill_id=sk.id))
    line = next(i for i in ana.get("/api/feed").json() if i["id"] == f"heard:{m.id}")
    assert line["body"]["skill"] == {"id": sk.id, "status": "draft"}
    ana.patch(f"/api/skills/{sk.id}", json={"status": "published"})
    assert [i for i in maya.get("/api/feed").json()
            if i["type"] == "skill" and i["skill"]["id"] == sk.id]
