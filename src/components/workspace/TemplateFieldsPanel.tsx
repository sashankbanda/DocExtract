import { StructuredFieldData } from "@/types/document";
import { cn } from "@/lib/utils";
import { AnimatePresence, motion } from "framer-motion";
import { Tag } from "lucide-react";
import { useEffect, useState } from "react";

interface TemplateFieldsPanelProps {
  structuredFields?: Record<string, StructuredFieldData>;
  onFieldClick?: (wordIndexes: number[]) => void;
  onFieldHover?: (wordIndexes: number[] | null) => void;
  isLoading?: boolean;
}

function SkeletonCard() {
  return (
    <div className="p-4 rounded-xl glass animate-pulse">
      <div className="flex items-center gap-2 mb-2">
        <div className="w-3.5 h-3.5 bg-muted/50 rounded" />
        <div className="h-3 bg-muted/50 rounded w-20" />
      </div>
      <div className="h-4 bg-muted/50 rounded w-32" />
    </div>
  );
}

export function TemplateFieldsPanel({
  structuredFields,
  onFieldClick,
  onFieldHover,
  isLoading = false,
}: TemplateFieldsPanelProps) {
  const [hoveredField, setHoveredField] = useState<string | null>(null);
  const [isAnimating, setIsAnimating] = useState(false);

  const handleFieldClick = (key: string, wordIndexes: number[]) => {
    if (onFieldClick && wordIndexes.length > 0) {
      onFieldClick(wordIndexes);
    }
  };

  const handleFieldHover = (key: string | null, wordIndexes: number[] | null) => {
    setHoveredField(key);
    if (onFieldHover) {
      onFieldHover(wordIndexes);
    }
  };

  // Reset animation when structuredFields change
  useEffect(() => {
    if (structuredFields) {
      setIsAnimating(true);
      const timer = setTimeout(() => setIsAnimating(false), 300);
      return () => clearTimeout(timer);
    }
  }, [structuredFields]);

  // Convert structuredFields object to array of entries
  // Use word_indexes for highlighting (backend generates word-level boxes)
  const fields = structuredFields
    ? Object.entries(structuredFields)
        .map(([key, data]) => ({
          key,
          value: data.value || "",
          word_indexes: data.word_indexes || [],
        }))
        .filter((field) => field.value !== null && field.value !== "")
    : [];

  if (isLoading) {
    return (
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="grid grid-cols-1 sm:grid-cols-2 gap-3"
      >
        {Array.from({ length: 6 }).map((_, i) => (
          <SkeletonCard key={i} />
        ))}
      </motion.div>
    );
  }

  if (fields.length === 0) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col items-center justify-center gap-2 py-16 text-center text-muted-foreground"
      >
        <Tag className="w-8 h-8 mb-2 opacity-50" />
        <p className="text-sm">No template fields extracted yet</p>
        <p className="text-xs mt-1">Fields will appear here after extraction</p>
      </motion.div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2 }}
      className="grid grid-cols-1 sm:grid-cols-2 gap-3"
    >
      <AnimatePresence mode="popLayout">
        {fields.map((field, index) => {
          const isHovered = hoveredField === field.key;
          const hasWordIndexes = field.word_indexes.length > 0;
          return (
            <motion.div
              key={`${field.key}-${index}`}
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ 
                opacity: 1, 
                scale: 1,
                y: isHovered ? -2 : 0,
              }}
              exit={{ opacity: 0, scale: 0.95 }}
              transition={{ 
                delay: index * 0.03,
                duration: 0.2,
              }}
              className={cn(
                "p-4 rounded-xl glass transition-all duration-200 relative border border-transparent",
                hasWordIndexes && "cursor-pointer hover:bg-[hsl(var(--glass-bg)/0.8)] hover:border-primary/30",
                isHovered && hasWordIndexes && "shadow-lg shadow-primary/10 border-primary/50"
              )}
              onMouseEnter={() => handleFieldHover(field.key, field.word_indexes)}
              onMouseLeave={() => handleFieldHover(null, null)}
              onClick={() => handleFieldClick(field.key, field.word_indexes)}
            >
              {/* Subtle hover animation glow */}
              {hasWordIndexes && (
                <motion.div
                  className="absolute inset-0 rounded-xl bg-primary/5 pointer-events-none"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: isHovered ? 1 : 0 }}
                  transition={{ duration: 0.2 }}
                />
              )}

              <div className="relative flex items-start justify-between gap-2 mb-2">
                <div className="flex items-center gap-2">
                  <Tag className="w-3.5 h-3.5 text-primary" />
                  <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                    {field.key}
                  </span>
                </div>
              </div>
              <p className="text-sm font-medium text-foreground relative">
                {field.value}
              </p>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </motion.div>
  );
}
