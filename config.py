import os
from dotenv import load_dotenv

load_dotenv()

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "meta/llama-3.2-11b-vision-instruct")
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = "docqa"

UPLOAD_DIR = "uploads"
CHROMA_DIR = "chroma_store"
COLLECTION_NAME = "documents"

TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
TOP_K = 6

ALLOWED_EXT = {
    ".pdf", ".txt", ".md", ".csv",
    ".png", ".jpg", ".jpeg",
    ".docx", ".xlsx", ".xls",
}