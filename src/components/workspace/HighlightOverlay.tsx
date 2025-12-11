import { motion, AnimatePresence } from "framer-motion";
import { BoundingBox } from "@/types/document";
import { useCallback, useMemo, useEffect, useRef, useState } from "react";

interface HighlightOverlayProps {
  // New API: line number-based highlighting
  // NOTE: LLMWhisperer returns line-level bounding boxes, not word-level
  // We highlight entire lines based on line_numbers (1-based)
  boundingBoxes?: Record<string, unknown> | null; // Raw bounding box data from backend (contains line_metadata)
  selectedIndexes?: number[]; // Word indexes (legacy, for backward compatibility)
  activeLineNumbers?: number[]; // Line numbers to highlight (1-based) - PRIMARY METHOD
  pdfPageRefs?: React.RefObject<HTMLCanvasElement>[]; // Array of page canvas refs
  currentScale?: number; // Current zoom scale
  pageMetadata?: Array<{
    pageNumber: number;
    width: number;
    height: number;
    viewport: { width: number; height: number };
    scale: number;
  }>; // Page metadata for positioning
  activeHighlightId?: string | null; // ID of the active highlight (clicked)
  onHighlightClick?: (highlight: MergedHighlight) => void; // Callback when highlight is clicked
  scrollContainerRef?: React.RefObject<HTMLDivElement>; // Container ref for scrolling
  pagesLoaded?: boolean; // Whether PDF pages are fully loaded
  // Legacy API: direct bounding box highlighting (backward compatibility)
  highlights?: BoundingBox[]; // Pre-positioned highlights
  activeHighlight?: BoundingBox | null; // Active highlight
  scale?: number; // Scale for legacy highlights
}

interface MergedHighlight {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  page: number;
}

// Check if two boxes overlap or touch
function boxesOverlap(
  box1: { x: number; y: number; width: number; height: number },
  box2: { x: number; y: number; width: number; height: number },
  gapRatio: number = 0.5
): boolean {
  const gap = Math.min(box1.height, box2.height) * gapRatio;
  
  // Check horizontal overlap
  const horizontalOverlap =
    box1.x <= box2.x + box2.width + gap && box1.x + box1.width + gap >= box2.x;
  
  // Check vertical overlap (for same line)
  const verticalOverlap =
    Math.abs(box1.y - box2.y) <= Math.max(box1.height, box2.height) * 0.6;
  
  return horizontalOverlap && verticalOverlap;
}

// Merge overlapping boxes
function mergeBoxes(boxes: Array<{ x: number; y: number; width: number; height: number; page: number }>): MergedHighlight[] {
  if (boxes.length === 0) return [];

  // Group boxes by page
  const boxesByPage = new Map<number, Array<{ x: number; y: number; width: number; height: number }>>();
  boxes.forEach((box) => {
    if (!boxesByPage.has(box.page)) {
      boxesByPage.set(box.page, []);
    }
    boxesByPage.get(box.page)!.push({ x: box.x, y: box.y, width: box.width, height: box.height });
  });

  const merged: MergedHighlight[] = [];

  // Process each page independently
  boxesByPage.forEach((pageBoxes, page) => {
    // Sort boxes by x position, then y position
    const sorted = [...pageBoxes].sort((a, b) => {
      if (Math.abs(a.y - b.y) > Math.max(a.height, b.height) * 0.6) {
        return a.y - b.y; // Different lines
      }
      return a.x - b.x; // Same line
    });

    const mergedForPage: MergedHighlight[] = [];
    const processed = new Set<number>();

    for (let i = 0; i < sorted.length; i++) {
      if (processed.has(i)) continue;

      let currentBox = { ...sorted[i] };
      processed.add(i);

      // Try to merge with other boxes
      let mergedAny = true;
      while (mergedAny) {
        mergedAny = false;
        for (let j = i + 1; j < sorted.length; j++) {
          if (processed.has(j)) continue;

          if (boxesOverlap(currentBox, sorted[j])) {
            // Merge boxes
            const minX = Math.min(currentBox.x, sorted[j].x);
            const minY = Math.min(currentBox.y, sorted[j].y);
            const maxX = Math.max(
              currentBox.x + currentBox.width,
              sorted[j].x + sorted[j].width
            );
            const maxY = Math.max(
              currentBox.y + currentBox.height,
              sorted[j].y + sorted[j].height
            );

            currentBox = {
              x: minX,
              y: minY,
              width: maxX - minX,
              height: maxY - minY,
            };
            processed.add(j);
            mergedAny = true;
          }
        }
      }

      mergedForPage.push({
        id: `page-${page}-highlight-${mergedForPage.length}`,
        ...currentBox,
        page,
      });
    }

    merged.push(...mergedForPage);
  });

  return merged;
}

