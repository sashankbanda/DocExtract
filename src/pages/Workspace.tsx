import { ExtractedTextPanel } from "@/components/workspace/ExtractedTextPanel";
import { FileSelectorDropdown } from "@/components/workspace/FileSelectorDropdown";
import { PDFViewerRef, PDFViewerWrapper } from "@/components/workspace/PDFViewerWrapper";
import { StructuredTablePanel } from "@/components/workspace/StructuredTablePanel";
import { TemplateFieldsPanel } from "@/components/workspace/TemplateFieldsPanel";
import { TwoPaneLayout } from "@/components/workspace/TwoPaneLayout";
import { useExtractionContext } from "@/context/ExtractionContext";
import { cn } from "@/lib/utils";
import {
    BoundingBox,
    UploadedDocumentResult,
} from "@/types/document";
import { AnimatePresence, motion } from "framer-motion";
import { FileText, Loader2, Table, Tag, Upload } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";


type TabType = "text" | "tables" | "fields";

const tabs: { id: TabType; label: string; icon: typeof FileText }[] = [
  { id: "text", label: "Layout Text", icon: FileText },
  { id: "tables", label: "Tables", icon: Table },
  { id: "fields", label: "Fields", icon: Tag },
];

export default function Workspace() {
  const navigate = useNavigate();
  const { documents, selectedFile, setSelectedFile } = useExtractionContext();
  const [selectedFileId, setSelectedFileId] = useState<string>(documents[0]?.id ?? "");
  const [activeTab, setActiveTab] = useState<TabType>("text");
  const [hoveredBoundingBox, setHoveredBoundingBox] = useState<BoundingBox | null>(null);
  const [activeBoundingBox, setActiveBoundingBox] = useState<BoundingBox | null>(null);
  const [selectedWordIndexes, setSelectedWordIndexes] = useState<number[]>([]);
  const [activeHighlightId, setActiveHighlightId] = useState<string | null>(null);
  const [isSwitchingFile, setIsSwitchingFile] = useState(false);
  const pdfViewerRef = useRef<PDFViewerRef>(null);

  // Reset highlights and scroll when file changes
  useEffect(() => {
    if (!documents.length) {
      return;
    }
    if (!selectedFileId || !documents.some((doc) => doc.id === selectedFileId)) {
      const firstDoc = documents[0];
      if (firstDoc) {
        setSelectedFileId(firstDoc.id);
        setSelectedFile(firstDoc);
      }
    } else {
      const doc = documents.find((d) => d.id === selectedFileId);
      if (doc && doc.id !== selectedFile?.id) {
        setIsSwitchingFile(true);
        setSelectedFile(doc);
        // Reset highlights
        setSelectedWordIndexes([]);
        setActiveHighlightId(null);
        setHoveredBoundingBox(null);
        setActiveBoundingBox(null);
        // Reset scroll position
        setTimeout(() => {
          pdfViewerRef.current?.scrollToPage(1);
          setIsSwitchingFile(false);
        }, 100);
      }
    }
  }, [documents, selectedFileId, setSelectedFile, selectedFile]);

  const selectedDocument = useMemo<UploadedDocumentResult | null>(() => {
    return selectedFile || documents.find((doc) => doc.id === selectedFileId) || documents[0] || null;
  }, [documents, selectedFileId, selectedFile]);


  // Handle word index highlighting
  // NOTE: We use word_indexes for highlighting. The backend generates word-level boxes
  // from line-level boxes returned by LLMWhisperer.
  const handleWordIndexHover = useCallback((wordIndexes: number[] | null) => {
    setSelectedWordIndexes(wordIndexes || []);
  }, []);

  const handleWordIndexClick = useCallback((wordIndexes: number[]) => {
    setSelectedWordIndexes(wordIndexes);
    setActiveHighlightId(`highlight-${Date.now()}`);
    
    // Scroll to highlight
    if (pdfViewerRef.current && wordIndexes.length > 0) {
      pdfViewerRef.current.scrollToHighlight(wordIndexes);
    }
    
    setTimeout(() => setActiveHighlightId(null), 2000);
  }, []);

  // Legacy bounding box handlers (for backward compatibility)
  const handleItemHover = useCallback((boundingBox: BoundingBox | null) => {
    setHoveredBoundingBox(boundingBox);
  }, []);

  const handleItemClick = useCallback((boundingBox: BoundingBox) => {
    setActiveBoundingBox(boundingBox);
    setTimeout(() => setActiveBoundingBox(null), 2000);
  }, []);

  const allHighlights = hoveredBoundingBox ? [hoveredBoundingBox] : [];

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Only handle shortcuts when not typing in an input
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
        return;
      }

      if (e.ctrlKey || e.metaKey) {
        if (e.key === "1") {
          e.preventDefault();
          setActiveTab("text");
        } else if (e.key === "2") {
          e.preventDefault();
          setActiveTab("tables");
        } else if (e.key === "3") {
          e.preventDefault();
          setActiveTab("fields");
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  if (!documents.length) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-6 text-center px-6">
        <div className="space-y-3 max-w-xl">
          <h1 className="text-3xl font-semibold text-foreground">Upload documents to begin</h1>
          <p className="text-muted-foreground">
            We did not find any processed documents in this session. Upload files first to view
            extracted text, tables, and template fields.
          </p>
        </div>
        <button
          onClick={() => navigate("/upload")}
          className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-primary text-primary-foreground shadow-lg hover:shadow-primary/30 transition-shadow"
        >
          <Upload className="w-4 h-4" />
          Go to Uploads
        </button>
      </div>
    );
  }

  const renderTabContent = () => {
    if (!selectedDocument) {
      return <EmptyState message="Select a document to preview its extraction." />;
    }

    switch (activeTab) {
      case "text":
        return selectedDocument ? (
          <ExtractedTextPanel
            document={selectedDocument}
            onLineClick={handleWordIndexClick}
            onLineHover={handleWordIndexHover}
            isLoading={isSwitchingFile}
          />
        ) : (
          <EmptyState message="No text was returned for this document." />
        );
      case "tables":
        return (
          <StructuredTablePanel
            structuredFields={selectedDocument?.structuredFields}
            onFieldClick={handleWordIndexClick}
            onFieldHover={handleWordIndexHover}
            isLoading={isSwitchingFile}
          />
        );
      case "fields":
        return (
          <TemplateFieldsPanel
            structuredFields={selectedDocument?.structuredFields}
            onFieldClick={handleWordIndexClick}
            onFieldHover={handleWordIndexHover}
            isLoading={isSwitchingFile}
          />
        );
      default:
        return null;
    }
  };

  return (
    <div className="min-h-screen pt-16 relative">
      {/* Loading overlay when switching files */}
      <AnimatePresence>
        {isSwitchingFile && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm"
          >
            <div className="text-center">
              <Loader2 className="w-8 h-8 animate-spin text-primary mx-auto mb-2" />
              <p className="text-sm text-muted-foreground">Loading document...</p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <TwoPaneLayout
        leftPane={
          <PDFViewerWrapper
            ref={pdfViewerRef}
            documentId={selectedDocument?.id ?? ""}
            fileName={selectedDocument?.fileName}
            pdfSource={selectedDocument?.rawFile || null}
            boundingBoxes={selectedDocument?.boundingBoxes}
            selectedIndexes={selectedWordIndexes}
            activeHighlightId={activeHighlightId}
            highlights={allHighlights}
            activeHighlight={activeBoundingBox}
          />
        }
        rightPane={
          <div className="h-full flex flex-col">
            <div className="flex items-center justify-between p-4 border-b border-border/50">
              <FileSelectorDropdown
                files={documents.map((doc) => ({ id: doc.id, name: doc.fileName }))}
                selectedId={selectedDocument?.id ?? ""}
                onSelect={(id) => {
                  setSelectedFileId(id);
                  const doc = documents.find((d) => d.id === id);
                  if (doc) {
                    setSelectedFile(doc);
                  }
                }}
              />
            </div>

            <div className="flex items-center gap-1 p-4 border-b border-border/50">
              {tabs.map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={cn(
                    "relative flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all duration-200",
                    activeTab === tab.id
                      ? "text-primary"
                      : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
                  )}
                >
                  <tab.icon className="w-4 h-4" />
                  <span className="hidden sm:inline">{tab.label}</span>
                  {activeTab === tab.id && (
                    <motion.div
                      layoutId="tab-indicator"
                      className="absolute inset-0 rounded-xl bg-primary/10 border border-primary/30"
                      transition={{ type: "spring", bounce: 0.2, duration: 0.6 }}
                    />
                  )}
                </button>
              ))}
            </div>

            <div className="flex-1 overflow-y-auto p-4">
              <AnimatePresence mode="wait">
                <motion.div
                  key={activeTab}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -10 }}
                  transition={{ duration: 0.2 }}
                >
                  {renderTabContent()}
                </motion.div>
              </AnimatePresence>
            </div>
          </div>
        }
      />
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-16 text-center text-muted-foreground">
      <p className="text-sm max-w-md">{message}</p>
    </div>
  );
}
