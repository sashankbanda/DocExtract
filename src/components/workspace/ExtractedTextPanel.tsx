import { cn } from "@/lib/utils";
import { UploadedDocumentResult } from "@/types/document";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, ChevronRight, FileText } from "lucide-react";
import { useRef, useState, useMemo } from "react";

interface ExtractedTextPanelProps {
  document?: UploadedDocumentResult | null;
  onLineClick?: (lineIndexes: number[]) => void;
  onLineHover?: (lineIndexes: number[] | null) => void;
  isLoading?: boolean;
}

interface PageSection {
  pageNumber: number;
  lines: Array<{
    text: string;
    lineNumber: number;
  }>;
}

export function ExtractedTextPanel({
  document,
  onLineClick,
  onLineHover,
  isLoading = false,
}: ExtractedTextPanelProps) {
  const [expandedPages, setExpandedPages] = useState<Set<number>>(new Set([1]));
  const scrollContainerRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  
  const isActuallyLoading = isLoading || !document || !document.text;

  const pageSections = useMemo<PageSection[]>(() => {
    if (!document?.text) return [];

    const textLines = document.text.split("\n");
    const lineMetadata = Array.isArray((document.boundingBoxes as any)?.line_metadata)
      ? ((document.boundingBoxes as any).line_metadata as any[])
      : [];

    if (lineMetadata.length === 0) {
      // Fallback: single page with sequential line numbers
      return [
        {
          pageNumber: 1,
          lines: textLines
            .filter((line) => line.trim() !== "")
            .map((line, idx) => ({
              text: line,
              lineNumber: idx + 1,
            })),
        },
      ];
    }

    const grouped = new Map<number, PageSection>();

    lineMetadata.forEach((entry: any, idx: number) => {
      if (!entry || typeof entry !== "object") return;
      const pageNumber = Number(entry.page ?? 1);
      const lineNumber = Number(entry.line_number ?? entry.line_no ?? entry.line ?? idx + 1);
      const text =
        typeof entry.text === "string"
          ? entry.text
          : textLines[lineNumber - 1] ?? "";

      if (!grouped.has(pageNumber)) {
        grouped.set(pageNumber, { pageNumber, lines: [] });
      }

      grouped.get(pageNumber)!.lines.push({
        text,
        lineNumber,
      });
    });

    return Array.from(grouped.values()).map((section) => ({
      ...section,
      lines: section.lines.filter((line) => line.text.trim() !== ""),
    }));
  }, [document]);

  const togglePage = (pageNumber: number) => {
    setExpandedPages((prev) => {
      const next = new Set(prev);
      if (next.has(pageNumber)) {
        next.delete(pageNumber);
      } else {
        next.add(pageNumber);
      }
      return next;
    });
  };

  const handleLineClick = (lineNumber: number, pageNumber: number, lineElement?: HTMLElement) => {
    if (onLineClick) {
      onLineClick([lineNumber]);
    }

    if (lineElement) {
      const container = scrollContainerRefs.current.get(pageNumber);
      if (container) {
        const containerRect = container.getBoundingClientRect();
        const lineRect = lineElement.getBoundingClientRect();
        
        if (lineRect.left < containerRect.left || lineRect.right > containerRect.right) {
          const scrollLeft = lineElement.offsetLeft - 100;
          container.scrollTo({
            left: Math.max(0, scrollLeft),
            behavior: "smooth",
          });
        }
      }
    }
  };

  const handleLineHover = (lineNumber: number | null) => {
    if (onLineHover) {
      onLineHover(lineNumber ? [lineNumber] : null);
    }
  };

  if (isActuallyLoading) {
    return (
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="glass rounded-xl overflow-hidden"
      >
        <div className="flex items-center gap-2 px-4 py-3 border-b border-border/50">
          <FileText className="w-4 h-4 text-primary" />
          <span className="text-sm font-medium text-foreground">Extracted Text</span>
        </div>
        <div className="p-4 space-y-2">
          {Array.from({ length: 10 }).map((_, i) => (
            <SkeletonLine key={i} />
          ))}
        </div>
      </motion.div>
    );
  }

  if (!document || pageSections.length === 0) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col items-center justify-center gap-2 py-16 text-center text-muted-foreground"
      >
        <p className="text-sm">No text content available</p>
      </motion.div>
    );
  }

  return (
    <div className="space-y-2">
      {pageSections.map((section) => {
        const isExpanded = expandedPages.has(section.pageNumber);
        return (
          <motion.div
            key={section.pageNumber}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="glass rounded-xl overflow-hidden"
          >
            {/* Page Header - Collapsible */}
            <button
              onClick={() => togglePage(section.pageNumber)}
              className="w-full flex items-center justify-between px-4 py-3 hover:bg-muted/30 transition-colors"
            >
              <div className="flex items-center gap-2">
                {isExpanded ? (
                  <ChevronDown className="w-4 h-4 text-muted-foreground" />
                ) : (
                  <ChevronRight className="w-4 h-4 text-muted-foreground" />
                )}
                <FileText className="w-4 h-4 text-primary" />
                <span className="text-sm font-medium text-foreground">
                  Page {section.pageNumber}
                </span>
                <span className="text-xs text-muted-foreground">
                  ({section.lines.length} line{section.lines.length !== 1 ? "s" : ""})
                </span>
              </div>
            </button>

            {/* Page Content */}
            <AnimatePresence>
              {isExpanded && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.2 }}
                  className="overflow-hidden"
                >
                  <div
                    ref={(el) => {
                      if (el) {
                        scrollContainerRefs.current.set(section.pageNumber, el);
                      } else {
                        scrollContainerRefs.current.delete(section.pageNumber);
                      }
                    }}
                    className="w-full overflow-x-auto overflow-y-auto max-h-[600px]"
                  >
                    <pre
                      className="whitespace-pre font-mono text-sm leading-relaxed text-foreground p-4 m-0"
                      style={{
                        whiteSpace: "pre",
                        wordWrap: "normal",
                        overflowWrap: "normal",
                        wordBreak: "keep-all",
                      }}
                    >
                      {section.lines.map((line, lineIndex) => (
                        <span
                          key={lineIndex}
                          className={cn(
                            "block cursor-pointer transition-all duration-200",
                            "hover:bg-primary/10"
                          )}
                          onMouseEnter={() => handleLineHover(line.lineNumber)}
                          onMouseLeave={() => handleLineHover(null)}
                          onClick={(e) => {
                            const target = e.currentTarget;
                            handleLineClick(line.lineNumber, section.pageNumber, target);
                          }}
                          style={{
                            whiteSpace: "pre",
                            wordWrap: "normal",
                            overflowWrap: "normal",
                            wordBreak: "keep-all",
                          }}
                        >
                          {line.text}
                          {"\n"}
                        </span>
                      ))}
                    </pre>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        );
      })}
    </div>
  );
}
