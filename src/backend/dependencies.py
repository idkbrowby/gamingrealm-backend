from uuid import UUID

from fastapi import Depends, Header, HTTPException
from loguru import logger

from src.backend.auth.sessions import AbstractSessionStorage, InMemorySessionStorage, Session

_sessions = InMemorySessionStorage()


async def get_sessions() -> AbstractSessionStorage:
    """Returns session storage object."""
    return _sessions


async def is_authorized(
    session_id: UUID = Header(alias="session-id"),
    sessions: AbstractSessionStorage = Depends(get_sessions),
) -> UUID:
    """The headers must session-id."""
    logger.trace(f"Attempting authorization with session id: {session_id}")

    session: Session | None = await sessions.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=403, detail="Invalid session id or session has expired.")

    return session.user_id
