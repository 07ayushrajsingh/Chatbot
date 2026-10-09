from datetime import datetime
from bson import ObjectId
from pymongo import MongoClient

import config

_client = None


def get_db():
    global _client
    if _client is None:
        _client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=5000)
    return _client[config.MONGO_DB]


def ping():
    db = get_db()
    db.command("ping")
    return True


# document records, each one belongs to a chat

def save_document(chat_id, filename, stored_name, file_type, size_bytes, chunk_count):
    db = get_db()
    result = db.documents.insert_one({
        "chat_id": chat_id,
        "filename": filename,
        "stored_name": stored_name,
        "file_type": file_type,
        "size_bytes": size_bytes,
        "chunk_count": chunk_count,
        "uploaded_at": datetime.now(),
    })
    return str(result.inserted_id)


def update_chunk_count(doc_id, chunk_count):
    db = get_db()
    db.documents.update_one(
        {"_id": ObjectId(doc_id)},
        {"$set": {"chunk_count": chunk_count}},
    )


def list_documents(chat_id=None):
    db = get_db()
    query = {"chat_id": chat_id} if chat_id else {}
    docs = []
    for row in db.documents.find(query).sort("uploaded_at", 1):
        row["_id"] = str(row["_id"])
        docs.append(row)
    return docs


def get_document(doc_id):
    db = get_db()
    try:
        row = db.documents.find_one({"_id": ObjectId(doc_id)})
    except Exception:
        return None
    if row:
        row["_id"] = str(row["_id"])
    return row


def delete_document(doc_id):
    db = get_db()
    db.documents.delete_one({"_id": ObjectId(doc_id)})


def delete_chat_documents(chat_id):
    db = get_db()
    db.documents.delete_many({"chat_id": chat_id})


# chat sessions

def create_chat(title="New chat"):
    db = get_db()
    now = datetime.now()
    result = db.chats.insert_one({
        "title": title,
        "created_at": now,
        "updated_at": now,
    })
    return str(result.inserted_id)


def list_chats():
    db = get_db()
    rows = []
    for row in db.chats.find({"title": {"$exists": True}}).sort("updated_at", -1):
        rows.append({
            "chat_id": str(row["_id"]),
            "title": row.get("title") or "New chat",
            "updated_at": row.get("updated_at") or row.get("created_at"),
        })
    return rows


def rename_chat(chat_id, title):
    db = get_db()
    db.chats.update_one({"_id": ObjectId(chat_id)}, {"$set": {"title": title}})


def touch_chat(chat_id):
    db = get_db()
    db.chats.update_one(
        {"_id": ObjectId(chat_id)},
        {"$set": {"updated_at": datetime.now()}},
    )


def delete_chat(chat_id):
    db = get_db()
    db.messages.delete_many({"chat_id": chat_id})
    db.chats.delete_one({"_id": ObjectId(chat_id)})


def chat_exists(chat_id):
    if not chat_id:
        return False
    db = get_db()
    try:
        return db.chats.find_one({"_id": ObjectId(chat_id)}) is not None
    except Exception:
        return False


def drop_old_chats():
    """Removes records left behind by the earlier version of this app."""
    db = get_db()
    result = db.chats.delete_many({"title": {"$exists": False}})
    return result.deleted_count


# messages inside a chat

def save_message(chat_id, role, content, sources=None, looked_at=0, total=0):
    db = get_db()
    db.messages.insert_one({
        "chat_id": chat_id,
        "role": role,
        "content": content,
        "sources": sources or [],
        "looked_at": looked_at,
        "total": total,
        "created_at": datetime.now(),
    })
    touch_chat(chat_id)


def get_messages(chat_id):
    db = get_db()
    rows = []
    for row in db.messages.find({"chat_id": chat_id}).sort("created_at", 1):
        rows.append({
            "role": row.get("role"),
            "content": row.get("content"),
            "sources": row.get("sources", []),
            "looked_at": row.get("looked_at", 0),
            "total": row.get("total", 0),
        })
    return rows


def count_messages(chat_id):
    db = get_db()
    return db.messages.count_documents({"chat_id": chat_id})