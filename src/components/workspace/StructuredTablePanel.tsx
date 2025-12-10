import { StructuredFieldData } from "@/types/document";
import { cn } from "@/lib/utils";
import { motion } from "framer-motion";
import { Table } from "lucide-react";

interface StructuredTablePanelProps {
  structuredFields?: Record<string, StructuredFieldData>;
  onFieldClick?: (wordIndexes: number[]) => void;
  onFieldHover?: (wordIndexes: number[] | null) => void;
}

export function StructuredTablePanel({
  structuredFields,
  onFieldClick,
  onFieldHover,
}: StructuredTablePanelProps) {
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
        <Table className="w-8 h-8 mb-2 opacity-50" />
        <p className="text-sm">No structured fields extracted yet</p>
        <p className="text-xs mt-1">Fields will appear here after extraction</p>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
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
            {fields.map((field, index) => (
              <motion.tr
                key={`${field.key}-${index}`}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: index * 0.05 }}
                className={cn(
                  "border-t border-border/30 transition-colors",
                  field.word_indexes.length > 0 && "hover:bg-primary/10 cursor-pointer"
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
          </tbody>
        </table>
      </div>
    </motion.div>
  );
}
