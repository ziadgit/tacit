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
