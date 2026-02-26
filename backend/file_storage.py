"""File storage abstraction for both SQLite (filesystem) and MongoDB (GridFS) modes."""

import os
import base64
import uuid

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")


class FileStorageService:

    @staticmethod
    def ensure_upload_dir():
        os.makedirs(UPLOAD_DIR, exist_ok=True)

    @staticmethod
    def decode_data_uri(data_uri: str) -> tuple[bytes, str]:
        """Decode a base64 data URI. Returns (bytes, media_type)."""
        # data:image/png;base64,iVBOR...
        header, encoded = data_uri.split(",", 1)
        media_type = header.split(":")[1].split(";")[0]
        return base64.b64decode(encoded), media_type

    @staticmethod
    def save_file_sqlite(session_id: str, filename: str, data_bytes: bytes) -> str:
        """Save file to filesystem. Returns relative storage path."""
        FileStorageService.ensure_upload_dir()
        session_dir = os.path.join(UPLOAD_DIR, str(session_id))
        os.makedirs(session_dir, exist_ok=True)
        safe_name = f"{uuid.uuid4().hex}_{filename}"
        filepath = os.path.join(session_dir, safe_name)
        with open(filepath, "wb") as f:
            f.write(data_bytes)
        return os.path.relpath(filepath, UPLOAD_DIR)

    @staticmethod
    def read_file_sqlite(storage_path: str) -> bytes:
        """Read file from filesystem."""
        full_path = os.path.join(UPLOAD_DIR, storage_path)
        with open(full_path, "rb") as f:
            return f.read()

    @staticmethod
    async def save_file_gridfs(mongo_db, filename: str, data_bytes: bytes, metadata: dict) -> str:
        """Save file to GridFS. Returns the GridFS file_id as string."""
        from motor.motor_asyncio import AsyncIOMotorGridFSBucket
        fs = AsyncIOMotorGridFSBucket(mongo_db)
        file_id = await fs.upload_from_stream(filename, data_bytes, metadata=metadata)
        return str(file_id)

    @staticmethod
    async def read_file_gridfs(mongo_db, file_id: str) -> bytes:
        """Read file from GridFS."""
        from motor.motor_asyncio import AsyncIOMotorGridFSBucket
        from bson import ObjectId
        fs = AsyncIOMotorGridFSBucket(mongo_db)
        grid_out = await fs.open_download_stream(ObjectId(file_id))
        return await grid_out.read()
