
import re
import uuid

import chromadb
from chromadb.config import Settings
from fastembed import TextEmbedding
from langchain_text_splitters import RecursiveCharacterTextSplitter
from openai import OpenAI

import config

_embedder = None
_chroma = None
_llm = None


def get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = TextEmbedding(model_name=config.EMBED_MODEL)
    return _embedder


def get_collection():
    global _chroma
    if _chroma is None:
        _chroma = chromadb.PersistentClient(
            path=config.CHROMA_DIR,
            settings=Settings(anonymized_telemetry=False),
        )
    return _chroma.get_or_create_collection(name=config.COLLECTION_NAME)


def get_llm():
    global _llm
    if _llm is None:
        _llm = OpenAI(
            api_key=config.NVIDIA_API_KEY,
            base_url=config.NVIDIA_BASE_URL,
        )
    return _llm


# Grettings talk, answered without searching the documents

GREETING_WORDS = {
    "hi", "hii", "hiii", "hello", "helo", "hey", "heya", "yo",
    "namaste", "namaskar", "salaam", "hola",
}

THANKS_WORDS = {
    "thanks", "thank", "thanku", "thankyou", "tq", "ty", "thx", "thnx",
    "shukriya", "dhanyavad", "dhanyawad",
}

BYE_WORDS = {
    "bye", "goodbye", "goodnight", "gn", "cya", "alvida",
}

ACK_WORDS = {
    "ok", "okay", "k", "kk", "fine", "good", "great", "nice", "cool",
    "perfect", "awesome", "correct", "right", "done", "sahi", "theek",
    "achha", "acha",
}

FILLER_WORDS = {
    "you", "so", "much", "a", "lot", "very", "all", "the", "is", "it",
    "that", "this", "morning", "afternoon", "evening", "day",
    "bro", "bhai", "sir", "yes", "no", "and",
}


def clean_words(text):
    plain = re.sub(r"[^a-z\s]", " ", text.lower())
    return [w for w in plain.split() if w]


def small_talk(question):
    words = clean_words(question)

    if not words or len(words) > 5:
        return None

    joined = " ".join(words)

    if joined in ("who are you", "what are you", "what can you do",
                  "what do you do", "how do you work", "help"):
        return ("I answer questions about the files you add to this chat. "
                "Use the plus button to add a PDF, Word, Excel, text or image "
                "file, then ask me anything about it.")

    has_greeting = any(w in GREETING_WORDS for w in words)
    has_thanks = any(w in THANKS_WORDS for w in words)
    has_bye = any(w in BYE_WORDS for w in words)
    has_ack = any(w in ACK_WORDS for w in words)

    known = GREETING_WORDS | THANKS_WORDS | BYE_WORDS | ACK_WORDS

    for w in words:
        if w not in known and w not in FILLER_WORDS:
            return None

    if has_thanks:
        return "You are welcome. Ask me anything else about your files."
    if has_bye:
        return "Goodbye. Your chat stays saved if you want to come back to it."
    if has_greeting:
        return "Hello. Add a file with the plus button and ask me about it."
    if has_ack:
        return "Glad that helped. Ask me anything else about your files."

    return None


def split_text(text):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_text(text)


def embed_texts(texts):
    embedder = get_embedder()
    vectors = list(embedder.embed(texts))
    return [v.tolist() for v in vectors]


def add_document(text, filename, doc_id, chat_id):
    chunks = split_text(text)
    if not chunks:
        return 0

    vectors = embed_texts(chunks)

    ids = []
    metadatas = []
    for i in range(len(chunks)):
        ids.append(str(uuid.uuid4()))
        metadatas.append({
            "filename": filename,
            "doc_id": doc_id,
            "chat_id": chat_id,
            "chunk_index": i,
        })

    collection = get_collection()
    collection.add(
        ids=ids,
        documents=chunks,
        embeddings=vectors,
        metadatas=metadatas,
    )
    return len(chunks)


# searching and answering

def count_chunks(chat_id=None):
    collection = get_collection()
    if chat_id is None:
        return collection.count()
    found = collection.get(where={"chat_id": chat_id}, include=[])
    return len(found.get("ids", []))


