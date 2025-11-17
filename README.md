# ChatIEEE

> A full-stack RAG (Retrieval-Augmented Generation) system designed to search and query IEEE 802.11 standards documents using semantic search powered by OpenAI embeddings and PostgreSQL with pgvector.

## Overview

ChatIEEE is an intelligent retrieval system to search IEEE 802.11 standard documentation. This service combines:
- **Backend**: FastAPI server with advanced RAG pipeline featuring hybrid search (vector + lexical) and optional LLM reranking
- **Frontend**: Next.js 16 web application with React 19 for querying documents and uploading PDFs
- **Database**: PostgreSQL 17 with pgvector extension hosted on Neon for efficient similarity search
- **Storage**: Firebase Storage for extracted figure images

## Features

### Document Processing
- **PDF Ingestion**: Parse PDF documents with `pdfplumber` to extract text, tables, and figures
- **Strikeout Filtering**: Ignore strikethrough annotations so deleted text never reaches the chunker
- **Smart Chunking**: Automatically chunk documents into semantically meaningful segments (~1800 chars)
- **Structure Tracking**: Extract and preserve document structure (headings, sections, page numbers)
- **Table Extraction**: Separate handling of tabular data with markdown-like representation
- **Figure Extraction**: Extract diagrams and figures with captions for enhanced context
- **Deduplication**: Checksum-based document tracking to avoid redundant processing

### Search & Retrieval
- **Hybrid Search**: Combine vector similarity search with lexical (full-text) search
- **LLM Reranking**: Optional GPT-based reranking for improved result relevance
- **Embedding Generation**: Batch embedding computation using OpenAI's `text-embedding-3-small` model
- **Figure Matching**: Retrieve relevant figures based on query context
- **Answer Generation**: Generate answers from retrieved context using OpenAI GPT models

### Web Interface
- **Query Interface**: Clean, modern UI for asking questions about IEEE standards
- **Ingest Interface**: Upload and process new PDF documents through the web UI
- **Real-time Feedback**: Status updates during ingestion and query processing
- **Source Attribution**: Display chunks and figures used to generate answers

## Architecture

### Backend Stack
- **FastAPI** - Modern async Python web framework
- **PostgreSQL 17 + pgvector** - Vector database hosted on Neon
- **OpenAI API** - Embeddings and chat completion
- **Firebase Storage** - Cloud storage for extracted images
- **pdfplumber** - PDF text and table extraction

### Frontend Stack
- **Next.js 16** - React framework with App Router
- **React 19** - Latest React with modern features
- **TypeScript** - Type-safe development
- **Tailwind CSS 4** - Utility-first styling

## Project Structure

```
chatieee/
├── app/                             # Next.js frontend application
│   ├── page.tsx                    # Main query interface
│   ├── layout.tsx                  # Root layout with fonts
│   ├── globals.css                 # Global styles
│   └── ingest/
│       └── page.tsx                # PDF upload interface
├── src/                             # Python backend
│   ├── api.py                      # FastAPI application and endpoints
│   ├── config.py                   # Environment configuration
│   ├── query.py                    # Hybrid search and reranking
│   ├── query_rag.py                # Simple RAG query pipeline
│   ├── ingest/
│   │   ├── pdf_ingest.py           # PDF parsing and chunking
│   │   ├── embed_and_update_chunks.py  # Batch embedding generation
│   │   └── embedding.py            # Embedding client wrapper
│   └── utils/
│       ├── database.py             # Database helpers and queries
│       ├── logger.py               # Logging configuration
│       └── storage.py              # Firebase storage helpers
├── documents/                       # Uploaded IEEE documents
├── public/                          # Static assets
│   ├── fonts/                      # Inter font files
│   └── images/                     # Logo and icons
├── instructions/                    # Development documentation
├── issues/                          # Issue tracking
├── DATABASE_SCHEMA.md               # Complete database schema
├── pyproject.toml                   # Python project metadata
├── requirements.txt                 # Pinned Python dependencies
├── package.json                     # Node.js dependencies
├── tsconfig.json                    # TypeScript configuration
└── README.md                        # This file
```

## Database Schema

The system uses five main tables:

- **`rag_document`**: Stores document metadata, checksums, and provenance
- **`rag_document_page`**: Raw per-page text for debugging and reprocessing
- **`rag_chunk`**: Text chunks with embeddings (vector(1536)) for similarity search
- **`rag_figure`**: Extracted figures with images, captions, and labels
- **`rag_ingestion_run`**: Tracks ingestion job history and status

See [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) for complete schema details.

## Requirements

### Backend
- Python 3.13+
- PostgreSQL 17 with pgvector extension (hosted on Neon)
- OpenAI API key
- Firebase credentials (for image storage)

