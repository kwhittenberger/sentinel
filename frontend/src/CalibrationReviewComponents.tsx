import React, { useState } from 'react';
import './CalibrationReview.css';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type DiffStatus = 'match' | 'mismatch' | 'missing_a' | 'missing_b' | 'both_absent';

interface DiffTableProps {
  dataA: Record<string, any> | null;
  dataB: Record<string, any> | null;
  priorityFields?: string[];
  excludeFields?: string[];
  labelOverrides?: Record<string, string>;
  showConfidence?: boolean;
}

interface Stage1Data {
  extraction_data?: Record<string, any>;
  entity_count?: number;
  event_count?: number;
  overall_confidence?: number;
  classification_hints?: Array<{ domain_slug?: string; category_slug?: string; confidence?: number }>;
  [key: string]: any;
}

interface Stage2Result {
  schema_name?: string;
  confidence?: number;
  status?: string;
  provider?: string;
  model?: string;
  input_tokens?: number;
  output_tokens?: number;
  latency_ms?: number;
  extracted_data?: Record<string, any>;
  validation_errors?: Array<{ field: string; error: string }>;
  [key: string]: any;
}

// ---------------------------------------------------------------------------
// computeDiffStatus
// ---------------------------------------------------------------------------

function normalize(v: any): string {
  if (v == null) return '';
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (Array.isArray(v)) return [...v].map(x => String(x).trim().toLowerCase()).sort().join(',');
  return String(v).trim().toLowerCase();
}

export function computeDiffStatus(a: any, b: any): DiffStatus {
  const aNull = a == null || (typeof a === 'string' && a.trim() === '');
  const bNull = b == null || (typeof b === 'string' && b.trim() === '');
  if (aNull && bNull) return 'both_absent';
  if (aNull) return 'missing_a';
  if (bNull) return 'missing_b';
  return normalize(a) === normalize(b) ? 'match' : 'mismatch';
}

// ---------------------------------------------------------------------------
// DiffFieldRow
// ---------------------------------------------------------------------------

function formatValue(v: any): string {
  if (v == null) return '--';
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  if (Array.isArray(v)) return v.length === 0 ? '--' : v.join(', ');
  if (typeof v === 'object') return JSON.stringify(v, null, 2);
  return String(v);
}

