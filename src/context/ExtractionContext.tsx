import { UploadedDocumentResult } from "@/types/document";
import { createContext, ReactNode, useCallback, useContext, useMemo, useState } from "react";

interface ExtractionContextValue {
  documents: UploadedDocumentResult[];
  selectedFile: UploadedDocumentResult | null;
  setDocuments: (documents: UploadedDocumentResult[]) => void;
  addDocuments: (documents: UploadedDocumentResult[]) => void;
  clearDocuments: () => void;
  setSelectedFile: (file: UploadedDocumentResult | null) => void;
}

const ExtractionContext = createContext<ExtractionContextValue | undefined>(undefined);

export function ExtractionProvider({ children }: { children: ReactNode }) {
  const [documents, setDocuments] = useState<UploadedDocumentResult[]>([]);
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null);

  const selectedFile = useMemo<UploadedDocumentResult | null>(() => {
    if (!selectedFileId || !documents.length) {
      return documents[0] || null;
    }
    return documents.find((doc) => doc.id === selectedFileId) || documents[0] || null;
  }, [documents, selectedFileId]);

  const setSelectedFile = useCallback((file: UploadedDocumentResult | null) => {
    setSelectedFileId(file?.id || null);
  }, []);

  const value = useMemo<ExtractionContextValue>(
    () => ({
      documents,
      selectedFile,
      setDocuments,
      addDocuments: (incoming) =>
        setDocuments((prev) => {
          const byHash = new Map(prev.map((doc) => [doc.whisperHash, doc]));
          incoming.forEach((doc) => byHash.set(doc.whisperHash, doc));
          const updated = Array.from(byHash.values());
          // Auto-select first document if none selected
          if (!selectedFileId && updated.length > 0) {
            setSelectedFileId(updated[0].id);
          }
          return updated;
        }),
      clearDocuments: () => {
        setDocuments([]);
        setSelectedFileId(null);
      },
      setSelectedFile,
    }),
    [documents, selectedFile, selectedFileId, setSelectedFile]
  );

  return <ExtractionContext.Provider value={value}>{children}</ExtractionContext.Provider>;
}

export function useExtractionContext(): ExtractionContextValue {
  const context = useContext(ExtractionContext);
  if (!context) {
    throw new Error("useExtractionContext must be used within an ExtractionProvider");
  }
  return context;
}
