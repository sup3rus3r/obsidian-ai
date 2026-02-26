"""Per-session RAG with LEANN (Linux/macOS) or FAISS (Windows) backend."""

import io
import json
import os
import sys
import logging
import pickle
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

INDEX_DIR = os.path.join(os.path.dirname(__file__), "rag_indexes")

USE_FAISS = sys.platform == "win32"


# ---------------------------------------------------------------------------
# FAISS backend helpers (Windows)
# ---------------------------------------------------------------------------

_faiss_model = None


def _get_faiss_model():
    """Lazy-load the sentence-transformers model once."""
    global _faiss_model
    if _faiss_model is None:
        from sentence_transformers import SentenceTransformer
        _faiss_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _faiss_model


class _FaissIndex:
    """Simple wrapper around a FAISS flat index + metadata store."""

    def __init__(self):
        self.texts: list[str] = []
        self.metadatas: list[dict] = []
        self.index = None  # faiss.IndexFlatIP

    # -- persistence ----------------------------------------------------------

    def save(self, path: str):
        import faiss
        os.makedirs(os.path.dirname(path), exist_ok=True)
        faiss.write_index(self.index, path)
        meta_path = path + ".meta"
        with open(meta_path, "wb") as f:
            pickle.dump({"texts": self.texts, "metadatas": self.metadatas}, f)

    @classmethod
    def load(cls, path: str) -> "_FaissIndex":
        import faiss
        obj = cls()
        obj.index = faiss.read_index(path)
        meta_path = path + ".meta"
        with open(meta_path, "rb") as f:
            data = pickle.load(f)
        obj.texts = data["texts"]
        obj.metadatas = data["metadatas"]
        return obj

    # -- operations -----------------------------------------------------------

    def add(self, texts: list[str], metadatas: list[dict]):
        import faiss
        model = _get_faiss_model()
        embeddings = model.encode(texts, normalize_embeddings=True)
        embeddings = np.asarray(embeddings, dtype="float32")

        if self.index is None:
            dim = embeddings.shape[1]
            self.index = faiss.IndexFlatIP(dim)

        self.index.add(embeddings)
        self.texts.extend(texts)
        self.metadatas.extend(metadatas)

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        if self.index is None or self.index.ntotal == 0:
            return []
        model = _get_faiss_model()
        q_emb = model.encode([query], normalize_embeddings=True)
        q_emb = np.asarray(q_emb, dtype="float32")
        scores, indices = self.index.search(q_emb, min(top_k, self.index.ntotal))
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue
            results.append({
                "text": self.texts[idx],
                "score": float(score),
                "metadata": self.metadatas[idx],
            })
        return results


# ---------------------------------------------------------------------------
# RAGService
# ---------------------------------------------------------------------------


