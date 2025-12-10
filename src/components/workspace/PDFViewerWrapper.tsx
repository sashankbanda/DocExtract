import { BoundingBox } from "@/types/document";
import { motion } from "framer-motion";
import { Loader2, Maximize2, RotateCw, ZoomIn, ZoomOut } from "lucide-react";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
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

export interface PDFViewerRef {
  scrollToHighlight: (wordIndexes: number[]) => void;
  scrollToPage: (pageNumber: number, wordIndex?: number) => void;
  getPageForWordIndex: (wordIndex: number) => number | null;
}

export const PDFViewerWrapper = forwardRef<PDFViewerRef, PDFViewerWrapperProps>(
function PDFViewerWrapper({
  documentId,
  fileName,
  pdfSource,
  boundingBoxes,
  selectedIndexes = [],
  activeHighlightId = null,
  highlights = [],
  activeHighlight,
}, ref) {
  const [zoom, setZoom] = useState(100);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [isRendering, setIsRendering] = useState(false);
  const [pagesLoaded, setPagesLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pageMetadata, setPageMetadata] = useState<PageMetadata[]>([]);
  
  const containerRef = useRef<HTMLDivElement>(null);
  const pagesContainerRef = useRef<HTMLDivElement>(null);
  const pdfDocumentRef = useRef<pdfjsLib.PDFDocumentProxy | null>(null);
  const renderTaskRef = useRef<Map<number, pdfjsLib.RenderTask>>(new Map());
  const abortControllerRef = useRef<AbortController | null>(null);
  const canvasRefsRef = useRef<Map<number, HTMLCanvasElement>>(new Map());
  const wordIndexToPageMapRef = useRef<Map<number, number>>(new Map());

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
        setPagesLoaded(false);

        // Build word index to page mapping if bounding boxes are available
        if (boundingBoxes) {
          const wordIndexMap = new Map<number, number>();
          const words = (boundingBoxes.words as unknown[]) || [];
          const pages = (boundingBoxes.pages as unknown[]) || [];

          words.forEach((word: unknown) => {
            if (word && typeof word === "object" && "index" in word && "page" in word) {
              const index = word.index as number;
              const page = word.page as number;
              if (typeof index === "number" && typeof page === "number") {
                wordIndexMap.set(index, page);
              }
            }
          });

          pages.forEach((page: unknown) => {
            if (page && typeof page === "object") {
              const pageNum = ("page" in page ? page.page : "index" in page ? page.index : null) as number | null;
              const pageWords = ("words" in page ? page.words : []) as unknown[];
              pageWords.forEach((word: unknown) => {
                if (word && typeof word === "object" && "index" in word && pageNum !== null) {
                  const index = word.index as number;
                  if (typeof index === "number") {
                    wordIndexMap.set(index, pageNum);
                  }
                }
              });
            }
          });

          wordIndexToPageMapRef.current = wordIndexMap;
        }

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
      setPagesLoaded(false);
      return;
    }

    let isMounted = true;
    const scale = zoom / 100;
    setIsRendering(true);
    setPagesLoaded(false);

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
        setPagesLoaded(true);
        setIsRendering(false);
      }
    };

    renderPages();

    return () => {
      isMounted = false;
      renderTaskRef.current.forEach((task) => task.cancel());
      renderTaskRef.current.clear();
      setPagesLoaded(false);
      setIsRendering(false);
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

  // Scroll to page function
  const scrollToPage = useCallback((pageNumber: number, wordIndex?: number) => {
    if (!containerRef.current || !pageMetadata.length || pageNumber < 1 || pageNumber > totalPages) {
      return;
    }

    const pageIndex = pageNumber - 1;
    const pageMeta = pageMetadata[pageIndex];
    if (!pageMeta) return;

    const offsets = getPageOffsets();
    const pageOffset = offsets[pageIndex] || 0;

    let scrollY = pageOffset - 100; // 100px offset from top

    // If wordIndex is provided, try to scroll to that specific word
    if (wordIndex !== undefined && boundingBoxes) {
      const lookup = buildIndexLookup(boundingBoxes);
      const wordBox = lookup.get(wordIndex);
      if (wordBox && wordBox.page === pageNumber) {
        const scale = zoom / 100;
        const wordY = wordBox.y * scale;
        scrollY = pageOffset + wordY - 150; // 150px offset to show word near top
      }
    }

    containerRef.current.scrollTo({
      top: Math.max(0, scrollY),
      behavior: "smooth",
    });
  }, [pageMetadata, totalPages, zoom, boundingBoxes]);

  // Scroll to highlight function
  const scrollToHighlight = useCallback((wordIndexes: number[]) => {
    if (!wordIndexes.length || !boundingBoxes || !containerRef.current || !pageMetadata.length) {
      return;
    }

    // Find the page for the first word index
    const firstIndex = wordIndexes[0];
    const page = getPageForWordIndex(firstIndex);
    if (!page) return;

    scrollToPage(page, firstIndex);
  }, [boundingBoxes, pageMetadata, scrollToPage]);

  // Get page for word index
  const getPageForWordIndex = useCallback((wordIndex: number): number | null => {
    const page = wordIndexToPageMapRef.current.get(wordIndex);
    return page || null;
  }, []);

  // Expose imperative API via ref
  useImperativeHandle(ref, () => ({
    scrollToHighlight,
    scrollToPage,
    getPageForWordIndex,
  }), [scrollToHighlight, scrollToPage, getPageForWordIndex]);

  // Helper function to build index lookup (duplicated from HighlightOverlay for internal use)
  const buildIndexLookup = useCallback((bboxes: Record<string, unknown>): Map<number, BoundingBox> => {
    const lookup = new Map<number, BoundingBox>();
    if (!bboxes) return lookup;

    const words = (bboxes.words as unknown[]) || [];
    const pages = (bboxes.pages as unknown[]) || [];

    words.forEach((word: unknown) => {
      if (!word || typeof word !== "object") return;
      const wordObj = word as Record<string, unknown>;
      const index = wordObj.index;
      if (typeof index !== "number") return;

      const bbox = (wordObj.bbox || wordObj.bounding_box || {}) as Record<string, unknown>;
      if (!bbox || typeof bbox !== "object") return;

      const page = (wordObj.page || 1) as number;
      const x1 = (bbox.x1 ?? bbox.x ?? bbox.left ?? 0) as number;
      const y1 = (bbox.y1 ?? bbox.y ?? bbox.top ?? 0) as number;
      const x2 = (bbox.x2 ?? bbox.right ?? (x1 + ((bbox.width ?? 0) as number))) as number;
      const y2 = (bbox.y2 ?? bbox.bottom ?? (y1 + ((bbox.height ?? 0) as number))) as number;

      lookup.set(index, {
        x: Math.min(x1, x2),
        y: Math.min(y1, y2),
        width: Math.abs(x2 - x1),
        height: Math.abs(y2 - y1),
        page: typeof page === "number" ? page : 1,
      });
    });

    pages.forEach((page: unknown) => {
      if (!page || typeof page !== "object") return;
      const pageObj = page as Record<string, unknown>;
      const pageNum = (pageObj.page ?? pageObj.index ?? 1) as number;
      const pageWords = (pageObj.words || []) as unknown[];
      pageWords.forEach((word: unknown) => {
        if (!word || typeof word !== "object") return;
        const wordObj = word as Record<string, unknown>;
        const index = wordObj.index;
        if (typeof index !== "number") return;

        const bbox = (wordObj.bbox || wordObj.bounding_box || {}) as Record<string, unknown>;
        if (!bbox || typeof bbox !== "object") return;

        const x1 = (bbox.x1 ?? bbox.x ?? bbox.left ?? 0) as number;
        const y1 = (bbox.y1 ?? bbox.y ?? bbox.top ?? 0) as number;
        const x2 = (bbox.x2 ?? bbox.right ?? (x1 + ((bbox.width ?? 0) as number))) as number;
        const y2 = (bbox.y2 ?? bbox.bottom ?? (y1 + ((bbox.height ?? 0) as number))) as number;

        lookup.set(index, {
          x: Math.min(x1, x2),
          y: Math.min(y1, y2),
          width: Math.abs(x2 - x1),
          height: Math.abs(y2 - y1),
          page: typeof pageNum === "number" ? pageNum : 1,
        });
      });
    });

    return lookup;
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
          <>
            {/* Loading skeleton while rendering */}
            {isRendering && (
              <div className="absolute inset-0 flex items-center justify-center bg-background/50 z-10">
                <div className="text-center">
                  <Loader2 className="w-6 h-6 animate-spin text-primary mx-auto mb-2" />
                  <p className="text-xs text-muted-foreground">Rendering pages...</p>
                </div>
              </div>
            )}
            <motion.div
              ref={pagesContainerRef}
              className="relative"
              initial={{ opacity: 0 }}
              animate={{ opacity: pagesLoaded ? 1 : 0.5 }}
              transition={{ duration: 0.3 }}
            >
              {/* Pages are rendered as canvas elements */}
              {/* Highlight Overlay - positioned absolutely over the pages */}
              {pagesLoaded && pageMetadata.length > 0 && (
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
                      pagesLoaded={pagesLoaded}
                    />
                  ) : (
                    /* Legacy API: use positioned highlights */
                    <HighlightOverlay
                      highlights={getPositionedHighlights()}
                      activeHighlight={getPositionedActiveHighlight()}
                      scale={1}
                      pagesLoaded={pagesLoaded}
                    />
                  )}
                </div>
              )}
            </motion.div>
          </>
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
});
