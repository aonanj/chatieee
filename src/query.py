from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

import psycopg
from psycopg import sql as _sql
from psycopg.rows import dict_row

from src import config
from src.ingest.embedding import EmbeddingClient, embedding_to_pgvector

logger = config.LOGGER

try:  # pragma: no
    from openai import OpenAI
except Exception:  # pragma: no cover
    logger.info("OpenAI library not found, LLM reranking will be disabled")
    OpenAI = None  # type: ignore

# Allow appendix-style labels like "FIG. B-5", "FIGURE 9-22C", and dotted forms.
FIGURE_RE = re.compile(
    r"\b(FIG(?:URE)?\.?\s*(?:[A-Z]+(?:[.\-]\s*)?)?\d+(?:[.\-–]\d+)*(?:[A-Za-z]+)?)",
    re.IGNORECASE,
)

@dataclass(slots=True)
class ChunkMatch:
    id: int
    document_id: int
    page_start: int | None
    page_end: int | None
    content: str
    metadata: dict[str, Any]
    vector_score: float | None = None
    lexical_score: float | None = None
    rerank_score: float | None = None
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "content": self.content,
            "metadata": self.metadata,
            "vector_score": self.vector_score,
            "lexical_score": self.lexical_score,
            "rerank_score": self.rerank_score,
        }

# query.py
@dataclass(slots=True)
class FigureMatch:
    id: int
    document_id: int
    figure_label: str
    page_number: int | None
    caption: str | None
    image_uri: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "figure_label": self.figure_label,
            "page_number": self.page_number,
            "caption": self.caption,
            "image_uri": self.image_uri,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class PageMatch:
    id: int
    document_id: int
    page_number: int
    image_uri: str | None
    metadata: dict[str, Any]
    chunk_ids: list[int]
    rank: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "page_number": self.page_number,
            "image_uri": self.image_uri,
            "metadata": self.metadata,
            "chunk_ids": self.chunk_ids,
            "rank": self.rank,
        }

