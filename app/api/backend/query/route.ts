import { buildBackendUrl, backendErrorResponse, proxyBackendResponse } from "../utils";

export async function POST(request: Request) {
  let body: string;
  try {
    body = await request.text();
  } catch (error) {
    return backendErrorResponse(error);
  }

  try {
    const backendResponse = await fetch(buildBackendUrl("/query"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
    return proxyBackendResponse(backendResponse);
  } catch (error) {
    return backendErrorResponse(error);
  }
}
