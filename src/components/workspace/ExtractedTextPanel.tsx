import { cn } from "@/lib/utils";
import { BoundingBox, LayoutText, UploadedDocumentResult } from "@/types/document";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, ChevronRight, FileText } from "lucide-react";
import { useState, useMemo } from "react";

interface ExtractedTextPanelProps {
  document?: UploadedDocumentResult | null;
  onLineClick?: (wordIndexes: number[]) => void;
  onLineHover?: (wordIndexes: number[] | null) => void;
  isLoading?: boolean;
}

interface PageSection {
  pageNumber: number;
  lines: Array<{
    text: string;
    wordIndexes: number[];
    boundingBox?: BoundingBox;
  }>;
}

export function ExtractedTextPanel({
  document,
  onLineClick,
  onLineHover,
  isLoading = false,
}: ExtractedTextPanelProps) {
  const [expandedPages, setExpandedPages] = useState<Set<number>>(new Set([1]));
  
  // Determine loading state based on document availability
  const isActuallyLoading = isLoading || !document || !document.text;

  // Parse text into pages and lines with word indexes
  const pageSections = useMemo<PageSection[]>(() => {
    if (!document?.text) return [];

    const pages = document.pages as any[] | null;
    const boundingBoxes = document.boundingBoxes as Record<string, unknown> | null;

    // Build word index lookup from bounding boxes
    const wordIndexLookup = new Map<number, { text: string; page: number }>();
    if (boundingBoxes) {
      const words = (boundingBoxes.words as any[]) || [];
      const pagesData = (boundingBoxes.pages as any[]) || [];

      words.forEach((word: any) => {
        if (word?.index !== undefined) {
          wordIndexLookup.set(word.index, {
            text: word.text || "",
            page: word.page || 1,
          });
        }
      });

      pagesData.forEach((page: any) => {
        const pageNum = page.page ?? page.index ?? 1;
        (page.words || []).forEach((word: any) => {
          if (word?.index !== undefined) {
            wordIndexLookup.set(word.index, {
              text: word.text || "",
              page: pageNum,
            });
          }
        });
      });
    }

    // Split text by pages if available, otherwise treat as single page
    const sections: PageSection[] = [];
    
    if (pages && pages.length > 0) {
      // Group by pages
      const pagesMap = new Map<number, string[]>();
      const textLines = document.text.split("\n");

      // Try to map lines to pages based on word indexes
      let currentPage = 1;
      textLines.forEach((line, lineIndex) => {
        // Simple heuristic: if we have page metadata, use it
        const pageInfo = pages.find((p: any) => {
          const pageNum = p.page ?? p.index ?? 1;
          return pageNum === currentPage;
        });
        
        if (!pagesMap.has(currentPage)) {
          pagesMap.set(currentPage, []);
        }
        pagesMap.get(currentPage)!.push(line);

        // Try to detect page breaks (empty lines or page markers)
        if (line.trim() === "" && lineIndex > 0 && lineIndex < textLines.length - 1) {
          currentPage++;
        }
      });

      // Create sections for each page
      pagesMap.forEach((lines, pageNum) => {
        const pageLines = lines
          .map((line, idx) => {
            // Extract word indexes for this line (simplified - would need better parsing)
            const wordIndexes: number[] = [];
            const words = line.split(/\s+/);
            let wordIdx = 0;
            words.forEach((word) => {
              // Try to find matching word index
              for (const [index, data] of wordIndexLookup.entries()) {
                if (data.text === word && data.page === pageNum) {
                  wordIndexes.push(index);
                  break;
                }
              }
              wordIdx++;
            });

            return {
              text: line,
              wordIndexes,
            };
          })
          .filter((line) => line.text.trim() !== "");

        if (pageLines.length > 0) {
          sections.push({
            pageNumber: pageNum,
            lines: pageLines,
          });
        }
      });
    } else {
      // Single page - split by lines
      const lines = document.text.split("\n").filter((line) => line.trim() !== "");
      sections.push({
        pageNumber: 1,
        lines: lines.map((line) => ({
          text: line,
          wordIndexes: [], // Would need better parsing for word indexes
        })),
      });
    }

    return sections;
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

  const handleLineClick = (wordIndexes: number[]) => {
    if (onLineClick && wordIndexes.length > 0) {
      onLineClick(wordIndexes);
    }
  };

  const handleLineHover = (wordIndexes: number[] | null) => {
    if (onLineHover) {
      onLineHover(wordIndexes);
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
                  <div className="px-4 pb-4 space-y-1">
                    {section.lines.map((line, lineIndex) => (
                      <motion.div
                        key={lineIndex}
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: lineIndex * 0.02 }}
                        className={cn(
                          "px-3 py-2 rounded-lg cursor-pointer transition-all duration-200",
                          "hover:bg-primary/10 hover:border-l-2 hover:border-l-primary",
                          line.wordIndexes.length > 0 && "border-l-2 border-l-transparent"
                        )}
                        onMouseEnter={() => handleLineHover(line.wordIndexes)}
                        onMouseLeave={() => handleLineHover(null)}
                        onClick={() => handleLineClick(line.wordIndexes)}
                      >
                        <p className="text-sm text-foreground leading-relaxed whitespace-pre-wrap">
                          {line.text}
                        </p>
                      </motion.div>
                    ))}
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
