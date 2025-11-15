import { buildBackendUrl, backendErrorResponse, proxyBackendResponse } from "../utils";

export const runtime = "nodejs";

export async function POST(request: Request) {
  let incomingForm: FormData;
  try {
    incomingForm = await request.formData();
  } catch (error) {
    return backendErrorResponse(error);
  }

  const forwardForm = new FormData();
  incomingForm.forEach((value, key) => {
    if (typeof value === "string") {
      forwardForm.append(key, value);
    } else if (value instanceof File) {
      forwardForm.append(key, value, value.name);
    }
  });

  try {
    const backendResponse = await fetch(buildBackendUrl("/ingest_pdf"), {
      method: "POST",
      body: forwardForm,
    });
    return proxyBackendResponse(backendResponse);
  } catch (error) {
    return backendErrorResponse(error);
  }
}
