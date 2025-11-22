"use client";

import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";

import { buildClientApiUrl } from "@/app/lib/api";

type IngestResponse = {
  status: string;
  run_id?: string;
  document_path?: string;
  message?: string;
  error_message?: string;
};

const ingestEndpoint = buildClientApiUrl("/ingest_pdf");

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
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const statusChipMessage = error ?? status ?? (isUploading ? "Ingestion running…" : "Standing by");
  const statusChipTone = error ? "error" : status ? "success" : isUploading ? "processing" : "neutral";
  const statusChipClassName = ["status-chip", statusChipTone].filter(Boolean).join(" ");

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const nextFile = event.target.files?.[0] ?? null;
    setFile(nextFile);
    setLastUploaded(null);
  };

  const [pollInterval, setPollInterval] = useState<NodeJS.Timeout | null>(null);

  // Clean up interval on unmount
  useEffect(() => {
    return () => {
      if (pollInterval) clearInterval(pollInterval);
    };
  }, [pollInterval]);

  const pollStatus = async (runId: string) => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/api/backend/ingest/${runId}`);
        if (!res.ok) return; // Skip if network error
        
        const data = await res.json();
        
        if (data.status === "completed") {
          setStatus("Ingestion complete! Knowledge base updated.");
          setIsUploading(false); // Re-enable buttons
          clearInterval(interval);
        } else if (data.status === "failed") {
          setError(`Ingestion failed: ${data.error_message}`);
          setIsUploading(false);
          clearInterval(interval);
        } else {
          // Still processing
          setStatus("Ingesting document... (this may take a moment)");
        }
      } catch (e) {
        console.error("Polling error", e);
      }
    }, 2000); // Poll every 2 seconds
    
    setPollInterval(interval);
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!file) {
      setError("Select a PDF document to ingest.");
      return;
    }

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
      setResult(payload);
      setStatus(payload.message || "Processing...");
      if (payload.run_id) {
        pollStatus(payload.run_id);
      } else {
        setIsUploading(false); // No run_id to poll, so stop uploading state
      }
      setLastUploaded(file.name);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unexpected error while ingesting.";
      setError(message);
      setResult(null);
      setStatus(null);
    } finally {
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
            id="pdf-upload"
          />

          <label
            htmlFor="pdf-upload"
            className="upload-zone justify-center block max-w-100 cursor-pointer rounded-3xl border border-dashed border-slate-300 bg-white/80 px-8 py-8 text-center text-sm text-[#39506B]"
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
            <div className="flex items-start gap-3 rounded-2xl bg-white/70 px-4 py-3 shadow-sm ring-1 ring-slate-200">
              <input
                id="draft-document"
                type="checkbox"
                className="mt-1 h-5 w-5 rounded border-slate-300 text-[#39506B] focus:ring-2 focus:ring-[#39506B]"
                checked={draftDocument}
                disabled={isUploading}
                onChange={(event) => setDraftDocument(event.target.checked)}
              />
              <div className="space-y-1">
                <label htmlFor="draft-document" className="block text-sm font-semibold text-[#39506B]">
                  Draft Document
                </label>
                <p className="text-xs text-[#39506B] opacity-70">
                  Check to process strikeout text; leave unchecked to skip strikeout detection.
                </p>
              </div>
            </div>
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
