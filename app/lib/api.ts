"use client";

const rawClientBase = process.env.NEXT_PUBLIC_API_BASE_URL
  ? process.env.NEXT_PUBLIC_API_BASE_URL.replace(/\/$/, "")
  : null;

/**
 * Build an absolute or relative URL pointing to the FastAPI backend.
 *
 * When NEXT_PUBLIC_API_BASE_URL is defined, requests go directly to that host.
 * Otherwise they tunnel through the Next.js proxy under /api/backend.
 */
export const buildClientApiUrl = (path: string): string => {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  if (rawClientBase) {
    return `${rawClientBase}${normalizedPath}`;
  }
  return `/api/backend${normalizedPath}`;
};
