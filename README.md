# 📄🤖 Offline PDF Q&A with RAG

Ask questions about your PDFs and get answers grounded in the document, **fully offline**. No API keys, no cloud, no data leaving your machine.

---

## ✨ Features

- 📚 Upload one or more PDFs and query them in natural language
- 🔒 100% local: embeddings, vector store, and LLM all run on your machine
- 🎯 Answers are grounded in retrieved chunks, with source page references
- ⚡ Fast semantic search using a local vector index
- 🧩 Modular pipeline: swap the LLM, embedding model, or vector store easily

## 🧠 How It Works

```
PDF → Text Extraction → Chunking → Embeddings → Vector Store
                                                     │
User Question → Embed Query → Top-K Retrieval ───────┘
                                   │
                         Context + Question → Local LLM → Answer
```

1. **Ingest:** extract text from PDFs and split it into overlapping chunks
2. **Embed:** convert chunks into vectors with a local embedding model
3. **Store:** save vectors in a local index (FAISS / ChromaDB)
4. **Retrieve:** find the top-K chunks most similar to your question
5. **Generate:** pass the chunks and question to a local LLM to produce the answer

## 🛠️ Tech Stack

| Component        | Tool                                          |
| ---------------- | --------------------------------------------- |
| Language         | Python 3.10+                                  |
| PDF parsing      | PyMuPDF / pypdf                               |
| Embeddings       | sentence-transformers (`all-MiniLM-L6-v2`)    |
| Vector store     | FAISS or ChromaDB                             |
| LLM (local)      | Ollama (Llama 3 / Mistral / Phi-3)            |
| Orchestration    | LangChain                                     |
| UI               | Streamlit                                     |

> Adjust this table to match what you actually used.

##  Getting Started

### Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com) installed
- ~8 GB RAM recommended for 7B models

### Installation

```bash
git clone https://github.com/mirzamudassir1/offline-pdf-rag.git
cd offline-pdf-rag

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### Download a local model (one-time, needs internet)

```bash
ollama pull llama3
```

After this, everything runs without internet. The embedding model is also cached locally after its first download.

## ▶️ Usage

**1. Add your PDFs**

Place them in the `data/` folder.

**2. Build the index**

```bash
python ingest.py
```

**3. Launch the app**

```bash
streamlit run app.py
```

Open `http://localhost:8501`, then ask questions such as:

- *"Summarize chapter 3."*
- *"What are the key conclusions of this paper?"*
- *"What does the document say about payment terms?"*

## ⚙️ Configuration

Edit `config.py`:

| Setting           | Default              | Description                          |
| ----------------- | -------------------- | ------------------------------------ |
| `CHUNK_SIZE`      | `1000`               | Characters per chunk                 |
| `CHUNK_OVERLAP`   | `200`                | Overlap between chunks               |
| `TOP_K`           | `4`                  | Chunks retrieved per question        |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2`   | Local embedding model                |
| `LLM_MODEL`       | `llama3`             | Ollama model name                    |

## 🔧 Troubleshooting

- **Ollama connection error:** make sure the Ollama service is running (`ollama serve`)
- **Empty or garbled answers:** the PDF may be scanned images; run OCR (e.g. `ocrmypdf`) first
- **Slow responses:** use a smaller model (`phi3`, `llama3.2:3b`) or reduce `TOP_K`
- **Out of memory:** lower `CHUNK_SIZE` or switch to a quantized model

## ⚠️ Limitations

- Scanned PDFs need OCR before ingestion
- Answer quality depends on the local model size
- Tables and complex layouts may not extract cleanly

## 🗺️ Roadmap

- [ ] OCR support for scanned documents
- [ ] Chat history and follow-up questions
- [ ] Support for DOCX and TXT files
- [ ] Highlight source passages in the PDF viewer
- [ ] Docker setup

## 🤝 Contributing

Contributions are welcome. Fork the repo, create a feature branch, and open a pull request.

## 📜 License

MIT. See [LICENSE](LICENSE) for details.

## 👤 Author

**Mirza**: [@mirzamudassir1](https://github.com/mirzamudassir1)
