import { motion, AnimatePresence } from "framer-motion";
import { BoundingBox } from "@/types/document";
import { useMemo } from "react";

interface HighlightOverlayProps {
  boundingBoxes?: Record<string, unknown> | null;
  selectedLineIndexes?: number[];
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
  scale?: number;
}

interface LineHighlight {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  page: number;
}

export function HighlightOverlay({
  boundingBoxes,
  selectedLineIndexes = [],
  currentScale = 1,
  pageMetadata = [],
  activeHighlightId = null,
  pagesLoaded = true,
  highlights,
  activeHighlight,
  scale = 1,
}: HighlightOverlayProps) {
  const pageOffsets = useMemo(() => {
    if (!pageMetadata.length) return [];
    const offsets: number[] = [0];
    let currentOffset = 0;
    for (let i = 0; i < pageMetadata.length; i++) {
      currentOffset += pageMetadata[i].height + 16; // match PDF viewer margin
      offsets.push(currentOffset);
    }
    return offsets;
  }, [pageMetadata]);

  const positionedHighlights = useMemo<LineHighlight[]>(() => {
    // Legacy path
    if (!boundingBoxes) {
      return (highlights || []).map((h, idx) => ({
        id: `legacy-${idx}`,
        x: h.x * scale,
        y: h.y * scale,
        width: h.width * scale,
        height: h.height * scale,
        page: h.page || 1,
      }));
    }

    const lines = ((boundingBoxes as any).line_metadata || (boundingBoxes as any).lines || []) as any[];
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
  }, [boundingBoxes, selectedLineIndexes, pageMetadata, pageOffsets, currentScale, highlights, scale]);

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
    <div className="absolute inset-0 pointer-events-none overflow-hidden">
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