### Frontend
- Node.js 20+
- npm or yarn

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/aonanj/chatieee.git
cd chatieee
```

### 2. Backend Setup

Install Python dependencies:

```bash
pip install -r requirements.txt
```

Set up environment variables (create a `.env` file):

```bash
# Database
DATABASE_URL="postgresql://..."  # Your Neon connection string

# OpenAI
OPENAI_API_KEY="sk-..."          # Your OpenAI API key
EMBEDDING_MODEL="text-embedding-3-small"  # Optional, defaults to this
ANSWER_MODEL="gpt-5-mini"        # Optional, defaults to this

# Firebase Storage (for figure images)
FIREBASE_STORAGE_BUCKET="your-bucket.firebasestorage.app"

# Search Configuration (optional)
DEFAULT_VECTOR_K="20"            # Number of vector search results
DEFAULT_LEXICAL_K="20"           # Number of lexical search results
DEFAULT_TOP_K="10"               # Final number of results after reranking
MAX_CONTEXT_CHARS="8000"         # Max characters for context

# CORS (optional)
CORS_ALLOW_ORIGINS="http://localhost:3000,https://your-domain.com"
```

### 3. Frontend Setup

Install Node.js dependencies:

```bash
npm install
```

Configure the API endpoint (create a `.env.local` file):

```bash
NEXT_PUBLIC_API_BASE_URL="http://localhost:8000"
```

## Usage

### Start the Backend API

Run the FastAPI server:

```bash
# Development mode with auto-reload
uvicorn src.api:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000` with interactive docs at `http://localhost:8000/docs`.

### Start the Frontend

Run the Next.js development server:

```bash
npm run dev
```

The web interface will be available at `http://localhost:3000`.

### API Endpoints

#### Health Check
```bash
curl http://localhost:8000/healthz
```

#### Ingest a PDF Document (via API)

```bash
curl -X POST "http://localhost:8000/ingest_pdf" \
  -F "pdf=@documents/IEEE802-2024.pdf" \
  -F "external_id=ieee_802_2024" \
  -F "title=IEEE 802.11 Standard 2024" \
  -F "description=IEEE 802.11 wireless LAN standard"
```

This will:
1. Compute a checksum for change detection
2. Extract text, tables, and figures from each page
3. Create semantic chunks (~1800 characters)
4. Generate embeddings for all chunks
5. Store everything in the database

#### Query the System (via API)

```bash
curl -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the scope of IEEE 802-2024?"}'
```

Response includes:
- `answer`: Generated answer from the RAG system
- `chunks`: Source chunks used to generate the answer
- `figures`: Relevant figures referenced in the context

### Web Interface Usage

#### Query Documents
1. Navigate to `http://localhost:3000`
2. Enter question in the search box
3. View the generated answer with source chunks and figures

#### Upload New Documents
1. Navigate to `http://localhost:3000/ingest`
2. Select a PDF file to upload
3. Fill in metadata (external ID, title, description)
4. Click "Upload & Ingest" to process the document

### Command-Line Scripts

#### Ingest a PDF (CLI)

```bash
python src/ingest/pdf_ingest.py documents/IEEE802-2024.pdf \
    --external-id ieee_802_2024 \
    --title "IEEE 802.11 Standard 2024" \
    --description "IEEE 802.11 wireless LAN standard"
```

#### Generate Embeddings (CLI)

```bash
python src/ingest/embed_and_update_chunks.py
```

This processes chunks without embeddings and generates them in batches.

#### Query RAG System (CLI)

```bash
python src/query_rag.py "What is the scope of IEEE 802-2024?" \
    --k 8 \
    --max-context-chars 8000
```

## Development

### Code Quality Tools

The project uses:
- **Ruff**: Fast Python linting and code formatting
- **mypy**: Type checking (configured but optional)
- **pytest**: Testing framework
- **ESLint**: JavaScript/TypeScript linting
- **TypeScript**: Type-safe frontend development

Run Python linting:
```bash
ruff check src/
```

Auto-fix Python issues:
```bash
ruff check --fix src/
```

Run frontend linting:
```bash
npm run lint
```

### Development Dependencies

Install Python development tools:
```bash
pip install -e ".[dev]"
```

## Configuration

### Environment Variables

