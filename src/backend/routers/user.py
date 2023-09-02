from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from loguru import logger
from passlib.hash import argon2

from prisma.errors import PrismaError, RecordNotFoundError
from prisma.models import Follower, Password, Post, User
from prisma.partials import UserProfile
from src.backend.auth.sessions import AbstractSessionStorage
from src.backend.dependencies import get_sessions, is_authorized
from src.backend.models import (
    LoginSuccessResponse,
    MessageResponse,
    UserInLogin,
    UserInSignup,
    UserProfileResponse,
)
from src.backend.paginate_db import paginate

router = APIRouter(prefix="/user", tags=["user"])
COOKIE_MAX_AGE = 30 * 24 * 60 * 60  # 2592000 seconds (30 days)


async def hash_password(password: str) -> str:
    """Returns hash of the password."""
    logger.trace("Creating password hash.")
    return argon2.using(rounds=4).hash(password)


async def check_password(password: str, hash_: str) -> bool:
    """Compares salted-hash against hash of user-inputted password."""
    logger.trace("Checking if the password hashes match.")
    return argon2.verify(password, hash_)


async def set_session(
    user_profile: UserProfile, sessions: AbstractSessionStorage, message: str
) -> LoginSuccessResponse:
    """Creates session and sets cookie."""
    session = await sessions.create_session(UUID(user_profile.id))
    return LoginSuccessResponse(
        **{"session-id": str(session.id), "user": user_profile, "message": message}
    )


@router.post("/signup")
async def signup(
    user_login: UserInSignup = Body(),
    sessions: AbstractSessionStorage = Depends(get_sessions),
) -> LoginSuccessResponse:
    """Endpoint to sign up a user.

    Returns session id and user details if authentication is successful.
    """
    username = user_login.username
    password = user_login.password
    email = user_login.email

    user: User | None = await User.prisma().find_first(
        where={"OR": [{"username": username}, {"email": email}]}
    )
    if user is not None:
        logger.debug("Sign up attempted with username or email which already exists.")
        raise HTTPException(status_code=409, detail="The username or email already exists")

    user = await User.prisma().create(data={"username": username, "email": email})
    # as the password is in a separate table we need a separate insert statement here,
    await Password.prisma().create(
        {"user": {"connect": {"id": user.id}}, "password": await hash_password(password)}
    )
    user_profile = UserProfile(**user.dict())
    response = await set_session(user_profile, sessions, message="Account created.")

    logger.info(
        f"Account {user_profile.username}({user_profile.id}) successfully created."
        f"\nSession {response.session_id} successfully created"
    )
    return response


@router.post("/login")
async def login(
    user_login: UserInLogin,
    session_id: UUID | None = Header(default=None, alias="session-id"),
    sessions: AbstractSessionStorage = Depends(get_sessions),
) -> LoginSuccessResponse:
    """Endpoint to authenticate a user. Validation is done on form data before querying DB.

    Returns session id and user details if authentication is successful.
    """
    username = user_login.username
    password = user_login.password

    user: User | None = await User.prisma().find_first(where={"username": username})
    if user is None:
        raise HTTPException(status_code=404, detail="The username or password is incorrect.")
    db_pw = await Password.prisma().find_first(where={"user_id": user.id})
    # this case should NEVER happen, but we include it here for type-safety
    if db_pw is None:
        logger.error(
            f"Attempted logging in {username=} who does not have a password saved in the database."
        )
        raise HTTPException(status_code=404, detail="User exists but does not have a password")
    if not await check_password(password, db_pw.password):
        raise HTTPException(status_code=404, detail="The username or password is incorrect.")
    user_profile = UserProfile(**user.dict())
    response = await set_session(user_profile, sessions, message="Successfully logged in.")

    if session_id is not None and session_id in sessions:  # Checking for duplicate session.
        await sessions.delete_session(session_id)
        logger.warning(f"Deleted session {session_id} since a new session has been created.")

    logger.info(
        f"Session {response.session_id} successfully created"
        f" for {user_profile.username}({user_profile.id})."
    )
    return response


@router.post("/logout")
async def logout(
    user_id: Annotated[UUID, Depends(is_authorized)],
    session_id: UUID = Header(default=None),
    sessions: AbstractSessionStorage = Depends(get_sessions),
) -> MessageResponse:
    """Endpoint to log out a user. The header must include session-id.

    Session is deleted from session storage. Client has to delete session cookie.
    """
    await sessions.delete_session(session_id)
    return MessageResponse(message=f"Session {session_id} deleted.")


@router.get("/{user_id}", response_model=UserProfileResponse)
async def get_user(
    user_id: str,
    session_id: UUID | None = Header(default=None, alias="session-id"),
    sessions: AbstractSessionStorage = Depends(get_sessions),
) -> UserProfileResponse:
    """Endpoint to get a user's data.

    Returns user profile data (including number of followers, following, posts).
    """
    user = await User.prisma().find_first(where={"id": user_id})
    if not user:
        logger.debug(f"User {user_id} not found")
        raise HTTPException(status_code=404, detail="User not found.")
    followers = await Follower.prisma().count(where={"follows_id": user_id})
    following = await Follower.prisma().count(where={"user_id": user_id})
    posts = await paginate(Post, page_size=10, where={"author_id": user_id})
    posts_count = await Post.prisma().count(where={"author_id": user_id})
    if session_id:
        current_user = await sessions.get_session(session_id)
        if not current_user:
            raise HTTPException(401, "Invalid session ID sent.")
        is_following = (
            await Follower.prisma().find_first(
                where={"user_id": str(current_user.user_id), "follows_id": user.id}
            )
            is not None
        )
    else:
        is_following = None
    data = {
        **user.dict(
            exclude={
                "posts",
                "post_ratings",
                "comments",
                "reports",
                "follows",
                "password",
                "followers",
            }
        ),
        "follower_count": followers,
        "following_count": following,
        "posts": posts,
        "is_following": is_following,
        "posts_count": posts_count,
    }
    return UserProfileResponse(**data)


@router.get("/{uid}/followers")
async def get_user_followers(uid: str) -> list[Follower]:
    """Get the specified user's followers."""
    followers = await Follower.prisma().find_many(where={"follows_id": uid})
    return followers


@router.post("/{uid}/follow")
async def follow_user(
    user_id: Annotated[UUID, Depends(is_authorized)],
    uid: str,
) -> Follower:
    """Add the currently logged in user as a follower to user <uid>."""
    if uid == str(user_id):
        raise HTTPException(status_code=400, detail="User cannot follow themself.")

    try:
        follow_record = await Follower.prisma().create(
            data={
                "follows": {"connect": {"id": uid}},
                "user": {"connect": {"id": str(user_id)}},
            }
        )
    except RecordNotFoundError:
        logger.info("Invalid followee User ID provided.")
        raise HTTPException(
            status_code=404, detail="The user you are trying to follow does not exist."
        )
    except PrismaError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return follow_record


@router.post("/{uid}/unfollow")
async def unfollow_user(
    user_id: Annotated[UUID, Depends(is_authorized)],
    uid: str,
) -> Follower:
    """Make the currently logged in user unfollow user <uid>."""
    if uid == user_id:
        raise HTTPException(status_code=422, detail="User cannot unfollow themself.")
    try:
        deleted_record = await Follower.prisma().delete(
            where={"user_id_follows_id": {"follows_id": uid, "user_id": str(user_id)}}
        )
    except PrismaError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if not deleted_record:
        raise HTTPException(status_code=422, detail=f"User {user_id} wasn't following {uid}")
    return deleted_record
