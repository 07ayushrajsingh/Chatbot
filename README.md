# Document Q&A Chatbot

A full stack chatbot that reads the documents you upload and answers questions about them.
The answers come **only** from your uploaded files, not from the model's general knowledge.

---

## Table of Contents

1. [What this project does](#1-what-this-project-does)
2. [Why RAG and not a plain chatbot](#2-why-rag-and-not-a-plain-chatbot)
3. [Technology used and why](#3-technology-used-and-why)
4. [Project structure](#4-project-structure)
5. [How it works step by step](#5-how-it-works-step-by-step)
6. [File by file explanation](#6-file-by-file-explanation)
7. [Setup instructions](#7-setup-instructions)
8. [API endpoints](#8-api-endpoints)
9. [Common problems and fixes](#9-common-problems-and-fixes)

---

## 1. What this project does

You upload a file. The system reads it, understands it, and stores it in a way that lets it
be searched by meaning. Then you ask a question in plain English and get an answer taken
directly from that file, along with the name of the file the answer came from.

Supported file types: PDF, PNG, JPG, TXT, DOCX

**Example**

> You upload a vendor agreement PDF.
> You ask: *"What is the penalty if an order above 2000 kg is delayed?"*
> The system answers: *"1 percent per day."* and shows the source file name.

If you ask something that is not in any uploaded document, the system says the document
does not contain it. It does not invent an answer.

---

## 2. Why RAG and not a plain chatbot

A plain language model answers from what it learned during training. It has never seen
your company's documents, so it would either refuse or make something up.

RAG stands for **Retrieval-Augmented Generation**. The idea is simple:

1. **Retrieval** — find the parts of your documents that relate to the question
2. **Augmented** — paste those parts into the prompt as context
3. **Generation** — let the model write the answer using only that context

So the model is not remembering your document. It is reading the relevant part of it fresh,
every single time you ask a question.

**Why this matters**

| Without RAG | With RAG |
|---|---|
| Model answers from general knowledge | Model answers from your file |
| Can make up facts | Grounded in real text |
| No source | Shows which file the answer came from |
| Needs retraining for new documents | Just upload a new file |

---

## 3. Technology used and why

| Layer | Technology | Why this one |
|---|---|---|
| Web framework | Flask | Lightweight, easy routing, good for a focused app like this |
| Document database | MongoDB | Stores records with different shapes without a fixed schema |
| Vector database | ChromaDB | Stores embeddings and finds the closest match fast, runs locally with no server |
| Embedding model | BAAI/bge-small-en-v1.5 | Open source, runs on your own machine, free, works offline, strong at retrieval |
| Embedding runtime | fastembed | Runs the model through ONNX instead of PyTorch, much lighter to install |
| Language model | Llama 3.2 (open weight) | Served through NVIDIA NIM so no GPU is needed locally |
| Text splitting | LangChain text splitter | Splits text at natural boundaries instead of cutting mid-sentence |
| PDF reading | pypdf | Pure Python, no external software required |
| Image reading | Tesseract OCR + pytesseract | The standard open source OCR engine |
| Word reading | python-docx | Reads both paragraphs and tables from .docx files |

### Why two databases

This confuses people at first, so here is the difference.

**MongoDB** stores facts about your documents — file name, file type, size, upload time,
how many chunks were made, and the chat history. This is ordinary record keeping.

**ChromaDB** stores the actual text chunks along with their embeddings. Its job is
*meaning-based search*. If you ask about "payment terms" and the document says
"billing conditions", a normal database would find nothing. ChromaDB finds it, because
both phrases sit close together in meaning space.

### Why embeddings run locally but the language model runs on an API

Embeddings are needed in large numbers. A 50 page PDF produces 200 or more chunks, and
every one needs an embedding. Sending 200 network requests would be slow and would consume
API credits quickly. The embedding model is small (about 130 MB) and runs comfortably on
a CPU, so it stays local — free, fast, and works without internet.

The language model is different. A good one is too large to run on a normal laptop, and
it is only called **once per question**. So it makes sense to call it over the API.

---

## 4. Project structure

```
Chat Boat/
│
├── app.py                 Flask routes, ties everything together
├── config.py              All settings in one place
├── extractor.py           Converts any supported file into plain text
├── rag.py                 Chunking, embeddings, search, answer generation
├── mongo.py               Database operations
│
├── templates/
│   └── index.html         Chat interface
│
├── uploads/               Uploaded files are saved here
├── chroma_store/          Vector database files (auto created)
│
├── requirements.txt       Python packages
├── .env                   API key and settings (never commit this)
├── .gitignore
└── venv/                  Virtual environment
```

Only five Python files. Each one has a single clear job.

---

## 5. How it works step by step

There are two separate flows. Understanding them separately makes the whole project clear.

### Flow A — Uploading a document (happens once per file)

**Step 1. File is received and saved**

The browser sends the file to `/upload`. The file name is cleaned with `secure_filename`
to remove anything dangerous, then renamed to a random UUID before saving.

*Why rename it:* if two people upload `report.pdf`, the second would overwrite the first.
A UUID makes every stored file unique. The original name is kept separately in MongoDB
so the user still sees the name they recognise.

**Step 2. Text is extracted**

`extractor.py` checks the file extension and uses the right reader:

- PDF → `pypdf` reads each page and joins the text
- Image → Tesseract OCR converts the picture of text into real text
- TXT → read directly
- DOCX → `python-docx` reads paragraphs *and* table cells

After extraction, blank lines are removed so the text is compact.

*Why this matters:* every later step works on plain text. By converting everything to text
first, the rest of the system does not need to know or care what the original format was.

**Step 3. Text is split into chunks**

The full text is cut into pieces of about 1000 characters, with 150 characters of overlap
between neighbouring pieces.

*Why split at all:* you cannot send a 50 page document to the model for every question.
It would be slow, expensive, and the model would lose focus among too much text.

*Why overlap:* if a sentence explains something important and the cut falls right in the
middle of it, both halves lose their meaning. Overlapping means that sentence appears
complete in at least one chunk.

*Why a "recursive" splitter:* it tries to break at paragraph breaks first, then line breaks,
then sentence ends, and only cuts mid-word as a last resort. This keeps each chunk readable.

**Step 4. Each chunk is converted to an embedding**

An embedding is a list of numbers (384 of them in this project) that represents the
*meaning* of a piece of text. Texts with similar meaning produce similar number patterns.

*Why we need this:* it is what makes meaning-based search possible. Keyword search looks
for matching letters. Embedding search looks for matching meaning.

**Step 5. Everything is stored**

- Chunks and their embeddings go into ChromaDB, each tagged with the file name and document id
- File details go into MongoDB

The document id tag is important — it is what lets us delete all of one document's chunks
later without touching anything else.

### Flow B — Asking a question (happens every time)

**Step 1. The question becomes an embedding**

The same embedding model converts the question into the same kind of number list.
It has to be the same model, otherwise the numbers would not be comparable.

**Step 2. ChromaDB finds the closest chunks**

It compares the question's embedding against every stored chunk and returns the closest
matches — six of them by default (`TOP_K`).

*Why six:* too few and the answer may be incomplete, especially for questions that span
several documents. Too many and irrelevant text gets mixed in, which confuses the model
and makes answers worse.

**Step 3. A prompt is built**

The retrieved chunks are assembled into a prompt that instructs the model clearly:

> Answer the question using only the context below.
> If the answer is not present in the context, say that the document does not contain it.
> Do not use outside knowledge.

*Why those instructions matter:* this is what stops the model from inventing answers.
Without them, asking "What is the CEO's salary?" would produce a confident, completely
made up number. With them, the model correctly replies that the document does not contain it.

**Step 4. The model generates the answer**

The prompt is sent to the language model with `temperature=0.2`.

*Why low temperature:* temperature controls randomness. For creative writing you want it
high. For factual answers taken from a document, you want the model to stick closely to
what the text actually says, so a low value is correct.

**Step 5. Sources are picked and the answer is saved**

Only the chunks that scored close to the best match are counted as sources, so unrelated
files are not credited. The question, the answer and the sources are logged in MongoDB.

### The whole picture

```
UPLOAD
  file → extract text → split into chunks → make embeddings
       → store in ChromaDB (+ record in MongoDB)

ASK
  question → make embedding → find closest chunks in ChromaDB
           → build prompt with those chunks → send to model
           → answer + source shown to user (+ logged in MongoDB)
```

---

## 6. File by file explanation

### `config.py`

Every setting lives here, loaded from the `.env` file. Nothing is hardcoded elsewhere.

*Why:* when the model needs changing or the project moves to another machine, you edit one
file instead of hunting through the whole codebase. The secret API key stays in `.env`,
which is excluded by `.gitignore` and never gets committed.

Key settings:

| Setting | Meaning |
|---|---|
| `CHUNK_SIZE` | How big each text piece is (1000 characters) |
| `CHUNK_OVERLAP` | How much neighbouring pieces share (150 characters) |
| `TOP_K` | How many chunks to retrieve per question (6) |
| `ALLOWED_EXT` | Which file types are accepted |

### `extractor.py`

Takes a file path and returns plain text. One function per format, and one `extract_text`
function that picks the right one based on the extension.

*Why structured this way:* adding support for a new format later means adding one function
and one line, nothing else changes.

### `rag.py`

The core of the project. It handles:

- `split_text` — cuts text into overlapping chunks
- `embed_texts` — converts text to number vectors
- `add_document` — splits, embeds and stores a document
- `search` — finds the chunks closest to a question
- `build_prompt` — assembles the instruction and context
- `answer_question` — runs the full question-to-answer flow

The embedding model, the database client and the API client are each created only once and
reused. Loading the embedding model takes a few seconds, so recreating it on every request
would make the app noticeably slow.

### `mongo.py`

All database operations in one place. Two collections:

- `documents` — one record per uploaded file
- `chats` — one record per question asked

*Why keep this separate:* if the database ever changes, only this file is affected.

### `app.py`

The Flask layer. It receives requests, validates them, calls the right functions, and
returns JSON. It deliberately contains no business logic of its own — that lives in the
other files.

### `templates/index.html`

The interface. Upload box and document list on the left, chat on the right. Written as a
single file with plain JavaScript — no build step, no framework, nothing to compile.

---

## 7. Setup instructions

### Requirements to install first

| Software | Why it is needed |
|---|---|
| Python 3.12 | Python 3.13 and 3.14 do not yet have stable Windows builds for the native libraries used here |
| MongoDB Community Server | The document database |
| Tesseract OCR | Reads text from images |
| Visual C++ Redistributable | Required by ONNX runtime; without it Python crashes with no error message |

Visual C++ download: https://aka.ms/vs/17/release/vc_redist.x64.exe

### Project setup

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### Create the `.env` file

```
NVIDIA_API_KEY=your_key_here
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
LLM_MODEL=meta/llama-3.2-11b-vision-instruct
EMBED_MODEL=BAAI/bge-small-en-v1.5
MONGO_URI=mongodb://localhost:27017
```

Get a free API key from https://build.nvidia.com

### Run

```bash
python app.py
```

Open http://127.0.0.1:5000

---

## 8. API endpoints

| Method | Route | What it does |
|---|---|---|
| GET | `/` | The chat interface |
| POST | `/upload` | Accepts a file, extracts, indexes and stores it |
| POST | `/ask` | Takes a question, returns an answer with sources |
| GET | `/documents` | Lists all indexed documents |
| DELETE | `/documents/<id>` | Removes a document, its chunks and its file |
| GET | `/history` | Past questions and answers |
| GET | `/health` | Database status, chunk count, active model |

---

## 9. Common problems and fixes

**Python exits with no output and exit code -1073741819**

This is an access violation crash, almost always caused by a missing Visual C++
Redistributable. Install it from the link above and restart the machine.

**The model returns a 404 "Not found for account" error**

The model is listed but not enabled on your API key, or it has reached end of life.
Open `.env` and change `LLM_MODEL` to another model.

**Sources mention a file that is not in the document list**

Old chunks are still sitting in ChromaDB. Clear them:

```bash
python -c "import rag; rag.reset_store(); print(rag.count_chunks())"
```

**A cross-document question only finds part of the answer**

Increase `TOP_K` in `config.py`. Six is the default; eight or ten helps when the answer is
spread across several files. Going much higher starts to hurt answer quality.

**Images are not being read**

Check that Tesseract is installed and that `TESSERACT_PATH` in `config.py` points to the
real location of `tesseract.exe`.

---

## Reset everything

To clear all documents and start fresh:

```bash
python -c "import rag; rag.reset_store()"
python -c "import mongo; db = mongo.get_db(); db.documents.delete_many({}); db.chats.delete_many({})"
```

Then delete the files inside the `uploads` folder.
