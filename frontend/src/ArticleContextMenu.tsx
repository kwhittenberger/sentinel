import { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { PRIORITY_FIELDS, isExcludedField, snakeCaseToLabel, formatFieldValue } from './DynamicExtractionFields';
import type { CategoryFieldsByDomain } from './api';

interface ArticleContextMenuProps {
  containerRef: React.RefObject<HTMLDivElement | null>;
  editData: Record<string, unknown>;
  onAssignField: (fieldKey: string, value: string, append?: boolean) => void;
  categoryFields?: CategoryFieldsByDomain | null;
}

interface MenuState {
  x: number;
  y: number;
  selectedText: string;
}

function FieldButton({ fieldKey, editData, onAssignField, selectedText, closeMenu, required }: {
  fieldKey: string;
  editData: Record<string, unknown>;
  onAssignField: (fieldKey: string, value: string, append?: boolean) => void;
  selectedText: string;
  closeMenu: () => void;
  required?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const currentValue = editData[fieldKey];
  const hasValue = currentValue !== undefined && currentValue !== null && currentValue !== '';
  const formatted = hasValue ? formatFieldValue(currentValue) : '';

  // Field is empty — single click assigns directly
  if (!hasValue) {
    return (
      <button
        className={`context-menu-item${required ? ' context-menu-field-required' : ''}`}
        onClick={() => { onAssignField(fieldKey, selectedText); closeMenu(); }}
      >
        <span className="context-menu-field-name">{snakeCaseToLabel(fieldKey)}</span>
      </button>
    );
  }

  // Field has a value — click to expand Replace/Append options
  return (
    <div className={`context-menu-item-group${required ? ' context-menu-field-required' : ''}`}>
      <button
        className="context-menu-item"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="context-menu-field-name">{snakeCaseToLabel(fieldKey)}</span>
        <span className="context-menu-current-value">
          {formatted.length > 30 ? formatted.substring(0, 30) + '...' : formatted}
        </span>
      </button>
      {expanded && (
        <div className="context-menu-sub-actions">
          <button
            className="context-menu-sub-btn"
            onClick={() => { onAssignField(fieldKey, selectedText); closeMenu(); }}
          >
            Replace
          </button>
          <button
            className="context-menu-sub-btn"
            onClick={() => { onAssignField(fieldKey, selectedText, true); closeMenu(); }}
          >
            Append
          </button>
        </div>
      )}
    </div>
  );
}

export function ArticleContextMenu({ containerRef, editData, onAssignField, categoryFields }: ArticleContextMenuProps) {
  const [menu, setMenu] = useState<MenuState | null>(null);

  const closeMenu = useCallback(() => setMenu(null), []);

  // Build flat ordered field list (fallback when no categoryFields)
  const getFieldList = useCallback((): string[] => {
    const dataKeys = Object.keys(editData).filter(k => !isExcludedField(k));
    const priorityKeys = PRIORITY_FIELDS.filter(k =>
      dataKeys.includes(k) || !Object.keys(editData).length
    );
    const remainingKeys = dataKeys
      .filter(k => !PRIORITY_FIELDS.includes(k))
      .sort();

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
      if (!text) return;

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

  const menuWidth = 280;
  const menuMaxHeight = 400;
  const x = Math.min(menu.x, window.innerWidth - menuWidth - 8);
  const y = Math.min(menu.y, window.innerHeight - menuMaxHeight - 8);

  // Count how many categories each field appears in to find core (shared) fields
  const fieldCategoryCount = new Map<string, number>();
  const schemaFieldSet = new Set<string>();
  let totalCategories = 0;
  if (categoryFields) {
    for (const categories of Object.values(categoryFields)) {
      for (const { required, optional } of Object.values(categories)) {
        totalCategories++;
        for (const f of [...required, ...optional]) {
          schemaFieldSet.add(f);
          fieldCategoryCount.set(f, (fieldCategoryCount.get(f) || 0) + 1);
        }
      }
    }
  }

  // Core fields: appear in 2+ categories (shared across domains/categories)
  const coreFields = totalCategories >= 2
    ? [...fieldCategoryCount.entries()]
        .filter(([, count]) => count >= 2)
        .map(([field]) => field)
        .filter(f => !isExcludedField(f))
    : [];
  const coreFieldSet = new Set(coreFields);

  // Fields in editData not covered by any schema category
  const otherFields = categoryFields
    ? Object.keys(editData)
        .filter(k => !isExcludedField(k) && !schemaFieldSet.has(k))
        .sort()
    : [];

  const renderGrouped = () => (
    <>
      {coreFields.length > 0 && (
        <div className="context-menu-domain-group">
          <div className="context-menu-domain-header">Core</div>
          {coreFields.map(fieldKey => (
            <FieldButton
              key={fieldKey}
              fieldKey={fieldKey}
              editData={editData}
              onAssignField={onAssignField}
              selectedText={menu.selectedText}
              closeMenu={closeMenu}
            />
          ))}
        </div>
      )}
      {Object.entries(categoryFields!).map(([domain, categories]) => {
        // Check if this domain has any non-core fields
        const hasNonCore = Object.values(categories).some(({ required, optional }) =>
          [...required, ...optional].some(f => !coreFieldSet.has(f) && !isExcludedField(f))
        );
        if (!hasNonCore) return null;
        return (
          <div key={domain} className="context-menu-domain-group">
            <div className="context-menu-domain-header">{snakeCaseToLabel(domain)}</div>
            {Object.entries(categories).map(([category, { required, optional }]) => {
              const catRequired = required.filter(f => !isExcludedField(f) && !coreFieldSet.has(f));
              const catOptional = optional.filter(f => !isExcludedField(f) && !coreFieldSet.has(f));
              if (catRequired.length === 0 && catOptional.length === 0) return null;
              return (
                <div key={category} className="context-menu-category-group">
                  <div className="context-menu-category-header">{snakeCaseToLabel(category)}</div>
                  {catRequired.map(fieldKey => (
                    <FieldButton
                      key={fieldKey}
                      fieldKey={fieldKey}
                      editData={editData}
                      onAssignField={onAssignField}
                      selectedText={menu.selectedText}
                      closeMenu={closeMenu}
                      required
                    />
                  ))}
                  {catOptional.map(fieldKey => (
                    <FieldButton
                      key={fieldKey}
                      fieldKey={fieldKey}
                      editData={editData}
                      onAssignField={onAssignField}
                      selectedText={menu.selectedText}
                      closeMenu={closeMenu}
                    />
                  ))}
                </div>
              );
            })}
          </div>
        );
      })}
      {otherFields.length > 0 && (
        <div className="context-menu-domain-group">
          <div className="context-menu-domain-header">Other</div>
          {otherFields.map(fieldKey => (
            <FieldButton
              key={fieldKey}
              fieldKey={fieldKey}
              editData={editData}
              onAssignField={onAssignField}
              selectedText={menu.selectedText}
              closeMenu={closeMenu}
            />
          ))}
        </div>
      )}
    </>
  );

  const renderFlat = () => {
    const fields = getFieldList();
    if (fields.length === 0) {
      return <div className="context-menu-empty">No fields available</div>;
    }
    return fields.map(fieldKey => (
      <FieldButton
        key={fieldKey}
        fieldKey={fieldKey}
        editData={editData}
        onAssignField={onAssignField}
        selectedText={menu.selectedText}
        closeMenu={closeMenu}
      />
    ));
  };

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
        {categoryFields ? renderGrouped() : renderFlat()}
      </div>
    </div>,
    document.body
  );
}
