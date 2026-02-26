"""Router for serving uploaded files."""

import io
import os
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from config import DATABASE_TYPE
from database import get_db
from auth import get_current_user, TokenData
from models import FileAttachment
from file_storage import FileStorageService, UPLOAD_DIR

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import FileAttachmentCollection

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/{file_id}")
async def get_file(
    file_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Serve an uploaded file by ID."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        attachment = await FileAttachmentCollection.find_by_id(mongo_db, file_id)
        if not attachment or attachment.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="File not found")
        gridfs_id = attachment.get("gridfs_file_id")
        if not gridfs_id:
            raise HTTPException(status_code=404, detail="File data not found")
        data = await FileStorageService.read_file_gridfs(mongo_db, gridfs_id)
        return StreamingResponse(
            io.BytesIO(data),
            media_type=attachment.get("media_type", "application/octet-stream"),
            headers={"Content-Disposition": f'inline; filename="{attachment["filename"]}"'},
        )

    attachment = db.query(FileAttachment).filter(
        FileAttachment.id == int(file_id),
        FileAttachment.user_id == int(current_user.user_id),
    ).first()
    if not attachment:
        raise HTTPException(status_code=404, detail="File not found")
    full_path = os.path.join(UPLOAD_DIR, attachment.storage_path)
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="File data not found")
    return FileResponse(full_path, media_type=attachment.media_type, filename=attachment.filename)
