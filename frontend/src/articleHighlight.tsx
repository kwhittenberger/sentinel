import React from 'react';
import ReactMarkdown from 'react-markdown';

export interface HighlightEntry {
  label: string;
  value: string;
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
 */
export function collectHighlightsFromRecord(
  rec: Record<string, unknown>
): HighlightEntry[] {
  const str = (key: string): string | undefined => {
    const v = rec[key];
    return typeof v === 'string' ? v : undefined;
  };

  return collectHighlights([
    ['Victim Name', str('victim_name')],
    ['City', str('city')],
    ['Address', str('address')],
    ['Outcome', str('outcome_category')],
    ['Outcome Detail', str('outcome_detail')],
    ['Incident Type', str('incident_type')],
    ['Victim Category', str('victim_category')],
    ['Immigration Status', str('offender_immigration_status') ?? str('immigration_status')],
    ['Offender Name', str('offender_name')],
  ]);
}

/**
 * Replace occurrences of highlight values in a plain-text string with
 * <mark> elements.
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
 */
export function HighlightedArticle({
  content,
  highlights,
}: {
  content: string;
  highlights: HighlightEntry[];
}) {
  return (
    <ReactMarkdown skipHtml={true} components={highlightComponents(highlights)}>
      {content}
    </ReactMarkdown>
  );
}