class LLMReranker:
    def __init__(self, model: str | None = None) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        self._client = OpenAI(api_key=api_key) if (OpenAI and api_key) else None
        self.model = model or os.getenv("RAG_RERANK_MODEL", "gpt-5-mini")
    @property
    def available(self) -> bool:
        return self._client is not None
    def rerank(self, query: str, candidates: list[ChunkMatch]) -> list[ChunkMatch]:
        if not self.available or not candidates:
            return self._fallback(candidates)
        prompt = self._build_prompt(query, candidates)
        try:
            response = None
            if self._client is not None:
                response = self._client.responses.create(
                    model=self.model,
                    input=prompt
                )
            output = getattr(response, "output_text", None)
            if not output:
                output = response.output[0].content[0].text  # type: ignore[attr-defined]
            scores = self._parse_ranking_output(output)
            if not scores:
                logger.error("LLM reranker returned no parsable scores; falling back to heuristic ranking")
                return self._fallback(candidates)
            for candidate in candidates:
                if candidate.id in scores:
                    candidate.rerank_score = scores[candidate.id]
            remaining = [c for c in candidates if c.rerank_score is not None]
            if remaining:
                remaining.sort(key=lambda c: c.rerank_score or 0.0, reverse=True)
                rest = [c for c in candidates if c.rerank_score is None]
                rest.sort(key=lambda c: (c.vector_score or 0.0) + (c.lexical_score or 0.0), reverse=True)
                return remaining + rest
        except RuntimeError as exc:
            error = f"OpenAI client is not available: {exc}"
            logger.error(error)
            raise RuntimeError(error) from exc
        except Exception as exc:  # pragma: no cover - API failure path
            logger.error("LLM reranker failed, falling back to heuristic ranking", exc_info=exc)
        return self._fallback(candidates)
    def _fallback(self, candidates: list[ChunkMatch]) -> list[ChunkMatch]:
        if not candidates:
            return []
        max_vector = max((c.vector_score or 0.0) for c in candidates)
        max_lexical = max((c.lexical_score or 0.0) for c in candidates)
        for candidate in candidates:
            vector_component = (candidate.vector_score or 0.0) / max_vector if max_vector else 0.0
            lexical_component = (candidate.lexical_score or 0.0) / max_lexical if max_lexical else 0.0
            candidate.rerank_score = 0.6 * vector_component + 0.4 * lexical_component
        return sorted(candidates, key=lambda c: c.rerank_score or 0.0, reverse=True)

    def _build_prompt(self, query: str, candidates: list[ChunkMatch]) -> str:
        lines = [
            "You are a language model designed to evaluate the responses of this documentation query system.",
            "You will use a rating scale of 0 to 10, 0 being poorest response and 10 being the best.",
            "Responses with “not specified” or “no specific mention” or “rephrase question” or “unclear” or no documents returned or empty response are considered poor responses.",
            "Responses where the question appears to be answered are considered good.",
            "Responses that contain detailed answers are considered the best.",
            "Also, use your own judgement in analyzing if the question asked is actually answered in the response. Remember that a response that contains a request to “rephrase the question” is usually a non-response.",
            "Please rate the question/response pair entered. Only respond with the rating. No explanation necessary. Only integers.",
            "for answering the user's question. Return a JSON object with a 'ranking' array",
            "containing {“id”: chunk_id, “score”: relevance} objects in descending order.",
            "Query:",
            query.strip(),
            "\nPassages:",
        ]
        for candidate in candidates:
            snippet = candidate.content.strip().replace("\n", " ")
            lines.append(f"[{candidate.id}] {snippet}")
        return "\n".join(lines)

    def _parse_ranking_output(self, raw_output: str | None) -> dict[int, float]:
        if not raw_output:
            return {}
        try:
            parsed = json.loads(raw_output)
            logger.info("LLM reranker output parsed as JSON: %s", parsed)
        except json.JSONDecodeError:
            logger.error("LLM reranker produced non-JSON output: %s", raw_output[:200])
            return {}

        ranking_entries: list[Any] = []
        if isinstance(parsed, dict):
            ranking = (
                parsed.get("ranking")
                or parsed.get("rankings")
                or parsed.get("scores")
            )
            if ranking is None and {"id", "score"}.issubset(parsed.keys()):
                ranking_entries = [parsed]
            elif isinstance(ranking, list):
                ranking_entries = ranking
            elif parsed and all(isinstance(v, (int, float, str)) for v in parsed.values()):
                ranking_entries = [{"id": key, "score": value} for key, value in parsed.items()]
            else:
                logger.error("LLM reranker output missing 'ranking' array: %s", parsed)
                return {}
        elif isinstance(parsed, list):
            ranking_entries = parsed
        elif isinstance(parsed, (int, float, str)):
            logger.warning("LLM reranker returned scalar output instead of ranking JSON: %s", parsed)
            return {}
        else:
            logger.error("LLM reranker output has unexpected type: %s", type(parsed))
            return {}

        scores: dict[int, float] = {}
        for entry in ranking_entries:
            if not isinstance(entry, dict):
                continue
            try:
                candidate_id = int(entry["id"])
                candidate_score = float(entry["score"])
            except (KeyError, TypeError, ValueError):
                continue
            scores[candidate_id] = candidate_score
        return scores


