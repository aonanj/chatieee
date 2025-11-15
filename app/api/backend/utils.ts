import { NextResponse } from "next/server";

const rawBase =
  process.env.BACKEND_API_BASE_URL ??
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  "http://127.0.0.1:8000";

const backendBase = rawBase.replace(/\/$/, "");

export const buildBackendUrl = (path: string): string => {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${backendBase}${normalized}`;
};

export const proxyBackendResponse = async (response: Response): Promise<NextResponse> => {
  const headers = new Headers();
  response.headers.forEach((value, key) => {
    if (key.toLowerCase() === "content-length") {
      return;
    }
    headers.set(key, value);
  });
  const buffer = await response.arrayBuffer();
  return new NextResponse(buffer, {
    status: response.status,
    headers,
  });
};

export const backendErrorResponse = (error: unknown): NextResponse => {
  const message = error instanceof Error ? error.message : "Unknown error";
  return NextResponse.json(
    {
      detail: `Unable to reach backend API (${backendBase}): ${message}`,
    },
    { status: 502 },
  );
};
