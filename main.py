from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import uvicorn
import os
import shutil
from typing import List
from datetime import datetime
import re

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.llms import Ollama
from langchain.chains import RetrievalQA

from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine

from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv

from auth import (
    login_user, register_user, get_current_user,
    create_admin_if_not_exists, users_col
)

load_dotenv()

# ── fastapi ──────────────────────────────────────────────────
app = FastAPI(title="Privacy RAG System")
security = HTTPBearer(auto_error=False)

os.makedirs("documents", exist_ok=True)
os.makedirs("chroma_db", exist_ok=True)
os.makedirs("templates", exist_ok=True)

# ── mongodb ──────────────────────────────────────────────────
MONGO_URI     = os.getenv("MONGO_URI", "mongodb://localhost:27017")
mongo_client  = MongoClient(MONGO_URI)
db            = mongo_client["privacy_rag"]
col_documents = db["documents"]
col_queries   = db["query_history"]

# ── privacy engines ──────────────────────────────────────────
print("Loading privacy engine...")
analyzer   = AnalyzerEngine()
anonymizer = AnonymizerEngine()
print("✅ Privacy engine ready!")

# ── embeddings ───────────────────────────────────────────────
print("Loading embeddings...")
embeddings = HuggingFaceEmbeddings(
    model_name="all-MiniLM-L6-v2",
    model_kwargs={"device": "cpu"}
)
print("✅ Embeddings ready!")

# ── llm ──────────────────────────────────────────────────────
print("Connecting to Ollama...")
try:
    llm = Ollama(model="phi3:mini", base_url="http://localhost:11434", temperature=0.1, timeout=60)
    print("✅ Ollama ready!")
except Exception as e:
    print(f"⚠️  Ollama error: {e}")
    llm = None

# ── vector store ─────────────────────────────────────────────
print("Loading vector store...")
vectorstore = Chroma(persist_directory="./chroma_db", embedding_function=embeddings)
print("✅ Vector store ready!")

# ── create admin on startup ───────────────────────────────────
create_admin_if_not_exists()

# ── helpers ───────────────────────────────────────────────────
def bson_to_json(obj):
    if isinstance(obj, list):     return [bson_to_json(i) for i in obj]
    if isinstance(obj, dict):     return {k: bson_to_json(v) for k, v in obj.items()}
    if isinstance(obj, ObjectId): return str(obj)
    if isinstance(obj, datetime): return obj.isoformat()
    return obj

def require_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Not logged in")
    user = get_current_user(credentials.credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user

def require_admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
    user = require_user(credentials)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admins only")
    return user

# ── privacy functions ─────────────────────────────────────────
SENSITIVE_TYPES = [
    "PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS",
    "CREDIT_CARD", "SSN", "LOCATION", "DATE_TIME", "NRP", "AGE", "ID"
]

def contains_pii(text: str) -> dict:
    results  = analyzer.analyze(text=text, language="en")
    entities = []
    has_pii  = False
    for r in results:
        if r.entity_type in SENSITIVE_TYPES:
            has_pii = True
            entities.append({
                "type":  r.entity_type,
                "text":  text[r.start:r.end],
                "start": r.start,
                "end":   r.end
            })
    return {"has_pii": has_pii, "entity_count": len(entities), "entities": entities}

def anonymize_text(text: str) -> str:
    results = analyzer.analyze(text=text, language="en")
    return anonymizer.anonymize(text=text, analyzer_results=results).text

def is_query_safe(query: str) -> dict:
    pii            = contains_pii(query)
    asking_person  = any(e["type"] == "PERSON"                         for e in pii["entities"])
    asking_contact = any(e["type"] in ["PHONE_NUMBER","EMAIL_ADDRESS"] for e in pii["entities"])
    patterns = [
        r"\b(my|your|his|her|their)\s+(name|phone|email|address|age)\b",
        r"\b(tell me about|what is|show me)\s+[a-z]+'s\s+(info|details|profile)\b",
        r"\b(phone|mobile|cell|email|address|ssn|social)\s+(number|#)\b",
        r"\bhow old is\b",
        r"\bwhere does\b.*\blive\b"
    ]
    pattern_match = any(re.search(p, query.lower()) for p in patterns)
    unsafe = asking_person or asking_contact or pattern_match
    if asking_person:    reason = "Query asks about specific individuals"
    elif asking_contact: reason = "Query asks for contact information"
    elif pattern_match:  reason = "Query pattern suggests personal info request"
    else:                reason = "Query appears safe"
    return {"safe": not unsafe, "reason": reason, "entities": pii["entities"]}

# ── document processing ───────────────────────────────────────
def process_document(file_path: str, filename: str) -> dict:
    try:
        ext = filename.lower()
        if ext.endswith(".pdf"):
            loader = PyPDFLoader(file_path)
        elif ext.endswith(".txt"):
            loader = TextLoader(file_path, encoding="utf-8")
        elif ext.endswith(".docx"):
            from langchain_community.document_loaders import Docx2txtLoader
            loader = Docx2txtLoader(file_path)
        else:
            return {"error": "Unsupported file type"}

        docs = loader.load()
        if not docs:
            return {"error": "No text extracted"}

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=500, chunk_overlap=50,
            separators=["\n\n", "\n", ".", " ", ""]
        )
        chunks = splitter.split_documents(docs)

        total_pii = 0
        for i, chunk in enumerate(chunks):
            original   = chunk.page_content
            pii_check  = contains_pii(original)
            anonymized = anonymize_text(original)
            chunk.page_content = anonymized
            chunk.metadata["source"]            = filename
            chunk.metadata["chunk_id"]          = i
            chunk.metadata["original_length"]   = len(original)
            chunk.metadata["anonymized_length"] = len(anonymized)
            total_pii += pii_check["entity_count"]

        vectorstore.add_documents(chunks)

        col_documents.insert_one({
            "filename":    filename,
            "chunks":      len(chunks),
            "pages":       len(docs),
            "pii_found":   total_pii,
            "uploaded_at": datetime.utcnow(),
            "status":      "ready"
        })

        return {
            "success":      True,
            "filename":     filename,
            "chunks":       len(chunks),
            "pii_detected": total_pii
        }

    except Exception as e:
        return {"error": str(e)}

