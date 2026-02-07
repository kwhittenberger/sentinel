import { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { PRIORITY_FIELDS, isExcludedField, snakeCaseToLabel } from './DynamicExtractionFields';

interface ArticleContextMenuProps {
  containerRef: React.RefObject<HTMLDivElement | null>;
  editData: Record<string, unknown>;
  onAssignField: (fieldKey: string, value: string) => void;
}

interface MenuState {
  x: number;
  y: number;
  selectedText: string;
}

export function ArticleContextMenu({ containerRef, editData, onAssignField }: ArticleContextMenuProps) {
  const [menu, setMenu] = useState<MenuState | null>(null);

  const closeMenu = useCallback(() => setMenu(null), []);

  // Build ordered field list: priority first, then remaining alphabetically
  const getFieldList = useCallback((): string[] => {
    const dataKeys = Object.keys(editData).filter(k => !isExcludedField(k));
    const priorityKeys = PRIORITY_FIELDS.filter(k =>
      dataKeys.includes(k) || !Object.keys(editData).length
    );
    const remainingKeys = dataKeys
      .filter(k => !PRIORITY_FIELDS.includes(k))
      .sort();

    // Deduplicate while preserving order
    const seen = new Set<string>();
    const result: string[] = [];
    for (const key of [...priorityKeys, ...remainingKeys]) {
      if (!seen.has(key)) {
        seen.add(key);
        result.push(key);
      }
    }
    return result;
  }, [editData]);

  // Handle right-click on the container
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const handleContextMenu = (e: MouseEvent) => {
      const selection = window.getSelection();
      const text = selection?.toString().trim();
      if (!text) return; // No text selected — let native menu through

      e.preventDefault();
      setMenu({ x: e.clientX, y: e.clientY, selectedText: text });
    };

    container.addEventListener('contextmenu', handleContextMenu);
    return () => container.removeEventListener('contextmenu', handleContextMenu);
  }, [containerRef]);

  // Close on click outside, Escape, or scroll
  useEffect(() => {
    if (!menu) return;

    const handleClick = () => closeMenu();
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeMenu();
    };
    const handleScroll = () => closeMenu();

    document.addEventListener('click', handleClick);
    document.addEventListener('keydown', handleKeyDown);
    containerRef.current?.addEventListener('scroll', handleScroll, true);

    return () => {
      document.removeEventListener('click', handleClick);
      document.removeEventListener('keydown', handleKeyDown);
      containerRef.current?.removeEventListener('scroll', handleScroll, true);
    };
  }, [menu, closeMenu, containerRef]);

  if (!menu) return null;

  const fields = getFieldList();

  // Clamp menu position so it doesn't go off-screen
  const menuWidth = 260;
  const menuMaxHeight = 320;
  const x = Math.min(menu.x, window.innerWidth - menuWidth - 8);
  const y = Math.min(menu.y, window.innerHeight - menuMaxHeight - 8);

  return createPortal(
    <div
      className="article-context-menu"
      style={{ left: x, top: y }}
      onClick={e => e.stopPropagation()}
    >
      <div className="context-menu-header">
        Assign to field
      </div>
      <div className="context-menu-preview">
        &ldquo;{menu.selectedText.length > 60
          ? menu.selectedText.substring(0, 60) + '...'
          : menu.selectedText}&rdquo;
      </div>
      <div className="context-menu-items">
        {fields.length === 0 ? (
          <div className="context-menu-empty">No fields available</div>
        ) : (
          fields.map(key => {
            const currentValue = editData[key];
            const hasValue = currentValue !== undefined && currentValue !== null && currentValue !== '';
            return (
              <button
                key={key}
                className="context-menu-item"
                onClick={() => {
                  onAssignField(key, menu.selectedText);
                  closeMenu();
                }}
              >
                <span className="context-menu-field-name">{snakeCaseToLabel(key)}</span>
                {hasValue && (
                  <span className="context-menu-current-value">
                    {String(currentValue).length > 30
                      ? String(currentValue).substring(0, 30) + '...'
                      : String(currentValue)}
                  </span>
                )}
              </button>
            );
          })
        )}
      </div>
    </div>,
    document.body
  );
}
