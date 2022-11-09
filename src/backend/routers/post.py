from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from loguru import logger

from prisma.errors import PrismaError
from prisma.models import Post, PostComment
from src.backend.auth.sessions import AbstractSessionStorage
from src.backend.dependencies import get_sessions, is_authorized
from src.backend.models import PostCreateBody, PostDetails
from src.backend.paginate_db import Page, paginate

router = APIRouter(prefix="/post")


@router.get("/")
async def get_posts(
    take: int = Header(default=10),
    uid: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    cursor: str | None = Header(default=None),
) -> Page[Post]:
    """Paginate and get posts based on specified filters (user, tag etc).

    Expects pagination headers:
        take: The number of items to be retrieved in one page
        cursor: The ID of the last fetched item
    """
    filters = {}
    if uid:
        filters["author_id"] = uid
    if tag:
        filters["tag"] = {"tag_name": tag}
    filters["deleted"] = False
    return await paginate(Post, take, cursor, where=filters, order={"created_at": "desc"})


@router.get("/{id}", response_model=PostDetails)
async def get_post(id: str) -> PostDetails:
    """Get full details of a specific post."""
    post = await Post.prisma().find_first(
        where={"id": id, "deleted": False}, include={"tags": True, "media": True, "author": True}
    )
    if not post:
        raise HTTPException(404, "Post not found")
    comments = await paginate(
        PostComment, page_size=20, where={"post_id": id}, order={"created_at": "desc"}
    )
    return PostDetails(post=post, comments=comments)


@router.post("/create", response_model=Post)
async def create_post(
    post: PostCreateBody = Body(embed=True),
    user_id: UUID | None = Header(default=None),
    session_id: UUID | None = Header(default=None, alias="session-id"),
    sessions: AbstractSessionStorage = Depends(get_sessions),
) -> Post:
    """Create a new post."""
    await is_authorized(user_id, session_id, sessions)
    try:
        inserted_post = await Post.prisma().create(
            data={
                "author_id": str(user_id),
                "title": post.title,
                "text_content": post.text_content,
                "media": {"create": [{"object_url": url} for url in post.media]},
                "tags": {"connect": [{"tag_name": tname} for tname in post.tags]},
            }
        )
    except PrismaError as e:
        logger.warning(f"Could not create post: {e}")
        raise HTTPException(422, "Could not create the post due to an internal error")
    return inserted_post


@router.delete("/{id}")
async def delete_post(
    id: str,
    user_id: UUID | None = Header(default=None),
    session_id: UUID | None = Header(default=None, alias="session-id"),
    sessions: AbstractSessionStorage = Depends(get_sessions),
) -> JSONResponse:
    """Delete a post."""
    await is_authorized(user_id, session_id, sessions)
    try:
        # this endpoint only soft-deletes
        #
        deleted_post = await Post.prisma().update(data={"deleted": True}, where={"id": id})
    except PrismaError as e:
        logger.warning(f"Could not delete post: {e}")
        raise HTTPException(400, "Could not delete the post due to an internal error")
    if not deleted_post:
        return JSONResponse({"message": "Post did not exist"}, status_code=400)
    return JSONResponse({"message": "Post deleted"}, status_code=200)


@router.post("/{post_id}/comments", response_model=PostComment)
async def create_comment(
    post_id: str,
    comment_text: str = Body(),
    user_id: UUID | None = Header(default=None),
    session_id: UUID | None = Header(default=None),
    sessions: AbstractSessionStorage = Depends(get_sessions),
) -> PostComment:
    """Create a comment on the specified post."""
    await is_authorized(user_id, session_id, sessions)
    try:
        comment = await PostComment.prisma().create(
            data={
                "author_id": str(user_id),
                "post_id": post_id,
                "content": comment_text,
                "author": {"connect": {"id": str(user_id)}},
                "post": {"connect": {"id": post_id}},
            }
        )
    except PrismaError as e:
        logger.warning(f"Could not create comment: {e}")
        raise HTTPException(400, "Could not create the comment due to an internal error")
    return comment


@router.get("/{post_id}/comments")
async def get_comments(
    post_id: str, take: int = Header(default=10), cursor: str | None = Header(default=None)
) -> Page[PostComment]:
    """Paginate and get the comments of a post.

    Expects pagination headers:
        take: The number of items to be retrieved in one page
        cursor: The ID of the last fetched item
    """
    return await paginate(
        PostComment, take, cursor, where={"post_id": post_id}, order={"created_at": "desc"}
    )


@router.delete("/{post_id}/comments/{comment_id}")
async def delete_comment(
    post_id: str,
    comment_id: str,
    user_id: UUID | None = Header(default=None),
    session_id: UUID | None = Header(default=None, alias="session-id"),
    sessions: AbstractSessionStorage = Depends(get_sessions),
) -> JSONResponse:
    """Endpoint to delete a comment."""
    await is_authorized(user_id, session_id, sessions)
    try:
        deleted_comment = await PostComment.prisma().delete(where={"id": comment_id})
    except PrismaError as e:
        logger.warning(f"Could not delete comment: {e}")
        raise HTTPException(400, "Could not delete the comment due to an internal error")
    if not deleted_comment:
        return JSONResponse({"message": "Comment did not exist"}, status_code=400)
    return JSONResponse({"message": "Comment deleted"}, status_code=200)