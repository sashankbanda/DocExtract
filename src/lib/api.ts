import { UploadedDocumentResult } from "@/types/document";

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
