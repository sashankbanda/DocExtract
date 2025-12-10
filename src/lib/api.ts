import { StructuredFieldData, UploadedDocumentResult } from "@/types/document";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8004";

function buildUrl(path: string): string {
  return `${API_BASE_URL.replace(/\/$/, "")}${path}`;
}

async function parseJsonResponse(response: Response): Promise<any> {
  const text = await response.text();
  try {
    return text ? JSON.parse(text) : null;
  } catch (error) {
    throw new Error(text || "Unexpected response format from server.");
  }
}

async function handleResponse(response: Response): Promise<any> {
  if (!response.ok) {
    const payload = await parseJsonResponse(response);
    const message = payload?.detail || payload?.message || response.statusText;
    throw new Error(message || `Request failed with status ${response.status}`);
  }
  return parseJsonResponse(response);
}

export async function uploadDocuments(files: File[]): Promise<UploadedDocumentResult[]> {
  if (!files.length) {
    return [];
  }

  const formData = new FormData();
  files.forEach((file) => {
    formData.append("files", file);
  });

  const response = await fetch(buildUrl("/upload"), {
    method: "POST",
    body: formData,
  });

  const payload = await handleResponse(response);
  if (!Array.isArray(payload)) {
    throw new Error("Unexpected upload response format.");
  }

  return payload.map((item) => ({
    id: crypto.randomUUID(),
    fileName: item.fileName ?? "Unknown",
    text: item.text ?? "",
    whisperHash: item.whisperHash ?? "",
    boundingBoxes: item.boundingBoxes ?? null,
    pages: item.pages ?? null,
  }));
}

export async function uploadSingleDocument(
  file: File,
  onProgress?: (progress: number) => void
): Promise<UploadedDocumentResult> {
  const formData = new FormData();
  formData.append("files", file);

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();

    // Track upload progress
    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable && onProgress) {
        // Upload progress: 0-70% (uploading phase)
        const uploadProgress = Math.min(70, Math.round((e.loaded / e.total) * 70));
        onProgress(uploadProgress);
      }
    });

    xhr.addEventListener("load", async () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          // Processing progress: 70-90%
          if (onProgress) onProgress(90);

          const payload = await parseJsonResponse(new Response(xhr.responseText));
          
          if (!Array.isArray(payload) || payload.length === 0) {
            throw new Error("Unexpected upload response format.");
          }

          const item = payload[0];
          
          // Complete: 100%
          if (onProgress) onProgress(100);

          resolve({
            id: crypto.randomUUID(),
            fileName: item.fileName ?? "Unknown",
            text: item.text ?? "",
            whisperHash: item.whisperHash ?? "",
            boundingBoxes: item.boundingBoxes ?? null,
            pages: item.pages ?? null,
          });
        } catch (error) {
          reject(error instanceof Error ? error : new Error("Failed to parse response"));
        }
      } else {
        try {
          const payload = await parseJsonResponse(new Response(xhr.responseText));
          const message = payload?.detail || payload?.message || xhr.statusText;
          reject(new Error(message || `Request failed with status ${xhr.status}`));
        } catch {
          reject(new Error(`Request failed with status ${xhr.status}`));
        }
      }
    });

    xhr.addEventListener("error", () => {
      reject(new Error("Network error occurred during upload"));
    });

    xhr.addEventListener("abort", () => {
      reject(new Error("Upload was aborted"));
    });

    xhr.open("POST", buildUrl("/upload"));
    xhr.send(formData);
  });
}

export interface ExtractFieldsPayload {
  text: string;
  boundingBoxes?: Record<string, unknown> | unknown[] | null;
  templateName?: string;
}

export interface ExtractFieldsResponse {
  fields: Record<string, StructuredFieldData>;
}

export async function extractFields(
  payload: ExtractFieldsPayload
): Promise<ExtractFieldsResponse> {
  const response = await fetch(buildUrl("/extract-fields"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      text: payload.text,
      boundingBoxes: payload.boundingBoxes ?? {},
      templateName: payload.templateName || "standard_template",
    }),
  });

  const data = await handleResponse(response);
  
  if (!data || typeof data !== "object" || !data.fields) {
    throw new Error("Unexpected extract fields response format.");
  }

  return {
    fields: data.fields,
  };
}
