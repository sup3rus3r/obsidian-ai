"""Knowledge Base CRUD + document management endpoints."""

import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from config import DATABASE_TYPE
from database import get_db
from models import KnowledgeBase, KnowledgeBaseDocument
from schemas import (
    KnowledgeBaseCreate, KnowledgeBaseUpdate, KnowledgeBaseResponse,
    KnowledgeBaseListResponse, KBDocumentCreate, KBDocumentResponse,
    KBDocumentListResponse,
)
from auth import get_current_user, TokenData, require_permission
from file_storage import FileStorageService
from rag_service import RAGService

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import KnowledgeBaseCollection, KBDocumentCollection

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _kb_to_response(kb, doc_count: int = 0, is_mongo: bool = False) -> KnowledgeBaseResponse:
    if is_mongo:
        return KnowledgeBaseResponse(
            id=str(kb["_id"]),
            name=kb["name"],
            description=kb.get("description"),
            is_shared=kb.get("is_shared", False),
            is_active=kb.get("is_active", True),
            document_count=doc_count,
            created_at=kb["created_at"],
        )
    return KnowledgeBaseResponse(
        id=str(kb.id),
        name=kb.name,
        description=kb.description,
        is_shared=kb.is_shared,
        is_active=kb.is_active,
        document_count=doc_count,
        created_at=kb.created_at,
    )


def _doc_to_response(doc, is_mongo: bool = False) -> KBDocumentResponse:
    if is_mongo:
        return KBDocumentResponse(
            id=str(doc["_id"]),
            kb_id=str(doc["kb_id"]),
            doc_type=doc["doc_type"],
            name=doc["name"],
            filename=doc.get("filename"),
            media_type=doc.get("media_type"),
            indexed=doc.get("indexed", False),
            created_at=doc["created_at"],
        )
    return KBDocumentResponse(
        id=str(doc.id),
        kb_id=str(doc.kb_id),
        doc_type=doc.doc_type,
        name=doc.name,
        filename=doc.filename,
        media_type=doc.media_type,
        indexed=doc.indexed,
        created_at=doc.created_at,
    )


def _can_access_kb(kb, current_user: TokenData, is_mongo: bool = False) -> bool:
    """Return True if user owns the KB or it's shared."""
    if is_mongo:
        return kb.get("user_id") == current_user.user_id or kb.get("is_shared", False)
    return kb.user_id == int(current_user.user_id) or kb.is_shared


def _owns_kb(kb, current_user: TokenData, is_mongo: bool = False) -> bool:
    if is_mongo:
        return kb.get("user_id") == current_user.user_id
    return kb.user_id == int(current_user.user_id)


# ---------------------------------------------------------------------------
# Knowledge Base CRUD
# ---------------------------------------------------------------------------

@router.post("", response_model=KnowledgeBaseResponse)
async def create_knowledge_base(
    data: KnowledgeBaseCreate,
    current_user: TokenData = Depends(get_current_user),
    _perm=Depends(require_permission("create_knowledge_bases")),
    db: Session = Depends(get_db),
):
    # Only admins may create shared knowledge bases
    if data.is_shared and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can create shared knowledge bases")

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        doc = {
            "user_id": current_user.user_id,
            "name": data.name,
            "description": data.description,
            "is_shared": data.is_shared,
        }
        created = await KnowledgeBaseCollection.create(mongo_db, doc)
        return _kb_to_response(created, is_mongo=True)

    kb = KnowledgeBase(
        user_id=int(current_user.user_id),
        name=data.name,
        description=data.description,
        is_shared=data.is_shared,
    )
    db.add(kb)
    db.commit()
    db.refresh(kb)
    return _kb_to_response(kb)