export function DiffFieldRow({ label, valueA, valueB, singleColumn }: {
  label: string;
  valueA: any;
  valueB?: any;
  singleColumn?: boolean;
}) {
  const status = singleColumn ? 'match' : computeDiffStatus(valueA, valueB);
  return (
    <div className={`crc-diff-row ${singleColumn ? 'crc-single-col' : ''} crc-${status.replace('_', '-')}`}>
      <div className="crc-diff-label">{label}</div>
      <div className="crc-diff-cell">{formatValue(valueA)}</div>
      {!singleColumn && <div className="crc-diff-cell">{formatValue(valueB)}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// DiffTable
// ---------------------------------------------------------------------------

export function DiffTable({
  dataA,
  dataB,
  priorityFields = [],
  excludeFields = [],
  labelOverrides = {},
  showConfidence = false,
}: DiffTableProps) {
  const a = dataA || {};
  const b = dataB || {};

  const excludeSet = new Set(excludeFields);
  if (showConfidence) {
    // Don't show _confidence fields as standalone rows; they're inlined
    for (const k of Object.keys({ ...a, ...b })) {
      if (k.endsWith('_confidence')) excludeSet.add(k);
    }
  }

  const allKeys = new Set([...Object.keys(a), ...Object.keys(b)]);
  const orderedKeys: string[] = [];
  for (const k of priorityFields) {
    if (allKeys.has(k) && !excludeSet.has(k)) {
      orderedKeys.push(k);
      allKeys.delete(k);
    }
  }
  for (const k of [...allKeys].sort()) {
    if (!excludeSet.has(k)) orderedKeys.push(k);
  }

  if (orderedKeys.length === 0) {
    return <div style={{ padding: 8, fontSize: 11, color: 'var(--text-muted)' }}>No fields</div>;
  }

  const humanLabel = (key: string) => {
    if (labelOverrides[key]) return labelOverrides[key];
    return key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  };

  return (
    <div className="crc-diff-table">
      {orderedKeys.map(key => {
        const label = humanLabel(key);
        const confKey = `${key}_confidence`;
        const confA = showConfidence ? a[confKey] : undefined;
        const confB = showConfidence ? b[confKey] : undefined;
        return (
          <DiffFieldRow
            key={key}
            label={
              label + (confA != null || confB != null
                ? ` [${confA != null ? Math.round(confA * 100) + '%' : '?'}/${confB != null ? Math.round(confB * 100) + '%' : '?'}]`
                : '')
            }
            valueA={a[key]}
            valueB={b[key]}
          />
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// SingleColumnDiffTable (for golden view)
// ---------------------------------------------------------------------------

function SingleColumnDiffTable({ data, excludeFields = [], labelOverrides = {} }: {
  data: Record<string, any> | null;
  excludeFields?: string[];
  labelOverrides?: Record<string, string>;
}) {
  const d = data || {};
  const excludeSet = new Set(excludeFields);
  const keys = Object.keys(d).filter(k => !excludeSet.has(k)).sort();

  if (keys.length === 0) {
    return <div style={{ padding: 8, fontSize: 11, color: 'var(--text-muted)' }}>No data</div>;
  }

  const humanLabel = (key: string) => {
    if (labelOverrides[key]) return labelOverrides[key];
    return key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  };

  return (
    <div className="crc-diff-table">
      {keys.map(key => (
        <DiffFieldRow key={key} label={humanLabel(key)} valueA={d[key]} singleColumn />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stage1SummaryBar
// ---------------------------------------------------------------------------

function Stage1Column({ label, data }: { label: string; data: Stage1Data | null }) {
  const [showRaw, setShowRaw] = useState(false);

  if (!data) {
    return (
      <div className="crc-stage1-col">
        <h4>{label}</h4>
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>No data</div>
      </div>
    );
  }

  const entities = data.extraction_data?.entities || data.entities || {};
  const personCount = Array.isArray(entities.persons) ? entities.persons.length : 0;
  const orgCount = Array.isArray(entities.organizations) ? entities.organizations.length : 0;
  const locCount = Array.isArray(entities.locations) ? entities.locations.length : 0;
  const eventCount = data.event_count ?? (Array.isArray(data.extraction_data?.events) ? data.extraction_data!.events.length : 0);
  const confidence = data.overall_confidence ?? data.extraction_data?.extraction_confidence;
  const hints = data.classification_hints || data.extraction_data?.classification_hints || [];

  return (
    <div className="crc-stage1-col">
      <h4>{label}</h4>
      <div className="crc-stage1-stats">
        <span className="crc-stage1-stat">
          <strong>{personCount}</strong> persons
        </span>
        <span className="crc-stage1-stat">
          <strong>{orgCount}</strong> orgs
        </span>
        <span className="crc-stage1-stat">
          <strong>{locCount}</strong> locations
        </span>
        <span className="crc-stage1-stat">
          <strong>{eventCount}</strong> events
        </span>
        {confidence != null && (
          <span className="crc-confidence-badge">
            {Math.round(confidence * 100)}%
          </span>
        )}
      </div>
      {hints.length > 0 && (
        <div className="crc-pills">
          {hints.map((h: any, i: number) => (
            <span key={i} className="crc-pill">
              {h.category_slug || h.domain_slug}
              {h.confidence != null && ` ${Math.round(h.confidence * 100)}%`}
            </span>
          ))}
        </div>
      )}
      <button
        className="action-btn"
        onClick={() => setShowRaw(v => !v)}
        style={{ fontSize: 10, padding: '1px 6px', marginTop: 6 }}
      >
        {showRaw ? 'Hide' : 'Show'} Raw
      </button>
      {showRaw && (
        <pre className="crc-raw-json">
          {JSON.stringify(data.extraction_data || data, null, 2).substring(0, 2000)}
        </pre>
      )}
    </div>
  );
}

export function Stage1SummaryBar({ stage1A, stage1B }: {
  stage1A: Stage1Data | null;
  stage1B: Stage1Data | null;
}) {
  const [expanded, setExpanded] = useState(false);
  if (!stage1A && !stage1B) return null;

  return (
    <div style={{ marginBottom: 12 }}>
      <button
        className="action-btn crc-section-toggle"
        onClick={() => setExpanded(v => !v)}
      >
        {expanded ? '\u25BE' : '\u25B8'} Stage 1 IR Comparison
      </button>
      {expanded && (
        <div className="crc-stage1-summary">
          <Stage1Column label="Config A" data={stage1A} />
          <Stage1Column label="Config B" data={stage1B} />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stage2ComparisonGrid
// ---------------------------------------------------------------------------

function matchSchemas(listA: Stage2Result[], listB: Stage2Result[]): Array<{ name: string; a: Stage2Result | null; b: Stage2Result | null }> {
  const nameMap = new Map<string, { a: Stage2Result | null; b: Stage2Result | null }>();
  listA.forEach((r, i) => {
    const name = r.schema_name || `Schema ${i + 1}`;
    nameMap.set(name, { a: r, b: null });
  });
  listB.forEach((r, i) => {
    const name = r.schema_name || `Schema ${i + 1}`;
    const existing = nameMap.get(name);
    if (existing) {
      existing.b = r;
    } else {
      nameMap.set(name, { a: null, b: r });
    }
  });
  return [...nameMap.entries()].map(([name, pair]) => ({ name, ...pair }));
}

function SchemaAccordion({ name, a, b }: { name: string; a: Stage2Result | null; b: Stage2Result | null }) {
  const [expanded, setExpanded] = useState(false);
  const confA = a?.confidence != null ? `${Math.round(a.confidence * 100)}%` : '--';
  const confB = b?.confidence != null ? `${Math.round(b.confidence * 100)}%` : '--';

  return (
    <div className="crc-schema-accordion">
      <div className="crc-schema-header" onClick={() => setExpanded(v => !v)}>
        <span style={{ fontSize: 11 }}>{expanded ? '\u25BE' : '\u25B8'}</span>
        <span className="crc-schema-name">{name}</span>
        <div className="crc-schema-meta">
          <span>A: {confA}</span>
          <span>B: {confB}</span>
          {a?.latency_ms != null && <span>{Math.round(a.latency_ms)}ms</span>}
          {a?.input_tokens != null && <span>{a.input_tokens + (a.output_tokens || 0)} tok</span>}
        </div>
      </div>
      {expanded && (
        <div className="crc-schema-body">
          <DiffTable
            dataA={a?.extracted_data || null}
            dataB={b?.extracted_data || null}
            showConfidence
          />
        </div>
      )}
    </div>
  );
}

export function Stage2ComparisonGrid({ stage2A, stage2B }: {
  stage2A: Stage2Result[];
  stage2B: Stage2Result[];
}) {
  const [expanded, setExpanded] = useState(false);
  if (stage2A.length === 0 && stage2B.length === 0) return null;

  const matched = matchSchemas(stage2A, stage2B);

  return (
    <div style={{ marginBottom: 12 }}>
      <button
        className="action-btn crc-section-toggle"
        onClick={() => setExpanded(v => !v)}
      >
        {expanded ? '\u25BE' : '\u25B8'} Stage 2 Results ({matched.length} schema{matched.length !== 1 ? 's' : ''})
      </button>
      {expanded && (
        <div>
          {matched.map(({ name, a, b }) => (
            <SchemaAccordion key={name} name={name} a={a} b={b} />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// BestExtractionDiff
// ---------------------------------------------------------------------------

export function BestExtractionDiff({
  configALabel,
  configBLabel,
  extractionA,
  extractionB,
  confidenceA,
  confidenceB,
  errorA,
  errorB,
  chosenConfig,
  onChoose,
}: {
  configALabel: string;
  configBLabel: string;
  extractionA: Record<string, any> | null;
  extractionB: Record<string, any> | null;
  confidenceA: number | null;
  confidenceB: number | null;
  errorA: string | null;
  errorB: string | null;
  chosenConfig: string | null;
  onChoose: (config: string) => void;
}) {
  const hasError = errorA || errorB;
  const hasBothExtractions = extractionA && extractionB && !hasError;

  return (
    <div style={{ marginBottom: 16 }}>
      {/* Header row with choose buttons */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: hasBothExtractions ? 8 : 0 }}>
        <div className={`crc-config-col ${chosenConfig === 'A' ? 'crc-chosen' : ''}`}>
          <div className="crc-config-header">
            <div>
              <span className="crc-config-label">Config A</span>
              <span className="crc-config-model">{configALabel}</span>
            </div>
            {confidenceA != null && (
              <span style={{ fontSize: 11, fontWeight: 600 }}>{Math.round(confidenceA * 100)}%</span>
            )}
          </div>
          {errorA ? (
            <div style={{ color: '#ef4444', fontSize: 12 }}>Error: {errorA}</div>
          ) : !extractionA ? (
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>No extraction</div>
          ) : null}
          <button
            className="action-btn"
            onClick={() => onChoose('A')}
            disabled={!extractionA}
            style={{ marginTop: 8, width: '100%' }}
          >
            {chosenConfig === 'A' ? 'Chosen' : 'Choose A'}
          </button>
        </div>

        <div className={`crc-config-col ${chosenConfig === 'B' ? 'crc-chosen' : ''}`}>
          <div className="crc-config-header">
            <div>
              <span className="crc-config-label">Config B</span>
              <span className="crc-config-model">{configBLabel}</span>
            </div>
            {confidenceB != null && (
              <span style={{ fontSize: 11, fontWeight: 600 }}>{Math.round(confidenceB * 100)}%</span>
            )}
          </div>
          {errorB ? (
            <div style={{ color: '#ef4444', fontSize: 12 }}>Error: {errorB}</div>
          ) : !extractionB ? (
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>No extraction</div>
          ) : null}
          <button
            className="action-btn"
            onClick={() => onChoose('B')}
            disabled={!extractionB}
            style={{ marginTop: 8, width: '100%' }}
          >
            {chosenConfig === 'B' ? 'Chosen' : 'Choose B'}
          </button>
        </div>
      </div>

      {/* Structured diff table when both extractions are available */}
      {hasBothExtractions && (
        <DiffTable
          dataA={extractionA}
          dataB={extractionB}
          showConfidence
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// GoldenExtractionView
// ---------------------------------------------------------------------------

export function GoldenExtractionView({
  goldenJson,
  editing,
  onToggleEdit,
  onJsonChange,
  jsonError,
}: {
  goldenJson: string;
  editing: boolean;
  onToggleEdit: () => void;
  onJsonChange: (value: string) => void;
  jsonError: string | null;
}) {
  const [viewMode, setViewMode] = useState<'structured' | 'json'>('structured');
  let parsed: Record<string, any> | null = null;
  try {
    parsed = goldenJson ? JSON.parse(goldenJson) : null;
  } catch {
    parsed = null;
  }

  const inputStyle = {
    width: '100%',
    padding: '8px 10px',
    borderRadius: 6,
    border: '1px solid var(--border-color)',
    fontSize: 13,
    background: 'var(--bg-primary)',
  };

  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <label style={{ fontSize: 12, fontWeight: 600 }}>Golden Extraction</label>
        <div style={{ display: 'flex', gap: 4 }}>
          {!editing && parsed && (
            <button
              className="action-btn"
              onClick={() => setViewMode(v => v === 'structured' ? 'json' : 'structured')}
              style={{ fontSize: 11, padding: '2px 8px' }}
            >
              {viewMode === 'structured' ? 'JSON' : 'Structured'}
            </button>
          )}
          <button
            className="action-btn"
            onClick={onToggleEdit}
            style={{ fontSize: 11, padding: '2px 8px' }}
          >
            {editing ? 'View' : 'Edit'}
          </button>
        </div>
      </div>
      {editing ? (
        <textarea
          value={goldenJson}
          onChange={e => onJsonChange(e.target.value)}
          rows={10}
          style={{ ...inputStyle, fontFamily: 'monospace', resize: 'vertical' } as React.CSSProperties}
        />
      ) : viewMode === 'structured' && parsed ? (
        <SingleColumnDiffTable data={parsed} />
      ) : (
        <pre style={{
          fontSize: 11, maxHeight: 200, overflow: 'auto', margin: 0,
          background: 'var(--bg-secondary)', padding: 8, borderRadius: 6,
          whiteSpace: 'pre-wrap', wordBreak: 'break-word',
        }}>
          {goldenJson || '(none \u2014 choose A or B, or edit manually)'}
        </pre>
      )}
      {jsonError && <div style={{ color: '#ef4444', fontSize: 11, marginTop: 4 }}>{jsonError}</div>}
    </div>
  );
}
