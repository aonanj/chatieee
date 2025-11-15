# Database Schema

This document outlines the database schema for the project. The database is a **PostgreSQL 17** instance hosted on [**Neon**](https://neon.tech/).

## Table of Contents

* [public.rag_document](#publicrag_document)
* [public.rag_document_page](#publicrag_document_page)
* [public.rag_chunk](#publicrag_chunk)
* [public.rag_ingestion_run](#publicrag_ingestion_run)

---

## public.documents

Stores the core documents data. Tracks each PDF once, with metadata to support dedupe, re-ingest, and provenance.

### Columns

| Column | Type | Nullable | Default |
| :--- | :--- | :--- | :--- |
| `id` | `bigint` | not null | `nextval('rag_document_id_seq'::regclass)` |
| `external_id` | `text` | true | |
| `title` | `text` | true | |
| `description` | `text` | true | |
| `source_type` | `text` | not null | 'pdf'::text |
| `source_uri` | `text` | true | |
| `checksum` | `text` | true | |
| `total_pages` | `integer` | true | |
| `metadata` | `jsonb` | not null | '{}'::jsonb |
| `created_at` | `timestamp with time zone` | not null | `now()` |
| `updated_at` | `timestamp with time zone` | not null | `now()` |


### Indexes

* `rag_document_pkey` PRIMARY KEY, btree `(id)`
* `idx_rag_document_external_id` UNIQUE, btree `(external_id)`

### Referenced by

* TABLE `rag_chunk` CONSTRAINT `rag_chunk_document_id_fkey` FOREIGN KEY `(document_id)` REFERENCES `rag_document(id)` ON DELETE CASCADE
* TABLE `rag_document_page` CONSTRAINT `rag_document_page_document_id_fkey` FOREIGN KEY `(document_id)` REFERENCES `rag_document(id)` ON DELETE CASCADE
* TABLE `rag_ingestion_run` CONSTRAINT `rag_ingestion_run_document_id_fkey` FOREIGN KEY `(document_id)` REFERENCES `rag_document(id)` ON DELETE CASCADE

---

## public.rag_document_page

Stores the pages in each document in `rag_document`. Used for: debug parsing; rebuild chunks from raw per-page text; store layout/coordinate info separate from chunk text.

### Columns

| Column | Type | Nullable | Default |
| :--- | :--- | :--- | :--- |
| `id` | `bigint` | not null | `nextval('rag_document_page_id_seq'::regclass)` |
| `document_id` | `bigint` | not null | |
| `page_number` | `integer` | not null | |
| `text` | `text` | true | |
| `metadata` | `jsonb` | not null | '{}'::jsonb |
| `created_at` | `timestamp with time zone` | not null | `now()` |


### Indexes

* `rag_document_page_pkey` PRIMARY KEY, btree `(id)`
* `idx_rag_document_page_doc_page` UNIQUE, btree `(document_id, page_number)`

### Foreign-key constraints

* `rag_document_page_document_id_fkey` FOREIGN KEY `(document_id)` REFERENCES `rag_document(id)` ON DELETE CASCADE

---

## public.rag_chunk

Stores chunks and embeddings correspondings to documents in `rag_documents`.

### Columns

| Column | Type | Nullable | Default |
| :--- | :--- | :--- | :--- |
| `id` | `bigint` | not null | `nextval('rag_chunk_id_seq'::regclass)` |
| `document_id` | `bigint` | not null | |
| `chunk_index` | `integer` | not null | |
| `page_start` | `integer` | true | |
| `page_end` | `integer` | true | |
| `content` | `text` | not null | |
| `heading` | `text` | true | |
| `chunk_type` | `text` | not null | 'body'::text |
| `embedding` | `vector(1536)` | true | |
| `metadata` | `jsonb` | not null | '{}'::jsonb |
| `created_at` | `timestamp with time zone` | not null | `now()` |


### Indexes

* `rag_chunk_pkey` PRIMARY KEY, btree `(id)`
* `idx_rag_chunk_document_id` btree `(document_id)`
* `idx_rag_chunk_document_index` UNIQUE, btree `(document_id, chunk_index)`
* `idx_rag_chunk_embedding_ivfflat` ivfflat `(embedding)` WITH `(lists='100')`

### Foreign-key constraints

* `rag_chunk_document_id_fkey` FOREIGN KEY `(document_id)` REFERENCES `rag_document(id)` ON DELETE CASCADE

---

## public.rag_ingestion_run

Logs document ingestion runs. Used for: ingestion idempotency; debugging.

### Columns

| Column | Type | Nullable | Default |
| :--- | :--- | :--- | :--- |
| `id` | `bigint` | not null | `nextval('rag_document_id_seq'::regclass)` |
| `document_id` | `bigint` | not null | |
| `status` | `text` | not null | |
| `error_message` | `text` | true | |
| `started_at` | `timestamp with time zone` | not null | `now()` |
| `finished_at` | `timestamp with time zone` | true | |


### Indexes

* `rag_ingestion_run_pkey` PRIMARY KEY, btree `(id)`
* `idx_rag_ingestion_run_document_id` btree `(document_id)`

### Foreign-key constraints

* `rag_ingestion_run_document_id_fkey` FOREIGN KEY `(document_id)` REFERENCES `rag_document(id)` ON DELETE CASCADE