// Build index lookup from bounding box payload
function buildIndexLookup(boundingBoxes: Record<string, unknown>): Map<number, BoundingBox> {
  const lookup = new Map<number, BoundingBox>();

  if (!boundingBoxes) return lookup;

  // Try to extract words from different possible structures
  const words = (boundingBoxes.words as any[]) || [];
  const pages = (boundingBoxes.pages as any[]) || [];

  // Process words array
  words.forEach((word: any) => {
    if (!word || typeof word !== "object") return;
    const index = word.index;
    if (typeof index !== "number") return;

    const bbox = word.bbox || word.bounding_box || {};
    if (!bbox || typeof bbox !== "object") return;

    const page = word.page || 1;
    const x1 = bbox.x1 ?? bbox.x ?? bbox.left ?? 0;
    const y1 = bbox.y1 ?? bbox.y ?? bbox.top ?? 0;
    const x2 = bbox.x2 ?? bbox.right ?? x1 + (bbox.width ?? 0);
    const y2 = bbox.y2 ?? bbox.bottom ?? y1 + (bbox.height ?? 0);

    lookup.set(index, {
      x: Math.min(x1, x2),
      y: Math.min(y1, y2),
      width: Math.abs(x2 - x1),
      height: Math.abs(y2 - y1),
      page: typeof page === "number" ? page : 1,
    });
  });

  // Process pages array
  pages.forEach((page: any) => {
    const pageNum = page.page ?? page.index ?? 1;
    const pageWords = page.words || [];
    pageWords.forEach((word: any) => {
      if (!word || typeof word !== "object") return;
      const index = word.index;
      if (typeof index !== "number") return;

      const bbox = word.bbox || word.bounding_box || {};
      if (!bbox || typeof bbox !== "object") return;

      const x1 = bbox.x1 ?? bbox.x ?? bbox.left ?? 0;
      const y1 = bbox.y1 ?? bbox.y ?? bbox.top ?? 0;
      const x2 = bbox.x2 ?? bbox.right ?? x1 + (bbox.width ?? 0);
      const y2 = bbox.y2 ?? bbox.bottom ?? y1 + (bbox.height ?? 0);

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
}

export function HighlightOverlay({
  boundingBoxes,
  selectedIndexes = [],
  activeLineNumbers = [],
  pdfPageRefs = [],
  currentScale = 1,
  pageMetadata = [],
  activeHighlightId = null,
  onHighlightClick,
  scrollContainerRef,
  pagesLoaded = true,
  // Legacy API
  highlights,
  activeHighlight,
  scale = 1,
}: HighlightOverlayProps) {
  const glowTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const [clickedHighlightId, setClickedHighlightId] = useState<string | null>(null);
  const [pulseHighlightId, setPulseHighlightId] = useState<string | null>(null);

  // Determine which API to use - use new API if boundingBoxes is provided
  const useNewAPI = boundingBoxes !== undefined;

  // Extract line metadata from bounding boxes
  // LLMWhisperer returns line-level bounding boxes in line_metadata
  const lineMetadata = useMemo(() => {
    if (!boundingBoxes || typeof boundingBoxes !== "object") return [];
    
    // Try different possible keys for line metadata
    const lines = (boundingBoxes as any).line_metadata || 
                  (boundingBoxes as any).lines || 
                  (boundingBoxes as any).lineMetadata;
    
    return Array.isArray(lines) ? lines : [];
  }, [boundingBoxes]);

  // Convert line numbers to bounding boxes (PRIMARY METHOD)
  // LLMWhisperer returns line-level boxes, so we highlight entire lines
  const lineNumbersToBoxes = useMemo(() => {
    if (!useNewAPI || !lineMetadata.length || !activeLineNumbers.length) return [];

    const boxes: Array<{ x: number; y: number; width: number; height: number; page: number }> = [];
    const uniqueLineNumbers = Array.from(new Set(activeLineNumbers));

    uniqueLineNumbers.forEach((lineNumber) => {
      // Find line in metadata (line numbers are 1-based)
      const lineData = lineMetadata.find((line: any) => {
        const lineNo = line.line_no || line.line_number || line.line;
        return lineNo === lineNumber;
      });

      if (lineData && typeof lineData === "object") {
        // Extract bounding box from line data
        const bbox = lineData.bbox || lineData.bounding_box || lineData.box || lineData.raw_box;
        if (bbox) {
          let page = 1;
          let x = 0;
          let y = 0;
          let width = 0;
          let height = 0;

          if (Array.isArray(bbox) && bbox.length >= 4) {
            // Format: [page, base_y, height, page_height]
            page = bbox[0] || 1;
            y = bbox[1] || 0;
            height = bbox[2] || 0;
            // Width would need to be extracted from page width or line text
            width = 500; // Default width, should be adjusted based on page width
          } else if (typeof bbox === "object") {
            page = bbox.page || bbox.pageNumber || 1;
            x = bbox.x || bbox.left || 0;
            y = bbox.y || bbox.top || bbox.base_y || 0;
            width = bbox.width || bbox.right - bbox.left || 500;
            height = bbox.height || bbox.bottom - bbox.top || 0;
          }

          if (width > 0 && height > 0) {
            boxes.push({ x, y, width, height, page });
          }
        }
      }
    });

    return boxes;
  }, [useNewAPI, lineMetadata, activeLineNumbers]);

  // Convert word indexes to bounding boxes (legacy fallback)
  const wordIndexesToBoxes = useMemo(() => {
    if (!useNewAPI || !boundingBoxes || !selectedIndexes.length) return [];

    const lookup = buildIndexLookup(boundingBoxes);
    const boxes: Array<{ x: number; y: number; width: number; height: number; page: number }> = [];

    const uniqueIndexes = Array.from(new Set(selectedIndexes || []));

    uniqueIndexes.forEach((index) => {
      const box = lookup.get(index);
      if (box) {
        boxes.push(box);
      }
    });

    return boxes;
  }, [useNewAPI, boundingBoxes, selectedIndexes]);

  // Merge overlapping boxes (new API)
  // Prefer line-based boxes over word-based boxes
  const mergedHighlights = useMemo(() => {
    if (!useNewAPI) return [];
    // Use line-based boxes if available, otherwise fall back to word-based
    const boxesToMerge = lineNumbersToBoxes.length > 0 ? lineNumbersToBoxes : wordIndexesToBoxes;
    return mergeBoxes(boxesToMerge);
  }, [useNewAPI, lineNumbersToBoxes, wordIndexesToBoxes]);

  // Calculate page offsets for positioning (new API)
  const pageOffsets = useMemo(() => {
    if (!useNewAPI || !pageMetadata.length) return [];
    const offsets: number[] = [0];
    let currentOffset = 0;
    for (let i = 0; i < pageMetadata.length; i++) {
      currentOffset += pageMetadata[i].height + 16; // 16px margin between pages
      offsets.push(currentOffset);
    }
    return offsets;
  }, [useNewAPI, pageMetadata]);

  // Position highlights accounting for scale and page offsets (new API)
  const positionedHighlights = useMemo(() => {
    if (!useNewAPI) {
      // Legacy API: use pre-positioned highlights
      return (highlights || []).map((h, idx) => ({
        id: `legacy-${idx}`,
        x: h.x * scale,
        y: h.y * scale,
        width: h.width * scale,
        height: h.height * scale,
        page: h.page || 1,
      }));
    }

    return mergedHighlights.map((highlight) => {
      const pageIndex = highlight.page - 1;
      const pageMeta = pageMetadata[pageIndex];
      if (!pageMeta) return highlight;

      const pageOffset = pageOffsets[pageIndex] || 0;
      const pageHeight = pageMeta.height;

      // PDF.js uses bottom-left origin, HTML uses top-left
      // Convert Y coordinate: y_pdf = pageHeight - y_html - height
      // So: y_html = pageHeight - y_pdf - height
      const flippedY = pageHeight - highlight.y - highlight.height;

      return {
        ...highlight,
        x: highlight.x * currentScale,
        y: flippedY * currentScale + pageOffset,
        width: highlight.width * currentScale,
        height: highlight.height * currentScale,
      };
    });
  }, [useNewAPI, mergedHighlights, currentScale, pageOffsets, pageMetadata, highlights, scale]);

  // Handle highlight click - scroll to page and show glow
  const handleHighlightClick = useCallback(
    (highlight: MergedHighlight) => {
      // Clear any existing glow timeout
      if (glowTimeoutRef.current) {
        clearTimeout(glowTimeoutRef.current);
      }

      // Set clicked highlight for glow effect
      setClickedHighlightId(highlight.id);
      setPulseHighlightId(highlight.id);

      // Clear pulse after 1 second, glow stays longer
      setTimeout(() => {
        setPulseHighlightId(null);
      }, 1000);

      // Clear glow after 2 seconds
      glowTimeoutRef.current = setTimeout(() => {
        setClickedHighlightId(null);
      }, 2000);

      // Scroll to page if using new API
      if (useNewAPI && scrollContainerRef?.current && pageMetadata.length) {
        const pageIndex = highlight.page - 1;
        const pageOffset = pageOffsets[pageIndex] || 0;

        // Scroll to the highlight
        const container = scrollContainerRef.current;
        const scrollY = pageOffset + highlight.y - 150; // 150px offset from top
        container.scrollTo({
          top: Math.max(0, scrollY),
          behavior: "smooth",
        });
      }

      // Call the callback if provided
      if (onHighlightClick) {
        onHighlightClick(highlight);
      }
    },
    [useNewAPI, scrollContainerRef, pageMetadata, pageOffsets, onHighlightClick]
  );

  // Determine active highlight ID (new API) or use legacy activeHighlight
  const effectiveActiveHighlightId = useMemo(() => {
    // Clicked highlight takes precedence
    if (clickedHighlightId) return clickedHighlightId;
    
    if (useNewAPI) {
      // If activeHighlightId is set and we have selectedIndexes, show active highlights
      if (activeHighlightId && selectedIndexes && selectedIndexes.length > 0) {
        return activeHighlightId;
      }
      return null;
    }
    // Legacy API: check if any highlight matches activeHighlight
    if (!activeHighlight) return null;
    const matchingIndex = positionedHighlights.findIndex(
      (h) =>
        Math.abs(h.x - activeHighlight.x * scale) < 1 &&
        Math.abs(h.y - activeHighlight.y * scale) < 1 &&
        Math.abs(h.width - activeHighlight.width * scale) < 1 &&
        Math.abs(h.height - activeHighlight.height * scale) < 1
    );
    return matchingIndex >= 0 ? positionedHighlights[matchingIndex].id : null;
  }, [clickedHighlightId, useNewAPI, activeHighlightId, selectedIndexes, activeHighlight, positionedHighlights, scale]);

  // Clear glow timeout on unmount
  useEffect(() => {
    return () => {
      if (glowTimeoutRef.current) {
        clearTimeout(glowTimeoutRef.current);
      }
    };
  }, []);

  // Don't render if pages aren't loaded
  if (!pagesLoaded) {
    return null;
  }

  // Separate preview (hover) and active (clicked) highlights
  const previewHighlights = useMemo(() => {
    // Preview highlights are from selectedIndexes (hover state) - exclude active highlights
    if (!useNewAPI || !boundingBoxes || !selectedIndexes || selectedIndexes.length === 0) return [];
    if (effectiveActiveHighlightId) return []; // Don't show preview when active highlight is shown
    
    const lookup = buildIndexLookup(boundingBoxes);
    const boxes: Array<{ x: number; y: number; width: number; height: number; page: number }> = [];
    const uniqueIndexes = Array.from(new Set(selectedIndexes));
    
    uniqueIndexes.forEach((index) => {
      const box = lookup.get(index);
      if (box) {
        boxes.push(box);
      }
    });
    
    const merged = mergeBoxes(boxes);
    return merged.map((highlight) => {
      const pageIndex = highlight.page - 1;
      const pageMeta = pageMetadata[pageIndex];
      if (!pageMeta) return highlight;

      const pageOffset = pageOffsets[pageIndex] || 0;
      const pageHeight = pageMeta.height;

      // Convert Y coordinate from PDF.js (bottom-left) to HTML (top-left)
      const flippedY = pageHeight - highlight.y - highlight.height;

      return {
        ...highlight,
        x: highlight.x * currentScale,
        y: flippedY * currentScale + pageOffset,
        width: highlight.width * currentScale,
        height: highlight.height * currentScale,
      };
    });
  }, [useNewAPI, boundingBoxes, selectedIndexes, currentScale, pageOffsets, pageMetadata, effectiveActiveHighlightId]);

  const activeHighlights = useMemo(() => {
    // Active highlights are shown when activeHighlightId is set OR activeLineNumbers are provided
    // Use line-based highlights if available
    if (activeLineNumbers.length > 0 && lineNumbersToBoxes.length > 0) {
      // Map line-based boxes to positioned highlights
      return lineNumbersToBoxes.map((box, idx) => {
        const pageIndex = box.page - 1;
        const pageMeta = pageMetadata[pageIndex];
        if (!pageMeta) return null;

        const pageOffset = pageOffsets[pageIndex] || 0;
        const pageHeight = pageMeta.height;
        const flippedY = pageHeight - box.y - box.height;

        return {
          id: `line-${activeLineNumbers[idx]}-${idx}`,
          x: box.x * currentScale,
          y: flippedY * currentScale + pageOffset,
          width: box.width * currentScale,
          height: box.height * currentScale,
          page: box.page,
        };
      }).filter((h): h is MergedHighlight => h !== null);
    }
    
    if (!effectiveActiveHighlightId) return [];
    
    // Return all positioned highlights when active (they're already filtered by selectedIndexes)
    return positionedHighlights;
  }, [positionedHighlights, effectiveActiveHighlightId, activeLineNumbers, lineNumbersToBoxes, pageMetadata, pageOffsets, currentScale]);

  return (
    <div className="absolute inset-0 pointer-events-none overflow-hidden">
      {/* Preview layer (hover highlights) - subtle */}
      <AnimatePresence>
        {previewHighlights.map((highlight) => (
          <motion.div
            key={`preview-${highlight.id}`}
            className="absolute bg-blue-500/15 border border-blue-400/30 rounded-md pointer-events-none"
            style={{
              left: highlight.x,
              top: highlight.y,
              width: highlight.width,
              height: highlight.height,
            }}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
          />
        ))}
      </AnimatePresence>

      {/* Active layer (clicked highlights) - prominent with glow */}
      {activeHighlights.map((highlight) => {
        const isActive = effectiveActiveHighlightId !== null;
        const isPulsing = pulseHighlightId === highlight.id;

        return (
          <motion.div
            key={`active-${highlight.id}`}
            className="absolute bg-blue-500/30 border-2 border-blue-500 rounded-md pointer-events-auto cursor-pointer z-10"
            style={{
              left: highlight.x,
              top: highlight.y,
              width: highlight.width,
              height: highlight.height,
            }}
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ 
              opacity: 1, 
              scale: 1,
            }}
            transition={{ duration: 0.3 }}
            onClick={() => handleHighlightClick(highlight)}
            whileHover={{ opacity: 0.9 }}
          >
            {/* Pulse animation for clicked highlight */}
            <AnimatePresence>
              {isPulsing && (
                <motion.div
                  className="absolute -inset-1 bg-blue-500/50 rounded-lg pointer-events-none"
                  initial={{ opacity: 0, scale: 1 }}
                  animate={{ 
                    opacity: [0, 0.8, 0],
                    scale: [1, 1.1, 1],
                  }}
                  exit={{ opacity: 0 }}
                  transition={{
                    duration: 1,
                    ease: "easeOut",
                  }}
                />
              )}
            </AnimatePresence>

            {/* Glow effect for active highlight */}
            <AnimatePresence>
              {isActive && (
                <motion.div
                  className="absolute -inset-2 bg-blue-500/40 rounded-lg blur-md pointer-events-none"
                  initial={{ opacity: 0 }}
                  animate={{
                    opacity: [0.5, 0.8, 0.5],
                  }}
                  exit={{ opacity: 0 }}
                  transition={{
                    duration: 1.5,
                    repeat: Infinity,
                    ease: "easeInOut",
                  }}
                />
              )}
            </AnimatePresence>
          </motion.div>
        );
      })}
    </div>
  );
}
