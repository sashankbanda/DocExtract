import { BoundingBox } from "@/types/document";
import { motion } from "framer-motion";
import { Loader2, Maximize2, RotateCw, ZoomIn, ZoomOut } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import * as pdfjsLib from "pdfjs-dist";
import { HighlightOverlay } from "./HighlightOverlay";

// Set up PDF.js worker
pdfjsLib.GlobalWorkerOptions.workerSrc = `//cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjsLib.version}/pdf.worker.min.js`;

interface PDFViewerWrapperProps {
  documentId: string;
  fileName?: string;
  pdfSource?: string | File | ArrayBuffer | Uint8Array; // URL, File, or ArrayBuffer
  // New API: for word index-based highlighting
  boundingBoxes?: Record<string, unknown> | null; // Raw bounding box data from backend
  selectedIndexes?: number[]; // Word indexes to highlight
  activeHighlightId?: string | null; // ID of active highlight
  // Legacy API: for direct bounding box highlighting (backward compatibility)
  highlights?: BoundingBox[];
  activeHighlight?: BoundingBox | null;
}

interface PageMetadata {
  pageNumber: number;
  width: number;
  height: number;
  viewport: { width: number; height: number };
  scale: number;
}

export function PDFViewerWrapper({
  documentId,
  fileName,
  pdfSource,
  boundingBoxes,
  selectedIndexes = [],
  activeHighlightId = null,
  highlights = [],
  activeHighlight,
}: PDFViewerWrapperProps) {
  const [zoom, setZoom] = useState(100);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pageMetadata, setPageMetadata] = useState<PageMetadata[]>([]);
  
  const containerRef = useRef<HTMLDivElement>(null);
  const pagesContainerRef = useRef<HTMLDivElement>(null);
  const pdfDocumentRef = useRef<pdfjsLib.PDFDocumentProxy | null>(null);
  const renderTaskRef = useRef<Map<number, pdfjsLib.RenderTask>>(new Map());
  const abortControllerRef = useRef<AbortController | null>(null);
  const canvasRefsRef = useRef<Map<number, HTMLCanvasElement>>(new Map());

  // Load PDF document
  useEffect(() => {
    if (!pdfSource) {
      setTotalPages(0);
      setPageMetadata([]);
      pdfDocumentRef.current = null;
      return;
    }

    let isMounted = true;
    setIsLoading(true);
    setError(null);

    // Cancel any ongoing operations
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = new AbortController();

    const loadPDF = async () => {
      try {
        // Clean up previous canvases
        canvasRefsRef.current.forEach((canvas) => {
          const ctx = canvas.getContext("2d");
          if (ctx) {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
          }
        });
        canvasRefsRef.current.clear();
        renderTaskRef.current.forEach((task) => task.cancel());
        renderTaskRef.current.clear();

        // Load PDF document
        let loadingTask: pdfjsLib.PDFDocumentLoadingTask;
        
        if (pdfSource instanceof File) {
          const arrayBuffer = await pdfSource.arrayBuffer();
          loadingTask = pdfjsLib.getDocument({ data: arrayBuffer });
        } else if (pdfSource instanceof ArrayBuffer || pdfSource instanceof Uint8Array) {
          loadingTask = pdfjsLib.getDocument({ data: pdfSource });
        } else {
          // URL string
          loadingTask = pdfjsLib.getDocument({ url: pdfSource });
        }

        const pdf = await loadingTask.promise;

        if (!isMounted) {
          pdf.destroy();
          return;
        }

        pdfDocumentRef.current = pdf;
        setTotalPages(pdf.numPages);
        setCurrentPage(1);
        setZoom(100);

        // Initialize page metadata array
        const metadata: PageMetadata[] = [];
        for (let i = 1; i <= pdf.numPages; i++) {
          const page = await pdf.getPage(i);
          const viewport = page.getViewport({ scale: 1 });
          metadata.push({
            pageNumber: i,
            width: viewport.width,
            height: viewport.height,
            viewport: { width: viewport.width, height: viewport.height },
            scale: 1,
          });
        }
        setPageMetadata(metadata);
      } catch (err) {
        if (isMounted && !abortControllerRef.current.signal.aborted) {
          const message = err instanceof Error ? err.message : "Failed to load PDF";
          setError(message);
          console.error("PDF loading error:", err);
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    };

    loadPDF();

    return () => {
      isMounted = false;
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      if (pdfDocumentRef.current) {
        pdfDocumentRef.current.destroy();
        pdfDocumentRef.current = null;
      }
      renderTaskRef.current.forEach((task) => task.cancel());
      renderTaskRef.current.clear();
    };
  }, [pdfSource, documentId]);

  // Render pages when zoom or document changes
  useEffect(() => {
    if (!pdfDocumentRef.current || totalPages === 0 || !pagesContainerRef.current) {
      return;
    }

    let isMounted = true;
    const scale = zoom / 100;

    const renderPages = async () => {
      // Cancel any ongoing render tasks
      renderTaskRef.current.forEach((task) => task.cancel());
      renderTaskRef.current.clear();

      const pdf = pdfDocumentRef.current!;
      const container = pagesContainerRef.current!;

      // Clear existing content
      container.innerHTML = "";

      // Update metadata with new scale
      const updatedMetadata: PageMetadata[] = [];
      
      for (let pageNum = 1; pageNum <= totalPages; pageNum++) {
        if (!isMounted) break;

        try {
          const page = await pdf.getPage(pageNum);
          const viewport = page.getViewport({ scale });

          // Update metadata
          updatedMetadata.push({
            pageNumber: pageNum,
            width: viewport.width,
            height: viewport.height,
            viewport: { width: viewport.width, height: viewport.height },
            scale,
          });

          // Create canvas element
          const canvas = document.createElement("canvas");
          canvas.className = "block mx-auto mb-4 shadow-lg";
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          
          canvasRefsRef.current.set(pageNum, canvas);
          container.appendChild(canvas);

          // Render page
          const renderContext = {
            canvasContext: canvas.getContext("2d")!,
            viewport,
          };

          const renderTask = page.render(renderContext);
          renderTaskRef.current.set(pageNum, renderTask);

          await renderTask.promise;

          if (!isMounted) break;
        } catch (err) {
          if (isMounted && !(err instanceof Error && err.message.includes("cancelled"))) {
            console.error(`Error rendering page ${pageNum}:`, err);
          }
        }
      }

      if (isMounted) {
        setPageMetadata(updatedMetadata);
      }
    };

    renderPages();

    return () => {
      isMounted = false;
      renderTaskRef.current.forEach((task) => task.cancel());
      renderTaskRef.current.clear();
    };
  }, [zoom, totalPages, documentId]);

  const handleZoomIn = useCallback(() => {
    setZoom((prev) => Math.min(prev + 25, 200));
  }, []);

  const handleZoomOut = useCallback(() => {
    setZoom((prev) => Math.max(prev - 25, 50));
  }, []);

  const handleZoomReset = useCallback(() => {
    setZoom(100);
  }, []);

  // Calculate page offsets for highlight positioning
  const getPageOffsets = useCallback(() => {
    const offsets: number[] = [0];
    let currentOffset = 0;
    for (let i = 0; i < pageMetadata.length; i++) {
      currentOffset += pageMetadata[i].height + 16; // 16px margin between pages
      offsets.push(currentOffset);
    }
    return offsets;
  }, [pageMetadata]);

  // Map highlights to their correct positions accounting for page offsets
  const getPositionedHighlights = useCallback(() => {
    if (pageMetadata.length === 0) return [];
    const offsets = getPageOffsets();
    const scale = zoom / 100;

    return highlights.map((highlight) => {
      const pageIndex = (highlight.page || 1) - 1;
      const pageOffset = offsets[pageIndex] || 0;
      
      return {
        ...highlight,
        x: highlight.x * scale,
        y: highlight.y * scale + pageOffset,
        width: highlight.width * scale,
        height: highlight.height * scale,
      };
    });
  }, [highlights, pageMetadata, zoom, getPageOffsets]);

  const getPositionedActiveHighlight = useCallback(() => {
    if (!activeHighlight || pageMetadata.length === 0) return null;
    const offsets = getPageOffsets();
    const scale = zoom / 100;
    const pageIndex = (activeHighlight.page || 1) - 1;
    const pageOffset = offsets[pageIndex] || 0;

    return {
      ...activeHighlight,
      x: activeHighlight.x * scale,
      y: activeHighlight.y * scale + pageOffset,
      width: activeHighlight.width * scale,
      height: activeHighlight.height * scale,
    };
  }, [activeHighlight, pageMetadata, zoom, getPageOffsets]);

  if (error) {
    return (
      <div className="h-full flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border/50">
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">{fileName || "PDF Viewer"}</span>
          </div>
        </div>
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="text-center text-destructive">
            <p className="text-sm font-medium mb-2">Failed to load PDF</p>
            <p className="text-xs text-muted-foreground">{error}</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border/50">
        <div className="flex items-center gap-2">
          {isLoading ? (
            <div className="flex items-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin text-primary" />
              <span className="text-sm text-muted-foreground">Loading PDF...</span>
            </div>
          ) : (
            <span className="text-sm text-muted-foreground">
              {totalPages > 0 ? `Page ${currentPage} of ${totalPages}` : fileName || "PDF Viewer"}
            </span>
          )}
        </div>

        <div className="flex items-center gap-1">
          <button
            onClick={handleZoomOut}
            disabled={isLoading || totalPages === 0}
            className="p-2 rounded-lg hover:bg-muted/50 transition-colors text-muted-foreground hover:text-foreground disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <ZoomOut className="w-4 h-4" />
          </button>
          <span className="text-sm text-muted-foreground w-14 text-center">{zoom}%</span>
          <button
            onClick={handleZoomIn}
            disabled={isLoading || totalPages === 0}
            className="p-2 rounded-lg hover:bg-muted/50 transition-colors text-muted-foreground hover:text-foreground disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <ZoomIn className="w-4 h-4" />
          </button>
          <button
            onClick={handleZoomReset}
            disabled={isLoading || totalPages === 0 || zoom === 100}
            className="p-2 rounded-lg hover:bg-muted/50 transition-colors text-muted-foreground hover:text-foreground disabled:opacity-50 disabled:cursor-not-allowed"
            title="Reset zoom"
          >
            <span className="text-xs">100%</span>
          </button>
          <div className="w-px h-5 bg-border mx-2" />
          <button
            disabled={isLoading || totalPages === 0}
            className="p-2 rounded-lg hover:bg-muted/50 transition-colors text-muted-foreground hover:text-foreground disabled:opacity-50 disabled:cursor-not-allowed"
            title="Rotate"
          >
            <RotateCw className="w-4 h-4" />
          </button>
          <button
            disabled={isLoading || totalPages === 0}
            className="p-2 rounded-lg hover:bg-muted/50 transition-colors text-muted-foreground hover:text-foreground disabled:opacity-50 disabled:cursor-not-allowed"
            title="Fullscreen"
          >
            <Maximize2 className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* PDF Viewer Area */}
      <div
        ref={containerRef}
        className="flex-1 overflow-auto p-6 relative"
        style={{ backgroundColor: "hsl(var(--muted) / 0.3)" }}
        onScroll={(e) => {
          // Update current page based on scroll position
          if (pageMetadata.length === 0) return;
          
          const container = e.currentTarget;
          const scrollTop = container.scrollTop;
          const containerHeight = container.clientHeight;
          const scrollPosition = scrollTop + containerHeight / 2;

          let accumulatedHeight = 0;
          for (let i = 0; i < pageMetadata.length; i++) {
            const pageHeight = pageMetadata[i].height + 16; // 16px margin
            if (scrollPosition < accumulatedHeight + pageHeight) {
              setCurrentPage(i + 1);
              break;
            }
            accumulatedHeight += pageHeight;
          }
        }}
      >
        {isLoading && totalPages === 0 ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <Loader2 className="w-8 h-8 animate-spin text-primary mx-auto mb-4" />
              <p className="text-sm text-muted-foreground">Loading PDF document...</p>
            </div>
          </div>
        ) : totalPages > 0 ? (
          <motion.div
            ref={pagesContainerRef}
            className="relative"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.3 }}
          >
            {/* Pages are rendered as canvas elements */}
            {/* Highlight Overlay - positioned absolutely over the pages */}
            {pageMetadata.length > 0 && (
              <div
                className="absolute pointer-events-none"
                style={{
                  top: 0,
                  left: "50%",
                  transform: "translateX(-50%)",
                  width: pageMetadata[0]?.width || 0,
                  height: pageMetadata.reduce((sum, meta) => sum + meta.height + 16, 0),
                }}
              >
                {/* Use new API if boundingBoxes and selectedIndexes are provided */}
                {boundingBoxes && selectedIndexes.length > 0 ? (
                  <HighlightOverlay
                    boundingBoxes={boundingBoxes}
                    selectedIndexes={selectedIndexes}
                    pdfPageRefs={Array.from({ length: totalPages }, (_, i) => {
                      const canvas = canvasRefsRef.current.get(i + 1);
                      return { current: canvas } as React.RefObject<HTMLCanvasElement>;
                    })}
                    currentScale={zoom / 100}
                    pageMetadata={pageMetadata}
                    activeHighlightId={activeHighlightId}
                    scrollContainerRef={containerRef}
                  />
                ) : (
                  /* Legacy API: use positioned highlights */
                  <HighlightOverlay
                    highlights={getPositionedHighlights()}
                    activeHighlight={getPositionedActiveHighlight()}
                    scale={1}
                  />
                )}
              </div>
            )}
          </motion.div>
        ) : (
          <div className="flex items-center justify-center h-full">
            <div className="text-center text-muted-foreground">
              <p className="text-sm">No PDF loaded</p>
              {!pdfSource && (
                <p className="text-xs mt-2">PDF source not provided</p>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
