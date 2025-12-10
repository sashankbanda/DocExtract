export interface StructuredFieldData {
  value: string | null;
  start: number | null;
  end: number | null;
  word_indexes: number[];
}

export interface UploadFile {
  id: string;
  name: string;
  size: number;
  type: string;
  progress: number;
  status: 'pending' | 'uploading' | 'processing' | 'complete' | 'error';
  file?: File;
  rawFile?: File; // Original uploaded file
  previewUrl?: string; // Blob URL created from rawFile
  error?: string;
  whisperHash?: string;
  extraction?: {
    text: string;
    boundingBoxes?: Record<string, unknown> | null;
    pages?: unknown[] | null;
  };
  structuredFields?: Record<string, StructuredFieldData>;
}

export interface BoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
  page: number;
}

export interface ExtractedField {
  id: string;
  label: string;
  value: string;
  confidence: number;
  boundingBox?: BoundingBox;
  wordIndexes?: number[];
}

export interface TableCell {
  value: string;
  boundingBox?: BoundingBox;
}

export interface ExtractedTable {
  id: string;
  headers: string[];
  rows: TableCell[][];
  boundingBox?: BoundingBox;
}

export interface LayoutText {
  id: string;
  text: string;
  type: 'paragraph' | 'heading' | 'list-item';
  boundingBox?: BoundingBox;
}

export interface DocumentExtraction {
  id: string;
  fileName: string;
  layoutText: LayoutText[];
  tables: ExtractedTable[];
  templateFields: ExtractedField[];
}

export interface UploadedDocumentResult {
  id: string;
  fileName: string;
  text: string;
  whisperHash: string;
  boundingBoxes?: Record<string, unknown> | null;
  pages?: unknown[] | null;
  structuredFields?: Record<string, StructuredFieldData>;
  previewUrl?: string; // Blob URL for PDF rendering
}
