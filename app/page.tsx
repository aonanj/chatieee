"use client";

import Image from "next/image";
import { FormEvent, useEffect, useState } from "react";

import { buildClientApiUrl } from "@/app/lib/api";
import { resolveStorageUrl } from "@/app/lib/firebase-storage";

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

type PageSource = {
  id: number;
  document_id: number;
  page_number: number;
  image_uri?: string | null;
  metadata: Record<string, unknown> | null;
  chunk_ids: number[];
  rank: number;
};

type QueryResponse = {
  answer: string;
  chunks: Chunk[];
  pages: PageSource[];
  figures: Figure[];
};

type StorageLinkState = {
  status: "loading" | "ready" | "error";
  url?: string;
};

const queryEndpoint = buildClientApiUrl("/query");

export default function Home() {
  const [query, setQuery] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [lastRun, setLastRun] = useState<Date | null>(null);
  const [pageLinks, setPageLinks] = useState<Record<number, StorageLinkState>>({});
  const [figureLinks, setFigureLinks] = useState<Record<number, StorageLinkState>>({});

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
    setPageLinks({});
    setFigureLinks({});
  };

  useEffect(() => {
    const pages = result?.pages ?? [];
    if (!pages.length) {
      setPageLinks({});
      return;
    }

    const initialState = pages.reduce<Record<number, StorageLinkState>>((acc, page) => {
      acc[page.id] = { status: "loading" };
      return acc;
    }, {});
    setPageLinks(initialState);

    let cancelled = false;
    const resolveLinks = async () => {
      const resolutions = await Promise.all(
        pages.map(async (page) => {
          try {
            const url = await resolveStorageUrl(page.image_uri);
            if (url) {
              return [page.id, { status: "ready", url }] as const;
            }
            return [page.id, { status: "error" }] as const;
          } catch (err) {
            console.error("Failed to resolve page link", err);
            return [page.id, { status: "error" }] as const;
          }
        }),
      );
      if (cancelled) {
        return;
      }
      setPageLinks((prev) => {
        const nextState = { ...prev };
        for (const [id, payload] of resolutions) {
          nextState[id] = payload;
        }
        return nextState;
      });
    };

    void resolveLinks();
    return () => {
      cancelled = true;
    };
  }, [result?.pages]);

  useEffect(() => {
    const figures = result?.figures ?? [];
    if (!figures.length) {
      setFigureLinks({});
      return;
    }

    const initialState = figures.reduce<Record<number, StorageLinkState>>((acc, fig) => {
      acc[fig.id] = { status: "loading" };
      return acc;
    }, {});
    setFigureLinks(initialState);

    let cancelled = false;
    const resolveLinks = async () => {
      const resolutions = await Promise.all(
        figures.map(async (figure) => {
          try {
            const url = await resolveStorageUrl(figure.image_uri);
            if (url) {
              return [figure.id, { status: "ready", url }] as const;
            }
            return [figure.id, { status: "error" }] as const;
          } catch (err) {
            console.error("Failed to resolve figure link", err);
            return [figure.id, { status: "error" }] as const;
          }
        }),
      );
      if (cancelled) {
        return;
      }
      setFigureLinks((prev) => {
        const nextState = { ...prev };
        for (const [id, payload] of resolutions) {
          nextState[id] = payload;
        }
        return nextState;
      });
    };

    void resolveLinks();
    return () => {
      cancelled = true;
    };
  }, [result?.figures]);

  const chunkSubset = result?.chunks?.slice(0, 4) ?? [];
  const highlightedChunkIds = new Set(chunkSubset.map((chunk) => chunk.id));
  const rankedPages = result?.pages ?? [];
  const relevantPages = rankedPages.filter((page) =>
    page.chunk_ids.some((id) => highlightedChunkIds.has(id)),
  );
  const topPageSources = (relevantPages.length ? relevantPages : rankedPages).slice(0, 4);
  const lastRunLabel = lastRun
    ? lastRun.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : "No runs yet";

  return (
    <main className="page-gradient min-h-screen px-6 py-10 text-slate-900">
      <div className="app-wrapper">
        <div className="glass-surface">
          <section className="glass-card space-y-2 rounded-[34px] border border-white/60 px-10 py-10">
            <div>
              <header className="flex flex-col gap-2 text-left">
                <p className="section-tag">IEEE Knowledge Overview</p>
                <h1 className="text-3xl font-semibold text-slate-900 md:text-[34px]">
                  Semantic Search for WiFi Standards
                </h1>
                <p className="max-w-3xl text-sm text-slate-600 md:text-base">
                  An easier way to find relevant information in IEEE 802.11 standards.
                </p>
                <br />
              </header>
            </div>
            <div className="grid gap-8 sm:grid-cols-3">
              <div className="metric-card">
                <p className="metric-label">Last Run</p>
                <p className="metric-value">{lastRunLabel}</p>
              </div>
              <div className="metric-card">
                <p className="metric-label">Page Sources</p>
                <p className="metric-value">{result?.pages?.length ?? 0}</p>
              </div>
              <div className="metric-card">
                <p className="metric-label">Figure References</p>
                <p className="metric-value">{result?.figures?.length ?? 0}</p>
              </div>
            </div>
          </section>
        </div>

        <div className="glass-surface">
          <section className="glass-card rounded-[34px] border border-white/70 px-10 py-10 space-y-6">
            <header className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div>
                <p className="metric-label">Focus Question</p>
                <p className="text-lg font-semibold text-slate-900">What do you want to learn?</p>
              </div>
              <span className="status-chip neutral">
                {error ? "Disconnected" : "Connected to ingestion pipeline"}
              </span>
            </header>

            <form onSubmit={handleSubmit} className="flex flex-col gap-6">
              <textarea
                className="textarea-pill"
                placeholder="Example: Describe the fields present in Very-High Throughput frames."
                value={query}
                disabled={isLoading}
                onChange={(event) => setQuery(event.target.value)}
              />
              <div className="glass-card flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
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
                  <button type="submit" className="btn-modern" disabled={isLoading}>
                    {isLoading ? "Querying…" : "Run Query"}
                  </button>
                  <button type="button" className="btn-outline" onClick={handleReset}>
                    Reset
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
        </div>
        <div className="glass-surface">
          <section className="glass-card rounded-[34px] border border-white/70 px-10 py-10 space-y-6">
            <header className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
              <div>
                <p className="section-tag">Results</p>
                <p className="text-xl font-semibold text-slate-900">Contextual Answer + Sources</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <span className="status-chip">
                  {result ? `${result.pages.length} page sources` : "No pages"}
                </span>
                <span className="status-chip">
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

                {topPageSources.length > 0 && (
                  <div className="panel-sub space-y-4">
                    <div className="flex items-center justify-between">
                      <h3 className="text-base font-semibold text-slate-900">Supporting Sources</h3>
                      <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
                        Top {topPageSources.length} page previews
                      </p>
                    </div>
                    <div className="grid gap-4 md:grid-cols-2">
                      {topPageSources.map((page, index) => {
                        const linkState = pageLinks[page.id];
                        const chunkCount = page.chunk_ids.length;
                        const chunkLabel =
                          chunkCount === 1 ? "Referenced by 1 chunk" : `Referenced by ${chunkCount} chunks`;
                        const readyLink = linkState?.status === "ready" ? linkState.url : null;

                        return (
                          <article key={`page-${page.id}`} className="result-card space-y-3">
                            <div className="flex items-center justify-between text-xs text-slate-500">
                              <span className="font-semibold text-slate-700">Source {index + 1}</span>
                              <div className="flex gap-2">
                                <span className="status-chip mini">Doc #{page.document_id}</span>
                                <span className="status-chip mini">Page {page.page_number}</span>
                              </div>
                            </div>
                            <div className="mt-1 flex h-64 w-full items-center justify-center overflow-hidden rounded-2xl bg-white/70 px-2 py-2 shadow-inner">
                              {readyLink ? (
                                <div className="relative h-full w-full">
                                  <Image
                                    src={readyLink}
                                    alt={`Document ${page.document_id} page ${page.page_number}`}
                                    fill
                                    sizes="(min-width: 768px) 50vw, 100vw"
                                    className="rounded-xl border border-slate-200 bg-white object-contain"
                                    priority={index === 0}
                                  />
                                </div>
                              ) : linkState?.status === "loading" ? (
                                <div className="flex h-full w-full items-center justify-center text-xs text-slate-400">
                                  Rendering preview…
                                </div>
                              ) : (
                                <div className="flex h-full w-full items-center justify-center text-xs text-slate-400">
                                  Preview unavailable
                                </div>
                              )}
                            </div>
                            <div className="flex items-center justify-between text-xs text-slate-500">
                              <span>{chunkLabel}</span>
                              {readyLink ? (
                                <a
                                  href={readyLink}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="font-semibold text-blue-600 underline"
                                >
                                  Open page
                                </a>
                              ) : (
                                <span className="text-slate-400">No link</span>
                              )}
                            </div>
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
                          {figureLinks[figure.id]?.status === "ready" &&
                          figureLinks[figure.id]?.url ? (
                            <a
                              href={figureLinks[figure.id]?.url}
                              target="_blank"
                              rel="noreferrer"
                              className="mt-3 inline-flex text-xs font-semibold text-blue-600 underline"
                            >
                              View Figure
                            </a>
                          ) : figureLinks[figure.id]?.status === "loading" ? (
                            <span className="mt-3 inline-flex text-xs font-semibold text-slate-400">
                              Resolving link…
                            </span>
                          ) : (
                            <span className="mt-3 inline-flex text-xs font-semibold text-slate-400">
                              Link unavailable
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="textarea-pill">
                Waiting for query ...
              </div>
            )}
          </section>
        </div>
        <div className="glass-surface">
          <footer className="glass-card rounded-3xl border border-white/40 bg-white/30 px-8 py-4 text-center text-sm text-slate-600 backdrop-blur-xl">
            2025 © Phaethon Order LLC · support@phaethon.llc · Secure IEEE knowledge workflows
          </footer>
        </div>
      </div>
    </main>
  );
}
