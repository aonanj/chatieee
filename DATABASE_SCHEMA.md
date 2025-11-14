# Database Schema

This document outlines the database schema for the project. The database is a **PostgreSQL 17** instance hosted on [**Neon**](https://neon.tech/).

## Table of Contents

* [public.documents](#publicdocuments)
* [public.nodes](#publicnodes)

---

## public.documents

Stores the core documents data.

### Columns

| Column | Type | Nullable | Default |
| :--- | :--- | :--- | :--- |
| `document_id` | `bigint` | not null | `nextval('documents_document_id_seq'::regclass)` |
| `file_name` | `text` | not null | |
| `file_hash` | `character varying(64)` | not null | |
| `created at` | `timestamp with time zone` | | `CURRENT_TIMESTAMP` |


### Indexes

* `documents_pkey` PRIMARY KEY, btree `(document_id)`
* `documents_file_name_key` UNIQUE CONSTRAINT, btree `(file_name)`
* `idx_documents_file_hash` btree `(file_hash)`

### Referenced By

* `TABLE "nodes"` CONSTRAINT `"fk_document"` FOREIGN KEY `(document_id)` REFERENCES `documents(document_id)` ON DELETE CASCADE

---

## public.nodes

Stores the nodes corresponding to embeddings.

### Columns

| Column | Type | Nullable | Default |
| :--- | :--- | :--- | :--- |
| `node_id` | `uuid` | not null | `gen_random_uuid()` |
| `document_id` | `bigint` | not null | |
| `text_content` | `text` | not null | |
| `metadata` | `jsonb` | | |
| `embedding` | `vector(1536)` | | |


### Indexes

* `nodes_pkey` PRIMARY KEY, btree `(node_id)`
* `idx_nodes_document_id` btree `(document_id)`
* `idx_nodes_embedding_hnsw` hnsw `(embedding vector_cosine_ops)`
* `idx_nodes_metadata` gin `(metadata)`

### Foreign-key constraints:
`fk_document` FOREIGN KEY `(document_id)` REFERENCES `documents(document_id)` ON DELETE CASCADE

---