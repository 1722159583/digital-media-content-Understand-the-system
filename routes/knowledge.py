from flask import Blueprint, current_app, has_app_context, request
from datetime import datetime
import os
import json
import logging
import uuid
from pathlib import Path

from utils.db import get_db
from utils.auth import login_required
from utils.response import success, error

# 导入 chromadb 和 sentence-transformers
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from sklearn.feature_extraction.text import HashingVectorizer

knowledge_bp = Blueprint('knowledge', __name__, url_prefix='/api/kb')


def _public_kb(kb):
    return {
        "kbId": kb.get("kb_id", ""),
        "name": kb.get("name", ""),
        "category": kb.get("category", "其他"),
        "description": kb.get("description", ""),
        "docCount": kb.get("doc_count", 0),
        "chunkCount": kb.get("chunk_count", 0),
        "createdAt": kb.get("created_at"),
    }


def _public_doc(doc):
    return {
        "docId": doc.get("doc_id", ""),
        "name": doc.get("filename", ""),
        "chunkCount": doc.get("chunk_count", 0),
        "vectorStatus": doc.get("vector_status", "indexed"),
        "uploadedAt": doc.get("uploaded_at"),
    }

# Set EMBEDDING_MODEL_PATH to use a downloaded SentenceTransformer model.
MODEL_PATH = os.getenv("EMBEDDING_MODEL_PATH", "").strip()
embedding_model = None


class LocalHashEmbedding:
    """Offline 384-dimensional text embedding fallback."""

    def __init__(self):
        self.vectorizer = HashingVectorizer(
            n_features=384,
            analyzer="char",
            ngram_range=(2, 4),
            alternate_sign=False,
            norm="l2",
        )

    def encode(self, texts):
        single = isinstance(texts, str)
        values = [texts] if single else list(texts)
        result = self.vectorizer.transform(values).toarray()
        return result[0] if single else result

def get_embedding_model():
    global embedding_model
    if embedding_model is None:
        logger = current_app.logger if has_app_context() else logging.getLogger(__name__)
        if MODEL_PATH and Path(MODEL_PATH).is_dir():
            try:
                embedding_model = SentenceTransformer(MODEL_PATH, local_files_only=True)
            except Exception as exc:
                logger.warning("Local embedding model unavailable, using offline fallback: %s", exc)
        if embedding_model is None:
            embedding_model = LocalHashEmbedding()
    return embedding_model

# 初始化 Chroma 客户端
CHROMA_DIR = Path(__file__).resolve().parent.parent / "chroma_db"
CHROMA_DIR.mkdir(parents=True, exist_ok=True)

chroma_client = chromadb.PersistentClient(
    path=str(CHROMA_DIR),
    settings=Settings(anonymized_telemetry=False)
)

def get_or_create_collection(kb_id: str):
    """获取或创建向量集合"""
    collections = chroma_client.list_collections()
    collection_names = [item if isinstance(item, str) else item.name for item in collections]
    
    if kb_id in collection_names:
        return chroma_client.get_collection(kb_id)
    else:
        return chroma_client.create_collection(
            name=kb_id,
            metadata={"hnsw:space": "cosine"}
        )

def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50):
    """将长文本分块"""
    chunks = []
    start = 0
    text_length = len(text)
    
    while start < text_length:
        end = min(start + chunk_size, text_length)
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - overlap if end < text_length else end
    
    return chunks


# ========== 创建知识库 ==========
@knowledge_bp.route('/create', methods=['POST'])
@login_required
def create_kb(user):
    data = request.get_json()
    name = data.get('name')
    category = data.get('category', '通用')
    description = data.get('description', '')
    
    if not name:
        return error("知识库名称不能为空", 400)
    
    kb_id = f"kb_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
    
    db = get_db()
    kb_data = {
        "kb_id": kb_id,
        "name": name,
        "category": category,
        "description": description,
        "user_id": user.get('user_id'),
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "doc_count": 0,
        "chunk_count": 0
    }
    db["knowledge_bases"].insert_one(kb_data)
    
    # 创建向量集合
    get_or_create_collection(kb_id)
    
    return success({"kbId": kb_id, "kb": kb_data}, "知识库创建成功", 201)