class AnswerGenerator:
    def __init__(self, model: str | None = None, verbosity: str | None = None) -> None:
        if not OpenAI:
            error = "OpenAI SDK is not installed, cannot generate answers"
            logger.error(error)
            raise RuntimeError(error)
        api_key = config.OPENAI_API_KEY
        if not api_key:
            error = "OPENAI_API_KEY must be set to generate answers"
            logger.error(error)
            raise RuntimeError(error)
        self._client = OpenAI(api_key=api_key)
        self.model = model or config.ANSWER_MODEL
        self.verbosity = verbosity or config.DEFAULT_VERBOSITY

    def generate(self, question: str, chunks: Sequence[ChunkMatch], max_context_chars: int) -> str:
        if not chunks:
            return "No relevant content found in the indexed documents."
        context = self._build_context_snippets(chunks, max_context_chars)
        if not context:
            return "No relevant content found in the indexed documents."
        prompt = self._build_prompt(question, context)
        try:
            response = self._client.responses.create(model=self.model, input=prompt)
        except Exception as exc:  # pragma: no cover - network failure path
            logger.error("Failed to generate answer from OpenAI: %s", exc_info=exc)
            return "Unable to generate an answer at this time."
        answer = getattr(response, "output_text", None)
        if not answer:
            answer = response.output[0].content[0].text  # type: ignore[attr-defined]
        return answer.strip()

    def _build_context_snippets(self, chunks: Sequence[ChunkMatch], max_context_chars: int) -> str:
        snippets: list[str] = []
        total_chars = 0
        for index, chunk in enumerate(chunks, start=1):
            body = (chunk.content or "").strip()
            if not body:
                continue
            snippet = self._format_snippet(index, chunk, body)
            if max_context_chars > 0 and (total_chars + len(body) > max_context_chars and snippets):
                break
            snippets.append(snippet)
            total_chars += len(body)
        return "\n\n---\n\n".join(snippets)

    def _format_snippet(self, index: int, chunk: ChunkMatch, body: str) -> str:
        metadata = chunk.metadata or {}
        heading = (
            metadata.get("section")
            or metadata.get("heading")
            or metadata.get("title")
            or metadata.get("heading_override")
            or metadata.get("section_title")
        )
        page_start = metadata.get("page_start") or metadata.get("page") or metadata.get("page_number")
        page_end = metadata.get("page_end")
        document_label = (
            metadata.get("document_external_id")
            or metadata.get("document_title")
            or metadata.get("file_name")
            or f"doc-{chunk.document_id}"
        )
        location_parts = [f"Document: {document_label}"]
        if heading:
            location_parts.append(f"Section: {heading}")
        if page_start and page_end and page_start != page_end:
            location_parts.append(f"Pages: {page_start}-{page_end}")
        elif page_start:
            location_parts.append(f"Page: {page_start}")
        header = f"[Source {index}] {' | '.join(location_parts)}"
        return f"{header}\n{body}"

    def _build_prompt(self, question: str, context_snippets: str) -> str:
        return (
        "You are a technical assistant that answers questions strictly using the "
        "provided context snippets, which are excerpts from PDF documents such as "
        "technical standards or legal/technical specifications.\n"
        "Rules:\n"
        "1. Use ONLY the given context to answer. If the answer is not supported by the context, say you do not know.\n"
        "2. When you state a fact, reference the relevant source number(s) (e.g., [Source 1], [Source 3]).\n"
        "3. Do not invent section numbers, clause numbers, or page numbers that are not present in the context.\n"
        "4. Be concise and precise; prefer quoting short exact definitions or sentences from the context.\n"
        "5. If the context is contradictory or ambiguous, explain the ambiguity instead of guessing.\n"
        "6. If related figures are provided for a context, mention them explicitly (e.g., “As shown in FIG. 3 …”). Do not invent figures that are not listed.\n\n"
        "You are given several labeled source snippets from one or more PDF documents.\n\n"
        "Context snippets:\n"
        f"{context_snippets}\n\n"
        "Task:\n"
        f"Answer the following question using ONLY the information in the snippets above.\n\n"
        f"Question: {question}\n"
        ## "After your answer, list the sources you relied on in a brief 'Sources:' line, "
        ## "like 'Sources: [Source 1], [Source 3]'."
        )

