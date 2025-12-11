import { BoundingBox, Citation, UploadFile } from "@/types/document";
import { Loader2, RotateCw, ZoomIn, ZoomOut } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { HighlightOverlay } from "./HighlightOverlay";

interface ImageViewerProps {
  file: UploadFile;
  boundingBoxes?: Record<string, unknown> | null;
  selectedLineIndexes?: number[];
  citations?: Citation[];
  activeHighlightId?: string | null;
  highlights?: BoundingBox[];
  activeHighlight?: BoundingBox | null;
}

export function ImageViewer({
  file,
  boundingBoxes,
  selectedLineIndexes = [],
  citations = [],
  activeHighlightId,
  highlights = [],
  activeHighlight,
}: ImageViewerProps) {
  const [zoom, setZoom] = useState(100);
  const [rotation, setRotation] = useState(0);
  const [imageSrc, setImageSrc] = useState<string | null>(null);
  const [imageDimensions, setImageDimensions] = useState<{ width: number; height: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!file.rawFile) return;

    setLoading(true);
    const url = URL.createObjectURL(file.rawFile);
    setImageSrc(url);

    const img = new Image();
    img.onload = () => {
      setImageDimensions({ width: img.width, height: img.height });
      setLoading(false);
    };
    img.src = url;

    return () => {
      URL.revokeObjectURL(url);
    };
  }, [file]);

  const handleZoomIn = () => setZoom((prev) => Math.min(prev + 25, 200));
  const handleZoomOut = () => setZoom((prev) => Math.max(prev - 25, 50));
  const handleZoomReset = () => {
    setZoom(100);
    setRotation(0);
  };
  const handleRotate = () => setRotation((prev) => (prev + 90) % 360);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!imageSrc || !imageDimensions) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground">
        Failed to load image
      </div>
    );
  }

  const scale = zoom / 100;

  // Synthesize page metadata for HighlightOverlay
  // We treat the image as a single page document
  const pageMetadata = [{
    pageNumber: 1,
    width: imageDimensions.width,
    height: imageDimensions.height,
    viewport: { width: imageDimensions.width, height: imageDimensions.height },
    scale: 1, // Base scale of the image itself
  }];

  return (
    <div className="h-full flex flex-col">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border/50">
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground">{file.name}</span>
        </div>

        <div className="flex items-center gap-1">
          <button onClick={handleZoomOut} className="p-2 hover:bg-muted/50 rounded-lg">
            <ZoomOut className="w-4 h-4" />
          </button>
          <span className="text-sm w-12 text-center">{zoom}%</span>
          <button onClick={handleZoomIn} className="p-2 hover:bg-muted/50 rounded-lg">
            <ZoomIn className="w-4 h-4" />
          </button>
          <button onClick={handleZoomReset} className="p-2 hover:bg-muted/50 rounded-lg">
            <span className="text-xs">Reset</span>
          </button>
          <div className="w-px h-4 bg-border mx-2" />
          <button onClick={handleRotate} className="p-2 hover:bg-muted/50 rounded-lg">
            <RotateCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Image Area */}
      <div 
        ref={containerRef}
        className="flex-1 overflow-auto p-8 bg-muted/10 relative"
      >
        <div 
          className="relative mx-auto shadow-lg transition-transform duration-200 ease-out origin-top-center"
          style={{
            width: imageDimensions.width * scale,
            height: imageDimensions.height * scale,
            transform: `rotate(${rotation}deg)`,
          }}
        >
          <img
            src={imageSrc}
            alt={file.name}
            className="w-full h-full object-contain"
            draggable={false}
          />
          
          {/* Reuse HighlightOverlay */}
          <div className="absolute inset-0">
             <HighlightOverlay
                boundingBoxes={boundingBoxes}
                selectedLineIndexes={selectedLineIndexes}
                citations={citations}
                currentScale={scale}
                pageMetadata={pageMetadata}
                activeHighlightId={activeHighlightId}
                highlights={highlights}
                activeHighlight={activeHighlight}
                scale={scale} // Pass scale explicitly if needed by legacy path
             />
          </div>
        </div>
      </div>
    </div>
  );
}