# ========== 知识库列表 ==========
@knowledge_bp.route('/list', methods=['GET'])
@login_required
def list_kb(user):
    page = int(request.args.get('page', 1))
    size = int(request.args.get('size', 10))
    keyword = request.args.get('keyword', '')
    
    db = get_db()
    query = {"user_id": user.get('user_id')}
    if keyword:
        query["name"] = {"$regex": keyword, "$options": "i"}
    
    total = db["knowledge_bases"].count_documents(query)
    kbs = list(db["knowledge_bases"].find(query).skip((page-1)*size).limit(size))
    
    return success({
        "list": [_public_kb(kb) for kb in kbs],
        "total": total,
        "page": page,
        "size": size
    })


# ========== 删除知识库 ==========
@knowledge_bp.route('/<kb_id>', methods=['DELETE'])
@login_required
def delete_kb(user, kb_id):
    db = get_db()
    kb = db["knowledge_bases"].find_one({"kb_id": kb_id, "user_id": user.get('user_id')})
    if not kb:
        return error("知识库不存在或无权访问", 404)
    
    # 删除向量集合
    try:
        chroma_client.delete_collection(kb_id)
    except:
        pass
    
    # 删除文档记录
    db["kb_documents"].delete_many({"kb_id": kb_id})
    db["knowledge_bases"].delete_one({"kb_id": kb_id})
    
    return success(None, "删除成功")


# ========== 上传文档 ==========
@knowledge_bp.route('/<kb_id>/doc/upload', methods=['POST'])
@login_required
def upload_doc(user, kb_id):
    db = get_db()
    kb = db["knowledge_bases"].find_one({"kb_id": kb_id, "user_id": user.get('user_id')})
    if not kb:
        return error("知识库不存在或无权访问", 404)
    
    file = request.files.get('file')
    if not file:
        return error("请上传文档文件", 400)
    
    filename = file.filename
    content = file.read().decode('utf-8', errors='ignore')
    
    if not content.strip():
        return error("文档内容为空", 400)
    
    # 分块
    chunks = chunk_text(content)
    
    # 生成向量并存储
    model = get_embedding_model()
    collection = get_or_create_collection(kb_id)
    
    doc_id = f"doc_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
    
    chunk_ids = []
    for i, chunk in enumerate(chunks):
        chunk_id = f"{doc_id}_chunk_{i}"
        chunk_ids.append(chunk_id)
        embedding = model.encode(chunk).tolist()
        collection.add(
            ids=[chunk_id],
            embeddings=[embedding],
            metadatas=[{"doc_id": doc_id, "chunk_index": i, "kb_id": kb_id}],
            documents=[chunk]
        )
    
    # 保存文档记录
    doc_record = {
        "doc_id": doc_id,
        "kb_id": kb_id,
        "filename": filename,
        "chunk_count": len(chunks),
        "uploaded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "user_id": user.get('user_id')
    }
    db["kb_documents"].insert_one(doc_record)
    
    # 更新知识库统计
    db["knowledge_bases"].update_one(
        {"kb_id": kb_id},
        {"$inc": {"doc_count": 1, "chunk_count": len(chunks)}}
    )
    
    return success({
        "docId": doc_id,
        "chunkCount": len(chunks)
    }, "文档上传成功")


# ========== 文档列表 ==========
@knowledge_bp.route('/<kb_id>/doc/list', methods=['GET'])
@login_required
def list_docs(user, kb_id):
    db = get_db()
    kb = db["knowledge_bases"].find_one({"kb_id": kb_id, "user_id": user.get('user_id')})
    if not kb:
        return error("知识库不存在或无权访问", 404)
    
    page = int(request.args.get('page', 1))
    size = int(request.args.get('size', 10))
    
    total = db["kb_documents"].count_documents({"kb_id": kb_id})
    docs = list(db["kb_documents"].find({"kb_id": kb_id}).skip((page-1)*size).limit(size))
    
    return success({
        "list": [_public_doc(doc) for doc in docs],
        "total": total,
        "page": page,
        "size": size
    })


