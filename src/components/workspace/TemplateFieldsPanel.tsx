import { StructuredFieldData } from "@/types/document";
import { cn } from "@/lib/utils";
import { motion } from "framer-motion";
import { Tag } from "lucide-react";
import { useState } from "react";

interface TemplateFieldsPanelProps {
  structuredFields?: Record<string, StructuredFieldData>;
  onFieldClick?: (wordIndexes: number[]) => void;
  onFieldHover?: (wordIndexes: number[] | null) => void;
}

export function TemplateFieldsPanel({
  structuredFields,
  onFieldClick,
  onFieldHover,
}: TemplateFieldsPanelProps) {
  const [hoveredField, setHoveredField] = useState<string | null>(null);

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

  // Convert structuredFields object to array of entries
  const fields = structuredFields
    ? Object.entries(structuredFields)
        .map(([key, data]) => ({
          key,
          value: data.value || "",
          word_indexes: data.word_indexes || [],
        }))
        .filter((field) => field.value !== null && field.value !== "")
    : [];

  if (fields.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-16 text-center text-muted-foreground">
        <Tag className="w-8 h-8 mb-2 opacity-50" />
        <p className="text-sm">No template fields extracted yet</p>
        <p className="text-xs mt-1">Fields will appear here after extraction</p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      {fields.map((field, index) => {
        const isHovered = hoveredField === field.key;
        const hasWordIndexes = field.word_indexes.length > 0;
        return (
          <motion.div
            key={`${field.key}-${index}`}
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ 
              opacity: 1, 
              scale: 1,
              y: isHovered ? -2 : 0,
            }}
            transition={{ 
              delay: index * 0.05,
              duration: 0.2,
            }}
            className={cn(
              "p-4 rounded-xl glass transition-all duration-200 relative",
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
    </div>
  );
}
