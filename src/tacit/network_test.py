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


def test_profile_fields_and_counts(tmp_path):
    store, a, b, maya, ana = pair(tmp_path)
    r = a.patch("/api/me", json={"location": "Belgrade", "company": "Nebius Group",
                                 "expertise": ["AI adoption", "Voice agents"],
                                 "worth_knowing": ["Speaks five languages"]})
    assert r.status_code == 200 and r.json()["expertise"] == ["AI adoption", "Voice agents"]
    assert a.patch("/api/me", json={"expertise": ["x" * 31]}).status_code == 422
    assert a.patch("/api/me", json={"expertise": list("abcdef")}).status_code == 422
    skill(store, maya, status="published")
    t = now()
    store.add_moment(Moment(user_id=maya, kind="recommendation", started_at=t, ended_at=t,
                            title="Relevance", status="shared"))
    store.add_moment(Moment(user_id=maya, kind="idea", started_at=t, ended_at=t,
                            title="An idea", status="shared"))
    store.add_moment(Moment(user_id=ana, kind="handshake", started_at=t, ended_at=t,
                            body={"person_id": maya, "with": "Maya"}))
    p = b.get(f"/api/people/{maya}").json()
    assert p["handle"] == "maya" and p["location"] == "Belgrade" and p["company"] == "Nebius Group"
    assert p["expertise"] == ["AI adoption", "Voice agents"]
    assert p["worth_knowing"] == ["Speaks five languages"]
    assert (p["skill_count"], p["post_count"], p["recommendation_count"]) == (1, 2, 1)
    assert p["recommends"] == ["Relevance"] and p["met_at"] is not None
    assert a.get(f"/api/people/{maya}").json()["met_at"] is None   # nobody "meets" themselves
    a.patch("/api/me", json={"location": ""})
    assert b.get(f"/api/people/{maya}").json()["location"] is None


def test_old_databases_get_the_new_columns(tmp_path):
    import sqlite3

    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE users (id, name, phone, headline, links, consent_lookup, "
                "consent_call, portrait, portrait_source, kinds_off, share_creative, created_at, "
                "PRIMARY KEY (id))")
    con.execute("INSERT INTO users VALUES ('u1', 'Old User', '+14155550100', NULL, '[]', 0, 0, "
                "NULL, NULL, '[]', 0, '2026-11-14T00:00:00.000000+00:00')")
    con.commit()
    con.close()
    s = Store(db)
    u = s.get_user("u1")
    assert u.name == "Old User" and u.expertise == [] and u.location is None
    s.update_user("u1", company="Acme")
    assert s.get_user("u1").company == "Acme"


def test_kept_minutes_with_words_are_in_your_feed(tmp_path):
    from tacit.domain import BridgeDevice, Segment

    store, a, b, maya, ana = pair(tmp_path)
    dev = store.add_device(BridgeDevice(user_id=maya, band=16, token_sha256="x"))
    t = now()
    segs = [store.add_segment(Segment(device_id=dev.id, user_id=maya,
                                      started_at=t - timedelta(seconds=s), ended_at=t,
                                      speaker=spk, text=txt, level=lvl))
            for s, spk, lvl, txt in [(40, 0, 15, "Remember this one."), (30, 1, 32, "Sure.")]]
    kept = store.add_moment(Moment(user_id=maya, kind="kept", started_at=t - timedelta(minutes=1),
                                   ended_at=t, segment_ids=[x.id for x in segs],
                                   body={"found": ["idea"]}))
    store.add_moment(Moment(user_id=maya, kind="kept", started_at=t, ended_at=t))   # empty tap
    items = [i for i in a.get("/api/feed").json() if i["type"] == "heard" and i["kind"] == "kept"]
    assert len(items) == 1 and items[0]["id"] == f"heard:{kept.id}" and items[0]["only_you"]
    assert [(x["text"], x["you"]) for x in items[0]["body"]["lines"]] == [
        ("Remember this one.", True), ("Sure.", False)]
    assert items[0]["body"]["found"] == ["idea"]
    assert not [i for i in b.get("/api/feed").json() if i["type"] == "heard"]   # only Maya's