#### Backend (`.env`)
- `DATABASE_URL`: PostgreSQL connection string (required)
- `OPENAI_API_KEY`: OpenAI API key for embeddings and chat (required)
- `EMBEDDING_MODEL`: Model for embeddings (default: `text-embedding-3-small`)
- `ANSWER_MODEL`: Model for answer generation (default: `gpt-5-mini`)
- `RAG_RERANK_MODEL`: Model for LLM reranking (default: `gpt-5-mini`)
- `DEFAULT_VECTOR_K`: Number of vector search results (default: `20`)
- `DEFAULT_LEXICAL_K`: Number of lexical search results (default: `20`)
- `DEFAULT_TOP_K`: Final number of results to return (default: `10`)
- `DEFAULT_VERBOSITY`: Answer verbosity level (default: `high`)
- `MAX_CONTEXT_CHARS`: Maximum context length (default: `8000`)
- `CHUNK_UPDATE_BATCH_SIZE`: Embedding batch size (default: `200`)
- `FIREBASE_STORAGE_BUCKET`: Firebase bucket for images
- `CORS_ALLOW_ORIGINS`: Comma-separated list of allowed origins
- `LOG_TO_FILE`: Enable file logging (default: `false`)
- `LOG_FILE_PATH`: Log file location (default: `chatieee.log`)

#### Frontend (`.env.local`)
- `NEXT_PUBLIC_API_BASE_URL`: Backend API URL (default: `http://localhost:8000`)
- `NEXT_PUBLIC_FIREBASE_API_KEY`: Firebase web API key used to initialize the Storage client
- `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN`: Firebase auth domain (e.g., `your-project.firebaseapp.com`)
- `NEXT_PUBLIC_FIREBASE_PROJECT_ID`: Firebase project ID
- `NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET`: Firebase storage bucket (e.g., `chat-ieee.firebasestorage.app`)
- `NEXT_PUBLIC_FIREBASE_APP_ID`: Firebase app ID
- `NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID`: Messaging sender ID (optional, but recommended to keep configs aligned)

## Database Setup

The PostgreSQL database must have the pgvector extension enabled:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

The schema includes:
- Vector indexes for similarity search (HNSW algorithm)
- B-tree indexes for document and chunk lookups
- Full-text search indexes (tsvector) for lexical search
- Foreign key constraints for data integrity

Refer to [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) for complete setup details.

## Technical Details

### Hybrid Search Strategy

ChatIEEE implements a hybrid search approach:

1. **Vector Search**: Semantic similarity using OpenAI embeddings and pgvector
2. **Lexical Search**: Full-text search using PostgreSQL's tsvector
3. **Fusion**: Combines results from both approaches using reciprocal rank fusion
4. **Reranking**: Optional LLM-based reranking for improved relevance

### Document Processing Pipeline

1. **Upload**: PDF uploaded via web UI or API
2. **Extraction**: Extract text, tables, and figures with pdfplumber
3. **Chunking**: Create semantic chunks with structure tracking
4. **Embedding**: Generate embeddings using OpenAI API
5. **Storage**: Store in PostgreSQL with pgvector indexes
6. **Figure Storage**: Upload extracted images to Firebase Storage

### Answer Generation

1. **Query Processing**: User query is embedded
2. **Retrieval**: Hybrid search retrieves relevant chunks
3. **Context Building**: Assemble context from top chunks
4. **Figure Matching**: Find relevant figures mentioned in context
5. **Generation**: GPT model generates answer from context
6. **Response**: Return answer with source attribution

## Performance Considerations

- **Batch Embedding**: Process embeddings in configurable batch sizes
- **Connection Pooling**: psycopg connection pool for database efficiency
- **Async API**: FastAPI async endpoints for concurrent requests
- **Vector Indexes**: HNSW indexes for fast approximate nearest neighbor search
- **Incremental Updates**: Checksum-based change detection avoids reprocessing

## Troubleshooting

### Common Issues

**No embeddings generated**: Run `embed_and_update_chunks.py` after ingestion

**CORS errors**: Add your frontend URL to `CORS_ALLOW_ORIGINS`

**Connection errors**: Verify `DATABASE_URL` and PostgreSQL is accessible

**OpenAI API errors**: Check `OPENAI_API_KEY` is valid and has credits

**Figure upload fails**: Verify Firebase credentials and bucket name

## Future Enhancements

- [ ] Citation tracking and source highlighting
- [ ] Advanced figure recognition with vision models
- [ ] User authentication
- [ ] Saved queries/responses
- [ ] Custom embedding models (Sentence Transformers, etc.)

## License

This repository is publicly viewable for portfolio purposes only. The code is proprietary.

Copyright © 2025 Phaethon Order LLC. All rights reserved.

See [LICENSE.md](LICENSE.md) for complete terms.

## Authors

- **Phaethon Order LLC** - [admin@phaethon.llc](mailto:admin@phaethon.llc)

## Repository

- **GitHub**: [https://github.com/aonanj/chatieee](https://github.com/aonanj/chatieee)
- **Issues**: [https://github.com/aonanj/chatieee/issues](https://github.com/aonanj/chatieee/issues)

---

**ChatIEEE** - Intelligent search for IEEE 802.11 standards documentation
