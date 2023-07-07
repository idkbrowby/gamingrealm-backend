import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


# uh did we decide to not do tags...?
async def test_get_tags(client: AsyncClient):
    res = await client.get("/tags")
    # shouldn't this give an empty list response as json body?
    # why is it an empty string
    assert len(res.text) == 0
