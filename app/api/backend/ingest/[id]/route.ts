import { buildBackendUrl, backendErrorResponse, proxyBackendResponse } from "../../utils";

export const runtime = "nodejs";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  try {
    const backendResponse = await fetch(buildBackendUrl(`/ingest/${id}`), {
      method: "GET",
      headers: { "Content-Type": "application/json" },
      cache: "no-store", 
    });
    return proxyBackendResponse(backendResponse);
  } catch (error) {
    return backendErrorResponse(error);
  }
}