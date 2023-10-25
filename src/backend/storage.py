import os
import posixpath
import uuid
from typing import Literal

import httpx
from dotenv import load_dotenv
from fastapi import HTTPException, UploadFile
from storage3 import AsyncStorageClient, create_client
from storage3.utils import StorageException

ALLOWED_MIMETYPES = {"image/jpeg", "image/png"}
MAX_SIZE = 50 * 2**20  # 50 MB
BUCKET_NAME = "user-post"

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_API_KEY = os.getenv("SUPABASE_API_KEY")
BUCKET_NAME = os.getenv("SUPABASE_BUCKET_NAME", BUCKET_NAME)
headers = {"apiKey": SUPABASE_API_KEY, "Authorization": f"Bearer {SUPABASE_API_KEY}"}

storage_client: AsyncStorageClient = create_client(
    SUPABASE_URL, headers=headers, is_async=True
)  # type:ignore


def _validate_file(file: UploadFile) -> Literal[True]:
    if file.filename is None:
        raise HTTPException(status_code=400, detail="No filename provided.")
    if file.size is not None and file.size > MAX_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File '{file.filename}' exceeds the maximum allowed size of {MAX_SIZE}.",
        )
    if file.content_type not in ALLOWED_MIMETYPES:
        raise HTTPException(status_code=415, detail=f"Invalid file type for '{file.filename}'.")
    return True


async def _upload_to_storage(files: list[UploadFile], destination: str) -> list[str]:
    for file in files:
        _validate_file(file)

    urls = []
    filenames = set()
    for file in files:
        # Checking for duplicate filenames.
        filename = file.filename
        if filename in filenames:
            root, ext = os.path.splitext(filename)
            filename = f"{root}-{uuid.uuid4().hex}{ext}"
        filenames.add(filename)

        try:
            path = posixpath.join(destination, filename)
            file_options = {"content-type": file.content_type}
            res = await storage_client.from_(BUCKET_NAME).upload(
                path, await file.read(), file_options=file_options  # type: ignore
            )
        except StorageException as e:
            error_details = e.args[0]
            raise HTTPException(
                status_code=error_details["statusCode"], detail=error_details["message"]
            )
        except httpx.ConnectError:
            raise HTTPException(
                status_code=503,
                detail="Post could not be uploaded as object storage is not reachable.",
            )
        else:
            _, path = res.json()["Key"].split("/", 1)
            urls.append(await storage_client.from_(BUCKET_NAME).get_public_url(path))

    return urls
