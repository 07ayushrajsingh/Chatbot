# Flask backend for the document question answering chatbot

import os
import uuid

from flask import Flask, jsonify, render_template, request
from werkzeug.utils import secure_filename

import config
import extractor
import mongo
import rag

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

os.makedirs(config.UPLOAD_DIR, exist_ok=True)

mongo.drop_old_chats()


def allowed_file(filename):
    ext = os.path.splitext(filename)[1].lower()
    return ext in config.ALLOWED_EXT


def make_title(question):
    title = " ".join(question.split())
    if len(title) > 48:
        title = title[:48].rstrip() + "..."
    return title


def remove_file(stored_name):
    if not stored_name:
        return
    path = os.path.join(config.UPLOAD_DIR, stored_name)
    if os.path.exists(path):
        os.remove(path)


@app.route("/")
def home():
    return render_template("index.html")


# chats

@app.route("/chats", methods=["GET"])
def chats():
    items = []
    for row in mongo.list_chats():
        stamp = row["updated_at"]
        items.append({
            "chat_id": row["chat_id"],
            "title": row["title"],
            "updated_at": stamp.strftime("%d %b, %H:%M") if stamp else "",
        })
    return jsonify({"chats": items})


@app.route("/chats", methods=["POST"])
def new_chat():
    chat_id = mongo.create_chat()
    return jsonify({"chat_id": chat_id, "title": "New chat"})


@app.route("/chats/<chat_id>", methods=["GET"])
def chat_detail(chat_id):
    if not mongo.chat_exists(chat_id):
        return jsonify({"error": "Chat not found"}), 404

    files = []
    for row in mongo.list_documents(chat_id):
        files.append({
            "doc_id": row["_id"],
            "filename": row.get("filename"),
            "chunks": row.get("chunk_count", 0),
        })

    return jsonify({
        "messages": mongo.get_messages(chat_id),
        "files": files,
    })


@app.route("/chats/<chat_id>", methods=["DELETE"])
def remove_chat(chat_id):
    for row in mongo.list_documents(chat_id):
        remove_file(row.get("stored_name"))

    rag.delete_chat_documents(chat_id)
    mongo.delete_chat_documents(chat_id)
    mongo.delete_chat(chat_id)

    return jsonify({"message": "Chat removed"})


# documents

@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file received"}), 400

    uploaded = request.files["file"]
    if uploaded.filename == "":
        return jsonify({"error": "No file selected"}), 400

    if not allowed_file(uploaded.filename):
        return jsonify({"error": "This file type is not supported"}), 400

    chat_id = request.form.get("chat_id")
    if not mongo.chat_exists(chat_id):
        chat_id = mongo.create_chat()

    original_name = secure_filename(uploaded.filename)
    ext = os.path.splitext(original_name)[1].lower()
    stored_name = str(uuid.uuid4()) + ext
    path = os.path.join(config.UPLOAD_DIR, stored_name)
    uploaded.save(path)

    try:
        text = extractor.extract_text(path)
    except Exception as e:
        os.remove(path)
        return jsonify({"error": "Could not read this file: " + str(e)}), 400

    if not text.strip():
        os.remove(path)
        return jsonify({"error": "No readable text was found in this file"}), 400

    doc_id = mongo.save_document(
        chat_id=chat_id,
        filename=original_name,
        stored_name=stored_name,
        file_type=ext,
        size_bytes=os.path.getsize(path),
        chunk_count=0,
    )

    chunk_count = rag.add_document(text, original_name, doc_id, chat_id)
    mongo.update_chunk_count(doc_id, chunk_count)
    mongo.touch_chat(chat_id)

    return jsonify({
        "chat_id": chat_id,
        "doc_id": doc_id,
        "filename": original_name,
        "chunks": chunk_count,
    })


@app.route("/documents/<doc_id>", methods=["DELETE"])
def remove_document(doc_id):
    row = mongo.get_document(doc_id)

    rag.delete_document(doc_id)
    mongo.delete_document(doc_id)

    if row:
        remove_file(row.get("stored_name"))

    return jsonify({"message": "Document removed"})


# asking

@app.route("/ask", methods=["POST"])
def ask():
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    chat_id = data.get("chat_id")

    if not question:
        return jsonify({"error": "The question is empty"}), 400

    if not mongo.chat_exists(chat_id):
        chat_id = mongo.create_chat(make_title(question))
    elif mongo.count_messages(chat_id) == 0:
        mongo.rename_chat(chat_id, make_title(question))

    mongo.save_message(chat_id, "user", question)

    try:
        result = rag.answer_question(question, chat_id)
    except Exception as e:
        return jsonify({"error": "Could not generate an answer: " + str(e)}), 500

    mongo.save_message(
        chat_id,
        "assistant",
        result["answer"],
        result["sources"],
        result.get("looked_at", 0),
        result.get("total", 0),
    )

    return jsonify({
        "chat_id": chat_id,
        "answer": result["answer"],
        "sources": result["sources"],
        "looked_at": result.get("looked_at", 0),
        "total": result.get("total", 0),
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "mongo": mongo.ping(),
        "chunks": rag.count_chunks(),
        "model": config.LLM_MODEL,
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)