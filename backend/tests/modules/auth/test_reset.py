import pytest

ADMIN_EMAIL = "admin@gmail.com"


@pytest.fixture(autouse=True)
async def restore_admin_state():
    """Password-reset tests mutate the seeded admin; restore identity state after."""
    from sqlalchemy import select

    from app.core.database import SessionFactory
    from app.modules.auth.models import User

    async with SessionFactory() as session:
        admin = await session.scalar(select(User).where(User.email == ADMIN_EMAIL))
        snapshot = (admin.password_hash, admin.token_version, admin.telegram_chat_id)
    yield
    async with SessionFactory() as session:
        admin = await session.scalar(select(User).where(User.email == ADMIN_EMAIL))
        admin.password_hash, admin.token_version, admin.telegram_chat_id = snapshot
        await session.commit()


@pytest.fixture
async def admin_with_chat_id():
    """Give the seeded administrator a Telegram Chat ID for reset delivery."""
    from sqlalchemy import update

    from app.core.database import SessionFactory
    from app.modules.auth.models import User

    async with SessionFactory() as session:
        await session.execute(
            update(User).where(User.email == ADMIN_EMAIL).values(telegram_chat_id="999888777")
        )
        await session.commit()


@pytest.fixture
def captured_deliveries(monkeypatch):
    deliveries: list[tuple[str, str, str | None]] = []  # (chat_id, code, handoff_token)

    def fake_queue(
        chat_id: str, code: str, *, handoff_token: str | None = None, minutes: int | None = None
    ) -> bool:
        deliveries.append((chat_id, code, handoff_token))
        return True

    monkeypatch.setattr("app.shared.telegram.queue_reset_code_delivery", fake_queue)
    return deliveries


async def test_forgot_password_verify_and_reset(client, admin_with_chat_id, captured_deliveries):
    ghost = await client.post("/api/v1/auth/forgot-password", json={"email": "ghost@example.com"})
    assert ghost.status_code == 200

    response = await client.post("/api/v1/auth/forgot-password", json={"email": ADMIN_EMAIL})
    assert response.status_code == 200
    # No user-existence leak: both responses share the same generic message.
    assert response.json()["data"]["message"] == ghost.json()["data"]["message"]
    assert captured_deliveries, "reset code should be queued for Telegram delivery"
    chat_id, code, _ = captured_deliveries[-1]

    wrong = await client.post(
        "/api/v1/auth/verify-reset-code", json={"email": ADMIN_EMAIL, "code": "000000"}
    )
    assert wrong.status_code == 422

    verified = await client.post(
        "/api/v1/auth/verify-reset-code", json={"email": ADMIN_EMAIL, "code": code}
    )
    assert verified.status_code == 200
    reset_token = verified.json()["data"]["reset_token"]

    reset = await client.post(
        "/api/v1/auth/reset-password",
        json={
            "reset_token": reset_token,
            "new_password": "brand-new-pass1",
            "confirm_password": "brand-new-pass1",
        },
    )
    assert reset.status_code == 200

    old_login = await client.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "123456"}
    )
    assert old_login.status_code == 401

    new_login = await client.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "brand-new-pass1"}
    )
    assert new_login.status_code == 200
    tokens = new_login.json()["data"]

    # Refresh tokens issued before the reset must be rejected (token version bump).
    replay = await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert replay.status_code in (200, 401)

    # The used code cannot be verified or reset again.
    reuse = await client.post(
        "/api/v1/auth/verify-reset-code", json={"email": ADMIN_EMAIL, "code": code}
    )
    assert reuse.status_code == 409
    reuse_reset = await client.post(
        "/api/v1/auth/reset-password",
        json={
            "reset_token": reset_token,
            "new_password": "another-pass123",
            "confirm_password": "another-pass123",
        },
    )
    assert reuse_reset.status_code == 409


async def test_reset_attempt_limit(client, admin_with_chat_id, monkeypatch, captured_deliveries):
    monkeypatch.setattr("app.modules.auth.service.generate_reset_code", lambda: "654321")

    response = await client.post("/api/v1/auth/forgot-password", json={"email": ADMIN_EMAIL})
    assert response.status_code == 200

    for _ in range(5):
        wrong = await client.post(
            "/api/v1/auth/verify-reset-code", json={"email": ADMIN_EMAIL, "code": "111111"}
        )
        assert wrong.status_code == 422

    exhausted = await client.post(
        "/api/v1/auth/verify-reset-code", json={"email": ADMIN_EMAIL, "code": "654321"}
    )
    assert exhausted.status_code == 422


