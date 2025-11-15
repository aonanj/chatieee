"use client";

import Image from "next/image";
import Link from "next/link";
import { FormEvent, useState } from "react";

import { buildClientApiUrl } from "@/app/lib/api";

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

const queryEndpoint = buildClientApiUrl("/query");

export default function Home() {
  const [query, setQuery] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [lastRun, setLastRun] = useState<Date | null>(null);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) {
      setError("Enter a question to search the IEEE corpus.");
      return;
    }

    setIsLoading(true);
    setError(null);
    setStatus("Analyzing IEEE knowledge base…");

    try {
      const response = await fetch(queryEndpoint, {
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
      setLastRun(new Date());
      setStatus("Answer generated from the latest knowledge base.");
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Unexpected error while answering your question.";
      setError(message);
      setResult(null);
      setStatus(null);
    } finally {
      setIsLoading(false);
    }
  };

  const handleReset = () => {
    setQuery("");
    setResult(null);
    setStatus(null);
    setError(null);
    setLastRun(null);
  };

  const topChunks = result?.chunks?.slice(0, 4) ?? [];
  const lastRunLabel = lastRun
    ? lastRun.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : "No runs yet";

  return (
    <main className="page-gradient min-h-screen px-6 py-10 text-slate-900">
      <div className="app-wrapper">
        <section className="nav-card flex flex-col gap-6 rounded-3xl border border-white/50 bg-white/30 px-8 py-6 backdrop-blur-xl md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-4">
            <Image
              src="/images/chatieee-logo-white.png"
              alt="ChatIEEE logo"
              width={180}
              height={42}
              className="drop-shadow-lg"
              priority
            />
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-slate-600">ChatIEEE Suite</p>
              <p className="text-sm text-slate-700">Retrieve + Analyze your IEEE Corpus</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <Link href="/ingest" className="btn-modern min-w-[150px]">
              Ingest PDFs
            </Link>
            <a
              className="btn-outline"
              href="https://github.com/aonanj/chatieee"
              target="_blank"
              rel="noreferrer"
            >
              View Docs
            </a>
          </div>
        </section>

        <section className="surface-panel hero-panel space-y-10 rounded-[34px] border border-white/60 px-10 py-10">
          <header className="flex flex-col gap-2 text-left">
            <p className="section-tag">IEEE Knowledge Overview</p>
            <h1 className="text-3xl font-semibold text-slate-900 md:text-[34px]">
              Density &amp; Distribution Insights
            </h1>
            <p className="max-w-3xl text-sm text-slate-600 md:text-base">
              Measure saturation across IEEE standards, surface semantic neighbors, and cite the
              exact clauses supporting every answer.
            </p>
          </header>
          <div className="grid gap-8 sm:grid-cols-3">
            <div className="metric-card">
              <p className="metric-label">Last Run</p>
              <p className="metric-value">{lastRunLabel}</p>
            </div>
            <div className="metric-card">
              <p className="metric-label">Sources Queried</p>
              <p className="metric-value">{result?.chunks?.length ?? 0}</p>
            </div>
            <div className="metric-card">
              <p className="metric-label">Figure References</p>
              <p className="metric-value">{result?.figures?.length ?? 0}</p>
            </div>
          </div>
        </section>

        <section className="surface-panel rounded-[34px] border border-white/70 px-10 py-10 space-y-6">
          <header className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="section-tag">Focus Question</p>
              <p className="text-lg font-semibold text-slate-900">What do you want to learn?</p>
            </div>
            <span className="status-chip">
              {error ? "Disconnected" : "Connected to ingestion pipeline"}
            </span>
          </header>

          <form onSubmit={handleSubmit} className="flex flex-col gap-6">
            <textarea
              className="textarea-pill w-full"
              placeholder="e.g. Summarize the security updates introduced in IEEE 802.11-2024 clause 12."
              value={query}
              disabled={isLoading}
              onChange={(event) => setQuery(event.target.value)}
            />
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex flex-wrap gap-4 text-sm text-slate-600">
                <label className="toggle-pill">
                  <input type="checkbox" checked readOnly />
                  <span>Return supporting sources</span>
                </label>
                <label className="toggle-pill">
                  <input type="checkbox" checked readOnly />
                  <span>Reference figures when detected</span>
                </label>
              </div>
              <div className="flex flex-wrap gap-3">
                <button type="button" className="btn-outline min-w-[120px]" onClick={handleReset}>
                  Reset
                </button>
                <button type="submit" className="btn-modern min-w-[180px]" disabled={isLoading}>
                  {isLoading ? "Generating…" : "Generate Answer"}
                </button>
              </div>
            </div>
          </form>

          {error && (
            <div className="alert-card error">
              {error}
            </div>
          )}

          {status && !error && (
            <div className="alert-card info">
              {status}
            </div>
          )}
        </section>

        <section className="surface-panel rounded-[34px] border border-white/70 px-10 py-10 space-y-6">
          <header className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="section-tag">Results</p>
              <p className="text-xl font-semibold text-slate-900">Contextual Answer + Sources</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <span className="status-chip">
                {result ? `${result.chunks.length} chunks referenced` : "Awaiting first query"}
              </span>
              <span className="status-chip neutral">
                {result?.figures?.length ? `${result.figures.length} figures linked` : "No figures"}
              </span>
            </div>
          </header>

          {result ? (
            <div className="space-y-8">
              <div className="panel-sub">
                <h2 className="text-lg font-semibold text-slate-900">Answer</h2>
                <p className="mt-3 whitespace-pre-line text-base leading-relaxed text-slate-700">
                  {result.answer}
                </p>
              </div>

              {topChunks.length > 0 && (
                <div className="panel-sub space-y-4">
                  <div className="flex items-center justify-between">
                    <h3 className="text-base font-semibold text-slate-900">Supporting Sources</h3>
                    <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
                      Top {topChunks.length} snippets
                    </p>
                  </div>
                  <div className="grid gap-4 md:grid-cols-2">
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
                        <article key={chunk.id} className="result-card">
                          <div className="flex items-center justify-between text-xs text-slate-500">
                            <span className="font-semibold text-slate-700">Source {index + 1}</span>
                            <div className="flex gap-2">
                              <span className="status-chip mini">Doc #{chunk.document_id}</span>
                              {pageValue && <span className="status-chip mini">Page {pageValue}</span>}
                            </div>
                          </div>
                          {headingValue && typeof headingValue === "string" && (
                            <p className="mt-2 text-xs font-semibold uppercase tracking-widest text-slate-500">
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
                <div className="panel-sub space-y-4">
                  <div className="flex items-center justify-between">
                    <h3 className="text-base font-semibold text-slate-900">Figures Referenced</h3>
                    <p className="text-xs text-slate-500">Linked directly from rag_figure</p>
                  </div>
                  <div className="grid gap-4 md:grid-cols-3">
                    {result.figures.map((figure) => (
                      <div key={figure.id} className="figure-card">
                        <div className="flex items-center justify-between text-xs text-slate-500">
                          <span className="font-semibold text-slate-700">
                            {figure.figure_label}
                          </span>
                          {figure.page_number && <span>Page {figure.page_number}</span>}
                        </div>
                        {figure.caption && (
                          <p className="mt-2 text-sm text-slate-700">{figure.caption}</p>
                        )}
                        <a
                          href={figure.image_uri}
                          target="_blank"
                          rel="noreferrer"
                          className="mt-3 inline-flex text-xs font-semibold text-blue-600 underline"
                        >
                          View Figure
                        </a>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          ) : (
            <div className="panel-sub mt-6 text-sm text-slate-600">
              Submit a question to preview sourced answers and figures.
            </div>
          )}
        </section>

        <footer className="rounded-3xl border border-white/40 bg-white/30 px-8 py-4 text-center text-xs text-slate-600 backdrop-blur-xl">
          2025 © Phaethon Order LLC · support@phaethon.llc · Secure IEEE knowledge workflows
        </footer>
      </div>
    </main>
  );
}