@router.get("", response_model=KnowledgeBaseListResponse)
async def list_knowledge_bases(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        kbs = await KnowledgeBaseCollection.find_accessible(mongo_db, current_user.user_id)
        result = []
        for kb in kbs:
            count = await KBDocumentCollection.count_for_kb(mongo_db, str(kb["_id"]))
            result.append(_kb_to_response(kb, doc_count=count, is_mongo=True))
        return KnowledgeBaseListResponse(knowledge_bases=result)

    from sqlalchemy import or_
    kbs = db.query(KnowledgeBase).filter(
        KnowledgeBase.is_active == True,
        or_(
            KnowledgeBase.user_id == int(current_user.user_id),
            KnowledgeBase.is_shared == True,
        ),
    ).all()

    result = []
    for kb in kbs:
        count = db.query(KnowledgeBaseDocument).filter(
            KnowledgeBaseDocument.kb_id == kb.id,
        ).count()
        result.append(_kb_to_response(kb, doc_count=count))
    return KnowledgeBaseListResponse(knowledge_bases=result)


@router.get("/{kb_id}", response_model=KnowledgeBaseResponse)
async def get_knowledge_base(
    kb_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        kb = await KnowledgeBaseCollection.find_by_id(mongo_db, kb_id)
        if not kb or not _can_access_kb(kb, current_user, is_mongo=True):
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        count = await KBDocumentCollection.count_for_kb(mongo_db, kb_id)
        return _kb_to_response(kb, doc_count=count, is_mongo=True)

    from sqlalchemy import or_
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == int(kb_id),
        KnowledgeBase.is_active == True,
        or_(
            KnowledgeBase.user_id == int(current_user.user_id),
            KnowledgeBase.is_shared == True,
        ),
    ).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    count = db.query(KnowledgeBaseDocument).filter(KnowledgeBaseDocument.kb_id == kb.id).count()
    return _kb_to_response(kb, doc_count=count)


@router.put("/{kb_id}", response_model=KnowledgeBaseResponse)
async def update_knowledge_base(
    kb_id: str,
    data: KnowledgeBaseUpdate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if data.is_shared is True and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can make knowledge bases shared")

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        kb = await KnowledgeBaseCollection.find_by_id(mongo_db, kb_id)
        if not kb or not _owns_kb(kb, current_user, is_mongo=True):
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        updates = data.model_dump(exclude_unset=True)
        updated = await KnowledgeBaseCollection.update(mongo_db, kb_id, current_user.user_id, updates)
        count = await KBDocumentCollection.count_for_kb(mongo_db, kb_id)
        return _kb_to_response(updated, doc_count=count, is_mongo=True)

    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == int(kb_id),
        KnowledgeBase.user_id == int(current_user.user_id),
        KnowledgeBase.is_active == True,
    ).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(kb, key, value)
    db.commit()
    db.refresh(kb)
    count = db.query(KnowledgeBaseDocument).filter(KnowledgeBaseDocument.kb_id == kb.id).count()
    return _kb_to_response(kb, doc_count=count)


@router.delete("/{kb_id}")
async def delete_knowledge_base(
    kb_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        kb = await KnowledgeBaseCollection.find_by_id(mongo_db, kb_id)
        if not kb or not _owns_kb(kb, current_user, is_mongo=True):
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        await KnowledgeBaseCollection.delete(mongo_db, kb_id, current_user.user_id)
        RAGService.delete_kb_index(kb_id)
        return {"message": "Knowledge base deleted"}

    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == int(kb_id),
        KnowledgeBase.user_id == int(current_user.user_id),
        KnowledgeBase.is_active == True,
    ).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    kb.is_active = False
    db.commit()
    RAGService.delete_kb_index(kb_id)
    return {"message": "Knowledge base deleted"}


# ---------------------------------------------------------------------------
# Document endpoints
# ---------------------------------------------------------------------------

@router.get("/{kb_id}/documents", response_model=KBDocumentListResponse)
async def list_documents(
    kb_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        kb = await KnowledgeBaseCollection.find_by_id(mongo_db, kb_id)
        if not kb or not _can_access_kb(kb, current_user, is_mongo=True):
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        docs = await KBDocumentCollection.find_by_kb(mongo_db, kb_id)
        return KBDocumentListResponse(documents=[_doc_to_response(d, is_mongo=True) for d in docs])

    from sqlalchemy import or_
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == int(kb_id),
        KnowledgeBase.is_active == True,
        or_(
            KnowledgeBase.user_id == int(current_user.user_id),
            KnowledgeBase.is_shared == True,
        ),
    ).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    docs = db.query(KnowledgeBaseDocument).filter(
        KnowledgeBaseDocument.kb_id == kb.id,
    ).all()
    return KBDocumentListResponse(documents=[_doc_to_response(d) for d in docs])


@router.post("/{kb_id}/documents", response_model=KBDocumentResponse)
async def add_document(
    kb_id: str,
    data: KBDocumentCreate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        kb = await KnowledgeBaseCollection.find_by_id(mongo_db, kb_id)
        if not kb or not _can_access_kb(kb, current_user, is_mongo=True):
            raise HTTPException(status_code=404, detail="Knowledge base not found")

        file_id = None
        text_to_index = ""

        if data.doc_type == "text":
            if not data.content_text:
                raise HTTPException(status_code=400, detail="content_text required for text documents")
            text_to_index = data.content_text
        elif data.doc_type == "file":
            if not data.file_data or not data.filename:
                raise HTTPException(status_code=400, detail="file_data and filename required for file documents")
            file_bytes, _ = FileStorageService.decode_data_uri(data.file_data)
            file_id = await FileStorageService.save_file_gridfs(
                mongo_db, data.filename, file_bytes,
                {"kb_id": kb_id, "doc_name": data.name},
            )
            loop = asyncio.get_event_loop()
            text_to_index = await loop.run_in_executor(
                None, RAGService.extract_text, file_bytes, data.filename, data.media_type or ""
            )
        else:
            raise HTTPException(status_code=400, detail="doc_type must be 'text' or 'file'")

        indexed = False
        if text_to_index.strip():
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, RAGService.index_kb_document, kb_id, text_to_index,
                {"doc_name": data.name, "filename": data.filename},
            )
            indexed = True

        doc_rec = {
            "kb_id": kb_id,
            "doc_type": data.doc_type,
            "name": data.name,
            "content_text": data.content_text if data.doc_type == "text" else None,
            "file_id": file_id,
            "filename": data.filename,
            "media_type": data.media_type,
            "indexed": indexed,
        }
        created = await KBDocumentCollection.create(mongo_db, doc_rec)
        return _doc_to_response(created, is_mongo=True)

    # SQLite path
    from sqlalchemy import or_
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == int(kb_id),
        KnowledgeBase.is_active == True,
        or_(
            KnowledgeBase.user_id == int(current_user.user_id),
            KnowledgeBase.is_shared == True,
        ),
    ).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    file_id = None
    text_to_index = ""

    if data.doc_type == "text":
        if not data.content_text:
            raise HTTPException(status_code=400, detail="content_text required for text documents")
        text_to_index = data.content_text
    elif data.doc_type == "file":
        if not data.file_data or not data.filename:
            raise HTTPException(status_code=400, detail="file_data and filename required for file documents")
        file_bytes, _ = FileStorageService.decode_data_uri(data.file_data)
        file_id = FileStorageService.save_file_sqlite(f"kb_{kb_id}", data.filename, file_bytes)
        loop = asyncio.get_event_loop()
        text_to_index = await loop.run_in_executor(
            None, RAGService.extract_text, file_bytes, data.filename, data.media_type or ""
        )
    else:
        raise HTTPException(status_code=400, detail="doc_type must be 'text' or 'file'")

    indexed = False
    if text_to_index.strip():
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, RAGService.index_kb_document, kb_id, text_to_index,
            {"doc_name": data.name, "filename": data.filename},
        )
        indexed = True

    doc = KnowledgeBaseDocument(
        kb_id=int(kb_id),
        doc_type=data.doc_type,
        name=data.name,
        content_text=data.content_text if data.doc_type == "text" else None,
        file_id=file_id,
        filename=data.filename,
        media_type=data.media_type,
        indexed=indexed,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return _doc_to_response(doc)


@router.delete("/{kb_id}/documents/{doc_id}")
async def delete_document(
    kb_id: str,
    doc_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        kb = await KnowledgeBaseCollection.find_by_id(mongo_db, kb_id)
        if not kb or not _owns_kb(kb, current_user, is_mongo=True):
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        await KBDocumentCollection.delete(mongo_db, doc_id)
        return {"message": "Document deleted"}

    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == int(kb_id),
        KnowledgeBase.user_id == int(current_user.user_id),
        KnowledgeBase.is_active == True,
    ).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    doc = db.query(KnowledgeBaseDocument).filter(
        KnowledgeBaseDocument.id == int(doc_id),
        KnowledgeBaseDocument.kb_id == int(kb_id),
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    db.delete(doc)
    db.commit()
    return {"message": "Document deleted"}
