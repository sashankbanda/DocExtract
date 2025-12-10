import { GlassButton } from "@/components/ui/GlassButton";
import { GlassCard } from "@/components/ui/GlassCard";
import { toast } from "@/components/ui/use-toast";
import { FileDropzone } from "@/components/upload/FileDropzone";
import { FileListItem } from "@/components/upload/FileListItem";
import { useExtractionContext } from "@/context/ExtractionContext";
import { uploadDocuments } from "@/lib/api";
import { UploadFile, UploadedDocumentResult } from "@/types/document";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, FileText, Upload } from "lucide-react";
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
    setFiles((prev) => prev.filter((f) => f.id !== id));
  }, []);

  const handleUpload = useCallback(async () => {
    if (files.length === 0 || isUploading) return;
    setIsUploading(true);
    setFiles((prev) =>
      prev.map((file) => ({ ...file, status: "uploading", progress: 10, error: undefined }))
    );

    try {
      const payloadFiles = files
        .map((file) => file.file)
        .filter((file): file is File => Boolean(file));

      if (payloadFiles.length === 0) {
        throw new Error("No valid files to upload.");
      }

      setFiles((prev) => prev.map((file) => ({ ...file, status: "processing", progress: 35 })));

      const results = await uploadDocuments(payloadFiles);

      const resultMap = new Map<string, UploadedDocumentResult[]>();
      results.forEach((result) => {
        const list = resultMap.get(result.fileName) ?? [];
        list.push(result);
        resultMap.set(result.fileName, list);
      });
      const remainingResults = [...results];

      setFiles((prev) =>
        prev.map((file) => {
          const matches = resultMap.get(file.name);
          let matched: UploadedDocumentResult | undefined;

          if (matches && matches.length > 0) {
            matched = matches.shift();
            if (matched) {
              const idx = remainingResults.findIndex((item) => item === matched);
              if (idx >= 0) {
                remainingResults.splice(idx, 1);
              }
            }
          } else if (remainingResults.length > 0) {
            matched = remainingResults.shift();
          }

          if (matched) {
            return { ...file, status: "complete", progress: 100 };
          }
          return {
            ...file,
            status: "error",
            progress: 0,
            error: "No response for this file.",
          };
        })
      );

      addDocuments(results);
      toast({
        title: "Upload complete",
        description: `${results.length} file${results.length === 1 ? "" : "s"} processed successfully.`,
      });
      navigate("/workspace");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Upload failed.";
      setFiles((prev) =>
        prev.map((file) => ({
          ...file,
          status: "error",
          progress: 0,
          error: message,
        }))
      );
      toast({
        title: "Upload failed",
        description: message,
        variant: "destructive",
      });
    } finally {
      setIsUploading(false);
    }
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