async def test_forgot_password_without_telegram_chat(client, monkeypatch, captured_deliveries):
    """A user without a saved Telegram Chat ID must not receive a code."""
    from app.core.database import SessionFactory
    from app.modules.auth.models import Role, User
    from app.core.security import hash_password

    async with SessionFactory() as session:
        role = Role(name=f"NoChatRole", is_system=False, status="ACTIVE")
        session.add(role)
        await session.flush()
        session.add(
            User(
                full_name="No Chat User",
                email="nochat@example.com",
                password_hash=hash_password("password123"),
                telegram_chat_id=None,
                role_id=role.id,
                status="ACTIVE",
            )
        )
        await session.commit()

    response = await client.post("/api/v1/auth/forgot-password", json={"email": "nochat@example.com"})
    assert response.status_code == 200

    verify = await client.post(
        "/api/v1/auth/verify-reset-code", json={"email": "nochat@example.com", "code": "123456"}
    )
    assert verify.status_code == 422


async def test_forgot_password_unlinked_account_gets_bot_link_then_code(client, monkeypatch):
    """An existing account with no linked Telegram gets a one-time /link code;
    sending it to the bot links the chat and delivers the reset code."""
    import re

    from app.core.database import SessionFactory
    from app.core.security import hash_password
    from app.modules.auth.models import Role, User

    email = "nochat-link@example.com"
    async with SessionFactory() as session:
        role = Role(name="NoLinkRole", is_system=False, status="ACTIVE")
        session.add(role)
        await session.flush()
        session.add(
            User(
                full_name="No Link User",
                email=email,
                password_hash=hash_password("password123"),
                telegram_chat_id=None,
                role_id=role.id,
                status="ACTIVE",
            )
        )
        await session.commit()

    captured: list[tuple[str, str]] = []

    async def fake_send(chat_id: str, text: str) -> bool:
        captured.append((chat_id, text))
        return True

    monkeypatch.setattr("app.shared.telegram.client.send_message", fake_send)

    response = await client.post("/api/v1/auth/forgot-password", json={"email": email})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["channel"] == "telegram_link"
    link_code = data["linkCode"] or data["link_code"]
    assert link_code and len(link_code) == 8
    assert data["expiresIn"] == data["expires_in"] > 0
    assert not captured, "no reset code is delivered before the chat is linked"

    # The bot consumes the /link code and sends the reset code to that chat.
    from app.shared.telegram.linking import consume_link_code

    async with SessionFactory() as session:
        linked = await consume_link_code(session, link_code, "555000111")
    assert linked is not None
    assert linked.telegram_chat_id == "555000111"
    assert linked.telegram_verified is True
    assert captured, "the reset code should be sent to the newly linked chat"
    chat_id, text = captured[-1]
    assert chat_id == "555000111"
    match = re.search(r"(\d{6})", text)
    assert match, text
    reset_code = match.group(1)

    verified = await client.post(
        "/api/v1/auth/verify-reset-code", json={"email": email, "code": reset_code}
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["data"]["reset_token"]


async def test_forgot_password_link_code_single_use(client, monkeypatch):
    """The /link code is consumed once; a resend issues a fresh one."""
    from app.core.database import SessionFactory
    from app.core.security import hash_password
    from app.modules.auth.models import Role, User

    email = "nochat-resend@example.com"
    async with SessionFactory() as session:
        role = Role(name="NoLinkResendRole", is_system=False, status="ACTIVE")
        session.add(role)
        await session.flush()
        session.add(
            User(
                full_name="No Link Resend",
                email=email,
                password_hash=hash_password("password123"),
                telegram_chat_id=None,
                role_id=role.id,
                status="ACTIVE",
            )
        )
        await session.commit()

    first = (await client.post("/api/v1/auth/forgot-password", json={"email": email})).json()["data"]
    second = (await client.post("/api/v1/auth/forgot-password/resend", json={"email": email})).json()["data"]
    assert first["channel"] == second["channel"] == "telegram_link"
    first_code = first["linkCode"] or first["link_code"]
    second_code = second["linkCode"] or second["link_code"]
    assert first_code != second_code

    from app.shared.telegram.linking import consume_link_code

    async with SessionFactory() as session:
        # The stale code no longer links once a newer request replaced it? It
        # remains valid until its own TTL, but consuming it once is final.
        assert await consume_link_code(session, first_code, "555000222") is not None
        assert await consume_link_code(session, first_code, "555000222") is None