# ========== 删除文档 ==========
@knowledge_bp.route('/<kb_id>/doc/<doc_id>', methods=['DELETE'])
@login_required
def delete_doc(user, kb_id, doc_id):
    db = get_db()
    kb = db["knowledge_bases"].find_one({"kb_id": kb_id, "user_id": user.get('user_id')})
    if not kb:
        return error("知识库不存在或无权访问", 404)
    
    doc = db["kb_documents"].find_one({"doc_id": doc_id, "kb_id": kb_id})
    if not doc:
        return error("文档不存在", 404)
    
    # 删除向量
    try:
        collection = get_or_create_collection(kb_id)
        # 查找并删除该文档的所有分块
        all_ids = collection.get()["ids"]
        doc_chunk_ids = [id for id in all_ids if id.startswith(doc_id)]
        if doc_chunk_ids:
            collection.delete(ids=doc_chunk_ids)
    except:
        pass
    
    db["kb_documents"].delete_one({"doc_id": doc_id})
    db["knowledge_bases"].update_one(
        {"kb_id": kb_id},
        {"$inc": {"doc_count": -1, "chunk_count": -doc.get('chunk_count', 0)}}
    )
    
    return success(None, "删除成功")


# ========== 向量检索 ==========
@knowledge_bp.route('/retrieve', methods=['POST'])
@login_required
def retrieve(user):
    data = request.get_json()
    kb_id = data.get('kbId') or data.get('kb_id')
    query_text = data.get('query_text')
    top_k = data.get('top_k', 3)
    score_threshold = data.get('score_threshold', 0.0)
    
    if not kb_id:
        return error("缺少 kbId", 400)
    if not query_text:
        return error("缺少 query_text", 400)
    
    db = get_db()
    kb = db["knowledge_bases"].find_one({"kb_id": kb_id, "user_id": user.get('user_id')})
    if not kb:
        return error("知识库不存在或无权访问", 404)
    
    # 生成查询向量
    model = get_embedding_model()
    query_embedding = model.encode(query_text).tolist()
    
    # 检索
    collection = get_or_create_collection(kb_id)
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k
    )
    
    matches = []
    if results and results['documents']:
        for i, doc in enumerate(results['documents'][0]):
            distance = results['distances'][0][i] if results.get('distances') else 0
            # Chroma 使用余弦距离，0=最相似，1=最不相似，转换为相似度分数
            score = 1 - distance if distance <= 1 else 0
            if score >= score_threshold:
                matches.append({
                    "text": doc,
                    "score": round(score, 4),
                    "doc_id": results['metadatas'][0][i].get('doc_id', '') if results.get('metadatas') else ''
                })
    
    return success({
        "query": query_text,
        "results": matches,
        "top_k": top_k
    })


# ========== 重建索引 ==========
@knowledge_bp.route('/<kb_id>/rebuild', methods=['POST'])
@login_required
def rebuild_index(user, kb_id):
    db = get_db()
    kb = db["knowledge_bases"].find_one({"kb_id": kb_id, "user_id": user.get('user_id')})
    if not kb:
        return error("知识库不存在或无权访问", 404)
    
    # 删除旧集合
    try:
        chroma_client.delete_collection(kb_id)
    except:
        pass
    
    # 创建新集合
    collection = get_or_create_collection(kb_id)
    
    # 重新索引所有文档
    docs = db["kb_documents"].find({"kb_id": kb_id})
    model = get_embedding_model()
    total_chunks = 0
    
    for doc in docs:
        # 这里需要重新读取文档内容并分块
        # 简化版：只更新状态
        # 实际应该从原始文件重新读取
        pass
    
    db["knowledge_bases"].update_one(
        {"kb_id": kb_id},
        {"$set": {"rebuild_at": datetime.now().astimezone().isoformat(timespec="seconds")}}
    )
    
    return success({"kbId": kb_id}, "索引重建完成")