# ════════════════════════════════════════════════════════════
#  ROUTES
# ════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def login_page():
    with open("templates/login.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    with open("templates/admin.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/chat", response_class=HTMLResponse)
async def chat_page():
    with open("templates/chat.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.post("/auth/login")
async def login(data: dict):
    return login_user(data.get("email", ""), data.get("password", ""))

@app.post("/auth/register")
async def register(data: dict):
    return register_user(data.get("email", ""), data.get("password", ""))

@app.post("/upload")
async def upload_files(
    files: List[UploadFile] = File(...),
    user=Depends(require_admin)
):
    results = []
    for file in files:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in [".pdf", ".txt", ".docx"]:
            results.append({"filename": file.filename, "error": "Unsupported file type"})
            continue
        file_path = f"documents/{file.filename}"
        with open(file_path, "wb") as buf:
            shutil.copyfileobj(file.file, buf)
        results.append(process_document(file_path, file.filename))
    return {"status": "completed", "results": results}

@app.post("/check-privacy")
async def privacy_check(data: dict, user=Depends(require_user)):
    query  = data.get("query", "")
    result = is_query_safe(query)
    col_queries.insert_one({
        "query":      query,
        "safe":       result["safe"],
        "reason":     result["reason"],
        "user_email": user.get("email"),
        "answer":     None,
        "sources":    [],
        "timestamp":  datetime.utcnow()
    })
    return result

@app.post("/ask")
async def ask_question(data: dict, user=Depends(require_user)):
    query = data.get("query", "")
    if not query:
        return {"answer": "No question provided"}
    try:
        privacy = is_query_safe(query)
        if not privacy["safe"]:
            return {"answer": "I cannot answer this — it requests personal information."}

        if llm is None:
            return {
                "answer":  "⚠️ The AI model is currently unavailable. Please try again later.",
                "sources": []
            }

        retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
        qa        = RetrievalQA.from_chain_type(
            llm=llm, chain_type="stuff",
            retriever=retriever, return_source_documents=True
        )
        result  = qa.invoke({"query": query})
        answer = anonymize_text(anonymize_text(result["result"]))
        answer = anonymize_text(answer)
        sources = list({d.metadata.get("source", "unknown") for d in result["source_documents"]})

        latest = col_queries.find_one(
            {"user_email": user.get("email"), "answer": None},
            sort=[("timestamp", -1)]
        )
        if latest:
            col_queries.update_one(
                {"_id": latest["_id"]},
                {"$set": {"answer": answer, "sources": sources}}
            )

        return {"answer": answer, "sources": sources}

    except Exception as e:
        return {"answer": f"Error: {str(e)}"}

@app.get("/stats")
async def get_stats(user=Depends(require_user)):
    doc_count    = col_documents.count_documents({})
    vector_count = vectorstore._collection.count() if hasattr(vectorstore, "_collection") else 0
    user_count   = users_col.count_documents({})
    query_count  = col_queries.count_documents({})
    return {
        "documents":     doc_count,
        "vectors":       vector_count,
        "users":         user_count,
        "total_queries": query_count,
        "status":        "running"
    }

@app.get("/history")
async def query_history(limit: int = 50, filter: str = "all", user=Depends(require_user)):
    query_filter = {}
    if filter == "safe":    query_filter["safe"] = True
    if filter == "blocked": query_filter["safe"] = False
    docs = list(col_queries.find(query_filter).sort("timestamp", -1).limit(limit))
    return {"queries": bson_to_json(docs)}

@app.get("/admin/users")
async def list_users(user=Depends(require_admin)):
    docs = list(users_col.find({}, {"password": 0}).sort("created_at", -1))
    return {"users": bson_to_json(docs)}

@app.post("/admin/users/status")
async def update_user_status(data: dict, user=Depends(require_admin)):
    email     = data.get("email")
    newstatus = data.get("status")
    if not email or newstatus not in ["active", "blocked"]:
        return {"error": "Invalid request"}
    result = users_col.update_one({"email": email}, {"$set": {"status": newstatus}})
    if result.modified_count:
        return {"success": True}
    return {"error": "User not found"}

@app.post("/admin/users/delete")
async def delete_user(data: dict, user=Depends(require_admin)):
    email = data.get("email")
    if not email:
        return {"error": "Email required"}
    result = users_col.delete_one({"email": email, "role": {"$ne": "admin"}})
    if result.deleted_count:
        return {"success": True}
    return {"error": "User not found or cannot delete admin"}

if __name__ == "__main__":
    print("\n" + "="*50)
    print("🚀 PRIVACY RAG SYSTEM — Auth + MongoDB")
    print("="*50)
    print("🌐 Open: http://localhost:8000")
    print("="*50 + "\n")
    uvicorn.run(app, host="127.0.0.1", port=8000)