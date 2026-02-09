import React from 'react';
import ReactMarkdown from 'react-markdown';

/** A single span from the LLM's source_spans output (validated on backend). */
export interface SourceSpan {
  start: number;
  end: number;
  text: string;
}

/** Map of field keys to their character-offset spans. */
export type SourceSpans = Record<string, SourceSpan>;

export interface HighlightEntry {
  label: string;
  value: string;
  /** When present, use character-offset highlighting instead of regex. */
  span?: { start: number; end: number };
}

/**
 * Extract highlightable string values from an arbitrary record.
 * Pass a flat mapping of { displayLabel: fieldValue }.
 * Only strings longer than 2 characters are kept (avoids false positives
 * on state abbreviations, numbers, etc.).
 */
export function collectHighlights(
  fields: Array<[string, string | null | undefined]>
): HighlightEntry[] {
  return fields
    .filter((entry): entry is [string, string] => !!entry[1] && entry[1].length > 2 && entry[1].length < 200)
    .map(([label, value]) => ({ label, value }));
}

/**
 * Convenience: build highlights from a generic record by pulling standard
 * incident field names.  Works with FullIncident, Incident,
 * ExtractedIncidentData, or any object that may carry these keys.
 *
 * When sourceSpans is provided, each entry gets an exact character-offset
 * span attached for precise highlighting.
 */
export function collectHighlightsFromRecord(
  rec: Record<string, unknown>,
  sourceSpans?: SourceSpans | null,
): HighlightEntry[] {
  const str = (key: string): string | undefined => {
    const v = rec[key];
    return typeof v === 'string' ? v : undefined;
  };

  const fieldMap: Array<[string, string, string | null | undefined]> = [
    ['victim_name', 'Victim Name', str('victim_name')],
    ['city', 'City', str('city')],
    ['address', 'Address', str('address')],
    ['outcome_category', 'Outcome', str('outcome_category')],
    ['outcome_detail', 'Outcome Detail', str('outcome_detail')],
    ['incident_type', 'Incident Type', str('incident_type')],
    ['victim_category', 'Victim Category', str('victim_category')],
    ['offender_immigration_status', 'Immigration Status', str('offender_immigration_status') ?? str('immigration_status')],
    ['offender_name', 'Offender Name', str('offender_name')],
  ];

  const entries: HighlightEntry[] = [];
  for (const [fieldKey, label, value] of fieldMap) {
    if (!value || value.length <= 2 || value.length >= 200) continue;
    const span = sourceSpans?.[fieldKey];
    entries.push({
      label,
      value,
      span: span ? { start: span.start, end: span.end } : undefined,
    });
  }
  return entries;
}

/**
 * Replace occurrences of highlight values in a plain-text string with
 * <mark> elements (regex fallback path).
 */
export function highlightText(
  text: string,
  highlights: HighlightEntry[]
): React.ReactNode {
  if (!highlights.length) return text;

  const escaped = highlights.map(h => ({
    ...h,
    pattern: h.value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'),
  }));
  const regex = new RegExp(`(${escaped.map(h => h.pattern).join('|')})`, 'gi');
  const parts = text.split(regex);

  return parts.map((part, i) => {
    const match = escaped.find(h => h.value.toLowerCase() === part.toLowerCase());
    if (match) {
      return (
        <mark key={i} className="field-highlight" title={match.label}>
          {part}
        </mark>
      );
    }
    return part;
  });
}

/**
 * Render text with offset-based spans. Spans with exact character offsets
 * are placed precisely; remaining highlights without spans use regex
 * fallback on the gap segments between placed spans.
 */
function highlightTextWithSpans(
  text: string,
  highlights: HighlightEntry[],
): React.ReactNode {
  const spanHighlights = highlights.filter(h => h.span);
  const regexHighlights = highlights.filter(h => !h.span);

  if (!spanHighlights.length) {
    return highlightText(text, regexHighlights);
  }

  // Sort spans by start offset
  const sorted = [...spanHighlights].sort((a, b) => a.span!.start - b.span!.start);

  const parts: React.ReactNode[] = [];
  let cursor = 0;

  for (const entry of sorted) {
    const { start, end } = entry.span!;
    // Skip overlapping or out-of-bounds spans
    if (start < cursor || end > text.length) continue;

    // Gap before this span — apply regex fallback
    if (start > cursor) {
      const gap = text.slice(cursor, start);
      if (regexHighlights.length) {
        const highlighted = highlightText(gap, regexHighlights);
        parts.push(<React.Fragment key={`gap-${cursor}`}>{highlighted}</React.Fragment>);
      } else {
        parts.push(gap);
      }
    }

    // The span itself
    parts.push(
      <mark key={`span-${start}`} className="field-highlight field-highlight-grounded" title={entry.label}>
        {text.slice(start, end)}
      </mark>
    );
    cursor = end;
  }

  // Trailing gap
  if (cursor < text.length) {
    const gap = text.slice(cursor);
    if (regexHighlights.length) {
      const highlighted = highlightText(gap, regexHighlights);
      parts.push(<React.Fragment key={`gap-${cursor}`}>{highlighted}</React.Fragment>);
    } else {
      parts.push(gap);
    }
  }

  return parts;
}

function processChildren(
  children: React.ReactNode,
  highlights: HighlightEntry[]
): React.ReactNode {
  return React.Children.map(children, child => {
    if (typeof child === 'string') {
      return highlightText(child, highlights);
    }
    return child;
  });
}

/**
 * ReactMarkdown `components` override that highlights field values inside
 * text-bearing elements (<p>, <li>).
 */
export function highlightComponents(highlights: HighlightEntry[]) {
  return {
    p: ({ children }: { children?: React.ReactNode }) => (
      <p>{processChildren(children, highlights)}</p>
    ),
    li: ({ children }: { children?: React.ReactNode }) => (
      <li>{processChildren(children, highlights)}</li>
    ),
  };
}

/**
 * Render article content as formatted markdown with field-value highlighting.
 *
 * When any highlight has an exact span, renders paragraphs manually with
 * offset-based highlighting (ReactMarkdown splits text into per-<p> children
 * which breaks full-article character offsets). Falls back to ReactMarkdown
 * path when no spans are present.
 */
export function HighlightedArticle({
  content,
  highlights,
}: {
  content: string;
  highlights: HighlightEntry[];
}) {
  const hasSpans = highlights.some(h => h.span);

  if (hasSpans) {
    // Render manually: split on double-newline for paragraph breaks,
    // applying offset-based highlighting across the full text first
    // then splitting into paragraphs for display.
    const highlighted = highlightTextWithSpans(content, highlights);

    // If highlightTextWithSpans returned a simple string (no highlights hit),
    // still split into paragraphs for readability
    if (typeof highlighted === 'string') {
      const paragraphs = highlighted.split(/\n\n+/);
      return (
        <div>
          {paragraphs.map((p, i) => (
            <p key={i}>{p}</p>
          ))}
        </div>
      );
    }

    // For React node arrays, we wrap the entire highlighted output in a div.
    // Paragraph breaks are preserved as whitespace in the text gaps.
    return <div className="article-highlighted-spans">{highlighted}</div>;
  }

  return (
    <ReactMarkdown skipHtml={true} components={highlightComponents(highlights)}>
      {content}
    </ReactMarkdown>
  );
}
