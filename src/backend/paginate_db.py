"""Functions to paginate queries to the database."""
from typing import Callable, Generic, Type, TypeVar

from loguru import logger
from pydantic.generics import GenericModel

from prisma.models import Post, PostComment, User

_ModelT = TypeVar("_ModelT", User, Post, PostComment)


class Page(GenericModel, Generic[_ModelT]):
    """Represents a page of database objects.

    The cursor_id is Null if the query returned no responses.
    """

    data: list[_ModelT]
    count: int
    cursor_id: str | None


async def paginate(
    model: Type[_ModelT],
    page_size: int,
    cursor_id: str | None = None,
    f: Callable[[_ModelT], _ModelT] | None = None,
    **kwargs,
) -> Page[_ModelT]:
    """Make a paginated database query.

    Args:
        model: The model to query with
        page_size: The number of elements to return per page
        cursor_id: ID for an object to be used as a cursor
        f: A function to be applied to every object that was returned by the query
           This can be used to modify and filter the resultset.
        **kwargs: Keyword arguments to pass to Model.prisma().find_many
    Returns:
        Page
    """
    if cursor_id:
        logger.info(f"Making page query: {model}, page size={page_size}")
        data = await model.prisma().find_many(
            take=page_size, cursor={"id": cursor_id}, skip=1, **kwargs
        )
    else:
        data = await model.prisma().find_many(take=page_size, **kwargs)
    if f:
        data = list(map(f, data))  # type: ignore
    try:
        new_cursor_id = data[-1].id
    except IndexError:
        new_cursor_id = None
    if cursor_id == new_cursor_id:
        # the query is just returning the last record over and over now
        # return an empty set
        return Page(data=[], count=0, cursor_id=None)
    return Page(data=data, count=len(data), cursor_id=new_cursor_id)  # type: ignore