class HybridRetriever:
    VECTOR_QUERY = """
        SELECT id, document_id, page_start, page_end, content, metadata,
               1 - (embedding <=> %(embedding)s::vector) AS similarity,
               (embedding <=> %(embedding)s::vector) AS distance
          FROM rag_chunk
         WHERE embedding IS NOT NULL
      ORDER BY embedding <=> %(embedding)s::vector
         LIMIT %(limit)s
    """
    LEXICAL_QUERY = """
        SELECT id, document_id, page_start, page_end, content, metadata,
               ts_rank_cd(content_tsv, plainto_tsquery('english', %(query)s)) AS rank
          FROM rag_chunk
         WHERE content_tsv @@ plainto_tsquery('english', %(query)s)
      ORDER BY rank DESC
         LIMIT %(limit)s
    """
    def __init__(
        self,
        conninfo: str,
        embedder: EmbeddingClient | None = None,
        reranker: LLMReranker | None = None,
    ) -> None:
        self.conninfo = conninfo
        self.embedder = embedder or EmbeddingClient()
        self.reranker = reranker or LLMReranker()
    def search(self, query: str, vector_k: int = 20, lexical_k: int = 20, final_k: int = 10) -> list[ChunkMatch]:
        query_embedding = self.embedder.embed(query)
        vector_param = embedding_to_pgvector(query_embedding.vector)
        with psycopg.connect(self.conninfo) as conn:
            vector_results = self._vector_search(conn, vector_param, limit=vector_k)
            lexical_results = self._lexical_search(conn, query, limit=lexical_k)
        combined = self._combine_results(vector_results, lexical_results)
        reranked = self.reranker.rerank(query, combined)
        return reranked[:final_k]
    def _vector_search(self, conn: psycopg.Connection[Any], vector_param: str, limit: int) -> list[ChunkMatch]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(self.VECTOR_QUERY, {"embedding": vector_param, "limit": limit})
            rows = cur.fetchall()
        results: list[ChunkMatch] = []
        for row in rows:
            results.append(
                ChunkMatch(
                    id=row["id"],
                    document_id=row["document_id"],
                    page_start=row.get("page_start"),
                    page_end=row.get("page_end"),
                    content=row["content"],
                    metadata=row.get("metadata") or {},
                    vector_score=row["similarity"],
                )
            )
        return results
    def _lexical_search(self, conn: psycopg.Connection[Any], query: str, limit: int) -> list[ChunkMatch]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(self.LEXICAL_QUERY, {"query": query, "limit": limit})
            rows = cur.fetchall()
        results: list[ChunkMatch] = []
        for row in rows:
            results.append(
                ChunkMatch(
                    id=row["id"],
                    document_id=row["document_id"],
                    page_start=row.get("page_start"),
                    page_end=row.get("page_end"),
                    content=row["content"],
                    metadata=row.get("metadata") or {},
                    lexical_score=row["rank"],
                )
            )
        return results
    def _combine_results(
        self,
        vector_results: Iterable[ChunkMatch],
        lexical_results: Iterable[ChunkMatch],
    ) -> list[ChunkMatch]:
        combined: dict[int, ChunkMatch] = {}
        for result in vector_results:
            combined[result.id] = result
        for result in lexical_results:
            existing = combined.get(result.id)
            if existing:
                existing.lexical_score = result.lexical_score
                if existing.metadata == {} and result.metadata:
                    existing.metadata = result.metadata
            else:
                combined[result.id] = result
        return list(combined.values())

def extract_figure_labels(text: str) -> list[str]:
    labels: set[str] = set()
    for match in FIGURE_RE.finditer(text or ""):
        labels.add(normalise_figure_label(match.group(1)))
    return sorted(labels)

def normalise_figure_label(raw: str) -> str:
    cleaned = re.sub(r"(?i)^fig(?:ure)?\.?\s*", "", raw or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        return "FIGURE"
    return f"FIGURE {cleaned.upper()}"

def get_pages_for_chunks(
    conninfo: str,
    chunks: list[ChunkMatch],
) -> list[PageMatch]:
    if not chunks:
        return []

    chunk_order = {chunk.id: idx for idx, chunk in enumerate(chunks)}
    page_requirements: dict[tuple[int, int], set[int]] = {}
    page_rank: dict[tuple[int, int], int] = {}

    for chunk in chunks:
        if chunk.page_start is None and chunk.page_end is None:
            continue
        start = chunk.page_start or chunk.page_end
        end = chunk.page_end or chunk.page_start or start
        if start is None:
            continue
        if end is None or end < start:
            end = start
        for page_number in range(start, end + 1):
            key = (chunk.document_id, page_number)
            if key not in page_requirements:
                page_requirements[key] = set()
            page_requirements[key].add(chunk.id)
            page_rank[key] = min(page_rank.get(key, chunk_order[chunk.id]), chunk_order[chunk.id])

    if not page_requirements:
        logger.info("No page coverage detected for retrieved chunks")
        return []

    values = ",".join(["(%s, %s)"] * len(page_requirements))
    sql = f"""
        WITH requested(document_id, page_number) AS (
            VALUES {values}
        )
        SELECT p.id, p.document_id, p.page_number, p.image_uri, p.metadata
          FROM rag_document_page p
          JOIN requested r
            ON p.document_id = r.document_id
           AND p.page_number = r.page_number
    """

    params: list[Any] = []
    for doc_id, page_number in page_requirements:
        params.extend([doc_id, page_number])

    matches: list[PageMatch] = []
    with psycopg.connect(conninfo) as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_sql.SQL(sql), params)  # type: ignore[arg-type]
        for row in cur:
            key = (row["document_id"], row["page_number"])
            related_chunks = sorted(
                page_requirements.get(key, set()),
                key=lambda cid: chunk_order.get(cid, float("inf")),
            )
            matches.append(
                PageMatch(
                    id=row["id"],
                    document_id=row["document_id"],
                    page_number=row["page_number"],
                    image_uri=row.get("image_uri"),
                    metadata=row.get("metadata") or {},
                    chunk_ids=related_chunks,
                    rank=page_rank.get(key, len(chunks)),
                )
            )

    matches.sort(key=lambda m: (m.rank, m.document_id, m.page_number))
    return matches

