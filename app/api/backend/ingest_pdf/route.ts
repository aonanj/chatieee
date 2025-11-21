import { buildBackendUrl, backendErrorResponse, proxyBackendResponse } from "../utils";

export const runtime = "nodejs";
// Allow large uploads and ingestion work to finish before the hosting platform times out.
export const maxDuration = 500;

export async function POST(request: Request) {
  try {
    // Extract key headers to preserve the multipart boundary and content length
    const headers = new Headers();
    const contentType = request.headers.get("content-type");
    const contentLength = request.headers.get("content-length");

    if (contentType) headers.set("content-type", contentType);
    if (contentLength) headers.set("content-length", contentLength);

    // Stream the request body directly to the backend without buffering
    const backendResponse = await fetch(buildBackendUrl("/ingest_pdf"), {
      method: "POST",
      headers: headers,
      body: request.body,
      // @ts-expect-error "duplex" is required for streaming bodies in Node.js environments but is missing from some type definitions
      duplex: "half", 
    });

    return proxyBackendResponse(backendResponse);
  } catch (error) {
    return backendErrorResponse(error);
  }
}
