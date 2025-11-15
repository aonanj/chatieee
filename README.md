# ChatIEEE

> A RAG (Retrieval-Augmented Generation) system designed to search and query IEEE 802.11 standards documents using semantic search powered by OpenAI embeddings and PostgreSQL with pgvector.

## Overview

ChatIEEE is a PDF ingestion and retrieval system that:
- Extracts and chunks IEEE 802.11 standards documents
- Generates embeddings for semantic search using OpenAI's API
- Stores chunks and embeddings in a PostgreSQL database with pgvector extension
- Enables efficient similarity search across technical documentation

## Features

- **PDF Ingestion**: Parse PDF documents with `pdfplumber` to extract text and tables
- **Smart Chunking**: Automatically chunk documents into semantically meaningful segments (~1800 chars)
- **Table Extraction**: Separate handling of tabular data with markdown-like representation
- **Embedding Generation**: Batch embedding computation using OpenAI's `text-embedding-3-small` model
- **Deduplication**: Checksum-based document tracking to avoid redundant processing
- **PostgreSQL/pgvector Backend**: Efficient vector similarity search using Neon-hosted PostgreSQL 17

## Project Structure

```
chatieee/
├── src/
│   ├── __init__.py
│   ├── config.py                    # Environment configuration
│   ├── ingest/
│   │   ├── pdf_ingest.py           # PDF parsing and chunking
│   │   └── embed_and_update_chunks.py  # Batch embedding generation
│   └── utils/
│       ├── database.py              # Database helpers and queries
│       └── logger.py                # Logging configuration
├── documents/                       # IEEE documents directory
│   └── IEEE802-2024.pdf
├── instructions/                    # Project documentation
├── issues/                          # Issue tracking
├── DATABASE_SCHEMA.md               # Database schema documentation
├── pyproject.toml                   # Project metadata and dependencies
├── requirements.txt                 # Pinned dependencies
└── README.md                        # This file
```

## Database Schema

The system uses four main tables:

- **`rag_document`**: Stores document metadata, checksums, and provenance
- **`rag_document_page`**: Raw per-page text for debugging and reprocessing
- **`rag_chunk`**: Text chunks with embeddings (vector(1536)) for similarity search
- **`rag_ingestion_run`**: Tracks ingestion job history and status

See [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) for complete schema details.

## Requirements

- Python 3.13+
- PostgreSQL 17 with pgvector extension (hosted on Neon.text)
- OpenAI API key

## Installation

1. Clone the repository:
```bash
git clone https://github.com/aonanj/chatieee.git
cd chatieee
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
export DATABASE_URL="postgresql://..."  # Your Neon connection string
export OPENAI_API_KEY="sk-..."          # Your OpenAI API key
export EMBEDDING_MODEL="text-embedding-3-small"  # Optional, defaults to this
```

## Usage

### Ingest a PDF Document

```bash
python src/ingest/pdf_ingest.py documents/IEEE802-2024.pdf \
    --external-id ieee_802_2024 \
    --title "IEEE 802.11 Standard 2024" \
    --description "IEEE 802.11 wireless LAN standard"
```

This will:
1. Compute a checksum for change detection
2. Extract text and tables from each page
3. Create semantic chunks (~1800 characters)
4. Store chunks in the database (without embeddings)

### Generate Embeddings

After ingesting, generate embeddings for the chunks:

```bash
python src/ingest/embed_and_update_chunks.py --max-chunks 500
```

Or for a specific document:

```bash
python src/ingest/embed_and_update_chunks.py --document-id 42 --max-chunks 200
```

## Development

### Code Quality Tools

The project uses:
- **Ruff**: Linting and code formatting
- **mypy**: Type checking (configured but optional)
- **pytest**: Testing framework

Run linting:
```bash
ruff check src/
```

Auto-fix issues:
```bash
ruff check --fix src/
```

### Development Dependencies

Install development tools:
```bash
pip install -e ".[dev]"
```

## Configuration

Environment variables:
- `DATABASE_URL`: PostgreSQL connection string (required)
- `OPENAI_API_KEY`: OpenAI API key for embeddings (required)
- `EMBEDDING_MODEL`: OpenAI model name (default: `text-embedding-3-small`)
- `LOG_TO_FILE`: Enable file logging (default: false)
- `LOG_FILE_PATH`: Log file location (default: `chatieee.log`)

## Database Setup

The PostgreSQL database must have the pgvector extension enabled:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

The schema includes proper indexes for efficient similarity search and document lookups. Refer to [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) for setup details.

## License

This repository is publicly viewable for portfolio purposes only. The code is proprietary.
Copyright © 2025 Phaethon Order LLC. All rights reserved.
See [LICENSE](LICENSE.md) for terms.

## Contact

Questions or support: [support@phaethon.llc](mailto:support@phaethon.llc).
