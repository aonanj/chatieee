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
  try {
    incomingForm.forEach((value, key) => {
      if (typeof value === "string") {
        forwardForm.append(key, value);
      } else {
        const file = value as File;
        forwardForm.append(key, file, file.name);
      }
    });
  } catch (error) {
    return backendErrorResponse(error);
  }

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