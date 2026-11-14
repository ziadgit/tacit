from datetime import timedelta

from fastapi.testclient import TestClient

from tacit.app import create_app
from tacit.domain import Moment, Pass, Skill, now
from tacit.store import Store
from tacit.testing import make_settings, onboard


def pair(tmp_path):
    store = Store(tmp_path / "t.db")
    s = make_settings()
    a = TestClient(create_app(s, store=store), base_url="https://localhost")
    b = TestClient(create_app(s, store=store), base_url="https://localhost")
    ma = onboard(a, phone="+14155550100", name="Maya Lin")
    mb = onboard(b, phone="+14155550101", name="Ana Ruiz")
    return store, a, b, ma["id"], mb["id"]


def skill(store, owner, title="Open an update with the number", **kw):
    return store.add_skill(Skill(owner_id=owner, title=title, verdict="Lead with it.",
                                 reason="People read the top.", quote="I lead with it", **kw))


def test_mine_and_patch(tmp_path):
    store, a, b, maya, ana = pair(tmp_path)
    s1 = skill(store, maya, jev_specific=0.8)
    s2 = skill(store, maya, title="Second")
    mine = a.get("/api/skills/mine").json()
    assert [m["id"] for m in mine] == [s2.id, s1.id]
    assert mine[1]["jev_specific"] == 0.8
    r = a.patch(f"/api/skills/{s1.id}", json={"status": "published", "visibility": "followers",
                                              "title": "  Lead with the number "})
    assert r.status_code == 200
    assert r.json()["status"] == "published" and r.json()["title"] == "Lead with the number"
    assert a.patch(f"/api/skills/{s2.id}", json={"status": "draft"}).status_code == 422
    assert a.patch(f"/api/skills/{s2.id}", json={"title": "x" * 81}).status_code == 422
    # not the owner → 404
    assert b.patch(f"/api/skills/{s1.id}", json={"status": "removed"}).status_code == 404
    a.patch(f"/api/skills/{s2.id}", json={"status": "removed"})
    assert [m["id"] for m in a.get("/api/skills/mine").json()] == [s1.id]
    assert a.patch(f"/api/skills/{s2.id}", json={"status": "published"}).status_code == 404


def test_people_and_locking(tmp_path):
    store, a, b, maya, ana = pair(tmp_path)
    skill(store, maya, title="Public one", status="published")
    skill(store, maya, title="Locked one", status="published", visibility="followers")
    skill(store, maya, title="Draft one")
    people = b.get("/api/people").json()
    assert [p["id"] for p in people] == [maya]
    p = people[0]
    assert p["first_name"] == "Maya" and p["skill_count"] == 2
    assert "phone" not in p and "links" not in p and "name" not in p
    detail = b.get(f"/api/people/{maya}").json()
    by_title = {s["title"]: s for s in detail["skills"]}
    assert set(by_title) == {"Public one", "Locked one"}
    locked = by_title["Locked one"]
    assert locked["locked"] is True and locked["verdict"] is None and locked["quote"] is None
    assert by_title["Public one"]["verdict"] == "Lead with it."
    assert by_title["Public one"]["jev_specific"] is None  # scores are the owner's only
    # owner sees everything
    own = a.get(f"/api/people/{maya}").json()
    assert all(not s["locked"] for s in own["skills"])
    # a free follow doesn't unlock; a paid one does
    assert b.post(f"/api/follow/{maya}").json()["following"] is True
    assert b.get(f"/api/people/{maya}").json()["follower_count"] == 1
    assert {s["locked"] for s in b.get(f"/api/people/{maya}").json()["skills"]} == {True, False}
    store.set_follow_paid(ana, maya, "cs_test_1")
    assert not any(s["locked"] for s in b.get(f"/api/people/{maya}").json()["skills"])
    assert b.get("/api/people/nope").status_code == 404


def test_follow_rules(tmp_path):
    store, a, b, maya, ana = pair(tmp_path)
    assert a.post(f"/api/follow/{maya}").status_code == 400
    assert a.post("/api/follow/nope").status_code == 404
    assert a.post(f"/api/follow/{ana}").status_code == 200
    assert store.get_follow(maya, ana) is not None
    assert a.delete(f"/api/follow/{ana}").status_code == 204
    assert store.get_follow(maya, ana) is None


def test_feed_typed_items(tmp_path):
    store, a, b, maya, ana = pair(tmp_path)
    t = now()
    pub = skill(store, maya, title="Public", status="published")
    skill(store, maya, title="Locked", status="published", visibility="followers")
    skill(store, maya, title="Draft")
    store.add_moment(Moment(user_id=maya, kind="drawing", started_at=t - timedelta(minutes=25),
                            ended_at=t, confidence=0.8, source="motion"))
    store.add_moment(Moment(user_id=maya, kind="idea", started_at=t, ended_at=t,
                            title="A tiny idea", body={"idea": "x", "quote": "secret words"},
                            status="shared"))
    store.add_moment(Moment(user_id=maya, kind="decision", started_at=t, ended_at=t,
                            title="Private decision", status="shared"))
    # nothing until following
    assert b.get("/api/feed").json() == []
    b.post(f"/api/follow/{maya}")
    items = b.get("/api/feed").json()
    types = sorted(i["type"] for i in items)
    assert types == ["post", "skill"]  # creative is off by default, locked/draft hidden
    post = next(i for i in items if i["type"] == "post")
    assert "quote" not in post["body"] and post["person"]["first_name"] == "Maya"
    a.patch("/api/me", json={"share_creative": True})
    creative = [i for i in b.get("/api/feed").json() if i["type"] == "creative"]
    assert creative and creative[0]["minutes"] == 25 and creative[0]["kind"] == "drawing"

    # a received piece of advice: anonymous until a pass with a published skill
    m = store.add_moment(Moment(user_id=ana, kind="advice_received", started_at=t, ended_at=t,
                                title="Lead with the number",
                                body={"title": "Lead with the number", "verdict": "v",
                                      "reason": "r", "quote": "I lead with it"}))
    picked = [i for i in b.get("/api/feed").json() if i["type"] == "picked_up"]
    assert picked[0]["only_you"] is True
    assert picked[0]["giver"]["first_name"] == "someone you talked with"
    assert picked[0]["body"].get("quote") is None
    assert not [i for i in a.get("/api/feed").json() if i["type"] == "picked_up"]

    draft = skill(store, maya, title="Lead with the number")
    store.add_pass(Pass(giver_id=maya, receiver_id=ana, skill_id=draft.id,
                        receiver_moment_id=m.id))
    assert not [i for i in b.get("/api/feed").json() if i["type"] == "pass"]
    store.update_skill(draft.id, status="published")
    feed_b = b.get("/api/feed").json()
    passes = [i for i in feed_b if i["type"] == "pass"]
    assert passes and passes[0]["lit"] is True
    assert passes[0]["giver"]["first_name"] == "Maya"
    assert passes[0]["receiver"]["first_name"] == "Ana"
    picked = next(i for i in feed_b if i["type"] == "picked_up")
    assert picked["giver"]["first_name"] == "Maya" and picked["body"]["quote"] == "I lead with it"
    # the giver sees the pass too, without following the receiver
    assert [i for i in a.get("/api/feed").json() if i["type"] == "pass"]
    assert pub.id in {i["skill"]["id"] for i in feed_b if i["type"] == "skill"}
