import { cn } from "@/lib/utils";
import { motion } from "framer-motion";
import { Sparkles, Tag } from "lucide-react";
import { useState } from "react";

interface TemplateField {
  key: string;
  value: string;
  word_indexes: number[];
  confidence?: number;
}

interface TemplateFieldsPanelProps {
  fields?: TemplateField[];
  onFieldClick?: (wordIndexes: number[]) => void;
  onFieldHover?: (wordIndexes: number[] | null) => void;
}

export function TemplateFieldsPanel({
  fields = [],
  onFieldClick,
  onFieldHover,
}: TemplateFieldsPanelProps) {
  const [hoveredField, setHoveredField] = useState<string | null>(null);

  const getConfidenceColor = (confidence?: number) => {
    if (!confidence) return "text-muted-foreground";
    if (confidence >= 0.9) return "text-green-400";
    if (confidence >= 0.7) return "text-yellow-400";
    return "text-orange-400";
  };

  const handleFieldClick = (field: TemplateField) => {
    if (onFieldClick && field.word_indexes.length > 0) {
      onFieldClick(field.word_indexes);
    }
  };

  const handleFieldHover = (field: TemplateField | null) => {
    if (field) {
      setHoveredField(field.key);
      if (onFieldHover && field.word_indexes.length > 0) {
        onFieldHover(field.word_indexes);
      }
    } else {
      setHoveredField(null);
      if (onFieldHover) {
        onFieldHover(null);
      }
    }
  };

  if (fields.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-16 text-center text-muted-foreground">
        <Tag className="w-8 h-8 mb-2 opacity-50" />
        <p className="text-sm">No template fields extracted yet</p>
        <p className="text-xs mt-1">Define a template and extract fields to see results here</p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      {fields.map((field, index) => {
        const isHovered = hoveredField === field.key;
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
              "p-4 rounded-xl glass cursor-pointer transition-all duration-200 relative",
              "hover:bg-[hsl(var(--glass-bg)/0.8)] hover:border-primary/30",
              isHovered && "shadow-lg shadow-primary/10 border-primary/50"
            )}
            onMouseEnter={() => handleFieldHover(field)}
            onMouseLeave={() => handleFieldHover(null)}
            onClick={() => handleFieldClick(field)}
          >
            {/* Subtle hover animation glow */}
            <motion.div
              className="absolute inset-0 rounded-xl bg-primary/5 pointer-events-none"
              initial={{ opacity: 0 }}
              animate={{ opacity: isHovered ? 1 : 0 }}
              transition={{ duration: 0.2 }}
            />

            <div className="relative flex items-start justify-between gap-2 mb-2">
              <div className="flex items-center gap-2">
                <Tag className="w-3.5 h-3.5 text-primary" />
                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  {field.key}
                </span>
              </div>
              {field.confidence !== undefined && (
                <div className={cn("flex items-center gap-1 text-xs", getConfidenceColor(field.confidence))}>
                  <Sparkles className="w-3 h-3" />
                  {Math.round(field.confidence * 100)}%
                </div>
              )}
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
