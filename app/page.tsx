"use client";

import Image from "next/image";
import Link from "next/link";
import { FormEvent, useState } from "react";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type Chunk = {
  id: number;
  document_id: number;
  content: string;
  metadata: Record<string, unknown> | null;
  vector_score?: number | null;
  lexical_score?: number | null;
  rerank_score?: number | null;
};

type Figure = {
  id: number;
  document_id: number;
  figure_label: string;
  caption?: string | null;
  image_uri: string;
  page_number?: number | null;
};

type QueryResponse = {
  answer: string;
  chunks: Chunk[];
  figures: Figure[];
};

const metadataValue = (
  metadata: Chunk["metadata"],
  key: string,
): string | number | undefined => {
  if (!metadata || typeof metadata !== "object") {
    return undefined;
  }
  const record = metadata as Record<string, unknown>;
  const value = record[key];
  if (typeof value === "string" || typeof value === "number") {
    return value;
  }
  return undefined;
};

export default function Home() {
  const [query, setQuery] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<QueryResponse | null>(null);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) {
      setError("Enter a question to search the IEEE corpus.");
      return;
    }

    setIsLoading(true);
    setError(null);
    setStatus("Searching indexed documents...");

    try {
      const response = await fetch(`${API_BASE_URL}/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: trimmed }),
      });

      const text = await response.text();
      if (!response.ok) {
        let detailMessage = "Failed to fetch an answer.";
        try {
          const parsed = JSON.parse(text);
          if (typeof parsed.detail === "string") {
            detailMessage = parsed.detail;
          }
        } catch {
          if (text) {
            detailMessage = text;
          }
        }
        throw new Error(detailMessage);
      }

      let payload: QueryResponse;
      try {
        payload = JSON.parse(text) as QueryResponse;
      } catch {
        throw new Error("Received an unexpected response from the server.");
      }

      setResult(payload);
      setStatus("Answer generated from the latest knowledge base.");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unexpected error while answering your question.";
      setError(message);
      setResult(null);
      setStatus(null);
    } finally {
      setIsLoading(false);
    }
  };

  const topChunks = result?.chunks?.slice(0, 4) ?? [];

  return (
    <main className="flex min-h-screen flex-col items-center px-5 py-10 text-white">
      <section className="glass-surface w-full max-w-5xl rounded-3xl px-8 py-10">
        <header className="mb-8 flex flex-col items-center gap-4 text-center">
          <Image
            src="/images/chatieee-logo-white.png"
            alt="ChatIEEE logo"
            width={240}
            height={60}
            priority
          />
          <p className="max-w-2xl text-base text-slate-200">
            Ask questions about the IEEE Corpus and receive sourced answers generated from your ingested PDFs.
          </p>
          <div className="flex flex-wrap justify-center gap-3">
            <Link href="/ingest" className="btn-modern">
              Ingest a PDF
            </Link>
            <a
              className="btn-outline"
              href="https://github.com/aonanj/chatieee"
              target="_blank"
              rel="noreferrer"
            >
              View GitHub
            </a>
          </div>
        </header>

        <form onSubmit={handleSubmit} className="glass-card mx-auto flex max-w-3xl flex-col gap-4 px-6 py-6 text-gray-900">
          <label className="text-sm font-semibold text-slate-600">
            Ask a question
          </label>
          <textarea
            className="min-h-[120px] rounded-2xl border border-white/50 bg-white/70 p-4 text-base text-slate-800 shadow-lg outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-200"
            placeholder="e.g. What changes were introduced in the 2024 revision of section 9.4?"
            value={query}
            disabled={isLoading}
            onChange={(event) => setQuery(event.target.value)}
          />
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <span className="text-sm text-slate-500">
              Answers cite snippets pulled directly from your ingested PDFs.
            </span>
            <button type="submit" className="btn-modern min-w-[180px]" disabled={isLoading}>
              {isLoading ? "Generating..." : "Get Answer"}
            </button>
          </div>
        </form>

        {error && (
          <div className="glass-card mt-6 border border-red-200 bg-red-50/70 px-5 py-4 text-sm text-red-800">
            {error}
          </div>
        )}

        {status && !error && (
          <div className="glass-card mt-6 border border-indigo-100 bg-white/70 px-5 py-3 text-sm text-slate-600">
            {status}
          </div>
        )}

        {result && !error && (
          <div className="mt-8 grid gap-6">
            <div className="glass-card border border-white/50 bg-white/85 px-7 py-6 text-gray-900 shadow-2xl">
              <h2 className="text-lg font-semibold text-slate-800">Answer</h2>
              <p className="mt-3 whitespace-pre-line text-base leading-relaxed text-slate-700">
                {result.answer}
              </p>
            </div>

            {topChunks.length > 0 && (
              <div className="glass-card border border-white/50 bg-white/80 px-7 py-6 text-gray-900">
                <h3 className="text-base font-semibold text-slate-800">Supporting Sources</h3>
                <div className="mt-4 space-y-4">
                  {topChunks.map((chunk, index) => {
                    const headingValue =
                      metadataValue(chunk.metadata, "section") ??
                      metadataValue(chunk.metadata, "heading") ??
                      metadataValue(chunk.metadata, "title");
                    const pageValue =
                      metadataValue(chunk.metadata, "page_start") ??
                      metadataValue(chunk.metadata, "page") ??
                      metadataValue(chunk.metadata, "page_number");

                    return (
                      <article
                        key={chunk.id}
                        className="rounded-3xl border border-slate-100 bg-white/90 p-4 shadow-lg"
                      >
                        <div className="flex flex-col gap-2 text-xs text-slate-500 sm:flex-row sm:items-center sm:justify-between">
                          <span className="font-semibold text-slate-700">Source {index + 1}</span>
                          <div className="flex flex-wrap gap-2 text-[11px] uppercase tracking-wide">
                            <span>Document #{chunk.document_id}</span>
                            {pageValue && <span>Page {pageValue}</span>}
                          </div>
                        </div>
                        {headingValue && typeof headingValue === "string" && (
                          <p className="mt-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                            {headingValue}
                          </p>
                        )}
                        <p className="mt-3 text-sm leading-relaxed text-slate-700">
                          {chunk.content}
                        </p>
                      </article>
                    );
                  })}
                </div>
              </div>
            )}

            {result.figures?.length ? (
              <div className="glass-card border border-white/50 bg-white/85 px-7 py-6 text-gray-900">
                <h3 className="text-base font-semibold text-slate-800">Figures Mentioned</h3>
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  {result.figures.map((figure) => (
                    <div
                      key={figure.id}
                      className="rounded-2xl border border-slate-100 bg-white/90 p-4 text-sm"
                    >
                      <div className="flex items-center justify-between text-xs text-slate-500">
                        <span className="font-semibold text-slate-700">{figure.figure_label}</span>
                        {figure.page_number && <span>Page {figure.page_number}</span>}
                      </div>
                      {figure.caption && (
                        <p className="mt-2 text-slate-700">{figure.caption}</p>
                      )}
                      <a
                        href={figure.image_uri}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-3 inline-flex text-xs font-semibold text-blue-600 underline"
                      >
                        View Image
                      </a>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        )}
      </section>

      <footer className="mt-8 text-center text-xs text-white/80">
        Built with ❤️ for the IEEE knowledge base.
      </footer>
    </main>
  );
}
