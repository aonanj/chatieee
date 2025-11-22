"use client";

import { ChangeEvent, DragEvent, FormEvent, useEffect, useRef, useState } from "react";

import { buildClientApiUrl } from "@/app/lib/api";

type IngestResponse = {
  status: string;
  run_id?: string;
  document_path?: string;
  message?: string;
  error_message?: string;
};

type IngestStatusResponse = {
  status: string;
  error_message?: string;
  started_at?: string;
  finished_at?: string;
};

const ingestEndpoint = buildClientApiUrl("/ingest_pdf");
const ESTIMATED_INGEST_MS = 12 * 60 * 1000; // Rough 12-minute ingest target

export default function IngestPage() {
  const [file, setFile] = useState<File | null>(null);
  const [externalId, setExternalId] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [sourceUri, setSourceUri] = useState("");
  const [draftDocument, setDraftDocument] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<IngestResponse | null>(null);
  const [lastUploaded, setLastUploaded] = useState<string | null>(null);
  const [isDragActive, setIsDragActive] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const ingestionStartedAtRef = useRef<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const uploadDisabled = isUploading;
  const statusChipMessage =
    error ??
    status ??
    (isUploading ? (progress !== null ? `Ingestion running (~${progress}% est.)` : "Ingestion running…") : "Standing by");
  const statusChipTone = error ? "error" : isUploading ? "processing" : status ? "success" : "neutral";
  const statusChipClassName = ["status-chip", statusChipTone].filter(Boolean).join(" ");
  const clampedProgress = progress === null ? null : Math.min(Math.max(progress, 0), 100);
  const uploadZoneClassName = [
    "upload-zone justify-center block max-w-100 rounded-3xl border border-dashed border-slate-300 bg-white/80 px-8 py-8 text-center text-sm text-[#39506B]",
    uploadDisabled ? "pointer-events-none opacity-60" : "cursor-pointer hover:border-[#39506B]",
    isDragActive && !uploadDisabled ? "border-[#39506B] bg-white shadow-lg" : "",
  ].join(" ");

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const nextFile = event.target.files?.[0] ?? null;
    setFile(nextFile);
    setLastUploaded(null);
    setIsDragActive(false);
  };

  const handleDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setIsDragActive(false);
    if (uploadDisabled) return;

    const droppedFile = event.dataTransfer?.files?.[0];
    if (!droppedFile) return;

    const isPdf = droppedFile.type === "application/pdf" || droppedFile.name.toLowerCase().endsWith(".pdf");
    if (!isPdf) {
      setError("Only PDF files are supported.");
      return;
    }

    setError(null);
    setFile(droppedFile);
    setLastUploaded(null);
  };

  const handleDragOver = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    if (!isDragActive) setIsDragActive(true);
  };

  const handleDragLeave = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setIsDragActive(false);
  };

  // Clean up interval on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, []);

  const clearExistingPoll = () => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  };

  const computeApproxProgress = (startedAt?: string | null, finishedAt?: string | null) => {
    if (finishedAt) return 100;
    const effectiveStart = startedAt ? new Date(startedAt).getTime() : ingestionStartedAtRef.current;
    if (!effectiveStart) return null;
    const elapsedMs = Math.max(0, Date.now() - effectiveStart);
    const estimated = Math.round((elapsedMs / ESTIMATED_INGEST_MS) * 100);
    return Math.max(3, Math.min(estimated, 97));
  };

  const pollStatus = (runId: string) => {
    clearExistingPoll();

    pollIntervalRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/backend/ingest/${runId}`);
        if (!res.ok) return; // Skip if network error

        const data: IngestStatusResponse = await res.json();

        if (data.started_at) {
          ingestionStartedAtRef.current = new Date(data.started_at).getTime();
        }

        if (data.status === "completed") {
          setProgress(100);
          setStatus("Document intake complete. Content now searchable.");
          setIsUploading(false); // Re-enable buttons
          ingestionStartedAtRef.current = null;
          clearExistingPoll();
        } else if (data.status === "failed") {
          setError(`Ingestion failed: ${data.error_message ?? "Unknown error."}`);
          setStatus(data.error_message ? `Ingestion failed: ${data.error_message}` : "Ingestion failed.");
          setProgress(null);
          setIsUploading(false);
          ingestionStartedAtRef.current = null;
          clearExistingPoll();
        } else {
          // Still processing
          const approx = computeApproxProgress(data.started_at, data.finished_at);
          setProgress(approx);
          setStatus(approx !== null ? `Processing document… ~${approx}% complete (est.)` : "Processing document... (this may take a moment)");
        }
      } catch (e) {
        console.error("Polling error", e);
      }
    }, 10000); // Poll every 10 seconds
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!file) {
      setError("Select a PDF document to ingest.");
      return;
    }

    clearExistingPoll();
    ingestionStartedAtRef.current = Date.now();
    setProgress(0);
    setIsUploading(true);
    setError(null);
    setStatus("Uploading PDF and starting ingestion…");
    setResult(null);

    try {
      const formData = new FormData();
      formData.append("pdf", file);
      if (externalId.trim()) {
        formData.append("external_id", externalId.trim());
      }
      if (title.trim()) {
        formData.append("title", title.trim());
      }
      if (description.trim()) {
        formData.append("description", description.trim());
      }
      if (sourceUri.trim()) {
        formData.append("source_uri", sourceUri.trim());
      }
      formData.append("draft_document", draftDocument ? "true" : "false");

      const response = await fetch(ingestEndpoint, {
        method: "POST",
        body: formData,
      });
      const text = await response.text();
      if (!response.ok) {
        let detailMessage = "Failed to ingest PDF.";
        try {
          const parsed = JSON.parse(text);
          if (typeof parsed.detail === "string") {
            detailMessage = parsed.detail;
          }
        } catch {
          if (text) {
            detailMessage = `Failed to ingest PDF: ${text}`;
          }
        }
        throw new Error(`Error Message: ${detailMessage}`);
      }

      let payload: IngestResponse;

      payload = JSON.parse(text) as IngestResponse;
      const initialProgress = computeApproxProgress();
      const initialStatus =
        payload.run_id && initialProgress !== null
          ? `Processing document… ~${initialProgress}% complete (est.)`
          : payload.message || "Processing...";
      setResult(payload);
      setProgress(payload.run_id ? initialProgress : null);
      setStatus(initialStatus);
      if (payload.run_id) {
        pollStatus(payload.run_id);
      } else {
        ingestionStartedAtRef.current = null;
        setIsUploading(false); // No run_id to poll, so stop uploading state
      }
      setLastUploaded(file.name);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unexpected error while ingesting.";
      setError(message);
      setResult(null);
      setStatus(null);
      setProgress(null);
      ingestionStartedAtRef.current = null;
      clearExistingPoll();
      setIsUploading(false);
    }
  };

  return (
    <main className="page-gradient min-h-screen px-6 py-10 text-[#39506B]">
      <div className="app-wrapper">
        <div className="glass-surface">
          <section className="glass-card space-y-8 rounded-[34px] border border-white/60 px-10 py-10">
            <header className="flex flex-col gap-2 text-left">
              <p className="section-tag">Document intake</p>
              <h1 className="text-5xl font-semibold text-[#39506B] md:text-[30px]">
                Add WiFi Standards Documents
              </h1>
              <p className="max-w-3xl text-sm text-[#39506B] md:text-base opacity-75">
                Upload IEEE 802.11 standards documents to add them to the knowledge base. Documents must be in PDF format. Text, tables, and figures are extracted and embedded for semantic search.
              </p>
            </header>
            <div className="grid gap-6 sm:grid-cols-3">
              <div className="metric-card">
                <p className="metric-label">Last Upload</p>
                <p className="metric-value">{lastUploaded ?? "No uploads yet"}</p>
              </div>
              <div className="metric-card">
                <p className="metric-label">Status</p>
                <p className="metric-value">{status ?? "Idle"}</p>
                {clampedProgress !== null && (
                  <>
                    <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-white/50">
                      <div
                        className="h-full rounded-full bg-[#39506B] transition-all duration-500"
                        style={{ width: `${clampedProgress}%` }}
                      />
                    </div>
                    <p className="mt-2 text-xs text-[#39506B] opacity-70">
                      ~{clampedProgress}% complete (estimated)
                    </p>
                  </>
                )}
              </div>
              <div className="metric-card">
                <p className="metric-label">Stored Path</p>
                <p className="metric-value text-sm">
                  {result?.document_path ?? "N/A"}
                </p>
              </div>
            </div>
          </section>
         </div> 
        <div className="glass-surface">
        <form onSubmit={handleSubmit} className="glass-card rounded-[34px] border border-white/70 px-10 py-10 space-y-8">
          <header className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="section-tag">Upload PDF</p>
              <p className="text-lg font-semibold text-[#39506B]">Increase WiFi knowledge base</p>
            </div>
            <span className={statusChipClassName}>{statusChipMessage}</span>
          </header>

          <input
            ref={fileInputRef}
            type="file"
            accept="application/pdf,.pdf"
            onChange={handleFileChange}
            className="hidden"
            disabled={uploadDisabled}
            id="pdf-upload"
          />

          <label
            htmlFor="pdf-upload"
            className={uploadZoneClassName}
            aria-disabled={uploadDisabled}
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
          >
            <p className="text-base font-semibold text-slate-800">Drop PDF here or click to browse</p>
            <p className="mt-1 text-xs text-slate-500">Max 50 MB · Stored under documents/</p>
            <p className="mt-3 text-sm text-[#39506B]">
              {file ? file.name : "No file selected"}
            </p>
          </label>

          <div className="grid gap-6 md:grid-cols-2">
            <label className="field-label">
              External ID
              <input
                type="text"
                className="input-pill"
                placeholder="ieee-802-2024"
                value={externalId}
                disabled={isUploading}
                onChange={(event) => setExternalId(event.target.value)}
              />
            </label>
            <label className="field-label">
              Title
              <input
                type="text"
                className="input-pill"
                placeholder="IEEE 802.11 Standard 2024"
                value={title}
                disabled={isUploading}
                onChange={(event) => setTitle(event.target.value)}
              />
            </label>
            <label className="field-label md:col-span-2">
              Description
              <textarea
                className="input-pill"
                placeholder="Optional description for this document."
                value={description}
                disabled={isUploading}
                onChange={(event) => setDescription(event.target.value)}
              />
            </label>
            <label className="field-label md:col-span-2">
              Source URL (optional)
              <input
                type="url"
                className="input-pill"
                placeholder="https://standards.ieee.org/..."
                value={sourceUri}
                disabled={isUploading}
                onChange={(event) => setSourceUri(event.target.value)}
              />
            </label>
            <label className="field-label md:col-span-2">
              Draft Document
              <div className="input-pill flex w-full items-center gap-3 text-[#39506B]">
                <input
                  id="draft-document"
                  type="checkbox"
                  className="h-5 w-5 rounded border-slate-300 text-[#39506B] focus:ring-2 focus:ring-[#39506B]"
                  checked={draftDocument}
                  disabled={isUploading}
                  onChange={(event) => setDraftDocument(event.target.checked)}
                />
                <span className="text-xs opacity-70">
                  Check to process strikeout text; leave unchecked to skip strikeout detection.
                </span>
              </div>
            </label>
              </div>

          <div className="flex flex-wrap gap-3 justify-self-end">
            <button type="submit" className="btn-modern min-w-[180px]" disabled={isUploading || !file}>
              {isUploading ? "Processing…" : "Upload Document"}
            </button>
            <button
              type="button"
              className="btn-outline"
              disabled={isUploading}
              onClick={() => {
                setFile(null);
                setExternalId("");
                setTitle("");
                setDescription("");
                setSourceUri("");
                setDraftDocument(false);
                setResult(null);
                setStatus(null);
                setError(null);
                setProgress(null);
                ingestionStartedAtRef.current = null;
                clearExistingPoll();
                setLastUploaded(null);
                if (fileInputRef.current) {
                  fileInputRef.current.value = "";
                }
              }}
            >
              Reset
            </button>
          </div>
        </form>
        </div>
        <div className="glass-surface">
          <footer className="glass-card rounded-3xl border border-white/40 bg-white/30 px-8 py-4 text-center text-xs text-[#39506B] backdrop-blur-xl">
            2025 © Phaethon Order LLC · support@phaethon.llc · Secure IEEE knowledge workflows
          </footer>
        </div>
      </div>
    </main>
  );
}