class RAGService:

    @staticmethod
    def _index_path(session_id: str) -> str:
        os.makedirs(INDEX_DIR, exist_ok=True)
        ext = ".faiss" if USE_FAISS else ".leann"
        return os.path.join(INDEX_DIR, f"session_{session_id}{ext}")

    @staticmethod
    def has_index(session_id: str) -> bool:
        return os.path.exists(RAGService._index_path(session_id))

    # -- indexing -------------------------------------------------------------

    @staticmethod
    def index_document(session_id: str, text: str, metadata: dict):
        """Chunk text and add to the session's vector index."""
        path = RAGService._index_path(session_id)
        chunks = RAGService._chunk_text(text, chunk_size=500, overlap=50)

        if USE_FAISS:
            if os.path.exists(path):
                idx = _FaissIndex.load(path)
            else:
                idx = _FaissIndex()
            chunk_metas = [{**metadata, "chunk_index": i} for i, _ in enumerate(chunks)]
            idx.add(chunks, chunk_metas)
            idx.save(path)
        else:
            from leann.api import LeannBuilder
            builder = LeannBuilder(backend_name="hnsw")
            for i, chunk in enumerate(chunks):
                chunk_meta = {**metadata, "chunk_index": i}
                builder.add_text(chunk, metadata=chunk_meta)
            if os.path.exists(path):
                builder.update_index(path)
            else:
                builder.build_index(path)

    # -- search ---------------------------------------------------------------

    @staticmethod
    def search(session_id: str, query: str, top_k: int = 5) -> list[dict]:
        """Search the session's vector index."""
        path = RAGService._index_path(session_id)
        if not os.path.exists(path):
            return []

        try:
            if USE_FAISS:
                idx = _FaissIndex.load(path)
                return idx.search(query, top_k=top_k)
            else:
                from leann.api import LeannSearcher
                searcher = LeannSearcher(path)
                results = searcher.search(query, top_k=top_k)
                out = [
                    {"text": r.text, "score": r.score, "metadata": r.metadata}
                    for r in results
                ]
                searcher.cleanup()
                return out
        except Exception as e:
            logger.warning(f"RAG search failed for session {session_id}: {e}")
            return []

    # -- text extraction ------------------------------------------------------

    @staticmethod
    def extract_text(file_bytes: bytes, filename: str, media_type: str) -> str:
        """Extract plain text from a document file."""
        lower = filename.lower()

        if media_type == "text/plain" or lower.endswith(".txt"):
            return file_bytes.decode("utf-8", errors="replace")

        if media_type == "text/markdown" or lower.endswith(".md"):
            return file_bytes.decode("utf-8", errors="replace")

        if media_type == "application/pdf" or lower.endswith(".pdf"):
            try:
                import pdfplumber
                with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                    return "\n".join(page.extract_text() or "" for page in pdf.pages)
            except ImportError:
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(file_bytes))
                return "\n".join(page.extract_text() or "" for page in reader.pages)

        if lower.endswith(".docx"):
            try:
                import docx
                doc = docx.Document(io.BytesIO(file_bytes))
                return "\n".join(para.text for para in doc.paragraphs)
            except ImportError:
                logger.warning("python-docx not installed, cannot extract DOCX text")
                return ""

        return ""

    # -- knowledge base (persistent, agent-scoped) ----------------------------

    @staticmethod
    def _kb_index_path(kb_id: str) -> str:
        os.makedirs(INDEX_DIR, exist_ok=True)
        ext = ".faiss" if USE_FAISS else ".leann"
        return os.path.join(INDEX_DIR, f"kb_{kb_id}{ext}")

    @staticmethod
    def has_kb_index(kb_id: str) -> bool:
        return os.path.exists(RAGService._kb_index_path(kb_id))

    @staticmethod
    def index_kb_document(kb_id: str, text: str, metadata: dict):
        """Chunk text and add to the knowledge base's persistent vector index."""
        path = RAGService._kb_index_path(kb_id)
        chunks = RAGService._chunk_text(text, chunk_size=500, overlap=50)
        if not chunks:
            return

        if USE_FAISS:
            if os.path.exists(path):
                idx = _FaissIndex.load(path)
            else:
                idx = _FaissIndex()
            chunk_metas = [{**metadata, "chunk_index": i} for i, _ in enumerate(chunks)]
            idx.add(chunks, chunk_metas)
            idx.save(path)
        else:
            from leann.api import LeannBuilder
            builder = LeannBuilder(backend_name="hnsw")
            for i, chunk in enumerate(chunks):
                chunk_meta = {**metadata, "chunk_index": i}
                builder.add_text(chunk, metadata=chunk_meta)
            if os.path.exists(path):
                builder.update_index(path)
            else:
                builder.build_index(path)

    @staticmethod
    def search_kb(kb_id: str, query: str, top_k: int = 5) -> list[dict]:
        """Search a knowledge base's vector index."""
        path = RAGService._kb_index_path(kb_id)
        if not os.path.exists(path):
            return []

        try:
            if USE_FAISS:
                idx = _FaissIndex.load(path)
                return idx.search(query, top_k=top_k)
            else:
                from leann.api import LeannSearcher
                searcher = LeannSearcher(path)
                results = searcher.search(query, top_k=top_k)
                out = [
                    {"text": r.text, "score": r.score, "metadata": r.metadata}
                    for r in results
                ]
                searcher.cleanup()
                return out
        except Exception as e:
            logger.warning(f"KB RAG search failed for kb {kb_id}: {e}")
            return []

    @staticmethod
    def delete_kb_index(kb_id: str):
        """Remove all index files for a knowledge base."""
        path = RAGService._kb_index_path(kb_id)
        if os.path.exists(path):
            os.remove(path)
        meta_path = path + ".meta"
        if os.path.exists(meta_path):
            os.remove(meta_path)

    # -- helpers --------------------------------------------------------------

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
        """Split text into overlapping chunks."""
        if not text.strip():
            return []
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunks.append(text[start:end])
            start = end - overlap
        return chunks
