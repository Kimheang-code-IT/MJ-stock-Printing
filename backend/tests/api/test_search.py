"""Global search endpoint: auth, results, and permission filtering."""

from tests.utils import admin_headers, create_user_with_role, login


async def test_search_requires_auth(client):
    response = await client.get("/api/v1/search", params={"q": "walk"})
    assert response.status_code == 401


async def test_search_finds_seeded_customer(client):
    headers = await admin_headers(client)
    response = await client.get("/api/v1/search", params={"q": "walk-in"}, headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total"] >= 1
    hit = next(h for h in data["hits"] if h["type"] == "customer")
    assert hit["title"] == "Walk-in Customer"
    assert hit["url"].startswith("/setup/customers/")


async def test_search_blank_query_returns_no_hits(client):
    headers = await admin_headers(client)
    response = await client.get("/api/v1/search", params={"q": "   "}, headers=headers)
    assert response.status_code == 200
    assert response.json()["data"] == {"hits": [], "total": 0}


async def test_search_respects_view_permissions(client, db_session):
    await create_user_with_role(
        db_session,
        email="search-viewer@example.com",
        password="viewerpass1",
        role_name="SearchViewer",
        permissions=["category.view"],
    )
    await db_session.commit()
    tokens = await login(client, "search-viewer@example.com", "viewerpass1")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    response = await client.get("/api/v1/search", params={"q": "walk-in"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["data"]["hits"] == []
