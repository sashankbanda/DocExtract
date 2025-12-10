import { GlassButton } from "@/components/ui/GlassButton";
import { GlassCard } from "@/components/ui/GlassCard";
import { toast } from "@/components/ui/use-toast";
import { FileDropzone } from "@/components/upload/FileDropzone";
import { FileListItem } from "@/components/upload/FileListItem";
import { useExtractionContext } from "@/context/ExtractionContext";
import { extractFields, uploadSingleDocument } from "@/lib/api";
import { UploadFile, UploadedDocumentResult } from "@/types/document";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, FileText, Loader2, Upload } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

export default function UploadPage() {
  const navigate = useNavigate();
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const { addDocuments } = useExtractionContext();

  const handleFilesAdded = useCallback((newFiles: File[]) => {
    const uploadFiles: UploadFile[] = newFiles.map((file) => ({
      id: `${file.name}-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      name: file.name,
      size: file.size,
      type: file.type,
      progress: 0,
      status: "pending" as const,
      file,
    }));
    setFiles((prev) => [...prev, ...uploadFiles]);
  }, []);

  const handleRemoveFile = useCallback((id: string) => {
    setFiles((prev) => {
      const file = prev.find((f) => f.id === id);
      // Prevent removing files that are currently uploading or processing
      if (file && (file.status === "uploading" || file.status === "processing")) {
        return prev;
      }
      return prev.filter((f) => f.id !== id);
    });
  }, []);

  const handleUpload = useCallback(async () => {
    const filesToUpload = files.filter((f) => f.status === "pending" && f.file);
    if (filesToUpload.length === 0 || isUploading) return;

    setIsUploading(true);
    const uploadedResults: UploadedDocumentResult[] = [];

    // Upload files sequentially with individual progress tracking
    for (const uploadFile of filesToUpload) {
      if (!uploadFile.file) continue;

      const fileId = uploadFile.id;

      try {
        // Initialize upload state
        setFiles((prev) =>
          prev.map((f) =>
            f.id === fileId
              ? { ...f, status: "uploading", progress: 0, error: undefined }
              : f
          )
        );

        // Upload with progress tracking
        const result = await uploadSingleDocument(uploadFile.file, (progress) => {
          setFiles((prev) =>
            prev.map((f) => {
              if (f.id === fileId) {
                const status = progress < 70 ? "uploading" : progress < 100 ? "processing" : "complete";
                return { ...f, progress, status };
              }
              return f;
            })
          );
        });

        // Update file with result data
        setFiles((prev) =>
          prev.map((f) =>
            f.id === fileId
              ? {
                  ...f,
                  status: "processing",
                  progress: 100,
                  whisperHash: result.whisperHash,
                  extraction: {
                    text: result.text,
                    boundingBoxes: result.boundingBoxes,
                    pages: result.pages,
                  },
                }
              : f
          )
        );

        // Extract structured fields if we have text (bounding boxes are optional)
        let structuredFields: Record<string, { value: string | null; start: number | null; end: number | null; word_indexes: number[] }> = {};
        
        if (result.text) {
          try {
            setFiles((prev) =>
              prev.map((f) =>
                f.id === fileId ? { ...f, status: "processing" } : f
              )
            );

            const structured = await extractFields({
              text: result.text,
              boundingBoxes: result.boundingBoxes || {},
              templateName: "standard_template",
            });

            structuredFields = structured.fields;

            // Update file with structured fields
            setFiles((prev) =>
              prev.map((f) =>
                f.id === fileId
                  ? {
                      ...f,
                      status: "complete",
                      structuredFields: structuredFields,
                    }
                  : f
              )
            );
          } catch (error) {
            // If structured extraction fails, continue with empty structuredFields
            const errorMessage = error instanceof Error ? error.message : "Structured extraction failed";
            console.warn(`Failed to extract structured fields for ${result.fileName}:`, errorMessage);
            
            setFiles((prev) =>
              prev.map((f) =>
                f.id === fileId
                  ? {
                      ...f,
                      status: "complete",
                      structuredFields: {},
                    }
                  : f
              )
            );
          }
        } else {
          // Mark as complete if no text/bounding boxes
          setFiles((prev) =>
            prev.map((f) =>
              f.id === fileId ? { ...f, status: "complete" } : f
            )
          );
        }

        // Create enriched result with structured fields
        const enrichedResult: UploadedDocumentResult = {
          ...result,
          structuredFields,
        };

        uploadedResults.push(enrichedResult);
      } catch (error) {
        const message = error instanceof Error ? error.message : "Upload failed.";
        setFiles((prev) =>
          prev.map((f) =>
            f.id === fileId
              ? {
                  ...f,
                  status: "error",
                  progress: 0,
                  error: message,
                }
              : f
          )
        );
      }
    }

    // Update context and navigate if we have successful uploads
    if (uploadedResults.length > 0) {
      addDocuments(uploadedResults);
      toast({
        title: "Upload complete",
        description: `${uploadedResults.length} file${uploadedResults.length === 1 ? "" : "s"} processed successfully.`,
      });

      // Navigate to workspace - documents are already in context
      navigate("/workspace");
    } else {
      toast({
        title: "Upload failed",
        description: "No files were successfully uploaded.",
        variant: "destructive",
      });
    }

    setIsUploading(false);
  }, [files, isUploading, addDocuments, navigate]);

  // Check if all files are complete
  const hasFiles = files.length > 0;
  const isProcessing = files.some((file) => file.status === "uploading" || file.status === "processing");
  const anySuccessful = files.some((file) => file.status === "complete");

  useEffect(() => {
    if (!isProcessing) {
      setIsUploading(false);
    }
  }, [isProcessing]);

  return (
    <div className="min-h-screen pt-24 pb-12 px-6">
      <div className="max-w-3xl mx-auto">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-center mb-10"
        >
          <h1 className="text-3xl sm:text-4xl font-bold text-foreground mb-3">
            Upload Documents
          </h1>
          <p className="text-muted-foreground">
            Drop your PDF, image, DOCX, or XLSX files below to begin extraction
          </p>
        </motion.div>

        {/* Upload Card */}
        <GlassCard className="mb-6">
          <FileDropzone onFilesAdded={handleFilesAdded} disabled={isUploading || isProcessing} />
        </GlassCard>

        {/* File List */}
        <AnimatePresence mode="popLayout">
          {hasFiles && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="mb-6"
            >
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-medium text-foreground flex items-center gap-2">
                  <FileText className="w-4 h-4 text-primary" />
                  Selected Files ({files.length})
                </h3>
              </div>

              <AnimatePresence mode="popLayout">
                {files.map((file) => (
                  <FileListItem
                    key={file.id}
                    file={file}
                    onRemove={handleRemoveFile}
                  />
                ))}
              </AnimatePresence>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Actions */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
          className="flex flex-col sm:flex-row gap-4 justify-center"
        >
          <GlassButton
            variant="primary"
            size="lg"
            onClick={handleUpload}
            disabled={!hasFiles || isUploading || isProcessing}
            className="min-w-[200px]"
          >
            {isUploading || isProcessing ? (
              <>
                <motion.div
                  animate={{ rotate: 360 }}
                  transition={{ repeat: Infinity, duration: 1, ease: "linear" }}
                >
                  <Upload className="w-5 h-5" />
                </motion.div>
                Processing...
              </>
            ) : (
              <>
                <Upload className="w-5 h-5" />
                {anySuccessful ? "Upload More" : "Upload & Extract"}
              </>
            )}
          </GlassButton>
          {anySuccessful && (
            <GlassButton
              variant="ghost"
              size="lg"
              onClick={() => navigate("/workspace")}
              className="min-w-[200px]"
            >
              View Results
              <ArrowRight className="w-5 h-5" />
            </GlassButton>
          )}
        </motion.div>
      </div>
    </div>
  );
}
