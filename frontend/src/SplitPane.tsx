import { useState, useRef, useCallback, useEffect } from 'react';
import type { ReactNode } from 'react';

interface SplitPaneProps {
  left: ReactNode;
  right: ReactNode;
  defaultLeftWidth?: number;
  minLeftWidth?: number;
  maxLeftWidth?: number;
  storageKey?: string;
  className?: string;
}

export function SplitPane({
  left,
  right,
  defaultLeftWidth = 350,
  minLeftWidth = 200,
  maxLeftWidth = 600,
  storageKey,
  className = '',
}: SplitPaneProps) {
  // Load from localStorage if key provided
  const getInitialWidth = () => {
    if (storageKey) {
      const saved = localStorage.getItem(`splitpane-${storageKey}`);
      if (saved) {
        const parsed = parseInt(saved, 10);
        if (!isNaN(parsed) && parsed >= minLeftWidth && parsed <= maxLeftWidth) {
          return parsed;
        }
      }
    }
    return defaultLeftWidth;
  };

  const [leftWidth, setLeftWidth] = useState(getInitialWidth);
  const [isDragging, setIsDragging] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const startXRef = useRef(0);
  const startWidthRef = useRef(0);

  // Save to localStorage when width changes
  useEffect(() => {
    if (storageKey && !isDragging) {
      localStorage.setItem(`splitpane-${storageKey}`, String(leftWidth));
    }
  }, [leftWidth, storageKey, isDragging]);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsDragging(true);
    startXRef.current = e.clientX;
    startWidthRef.current = leftWidth;
  }, [leftWidth]);

  const KEYBOARD_STEP = 20;

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    let newWidth = leftWidth;
    if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
      newWidth = Math.max(minLeftWidth, leftWidth - KEYBOARD_STEP);
    } else if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
      newWidth = Math.min(maxLeftWidth, leftWidth + KEYBOARD_STEP);
    } else if (e.key === 'Home') {
      newWidth = minLeftWidth;
    } else if (e.key === 'End') {
      newWidth = maxLeftWidth;
    } else {
      return;
    }
    e.preventDefault();
    setLeftWidth(newWidth);
  }, [leftWidth, minLeftWidth, maxLeftWidth]);

  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (!isDragging) return;

    const delta = e.clientX - startXRef.current;
    const newWidth = Math.min(maxLeftWidth, Math.max(minLeftWidth, startWidthRef.current + delta));
    setLeftWidth(newWidth);
  }, [isDragging, minLeftWidth, maxLeftWidth]);

  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
  }, []);

  useEffect(() => {
    if (isDragging) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    }

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
  }, [isDragging, handleMouseMove, handleMouseUp]);

  return (
    <div ref={containerRef} className={`split-pane ${className} ${isDragging ? 'dragging' : ''}`}>
      <div className="split-pane-left" style={{ width: leftWidth, minWidth: leftWidth }}>
        {left}
      </div>
      <div
        className="split-pane-divider"
        onMouseDown={handleMouseDown}
        onKeyDown={handleKeyDown}
        role="separator"
        tabIndex={0}
        aria-orientation="vertical"
        aria-valuenow={leftWidth}
        aria-valuemin={minLeftWidth}
        aria-valuemax={maxLeftWidth}
        aria-label="Resize panes"
      >
        <div className="split-pane-divider-handle" />
      </div>
      <div className="split-pane-right">
        {right}
      </div>

      <style>{`
        .split-pane {
          display: flex;
          flex: 1;
          min-height: 0;
          overflow: hidden;
        }

        .split-pane-left {
          flex-shrink: 0;
          overflow: hidden;
          display: flex;
          flex-direction: column;
        }

        .split-pane-left > * {
          flex: 1;
          min-height: 0;
          overflow-y: auto;
        }

        .split-pane-divider {
          width: 8px;
          background: transparent;
          cursor: col-resize;
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
          position: relative;
          z-index: 10;
        }

        .split-pane-divider:hover,
        .split-pane-divider:focus-visible,
        .split-pane.dragging .split-pane-divider {
          background: rgba(59, 130, 246, 0.1);
        }

        .split-pane-divider:focus-visible {
          outline: 2px solid #3b82f6;
          outline-offset: -2px;
        }

        .split-pane-divider-handle {
          width: 4px;
          height: 40px;
          background: var(--border-color, #333);
          border-radius: 2px;
          transition: background 0.15s, height 0.15s;
        }

        .split-pane-divider:hover .split-pane-divider-handle,
        .split-pane-divider:focus-visible .split-pane-divider-handle,
        .split-pane.dragging .split-pane-divider-handle {
          background: #3b82f6;
          height: 60px;
        }

        .split-pane-right {
          flex: 1;
          min-width: 0;
          overflow: hidden;
          display: flex;
          flex-direction: column;
        }

        .split-pane-right > * {
          flex: 1;
          min-height: 0;
          overflow-y: auto;
        }

        .split-pane.dragging {
          cursor: col-resize;
        }

        .split-pane.dragging .split-pane-left,
        .split-pane.dragging .split-pane-right {
          pointer-events: none;
        }
      `}</style>
    </div>
  );
}

export default SplitPane;
