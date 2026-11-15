import asyncio
import json
from types import SimpleNamespace

import pytest

from tacit import context
from tacit.context import PROFILE_SCHEMA, lookup, parse_items, search_kwargs
from tacit.domain import User
from tacit.testing import client, make_settings, onboard


class FakeExa:
    def __init__(self, content=None, exc=None, delay=0.0):
        self.calls = []
        self.content, self.exc, self.delay = content, exc, delay

    async def search(self, query, **kwargs):
        self.calls.append((query, kwargs))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return SimpleNamespace(output=SimpleNamespace(content=self.content), results=[])


ITEMS = {"items": [
    {"kind": "role", "text": "Head of product at Acme", "source_url": "https://acme.com/team"},
    {"kind": "writing", "text": "Writes about updates", "source_url": "ftp://x.com"},
    {"kind": "bogus", "text": "x", "source_url": "https://x.com"},
    {"kind": "work", "text": "  Built  the  launch  ", "source_url": "http://b.com"},
]}


def user(**kw):
    return User(name="Maya Lin", phone="+14155550100", headline="Ten years in product",
                links=["https://maya.example.com"], consent_lookup=True, consent_call=False, **kw)


async def test_exact_kwargs_and_no_phone():
    exa = FakeExa(ITEMS)
    items = await lookup(user(), exa, make_settings())
    (query, kwargs), = exa.calls
    assert query == "Maya Lin Ten years in product https://maya.example.com/"
    assert "+1415" not in query and "4155550100" not in json.dumps(kwargs)
    assert kwargs == {
        "type": "auto",
        "objective": (
            "Find public professional information about Maya Lin (Ten years in product): roles, "
            "areas of expertise, notable work and writing. Prefer the pages the person linked "
            "and pages they wrote themselves. Exclude other people with the same name, "
            "people-search and data-broker sites, and anything about their private life, "
            "family, address or health."),
        "system_prompt": context.SYSTEM_PROMPT,
        "output_schema": PROFILE_SCHEMA,
        "contents": {"highlights": True},
    }
    assert [(i.kind, i.text) for i in items] == [
        ("role", "Head of product at Acme"), ("work", "Built the launch")]


def test_query_without_headline():
    u = User(name="Ana", phone="+14155550101", consent_lookup=True, consent_call=False)
    q, kw = search_kwargs(u)
    assert q == "Ana" and "Ana ()" in kw["objective"]


def test_parse_string_and_caps():
    many = {"items": [{"kind": "other", "text": f"f{i}", "source_url": "https://a.com"}
                      for i in range(20)]}
    assert len(parse_items(json.dumps(many), "u")) == 12
    assert parse_items("not json", "u") == []
    assert parse_items(None, "u") == []
    assert parse_items({"items": "x"}, "u") == []


async def test_timeout_and_error():
    s = make_settings(exa_timeout_s=0.01)
    with pytest.raises(context.LookupError_):
        await lookup(user(), FakeExa(ITEMS, delay=0.2), s)
    with pytest.raises(context.LookupError_):
        await lookup(user(), FakeExa(exc=RuntimeError("boom key=sk")), s)


def test_api_flow(tmp_path):
    exa = FakeExa(ITEMS)
    c = client(tmp_path, exa=exa)
    onboard(c)
    r = c.post("/api/context/lookup")
    assert r.status_code == 200
    items = r.json()
    assert [i["status"] for i in items] == ["pending", "pending"]
    r = c.patch(f"/api/context/{items[0]['id']}", json={"status": "kept"})
    assert r.json()["status"] == "kept"
    c.patch(f"/api/context/{items[1]['id']}", json={"status": "removed"})
    me = c.get("/api/me").json()
    assert [i["status"] for i in me["context"]] == ["kept"]
    assert c.patch(f"/api/context/{items[0]['id']}", json={"status": "x"}).status_code == 422


def test_api_consent_rate_limit_and_failure(tmp_path):
    c = client(tmp_path, make_settings(lookups_per_user_per_day=2), exa=FakeExa(ITEMS))
    onboard(c, consent_lookup=False)
    assert c.post("/api/context/lookup").status_code == 403
    c.patch("/api/me", json={"consent_lookup": True})
    assert c.post("/api/context/lookup").status_code == 200
    assert c.post("/api/context/lookup").status_code == 200
    assert c.post("/api/context/lookup").status_code == 429


def test_api_502_stores_nothing(tmp_path):
    c = client(tmp_path, exa=FakeExa(exc=RuntimeError("x")))
    onboard(c)
    r = c.post("/api/context/lookup")
    assert r.status_code == 502 and r.json() == {"detail": "couldn't look you up right now"}
    assert c.get("/api/me").json()["context"] == []


def test_other_users_item_is_404(tmp_path):
    c = client(tmp_path, exa=FakeExa(ITEMS))
    onboard(c)
    item = c.post("/api/context/lookup").json()[0]
    c.cookies.clear()
    onboard(c, phone="+14155550199", name="Ana")
    assert c.patch(f"/api/context/{item['id']}", json={"status": "kept"}).status_code == 404
