"use client";

import Image from "next/image";
import { FormEvent, useEffect, useMemo, useState } from "react";

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
const PAGE_PREVIEW_PAGE_SIZE = 4;
const FIGURE_PREVIEW_PAGE_SIZE = 4;

export default function Home() {
  const [query, setQuery] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [lastRun, setLastRun] = useState<Date | null>(null);
  const [pageLinks, setPageLinks] = useState<Record<number, StorageLinkState>>({});
  const [figureLinks, setFigureLinks] = useState<Record<number, StorageLinkState>>({});
  const [pageSourcePage, setPageSourcePage] = useState(0);
  const [figureSourcePage, setFigureSourcePage] = useState(0);

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
    setPageSourcePage(0);
    setFigureSourcePage(0);
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
  useEffect(() => {
    setPageSourcePage(0);
  }, [result?.pages]);

  useEffect(() => {
    setFigureSourcePage(0);
  }, [result?.figures]);

  const chunkSourceLookup = useMemo(() => {
    const lookup = new Map<number, number>();
    (result?.chunks ?? []).forEach((chunk, index) => {
      lookup.set(chunk.id, index + 1);
    });
    return lookup;
  }, [result?.chunks]);

  const rankedPages = result?.pages ?? [];
  const totalPageSources = rankedPages.length;
  const pageCount = Math.max(1, Math.ceil(totalPageSources / PAGE_PREVIEW_PAGE_SIZE));
  const currentPageIndex = Math.min(pageSourcePage, Math.max(pageCount - 1, 0));
  const pageSliceStart = currentPageIndex * PAGE_PREVIEW_PAGE_SIZE;
  const visiblePageSources = rankedPages.slice(
    pageSliceStart,
    pageSliceStart + PAGE_PREVIEW_PAGE_SIZE,
  );

  const referencedFigures = result?.figures ?? [];
  const totalFigureSources = referencedFigures.length;
  const figurePageCount = Math.max(1, Math.ceil(totalFigureSources / FIGURE_PREVIEW_PAGE_SIZE));
  const currentFigureIndex = Math.min(figureSourcePage, Math.max(figurePageCount - 1, 0));
  const figureSliceStart = currentFigureIndex * FIGURE_PREVIEW_PAGE_SIZE;
  const visibleFigures = referencedFigures.slice(
    figureSliceStart,
    figureSliceStart + FIGURE_PREVIEW_PAGE_SIZE,
  );

  const lastRunLabel = lastRun
    ? lastRun.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : "No runs yet";
  const statusChipMessage = error ?? status ?? "Connected to ingestion pipeline";
  const statusChipTone = error ? "error" : isLoading ? "processing" : status ? "success" : "neutral";
  const statusChipClassName = ["status-chip", statusChipTone].filter(Boolean).join(" ");

  return (
    <main className="page-gradient min-h-screen px-6 py-10 text-[#39506B]">
      <div className="app-wrapper">
        <div className="glass-surface">
          <section className="glass-card space-y-2 rounded-[34px] border border-white/60 px-10 py-10">
            <div>
              <header className="flex flex-col gap-2 text-left">
                <p className="section-tag">IEEE Knowledge Overview</p>
                <h1 className="text-5xl font-semibold text-[#39506B] md:text-[30px]">
                  Semantic Search for WiFi Standards
                </h1>
                <p className="max-w-3xl text-sm text-[#39506B] md:text-base opacity-75">
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
                <p className="text-lg font-semibold text-[#39506B]">Input IEEE 802.11 Standards Query</p>
              </div>
              <span className={statusChipClassName}>
                {statusChipMessage}
              </span>
            </header>

            <form onSubmit={handleSubmit} className="flex flex-col gap-6">
              <textarea
                className="textarea-pill"
                placeholder="Example: Describe the Wakeup Schedule in TDLS peer PSM."
                value={query}
                disabled={isLoading}
                onChange={(event) => setQuery(event.target.value)}
              />
              <div className="glass-card flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div className="flex flex-wrap gap-4 text-sm text-[#39506B]">
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

          </section>
        </div>
        <div className="glass-surface">
          <section className="glass-card rounded-[34px] border border-white/70 px-10 py-10 space-y-6">
            <header className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
              <div>
                <p className="section-tag">Results</p>
                <p className="text-lg font-semibold text-[#39506B]">Contextual Answer + Sources</p>
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
                  <h2 className="text-lg font-semibold text-[#39506B]">Answer</h2>
                  <p className="mt-3 whitespace-pre-line text-base leading-relaxed text-slate-700">
                    {result.answer}
                  </p>
                </div>

                {visiblePageSources.length > 0 && (
                  <div className="panel-sub space-y-4">
                    <div className="flex items-center justify-between">
                      <h3 className="text-base font-semibold text-[#39506B]">Supporting Sources</h3>
                      <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
                        Showing {visiblePageSources.length} of {totalPageSources} pages (Page{" "}
                        {currentPageIndex + 1} of {pageCount})
                      </p>
                    </div>
                    <div className="grid gap-4 md:grid-cols-2">
                      {visiblePageSources.map((page, index) => {
                        const linkState = pageLinks[page.id];
                        const chunkCount = page.chunk_ids.length;
                        const chunkLabel =
                          chunkCount === 1 ? "Referenced by 1 chunk" : `Referenced by ${chunkCount} chunks`;
                        const readyLink = linkState?.status === "ready" ? linkState.url : null;
                        const pageSources = page.chunk_ids
                          .map((chunkId) => chunkSourceLookup.get(chunkId))
                          .filter((value): value is number => typeof value === "number")
                          .sort((a, b) => a - b);
                        const sourcesLabel = pageSources.length
                          ? `Source(s) ${pageSources.join(", ")}`
                          : "Source(s) unavailable";

                        return (
                          <article key={`page-${page.id}`} className="result-card space-y-3">
                            <div className="flex items-center justify-between text-xs text-slate-500">
                              <span className="font-semibold text-slate-700">
                                Page Preview {pageSliceStart + index + 1}
                              </span>
                              <div className="flex gap-2">
                                <span className="status-chip mini">Doc #{page.document_id}</span>
                                <span className="status-chip mini">Page {page.page_number}</span>
                              </div>
                            </div>
                            <div className="mt-1 flex h-64 w-full items-center justify-center overflow-hidden rounded-2xl bg-white/70 px-2 py-2 shadow-inner">
                              {readyLink ? (
                                <div className="relative h-full w-full">
                                  {/* Firebase Hosting cannot run the Next.js image optimizer for signed Storage URLs */}
                                  <Image
                                    src={readyLink}
                                    alt={`Document ${page.document_id} page ${page.page_number}`}
                                    fill
                                    sizes="(min-width: 768px) 50vw, 100vw"
                                    className="rounded-xl border border-slate-200 bg-white object-contain"
                                    priority={index === 0}
                                    unoptimized
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
                            <div className="flex flex-col gap-1 text-xs text-slate-500 sm:flex-row sm:items-center sm:justify-between">
                              <span>{chunkLabel}</span>
                              <span className="font-semibold text-slate-700">{sourcesLabel}</span>
                            </div>
                            <div className="flex items-center justify-between text-xs text-slate-500">
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
                    {pageCount > 1 && (
                      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
                        <button
                          type="button"
                          className="btn-outline disabled:cursor-not-allowed disabled:opacity-50"
                          onClick={() => setPageSourcePage((prev) => Math.max(prev - 1, 0))}
                          disabled={currentPageIndex === 0}
                        >
                          Previous
                        </button>
                        <span>
                          Page {currentPageIndex + 1} of {pageCount}
                        </span>
                        <button
                          type="button"
                          className="btn-modern disabled:cursor-not-allowed disabled:opacity-50"
                          onClick={() =>
                            setPageSourcePage((prev) =>
                              Math.min(prev + 1, Math.max(pageCount - 1, 0)),
                            )
                          }
                          disabled={currentPageIndex >= pageCount - 1}
                        >
                          Next
                        </button>
                      </div>
                    )}
                  </div>
                )}

                {totalFigureSources ? (
                  <div className="panel-sub space-y-4">
                    <div className="flex items-center justify-between">
                      <h3 className="text-base font-semibold text-[#39506B]">Figures Referenced</h3>
                      <p className="text-xs text-slate-500">
                        Showing {visibleFigures.length} of {totalFigureSources} figures (Page{" "}
                        {currentFigureIndex + 1} of {figurePageCount})
                      </p>
                    </div>
                    <div className="grid gap-4 md:grid-cols-3">
                      {visibleFigures.map((figure, index) => {
                        const linkState = figureLinks[figure.id];
                        const readyLink = linkState?.status === "ready" ? linkState.url : null;
                        return (
                          <div key={figure.id} className="figure-card space-y-3">
                            <div className="flex items-center justify-between text-xs text-slate-500">
                              <span className="font-semibold text-slate-700">
                                {figure.figure_label}
                              </span>
                              {figure.page_number && <span>Page {figure.page_number}</span>}
                            </div>
                            {figure.caption && (
                              <p className="text-sm text-slate-700">{figure.caption}</p>
                            )}
                            <div className="relative flex h-48 w-full items-center justify-center overflow-hidden rounded-2xl bg-white/70 p-2 shadow-inner">
                              {readyLink ? (
                                <>
                                  {/* Serve figures without Next.js optimization so Firebase Hosting can stream the signed URL */}
                                  <Image
                                    src={readyLink}
                                    alt={figure.figure_label}
                                    fill
                                    sizes="(min-width: 768px) 33vw, 100vw"
                                    className="rounded-xl border border-slate-200 bg-white object-contain"
                                    priority={currentFigureIndex === 0 && index === 0}
                                    unoptimized
                                  />
                                </>
                              ) : linkState?.status === "loading" ? (
                                <span className="text-xs text-slate-400">Rendering preview…</span>
                              ) : (
                                <span className="text-xs text-slate-400">Preview unavailable</span>
                              )}
                            </div>
                            <div className="flex items-center justify-between text-xs text-slate-500">
                              {readyLink ? (
                                <a
                                  href={readyLink}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="font-semibold text-blue-600 underline"
                                >
                                  View figure
                                </a>
                              ) : (
                                <span className="text-slate-400">No link</span>
                              )}
                              <span className="text-slate-400">
                                Figure {figureSliceStart + index + 1}
                              </span>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                    {figurePageCount > 1 && (
                      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
                        <button
                          type="button"
                          className="btn-outline disabled:cursor-not-allowed disabled:opacity-50"
                          onClick={() => setFigureSourcePage((prev) => Math.max(prev - 1, 0))}
                          disabled={currentFigureIndex === 0}
                        >
                          Previous
                        </button>
                        <span>
                          Page {currentFigureIndex + 1} of {figurePageCount}
                        </span>
                        <button
                          type="button"
                          className="btn-modern disabled:cursor-not-allowed disabled:opacity-50"
                          onClick={() =>
                            setFigureSourcePage((prev) =>
                              Math.min(prev + 1, Math.max(figurePageCount - 1, 0)),
                            )
                          }
                          disabled={currentFigureIndex >= figurePageCount - 1}
                        >
                          Next
                        </button>
                      </div>
                    )}
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
          <footer className="glass-card rounded-3xl border border-white/40 bg-white/30 px-8 py-4 text-center text-sm text-[#39506B] backdrop-blur-xl">
            2025 © Phaethon Order LLC · support@phaethon.llc · Secure IEEE knowledge workflows
          </footer>
        </div>
      </div>
    </main>
  );
}
