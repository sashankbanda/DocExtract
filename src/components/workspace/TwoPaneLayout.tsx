import { ReactNode, useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { PanelLeft, PanelRight } from "lucide-react";

interface TwoPaneLayoutProps {
  leftPane: ReactNode;
  rightPane: ReactNode;
  leftWidth?: number; // Percentage (0-100)
}

const STORAGE_KEY = "workspace-pane-width";
const DEFAULT_LEFT_WIDTH = 55;
const MIN_LEFT_WIDTH = 30;
const MAX_LEFT_WIDTH = 80;

export function TwoPaneLayout({
  leftPane,
  rightPane,
  leftWidth: initialLeftWidth,
}: TwoPaneLayoutProps) {
  const [leftWidth, setLeftWidth] = useState<number>(() => {
    // Load from localStorage or use prop/default
    if (initialLeftWidth !== undefined) {
      return initialLeftWidth;
    }
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const parsed = parseFloat(saved);
        if (!isNaN(parsed) && parsed >= MIN_LEFT_WIDTH && parsed <= MAX_LEFT_WIDTH) {
          return parsed;
        }
      }
    } catch {
      // Ignore localStorage errors
    }
    return DEFAULT_LEFT_WIDTH;
  });

  const [isMobile, setIsMobile] = useState(false);
  const [rightPanelCollapsed, setRightPanelCollapsed] = useState(false);

  // Detect mobile
  useEffect(() => {
    const checkMobile = () => {
      setIsMobile(window.innerWidth < 768);
      if (window.innerWidth < 768) {
        setRightPanelCollapsed(true);
      }
    };
    checkMobile();
    window.addEventListener("resize", checkMobile);
    return () => window.removeEventListener("resize", checkMobile);
  }, []);

  // Save width to localStorage
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, leftWidth.toString());
    } catch {
      // Ignore localStorage errors
    }
  }, [leftWidth]);

  const handleResize = (sizes: number[]) => {
    if (sizes[0] !== undefined) {
      setLeftWidth(sizes[0]);
    }
  };

  if (isMobile) {
    return (
      <div className="h-[calc(100vh-4rem)] p-4">
        {rightPanelCollapsed ? (
          <div className="h-full glass rounded-2xl overflow-hidden relative">
            {leftPane}
            <button
              onClick={() => setRightPanelCollapsed(false)}
              className="absolute top-4 right-4 p-2 rounded-lg bg-background/80 backdrop-blur-sm border border-border hover:bg-background transition-colors"
              aria-label="Show panels"
            >
              <PanelRight className="w-4 h-4" />
            </button>
          </div>
        ) : (
          <div className="h-full glass rounded-2xl overflow-hidden relative">
            {rightPane}
            <button
              onClick={() => setRightPanelCollapsed(true)}
              className="absolute top-4 left-4 p-2 rounded-lg bg-background/80 backdrop-blur-sm border border-border hover:bg-background transition-colors"
              aria-label="Show PDF"
            >
              <PanelLeft className="w-4 h-4" />
            </button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="h-[calc(100vh-4rem)] p-4">
      <ResizablePanelGroup direction="horizontal" className="h-full">
        <ResizablePanel
          defaultSize={leftWidth}
          minSize={MIN_LEFT_WIDTH}
          maxSize={MAX_LEFT_WIDTH}
          onResize={handleResize}
          className="transition-all duration-200"
        >
          <div className="h-full glass rounded-2xl overflow-hidden">
            {leftPane}
          </div>
        </ResizablePanel>
        <ResizableHandle withHandle />
        <ResizablePanel defaultSize={100 - leftWidth} minSize={20}>
          <div className="h-full glass rounded-2xl overflow-hidden">
            {rightPane}
          </div>
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  );
}