def get_figures_for_chunks(
    conninfo: str,
    chunks: list[ChunkMatch],
) -> list[FigureMatch]:
    if not chunks:
        return []

    pairs: set[tuple[int, str]] = set()
    for ch in chunks:
        for label in extract_figure_labels(ch.content):
            pairs.add((ch.document_id, label))

    if not pairs:
        logger.info("No figure labels found in any chunks")
        return []

    values = ",".join(["(%s, %s)"] * len(pairs))
    sql = f"""
        WITH q(document_id, figure_label) AS (
            VALUES {values}
        )
        SELECT f.id, f.document_id, f.figure_label, f.page_number,
               f.caption, f.image_uri, f.metadata
          FROM rag_figure f
          JOIN q
            ON f.document_id = q.document_id
           AND f.figure_label = q.figure_label
    """

    params: list[Any] = []
    for doc_id, label in pairs:
        params.extend([doc_id, label])

    matches: list[FigureMatch] = []
    with psycopg.connect(conninfo) as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_sql.SQL(sql), params) # type: ignore
            logger.info("Processing figure retrieval results")
            for row in cur:
                matches.append(
                    FigureMatch(
                        id=row["id"],
                        document_id=row["document_id"],
                        figure_label=row["figure_label"],
                        page_number=row["page_number"],
                        caption=row["caption"],
                        image_uri=row["image_uri"],
                        metadata=row["metadata"] or {},
                    )
                )
    return matches

def answer_query(query: str):
    database_url = config.DATABASE_URL or ""

    embedder = EmbeddingClient(model=config.EMBEDDING_MODEL)
    reranker = LLMReranker(model=config.RERANK_MODEL)
    retriever = HybridRetriever(conninfo=database_url, embedder=embedder, reranker=reranker)
    results = retriever.search(query, vector_k=config.VECTOR_K, lexical_k=config.LEXICAL_K, final_k=config.TOP_K)
    logger.info("Retrieved %s candidate chunks for query '%s'", len(results), query)
    pages = get_pages_for_chunks(database_url, results)
    logger.info("Retrieved %s page images related to the chunks", len(pages))
    figures = get_figures_for_chunks(database_url, results)
    logger.info("Retrieved %s figures related to the chunks", len(figures))
    try:
        answerer = AnswerGenerator(model=config.ANSWER_MODEL, verbosity=config.DEFAULT_VERBOSITY)
        answer = answerer.generate(query, results, max_context_chars=config.MAX_CONTEXT_CHARS)
        payload = {
            "answer": answer,
            "chunks": [r.to_dict() for r in results],
            "pages": [p.to_dict() for p in pages],
            "figures": [f.to_dict() for f in figures],
        }
        logger.info("Generated answer for query '%s'", query)
        logger.info("Answer: %s", answer)
        logger.info("Payload: %s", json.dumps(payload, indent=2))
    except Exception as exc:
        error = f"Failed to generate answer: {exc}"
        logger.error(error)
        payload = {
            "error": error,
            "chunks": [r.to_dict() for r in results],
            "pages": [p.to_dict() for p in pages],
            "figures": [f.to_dict() for f in figures],
        }

    return json.dumps(payload, indent=2)
