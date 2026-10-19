"""`GET /users/lookup`: autocomplete every logged-in user may call (identity only), and adding a member by id."""

from __future__ import annotations

from app.db.session import get_sessionmaker
from app.models import Project, ProjectMember
from app.services import users as users_svc


async def _make_project(owner_id: int, slug: str = "lookup-proj") -> str:
    """An active project with its owner row, written directly (the member API does not depend on how the project
    came to exist, and the application / approval flow has its own tests)."""
    async with get_sessionmaker()() as session:
        p = Project(slug=slug, name="Lookup", data_type="TABULAR", task_type="regression", status="active")
        p.owner_id = owner_id
        p.members.append(ProjectMember(user_id=owner_id, role="owner", added_by_id=owner_id))
        session.add(p)
        await session.commit()
    return slug


async def _lookup(client, headers: dict[str, str], q: str) -> list[str]:
    r = await client.get("/api/v1/users/lookup", params={"q": q}, headers=headers)
    assert r.status_code == 200, r.text
    return [row["username"] for row in r.json()]


async def _add(client, headers: dict[str, str], slug: str, body: dict):
    return await client.post(f"/api/v1/projects/{slug}/members", json=body, headers=headers)


async def _create(username: str, display_name: str | None = None, *, active: bool = True) -> int:
    async with get_sessionmaker()() as session:
        u = await users_svc.create_local_user(
            session, username=username, password="pw123456", email=f"{username}@example.com", display_name=display_name
        )
        if not active:
            u.is_active = False
            await session.commit()
        return u.id


async def test_plain_user_gets_identity_only(client, user, other):
    r = await client.get("/api/v1/users/lookup", params={"q": "oth"}, headers=user)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [row["username"] for row in rows] == ["other"]
    assert set(rows[0]) == {"id", "username", "display_name", "email"}  # never role / is_active / hashes
    assert rows[0]["display_name"] == "其他人" and rows[0]["email"] == "other@example.com"
    # case-insensitive, and display name / e-mail are searched too
    for q in ("OTH", "其他", "other@EXAMPLE"):
        assert await _lookup(client, user, q) == ["other"], q


async def test_short_or_empty_query_returns_nothing(client, user, other):
    for q in ("o", " o ", ""):
        r = await client.get("/api/v1/users/lookup", params={"q": q}, headers=user)
        assert r.status_code == 200 and r.json() == [], q
    assert (await client.get("/api/v1/users/lookup", headers=user)).json() == []


async def test_lookup_requires_login(client, db):
    r = await client.get("/api/v1/users/lookup", params={"q": "admin"})
    assert r.status_code == 401


async def test_lookup_skips_inactive_users_caps_at_ten_and_orders_by_username(client, user):
    for i in range(12):
        await _create(f"lk-{i:02d}", active=i != 0)
    rows = (await client.get("/api/v1/users/lookup", params={"q": "LK-"}, headers=user)).json()
    names = [row["username"] for row in rows]
    assert len(names) == 10 and names == sorted(names)
    assert names[0] == "lk-01" and "lk-00" not in names


async def test_lookup_treats_like_wildcards_literally(client, user, other):
    for q in ("%%", "__", "%e%"):
        assert (await client.get("/api/v1/users/lookup", params={"q": q}, headers=user)).json() == [], q


async def test_add_member_by_user_id_and_legacy_identifier(client, user):
    me = (await client.get("/api/v1/me", headers=user)).json()
    slug = await _make_project(me["id"])
    third_id = await _create("third", "第三人")
    await _create("fourth")
    picked = (await client.get("/api/v1/users/lookup", params={"q": "third"}, headers=user)).json()
    assert [p["id"] for p in picked] == [third_id]
    r = await _add(client, user, slug, {"user_id": third_id, "role": "viewer"})
    assert r.status_code == 201, r.text
    roles = {m["user"]["username"]: m["role"] for m in r.json()["members"]}
    assert roles["third"] == "viewer"
    # the old field keeps working, and neither identifier is a validation error
    r = await _add(client, user, slug, {"username_or_email": "fourth"})
    assert r.status_code == 201 and "fourth" in {m["user"]["username"] for m in r.json()["members"]}
    assert (await _add(client, user, slug, {"role": "member"})).status_code == 422
    r = await _add(client, user, slug, {"user_id": 999999})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "USER_NOT_FOUND"
    r = await _add(client, user, slug, {"user_id": third_id})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ALREADY_MEMBER"
