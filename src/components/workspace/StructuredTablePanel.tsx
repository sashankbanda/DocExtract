import { StructuredFieldData } from "@/types/document";
import { cn } from "@/lib/utils";
import { AnimatePresence, motion } from "framer-motion";
import { Table } from "lucide-react";
import { useEffect, useState } from "react";

interface StructuredTablePanelProps {
  structuredFields?: Record<string, StructuredFieldData>;
  onFieldClick?: (wordIndexes: number[]) => void;
  onFieldHover?: (wordIndexes: number[] | null) => void;
  isLoading?: boolean;
}

function SkeletonRow() {
  return (
    <tr className="border-t border-border/30">
      <td className="px-4 py-3">
        <div className="h-4 bg-muted/50 rounded animate-pulse w-24" />
      </td>
      <td className="px-4 py-3">
        <div className="h-4 bg-muted/50 rounded animate-pulse w-48" />
      </td>
    </tr>
  );
}

export function StructuredTablePanel({
  structuredFields,
  onFieldClick,
  onFieldHover,
  isLoading = false,
}: StructuredTablePanelProps) {
  const [isAnimating, setIsAnimating] = useState(false);
  const handleRowClick = (wordIndexes: number[]) => {
    if (onFieldClick && wordIndexes.length > 0) {
      onFieldClick(wordIndexes);
    }
  };

  const handleRowHover = (wordIndexes: number[] | null) => {
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
        className="glass rounded-xl overflow-hidden"
      >
        <div className="flex items-center gap-2 px-4 py-3 border-b border-border/50">
          <Table className="w-4 h-4 text-primary" />
          <span className="text-sm font-medium text-foreground">Structured Fields</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-muted/30">
                <th className="px-4 py-3 text-left font-medium text-muted-foreground">Field</th>
                <th className="px-4 py-3 text-left font-medium text-muted-foreground">Value</th>
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: 5 }).map((_, i) => (
                <SkeletonRow key={i} />
              ))}
            </tbody>
          </table>
        </div>
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
        <Table className="w-8 h-8 mb-2 opacity-50" />
        <p className="text-sm">No structured fields extracted yet</p>
        <p className="text-xs mt-1">Fields will appear here after extraction</p>
      </motion.div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="glass rounded-xl overflow-hidden"
    >
      <div className="flex items-center gap-2 px-4 py-3 border-b border-border/50">
        <Table className="w-4 h-4 text-primary" />
        <span className="text-sm font-medium text-foreground">
          Structured Fields
        </span>
        <span className="text-xs text-muted-foreground">
          ({fields.length} field{fields.length !== 1 ? "s" : ""})
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-muted/30">
              <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                Field
              </th>
              <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                Value
              </th>
            </tr>
          </thead>
          <tbody>
            <AnimatePresence mode="popLayout">
              {fields.map((field, index) => (
                <motion.tr
                  key={`${field.key}-${index}`}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -10 }}
                  transition={{ delay: index * 0.03, duration: 0.2 }}
                  className={cn(
                    "border-t border-border/30 transition-all duration-200",
                    field.word_indexes.length > 0 && "hover:bg-primary/10 hover:border-primary/30 cursor-pointer"
                  )}
                  onMouseEnter={() => handleRowHover(field.word_indexes)}
                  onMouseLeave={() => handleRowHover(null)}
                  onClick={() => handleRowClick(field.word_indexes)}
                >
                  <td className="px-4 py-3 font-medium text-foreground">
                    {field.key}
                  </td>
                  <td className="px-4 py-3 text-foreground">
                    {field.value}
                  </td>
                </motion.tr>
              ))}
            </AnimatePresence>
          </tbody>
        </table>
      </div>
    </motion.div>
  );
}
