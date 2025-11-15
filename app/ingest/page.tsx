"use client";

import Image from "next/image";
import Link from "next/link";
import { ChangeEvent, FormEvent, useState } from "react";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type IngestResponse = {
  status: string;
  document_path?: string;
  message?: string;
};

export default function IngestPage() {
  const [file, setFile] = useState<File | null>(null);
  const [externalId, setExternalId] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [sourceUri, setSourceUri] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<IngestResponse | null>(null);

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const nextFile = event.target.files?.[0] ?? null;
    setFile(nextFile);
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!file) {
      setError("Select a PDF document to ingest.");
      return;
    }

    setIsUploading(true);
    setError(null);
    setStatus("Uploading PDF and starting ingestion...");
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

      const response = await fetch(`${API_BASE_URL}/ingest_pdf`, {
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
            detailMessage = text;
          }
        }
        throw new Error(detailMessage);
      }

      let payload: IngestResponse;
      try {
        payload = JSON.parse(text) as IngestResponse;
      } catch {
        throw new Error("Received an unexpected response from the server.");
      }

      setResult(payload);
      setStatus("PDF ingested successfully. Embeddings are ready.");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unexpected error while ingesting the PDF.";
      setError(message);
      setResult(null);
      setStatus(null);
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <main className="flex min-h-screen flex-col items-center px-5 py-10 text-white">
      <section className="glass-surface w-full max-w-4xl rounded-3xl px-8 py-10">
        <header className="mb-6 flex flex-col items-center gap-3 text-center">
          <Image
            src="/images/chatieee-logo-white.png"
            alt="ChatIEEE logo"
            width={200}
            height={48}
          />
          <p className="text-base text-slate-200">
            Upload new IEEE PDFs and send them to the ingestion pipeline.
          </p>
          <Link href="/" className="btn-outline">
            ← Back to Query
          </Link>
        </header>

        <form onSubmit={handleSubmit} className="glass-card flex flex-col gap-5 px-6 py-6 text-gray-900">
          <div>
            <label className="text-sm font-semibold text-slate-600">Select PDF document</label>
            <input
              type="file"
              accept="application/pdf,.pdf"
              onChange={handleFileChange}
              disabled={isUploading}
              className="mt-2 block w-full rounded-2xl border border-white/50 bg-white/70 px-4 py-2 text-sm text-slate-700 shadow-lg"
            />
            <p className="mt-2 text-xs text-slate-500">
              {file ? file.name : "No file selected yet."}
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="flex flex-col text-sm text-slate-600">
              External ID
              <input
                type="text"
                className="mt-2 rounded-2xl border border-white/50 bg-white/70 px-4 py-2 text-sm text-slate-700 shadow-lg"
                placeholder="ieee-802-2024"
                value={externalId}
                disabled={isUploading}
                onChange={(event) => setExternalId(event.target.value)}
              />
            </label>
            <label className="flex flex-col text-sm text-slate-600">
              Title
              <input
                type="text"
                className="mt-2 rounded-2xl border border-white/50 bg-white/70 px-4 py-2 text-sm text-slate-700 shadow-lg"
                placeholder="IEEE 802.11 Standard 2024"
                value={title}
                disabled={isUploading}
                onChange={(event) => setTitle(event.target.value)}
              />
            </label>
          </div>

          <label className="flex flex-col text-sm text-slate-600">
            Description
            <textarea
              className="mt-2 min-h-[90px] rounded-2xl border border-white/50 bg-white/70 px-4 py-2 text-sm text-slate-700 shadow-lg"
              placeholder="Optional description for this document."
              value={description}
              disabled={isUploading}
              onChange={(event) => setDescription(event.target.value)}
            />
          </label>

          <label className="flex flex-col text-sm text-slate-600">
            Source URL (optional)
            <input
              type="url"
              className="mt-2 rounded-2xl border border-white/50 bg-white/70 px-4 py-2 text-sm text-slate-700 shadow-lg"
              placeholder="https://standards.ieee.org/..."
              value={sourceUri}
              disabled={isUploading}
              onChange={(event) => setSourceUri(event.target.value)}
            />
          </label>

          <button type="submit" className="btn-modern mt-2 self-end px-8" disabled={isUploading || !file}>
            {isUploading ? "Ingesting..." : "Upload & Ingest"}
          </button>
        </form>

        <div className="mt-6 space-y-4 text-sm text-slate-100">
          <p>
            Documents are stored under <span className="font-semibold">documents/</span> before chunking and embedding.
          </p>
          <ul className="list-disc space-y-1 pl-5 text-slate-200">
            <li>The ingestion endpoint extracts text, tables, and figures.</li>
            <li>Chunks are embedded immediately so they become searchable.</li>
            <li>Re-uploading a PDF updates the existing document when the checksum matches.</li>
          </ul>
        </div>

        {error && (
          <div className="glass-card mt-6 border border-red-200 bg-red-50/80 px-5 py-4 text-sm text-red-800">
            {error}
          </div>
        )}

        {status && !error && (
          <div className="glass-card mt-6 border border-indigo-200 bg-white/70 px-5 py-3 text-sm text-slate-600">
            {status}
          </div>
        )}

        {result && !error && (
          <div className="glass-card mt-6 border border-emerald-200 bg-white/85 px-6 py-5 text-sm text-gray-900">
            <p className="font-semibold text-slate-800">{result.message ?? "Ingestion finished."}</p>
            {result.document_path && (
              <p className="mt-1 text-slate-600">Stored at: <code>{result.document_path}</code></p>
            )}
          </div>
        )}
      </section>
    </main>
  );
}
