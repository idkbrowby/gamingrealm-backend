from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from httpx import AsyncClient

from prisma import Prisma
from prisma.models import User
from src.backend.models import UserInLogin, UserInSignup
from src.backend.routers.user import hash_password

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="package")
@pytest.mark.anyio
async def user1(db: Prisma) -> AsyncGenerator[User, None]:
    user = await db.user.create(
        {
            "username": "johndoe",
            "email": "johndoe@company.org",
        }
    )
    await db.password.create(
        {"user": {"connect": {"id": user.id}}, "password": await hash_password("password12")}
    )
    yield user
    await db.user.delete(where={"id": user.id})


@pytest.fixture(scope="package")
@pytest.mark.anyio
async def user2(db: Prisma) -> AsyncGenerator[User, None]:
    user = await db.user.create(
        {
            "username": "genericuser",
            "email": "user@megacorp.org",
        }
    )
    await db.password.create(
        {"user": {"connect": {"id": user.id}}, "password": await hash_password("supersafe!")}
    )
    yield user
    await db.user.delete(where={"id": user.id})


@pytest.fixture(scope="package")
@pytest.mark.anyio
async def logged_in_user(
    client: AsyncClient, user1: User
) -> AsyncGenerator[tuple[User, str], None]:
    data = UserInLogin(username=user1.username, password="password12")
    res = await client.post("/user/login", json=data.dict())
    response_data = res.json()
    yield user1, response_data["session-id"]
    await client.post("/user/logout", headers={"session-id": response_data["session-id"]})


async def test_new_user_sign_up(client: AsyncClient):
    # we can safely just forget about this user - none of the other tests should depend on it
    # otherwise we'd need to do cleanup here (call signout) but that's for another test
    data = UserInSignup(username="newusuer", password="i<3blockchain", email="foo@bar.com")
    # the email field in the UserInSignup is type hinted as EmailStr as it is a pydantic validator
    # so passing in a string here is making pyright complain.
    res = await client.post("/user/signup", json=data.dict())
    assert res.status_code == 200
    response_data = res.json()
    assert response_data.get("session-id")


async def test_existing_user_cant_signup(client: AsyncClient, user1: User):
    data = UserInSignup(username=user1.username, password="password12", email=user1.email)
    res = await client.post("/user/signup", json=data.dict())
    assert res.status_code == 409


async def test_existing_user_can_login(client: AsyncClient, user1: User):
    data = UserInLogin(username=user1.username, password="password12")
    res = await client.post("/user/login", json=data.dict())
    assert res.status_code == 200
    response_data = res.json()
    assert response_data.get("session-id")
    await client.post("/user/logout", headers={"session-id": response_data["session-id"]})


async def test_non_existent_user_cant_login(client: AsyncClient):
    data = UserInLogin(username="nonexistent", password="bruhwhat?")
    res = await client.post("/user/login", json=data.dict())
    assert res.status_code == 404


async def test_get_non_existent_user(client: AsyncClient):
    # what if it generates an ID that already exists in the database? :p
    res = await client.get(f"/user/{uuid4()}")
    assert res.status_code == 404


async def test_get_user(client: AsyncClient, user1: User):
    res = await client.get(f"/user/{user1.id}")
    assert res.status_code == 200
    data = res.json()
    assert data.get("id") == user1.id
    assert data.get("is_following") is None


async def test_get_user_while_logged_in(
    client: AsyncClient, logged_in_user: tuple[User, str], user2: User
):
    # get user2 data while logged in as user1
    # here the is_following field should be set to False
    user, session = logged_in_user
    res = await client.get(f"/user/{user2.id}", headers={"session-id": session})
    assert res.status_code == 200
    assert res.json()["is_following"] is False


# test_x_authz_route_y is for testing the is_authorized dependency
async def test_authz_route_no_headers(client: AsyncClient):
    res = await client.post(f"/user/{uuid4()}/follow")
    assert res.status_code == 422


async def test_authz_route_invalid_session(client: AsyncClient):
    res = await client.post(f"/user/{uuid4()}/follow", headers={"session-id": str(uuid4())})
    assert res.status_code == 403


"""
async def test_get_user_followers(client: AsyncClient, user3: User, follows_user3: User):
    res = await client.get(f"/user/{user3.id}/followers")
    data = res.json()
    assert res.status_code == 200
    assert isinstance(data, list)
    assert data[0]["follows_id"] == user3.id
    assert data[0]["user_id"] == follows_user3.id
"""


async def test_get_user_followers_empty_response(client: AsyncClient, user1: User):
    res = await client.get(f"/user/{user1.id}/followers")
    data = res.json()
    assert res.status_code == 200
    assert len(data) == 0


async def test_get_non_existent_user_followers(client: AsyncClient):
    # the API just returns an empty list in this case also - should we error?
    res = await client.get(f"/user/{uuid4()}/followers")
    data = res.json()
    assert res.status_code == 200
    assert len(data) == 0


async def test_follow_user(
    client: AsyncClient, db: Prisma, user2: User, logged_in_user: tuple[User, str]
):
    follower, session = logged_in_user
    res = await client.post(f"/user/{user2.id}/follow", headers={"session-id": session})
    assert res.status_code == 200
    get_followers_res = await client.get(f"/user/{user2.id}/followers")
    follower_ids = [f["user_id"] for f in get_followers_res.json()]
    assert follower.id in follower_ids
    # cleanup
    await db.follower.delete(
        {"user_id_follows_id": {"follows_id": user2.id, "user_id": follower.id}}
    )


async def test_follow_non_existent_user(client: AsyncClient, logged_in_user: tuple[User, str]):
    follower, session = logged_in_user
    res = await client.post(f"/user/{uuid4()}/follow", headers={"session-id": session})
    assert res.status_code == 404


async def test_follow_self(client: AsyncClient, logged_in_user: tuple[User, str]):
    follower, session = logged_in_user
    res = await client.post(f"/user/{follower.id}/follow", headers={"session-id": session})
    assert res.status_code == 400
