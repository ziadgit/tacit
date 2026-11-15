from datetime import timedelta

import pytest

from tacit.domain import (
    BridgeDevice,
    Call,
    ContextItem,
    Moment,
    Pass,
    Segment,
    Skill,
    User,
    now,
)
from tacit.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def user(phone="+14155550100", name="Maya Lin") -> User:
    return User(name=name, phone=phone, consent_lookup=True, consent_call=False,
                links=["https://maya.example.com"])


def test_user_roundtrip(store):
    u = store.add_user(user())
    got = store.get_user(u.id)
    assert got.name == "Maya Lin" and str(got.links[0]) == "https://maya.example.com/"
    assert got.consent_lookup is True and got.consent_call is False
    assert store.user_by_phone("+14155550100").id == u.id
    store.update_user(u.id, headline="Ten years in product", kinds_off=["idea"])
    got = store.get_user(u.id)
    assert got.headline == "Ten years in product" and got.kinds_off == ["idea"]


def test_phone_unique(store):
    store.add_user(user())
    with pytest.raises(Exception):  # noqa: B017 - sqlite IntegrityError
        store.add_user(user(name="Other"))


def test_skills_and_people(store):
    a, b = store.add_user(user()), store.add_user(user("+14155550101", "Ana"))
    s1 = store.add_skill(Skill(owner_id=a.id, title="t", verdict="v", reason="r"))
    store.add_skill(Skill(owner_id=a.id, title="t2", verdict="v", reason="r", status="removed"))
    assert [s.id for s in store.skills_mine(a.id)] == [s1.id]
    assert store.people() == []
    store.update_skill(s1.id, status="published")
    people = store.people()
    assert [(p.id, n) for p, n in people] == [(a.id, 1)]
    store.follow(b.id, a.id)
    store.follow(b.id, a.id)
    assert store.follower_count(a.id) == 1
    store.set_follow_paid(b.id, a.id, "cs_1")
    f = store.get_follow(b.id, a.id)
    assert f.paid and f.stripe_session_id == "cs_1"
    store.unfollow(b.id, a.id)
    assert store.get_follow(b.id, a.id) is None


def test_calls(store):
    u = store.add_user(user())
    c = store.add_call(Call(user_id=u.id, direction="outbound"))
    assert store.active_call(u.id).id == c.id
    store.update_call(c.id, vapi_call_id="v1", status="ended")
    assert store.active_call(u.id) is None
    assert store.call_by_vapi_id("v1").id == c.id
    assert store.latest_call(u.id).status == "ended"


def test_rate_limit(store):
    u = store.add_user(user())
    assert all(store.allow(u.id, "call", 3) for _ in range(3))
    assert not store.allow(u.id, "call", 3)
    assert store.count_events(u.id, "call", now() - timedelta(days=1)) == 3
    assert store.count_events(u.id, "call", now() + timedelta(seconds=1)) == 0


def test_stripe_event_idempotent(store):
    assert store.mark_stripe_event("evt_1") is True
    assert store.mark_stripe_event("evt_1") is False


def test_segments_since(store):
    u = store.add_user(user())
    d = store.add_device(BridgeDevice(user_id=u.id, band=16, token_sha256="h"))
    t = now()
    old = store.add_segment(Segment(device_id=d.id, user_id=u.id, started_at=t - timedelta(
        seconds=60), ended_at=t - timedelta(seconds=50), text="a"))
    new = store.add_segment(Segment(device_id=d.id, user_id=u.id, started_at=t - timedelta(
        seconds=10), ended_at=t - timedelta(seconds=5), text="b"))
    assert store.delete_segments_since(d.id, t - timedelta(seconds=15)) == [new.id]
    assert [s.id for s in store.segments(d.id)] == [old.id]
    assert store.delete_segments_before(t) == 1


def test_delete_user_cascades(store):
    a, b = store.add_user(user()), store.add_user(user("+14155550101", "Ana"))
    s = store.add_skill(Skill(owner_id=a.id, title="t", verdict="v", reason="r"))
    store.add_context_items([ContextItem(user_id=a.id, kind="role", text="x",
                                         source_url="https://x.com")])
    store.add_call(Call(user_id=a.id, direction="inbound"))
    store.follow(a.id, b.id)
    store.follow(b.id, a.id)
    store.add_event(a.id, "call")
    d = store.add_device(BridgeDevice(user_id=a.id, band=16, token_sha256="h"))
    store.add_segment(Segment(device_id=d.id, user_id=a.id, started_at=now(), ended_at=now(),
                              text="x"))
    store.add_moment(Moment(user_id=a.id, kind="idea", started_at=now(), ended_at=now()))
    store.add_pass(Pass(giver_id=a.id, receiver_id=b.id, skill_id=s.id))
    store.delete_user(a.id)
    for table in ("users", "skills", "context_items", "calls", "devices", "segments",
                  "moments", "passes"):
        rows = store.db.execute(f"SELECT * FROM {table}").fetchall()
        assert all(a.id not in tuple(r) for r in rows), table
    assert store.db.execute("SELECT COUNT(*) FROM follows").fetchone()[0] == 0
    assert store.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    assert store.get_user(b.id) is not None
