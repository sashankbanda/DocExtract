import { BoundingBox, Citation } from "@/types/document";
import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

interface HighlightOverlayProps {
  boundingBoxes?: Record<string, unknown> | null;
  selectedLineIndexes?: number[];
  citations?: Citation[]; // New prop for robust highlights
  currentScale?: number;
  pageMetadata?: Array<{
    pageNumber: number;
    width: number;
    height: number;
    viewport: { width: number; height: number };
    scale: number;
  }>;
  activeHighlightId?: string | null;
  pagesLoaded?: boolean;
  highlights?: BoundingBox[];
  activeHighlight?: BoundingBox | null;
  scale?: number; // Keep scale prop for now, as it's used in legacyActiveHighlights
  isDebugMode?: boolean; // New prop
}

interface LineHighlight {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  page: number;
  text?: string; // For debug tooltip
  lineIndex?: number; // For debug tooltip
}

export function HighlightOverlay({
  boundingBoxes,
  selectedLineIndexes = [],
  citations = [],
  currentScale = 1,
  pageMetadata = [],
  activeHighlightId = null,
  pagesLoaded = true,
  highlights, // This prop is not used in the new rendering logic, but kept for compatibility
  activeHighlight, // This prop is not used in the new rendering logic, but kept for compatibility
  scale: propScale = 1, // Renamed to propScale to avoid conflict with internal state
  isDebugMode = false, // Default to false
}: HighlightOverlayProps) {
  const [scale, setScale] = useState(propScale); // Internal scale state
  const containerRef = useRef<HTMLDivElement>(null);

  // Update internal scale when propScale changes
  useEffect(() => {
    setScale(propScale);
  }, [propScale]);

  // This effect is typically used to adjust scale based on container width,
  // but the provided snippet doesn't include the logic for it.
  // Keeping it here as a placeholder if it was intended to be used.
  useEffect(() => {
    // Example: if (containerRef.current) { setScale(containerRef.current.offsetWidth / originalWidth); }
  }, [containerRef]);

  const getPageOffsets = useCallback(() => {
    if (!pageMetadata.length) return [];
    const offsets: number[] = [0];
    let currentOffset = 0;
    for (let i = 0; i < pageMetadata.length; i++) {
      currentOffset += pageMetadata[i].height + 16; // match PDF viewer margin
      offsets.push(currentOffset);
    }
    return offsets;
  }, [pageMetadata]);

  const pageOffsets = useMemo(() => getPageOffsets(), [getPageOffsets]);

  const positionedHighlights = useMemo<LineHighlight[]>(() => {
    // Priority 1: Use citations if available (Robust path)
    if (citations && citations.length > 0) {
      const boxes: LineHighlight[] = [];
      
      citations.forEach((citation, idx) => {
        const page = citation.page;
        const pageMeta = pageMetadata[page - 1];
        if (!pageMeta) return;

        const rawBox = citation.bbox;
        if (!Array.isArray(rawBox) || rawBox.length < 4) return;

        const baseY = Number(rawBox[1]);
        const rawHeight = Number(rawBox[2]);
        const pageHeightSource = Number(rawBox[3]);

        if (!pageHeightSource || rawHeight <= 0) return;

        const scaleFactor = pageMeta.height / pageHeightSource;
        const pageOffset = pageOffsets[page - 1] || 0;
        const yHtml = pageHeightSource - (baseY + rawHeight);

        boxes.push({
          id: `cit-${idx}`,
          page,
          x: 0, 
          y: yHtml * scaleFactor + pageOffset,
          width: pageMeta.width,
          height: rawHeight * scaleFactor,
        });
      });
      return boxes;
    }

    const lines = ((boundingBoxes as any)?.line_metadata || (boundingBoxes as any)?.lines || []) as any[];
    if (!Array.isArray(lines) || selectedLineIndexes.length === 0) return [];

    const uniqueIndexes = Array.from(new Set(selectedLineIndexes));
    const boxes: LineHighlight[] = [];

    uniqueIndexes.forEach((lineIdx) => {
      const entry =
        lines.find((item: any) => {
          const ln = item?.line_number ?? item?.line_no ?? item?.line;
          return Number(ln) === Number(lineIdx);
        }) || null;

      const rawBox = entry?.raw_box || entry?.raw || entry?.bbox || entry?.box;
      if (!entry || !Array.isArray(rawBox) || rawBox.length < 4) return;

      const page = Number(entry.page ?? rawBox[0] ?? 1);
      const pageMeta = pageMetadata[page - 1];
      if (!pageMeta) return;

      const baseY = Number(rawBox[1]);
      const rawHeight = Number(rawBox[2]);
      const pageHeightSource = Number(entry.page_height ?? entry.pageHeight ?? rawBox[3] ?? pageMeta.height);

      if (!pageHeightSource || rawHeight <= 0) return;

      const scaleFactor = pageMeta.height / pageHeightSource;
      const pageOffset = pageOffsets[page - 1] || 0;
      const yHtml = pageHeightSource - (baseY + rawHeight);

      boxes.push({
        id: `line-${lineIdx}`,
        page,
        x: 0,
        y: yHtml * scaleFactor + pageOffset,
        width: pageMeta.width,
        height: rawHeight * scaleFactor,
      });
    });

    return boxes;
  }, [boundingBoxes, selectedLineIndexes, pageMetadata, pageOffsets, currentScale, highlights, scale, citations]);

  // Calculate DEBUG highlights (all lines)
  const debugHighlights = useMemo<LineHighlight[]>(() => {
    if (!isDebugMode || !boundingBoxes || !pageMetadata.length) return [];

    const lineMetadata = ((boundingBoxes as any).line_metadata || (boundingBoxes as any).lines || []) as any[];
    const boxes: LineHighlight[] = [];

    lineMetadata.forEach((line, idx) => {
        const page = line.page || 1;
        const pageIndex = page - 1;
        const pageMeta = pageMetadata[pageIndex];
        if (!pageMeta) return;

        const pageOffset = pageOffsets[pageIndex] || 0;

        let rawBox = line.bbox || line.raw_box;
        if (!rawBox || rawBox.length < 4) return;

        // Normalize box
        const [x, y, w, h] = rawBox.map((v: any) => Number(v));
        
        let finalX = x;
        let finalY = y;
        let finalW = w;
        let finalH = h;
        
        const pageHeightSource = line.page_height || line.pageHeight;
        if (pageHeightSource && h > 0) {
             const scaleFactor = pageMeta.height / pageHeightSource;
             finalX = x * scaleFactor;
             finalW = w * scaleFactor;
             finalH = h * scaleFactor;
             
             const baseY = y;
             const rawHeight = h;
             const yHtml = pageHeightSource - (baseY + rawHeight);
             finalY = yHtml * scaleFactor;
        }

        boxes.push({
            id: `debug-${idx}`,
            page,
            x: finalX,
            y: finalY + pageOffset,
            width: finalW,
            height: finalH,
            text: line.text,
            lineIndex: line.line_index ?? idx
        });
    });

    return boxes;
  }, [isDebugMode, boundingBoxes, pageMetadata, pageOffsets]);

  const legacyActiveHighlights = useMemo<LineHighlight[]>(() => {
    if (!activeHighlight) return [];
    return [
      {
        id: "legacy-active",
        x: activeHighlight.x * scale,
        y: activeHighlight.y * scale,
        width: activeHighlight.width * scale,
        height: activeHighlight.height * scale,
        page: activeHighlight.page || 1,
      },
    ];
  }, [activeHighlight, scale]);

  if (!pagesLoaded) {
    return null;
  }

  const previewHighlights = activeHighlightId ? [] : positionedHighlights;
  const activeHighlights = activeHighlightId ? positionedHighlights : legacyActiveHighlights;

  return (
    <div className="absolute inset-0 pointer-events-none overflow-hidden" ref={containerRef}>
      {/* Render Debug Highlights */}
      {isDebugMode && debugHighlights.map((box) => (
        <div
          key={box.id}
          className="absolute border border-red-500/50 bg-red-500/10 hover:bg-red-500/30 transition-colors cursor-help z-50"
          style={{
            left: `${box.x}px`,
            top: `${box.y}px`,
            width: `${box.width}px`,
            height: `${box.height}px`,
            pointerEvents: "auto", // Allow hover
          }}
          title={`Line: ${box.lineIndex}\nPage: ${box.page}\nText: ${box.text}`}
        />
      ))}

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

      {activeHighlights.map((highlight) => (
        <motion.div
          key={`active-${highlight.id}`}
          className="absolute bg-blue-500/30 border-2 border-blue-500 rounded-md pointer-events-none z-10"
          style={{
            left: highlight.x,
            top: highlight.y,
            width: highlight.width,
            height: highlight.height,
          }}
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.3 }}
        />
      ))}
    </div>
  );
}
