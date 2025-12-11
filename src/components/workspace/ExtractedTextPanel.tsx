import { cn } from "@/lib/utils";
import { BoundingBox, LayoutText, UploadedDocumentResult } from "@/types/document";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, ChevronRight, FileText } from "lucide-react";
import { useRef, useState, useMemo } from "react";

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
  const scrollContainerRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  
  // Determine loading state based on document availability
  const isActuallyLoading = isLoading || !document || !document.text;

  // Parse text into pages and lines with word indexes
  const pageSections = useMemo<PageSection[]>(() => {
    if (!document?.text) return [];

    const pages = document.pages as any[] | null;
    const boundingBoxes = document.boundingBoxes as Record<string, unknown> | null;

    // Build word index to text mapping from tokenized text
    // The backend tokenizes text by splitting on whitespace, so we do the same
    const tokenizedText = document.text.split(/\s+/).filter(w => w.trim() !== "");
    const wordIndexToText = new Map<number, string>();
    tokenizedText.forEach((word, index) => {
      wordIndexToText.set(index, word);
    });
    
    // Build word index to page mapping from bounding boxes
    const wordIndexToPage = new Map<number, number>();
    if (boundingBoxes) {
      const words = (boundingBoxes.words as any[]) || [];
      const pagesData = (boundingBoxes.pages as any[]) || [];

      words.forEach((word: any) => {
        if (word?.index !== undefined) {
          wordIndexToPage.set(word.index, word.page || 1);
        }
      });

      pagesData.forEach((page: any) => {
        const pageNum = page.page ?? page.index ?? 1;
        (page.words || []).forEach((word: any) => {
          if (word?.index !== undefined) {
            wordIndexToPage.set(word.index, pageNum);
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
      // Map lines to word indexes by matching words in tokenized text
      let globalWordIndex = 0;
      pagesMap.forEach((lines, pageNum) => {
        const pageLines = lines
          .map((line) => {
            // Extract word indexes for this line by matching words sequentially
            const wordIndexes: number[] = [];
            const lineWords = line.split(/\s+/).filter(w => w.trim() !== "");
            
            // Match words starting from current global word index
            let searchStartIndex = globalWordIndex;
            for (const lineWord of lineWords) {
              // Find matching word in tokenized text starting from searchStartIndex
              let found = false;
              for (let i = searchStartIndex; i < tokenizedText.length; i++) {
                // Normalize for comparison (remove punctuation)
                const normalizedLineWord = lineWord.replace(/[^\w\s]/g, '').toLowerCase();
                const normalizedTokenWord = tokenizedText[i].replace(/[^\w\s]/g, '').toLowerCase();
                
                if (normalizedLineWord === normalizedTokenWord || 
                    tokenizedText[i].includes(lineWord) || 
                    lineWord.includes(tokenizedText[i])) {
                  // Check if this word belongs to the correct page
                  const wordPage = wordIndexToPage.get(i) || 1;
                  if (wordPage === pageNum || wordIndexToPage.size === 0) {
                    wordIndexes.push(i);
                    searchStartIndex = i + 1;
                    found = true;
                    break;
                  }
                }
              }
              if (!found) {
                // If not found, increment search index anyway to avoid infinite loop
                searchStartIndex++;
              }
            }
            
            globalWordIndex = searchStartIndex;

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
      // Map lines to word indexes by matching words in tokenized text
      const lines = document.text.split("\n").filter((line) => line.trim() !== "");
      let globalWordIndex = 0;
      const pageLines = lines.map((line) => {
        const wordIndexes: number[] = [];
        const lineWords = line.split(/\s+/).filter(w => w.trim() !== "");
        
        // Match words sequentially
        let searchStartIndex = globalWordIndex;
        for (const lineWord of lineWords) {
          for (let i = searchStartIndex; i < tokenizedText.length; i++) {
            const normalizedLineWord = lineWord.replace(/[^\w\s]/g, '').toLowerCase();
            const normalizedTokenWord = tokenizedText[i].replace(/[^\w\s]/g, '').toLowerCase();
            
            if (normalizedLineWord === normalizedTokenWord || 
                tokenizedText[i].includes(lineWord) || 
                lineWord.includes(tokenizedText[i])) {
              wordIndexes.push(i);
              searchStartIndex = i + 1;
              break;
            }
          }
        }
        globalWordIndex = searchStartIndex;
        
        return {
          text: line,
          wordIndexes,
        };
      });
      
      sections.push({
        pageNumber: 1,
        lines: pageLines,
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

  const handleLineClick = (wordIndexes: number[], pageNumber: number, lineElement?: HTMLElement) => {
    if (onLineClick && wordIndexes.length > 0) {
      onLineClick(wordIndexes);
    }

    // Scroll to the clicked line if it's off-screen
    if (lineElement) {
      const container = scrollContainerRefs.current.get(pageNumber);
      if (container) {
        const containerRect = container.getBoundingClientRect();
        const lineRect = lineElement.getBoundingClientRect();
        
        // Check if line is outside the visible area
        if (lineRect.left < containerRect.left || lineRect.right > containerRect.right) {
          const scrollLeft = lineElement.offsetLeft - 100; // 100px offset from left
          container.scrollTo({
            left: Math.max(0, scrollLeft),
            behavior: "smooth",
          });
        }
      }
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
                      {section.lines.map((line, lineIndex) => {
                        const hasWordIndexes = line.wordIndexes.length > 0;
                        return (
                          <span
                            key={lineIndex}
                            className={cn(
                              "block cursor-pointer transition-all duration-200",
                              "hover:bg-primary/10",
                              hasWordIndexes && "hover:bg-primary/15"
                            )}
                            onMouseEnter={() => handleLineHover(line.wordIndexes)}
                            onMouseLeave={() => handleLineHover(null)}
                            onClick={(e) => {
                              const target = e.currentTarget;
                              handleLineClick(line.wordIndexes, section.pageNumber, target);
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
                        );
                      })}
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