def match_score(distance):
    """Turns a vector distance into a rough 0 to 100 closeness score."""
    closeness = 1.0 - (float(distance) / 2.0)
    if closeness < 0:
        closeness = 0.0
    if closeness > 1:
        closeness = 1.0
    return int(round(closeness * 100))


def search(question, chat_id, top_k=None):
    if top_k is None:
        top_k = config.TOP_K

    available = count_chunks(chat_id)
    if available == 0:
        return []

    collection = get_collection()
    query_vector = embed_texts([question])[0]
    result = collection.query(
        query_embeddings=[query_vector],
        n_results=min(top_k, available),
        where={"chat_id": chat_id},
    )

    hits = []
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]

    for i in range(len(documents)):
        hits.append({
            "text": documents[i],
            "filename": metadatas[i].get("filename", "unknown"),
            "chunk_index": metadatas[i].get("chunk_index", 0),
            "distance": distances[i],
            "score": match_score(distances[i]),
        })
    return hits


NOT_FOUND_MARKER = "NOT_IN_DOCUMENT"


def not_found_message(names):
    if len(names) == 1:
        return ("This question is not covered in " + names[0] + ". "
                "Please ask something from this file. Thank you.")
    return ("This question is not covered in the files added to this chat. "
            "Please ask something from them. Thank you.")


def build_prompt(question, hits):
    parts = []
    names = []
    for i, hit in enumerate(hits):
        parts.append("[" + str(i + 1) + "] From " + hit["filename"] + ":\n" + hit["text"])
        if hit["filename"] not in names:
            names.append(hit["filename"])

    context = "\n\n".join(parts)
    file_list = ", ".join(names)

    prompt = (
        "You are a document assistant. Use only the passages below. "
        "Never add anything from your own knowledge.\n\n"
        "If the passages answer the question, give the answer in one or two "
        "short sentences.\n\n"
        "If the passages do not answer the question, reply with this one word "
        "and nothing else:\n"
        "  " + NOT_FOUND_MARKER + "\n"
        "Do not explain, do not apologise, do not add any other sentence.\n\n"
        "Passages:\n" + context + "\n\n"
        "Question: " + question + "\n\n"
        "Answer:"
    )
    return prompt


def pack_passages(hits):
    """Trims the retrieved passages down to what the screen needs."""
    items = []
    for i, hit in enumerate(hits):
        text = hit["text"].strip()
        if len(text) > 700:
            text = text[:700].rstrip() + " ..."
        items.append({
            "rank": i + 1,
            "filename": hit["filename"],
            "score": hit["score"],
            "text": text,
        })
    return items


def answer_question(question, chat_id):
    reply = small_talk(question)
    if reply:
        return {
            "answer": reply,
            "sources": [],
            "passages": [],
            "looked_at": 0,
            "total": count_chunks(chat_id),
            "best_score": None,
        }

    hits = search(question, chat_id)

    if not hits:
        return {
            "answer": "No files have been added to this chat yet. "
                      "Use the plus button to add one, then ask again.",
            "sources": [],
            "passages": [],
            "looked_at": 0,
            "total": 0,
            "best_score": None,
        }

    prompt = build_prompt(question, hits)

    client = get_llm()
    resp = client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=600,
    )
    answer = resp.choices[0].message.content.strip()

    best = hits[0]["distance"]
    sources = []
    for hit in hits:
        if hit["distance"] > best + 0.35:
            continue
        if hit["filename"] not in sources:
            sources.append(hit["filename"])

    if NOT_FOUND_MARKER in answer.upper():
        answer = not_found_message(sources)

    return {
        "answer": answer,
        "sources": sources,
        "passages": pack_passages(hits),
        "looked_at": len(hits),
        "total": count_chunks(chat_id),
        "best_score": hits[0]["score"],
    }


# removing chats from the chatbot db

def delete_document(doc_id):
    collection = get_collection()
    collection.delete(where={"doc_id": doc_id})


def delete_chat_documents(chat_id):
    collection = get_collection()
    collection.delete(where={"chat_id": chat_id})


def reset_store():
    collection = get_collection()
    ids = collection.get(include=[]).get("ids", [])
    if ids:
        collection.delete(ids=ids)