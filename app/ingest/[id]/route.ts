import { buildBackendUrl, backendErrorResponse, proxyBackendResponse } from "@/app/api/backend/utils";

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
    });
    return proxyBackendResponse(backendResponse);
  } catch (error) {
    return backendErrorResponse(error);
  }
}