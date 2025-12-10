import { UploadedDocumentResult } from "@/types/document";
import { createContext, ReactNode, useContext, useMemo, useState } from "react";

interface ExtractionContextValue {
  documents: UploadedDocumentResult[];
  setDocuments: (documents: UploadedDocumentResult[]) => void;
  addDocuments: (documents: UploadedDocumentResult[]) => void;
  clearDocuments: () => void;
}

const ExtractionContext = createContext<ExtractionContextValue | undefined>(undefined);

export function ExtractionProvider({ children }: { children: ReactNode }) {
  const [documents, setDocuments] = useState<UploadedDocumentResult[]>([]);

  const value = useMemo<ExtractionContextValue>(
    () => ({
      documents,
      setDocuments,
      addDocuments: (incoming) =>
        setDocuments((prev) => {
          const byHash = new Map(prev.map((doc) => [doc.whisperHash, doc]));
          incoming.forEach((doc) => byHash.set(doc.whisperHash, doc));
          return Array.from(byHash.values());
        }),
      clearDocuments: () => setDocuments([]),
    }),
    [documents]
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
