/**
 * Dynamic extraction field editor shared by BatchProcessing and CurationQueue.
 *
 * Renders editable form fields for any extraction schema — not limited to
 * the hardcoded enforcement/crime field set.
 */

// Priority fields shown first in edit form
const PRIORITY_FIELDS = [
  'date', 'state', 'city', 'incident_type', 'description',
  'person_name', 'victim_name', 'offender_name', 'defendant_name',
  'victim_age', 'victim_category', 'outcome_category',
];

// Metadata fields excluded from editing
const EXCLUDED_FIELDS = new Set([
  'confidence', 'overall_confidence', 'extraction_notes', 'is_relevant',
  'categories', 'category', 'extraction_type', 'success',
]);

function isExcludedField(key: string): boolean {
  return EXCLUDED_FIELDS.has(key) || key.endsWith('_confidence');
}

function snakeCaseToLabel(key: string): string {
  return key
    .split('_')
    .map(w => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

function isDateKey(key: string): boolean {
  return key === 'date' || key.endsWith('_date') || key.startsWith('date_');
}

interface DynamicExtractionFieldsProps {
  data: Record<string, unknown>;
  onChange: (data: Record<string, unknown>) => void;
}

export function DynamicExtractionFields({ data, onChange }: DynamicExtractionFieldsProps) {
  const allKeys = Object.keys(data).filter(k => !isExcludedField(k));

  const priorityKeys = PRIORITY_FIELDS.filter(k => allKeys.includes(k));
  const remainingKeys = allKeys
    .filter(k => !PRIORITY_FIELDS.includes(k))
    .sort();
  const orderedKeys = [...priorityKeys, ...remainingKeys];

  // Group into pairs for 2-column layout, except long-text fields get full width
  const rows: Array<{ keys: string[]; fullWidth: boolean }> = [];
  let pendingKey: string | null = null;

  for (const key of orderedKeys) {
    const value = data[key];
    const isLongText = key === 'description' ||
      (typeof value === 'string' && value.length > 100);

    if (isLongText) {
      // Flush any pending half-row
      if (pendingKey) {
        rows.push({ keys: [pendingKey], fullWidth: false });
        pendingKey = null;
      }
      rows.push({ keys: [key], fullWidth: true });
    } else if (pendingKey) {
      rows.push({ keys: [pendingKey, key], fullWidth: false });
      pendingKey = null;
    } else {
      pendingKey = key;
    }
  }
  if (pendingKey) {
    rows.push({ keys: [pendingKey], fullWidth: false });
  }

  const handleChange = (key: string, rawValue: string) => {
    const currentValue = data[key];
    let parsed: unknown;

    if (typeof currentValue === 'boolean') {
      parsed = rawValue === 'yes' ? true : rawValue === 'no' ? false : undefined;
    } else if (typeof currentValue === 'number') {
      const n = Number(rawValue);
      parsed = rawValue === '' ? undefined : isNaN(n) ? rawValue : n;
    } else if (Array.isArray(currentValue)) {
      parsed = rawValue.split(',').map(s => s.trim()).filter(Boolean);
    } else {
      parsed = rawValue || undefined;
    }

    onChange({ ...data, [key]: parsed });
  };

  const renderField = (key: string) => {
    const value = data[key];
    const label = snakeCaseToLabel(key);

    // Boolean → select
    if (typeof value === 'boolean' || value === undefined && key.startsWith('is_')) {
      return (
        <div className="form-group" key={key}>
          <label>{label}</label>
          <select
            value={value === true ? 'yes' : value === false ? 'no' : ''}
            onChange={e => handleChange(key, e.target.value)}
          >
            <option value="">Unknown</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        </div>
      );
    }

    // Date key → date input
    if (isDateKey(key)) {
      return (
        <div className="form-group" key={key}>
          <label>{label}</label>
          <input
            type="date"
            value={String(value ?? '')}
            onChange={e => handleChange(key, e.target.value)}
          />
        </div>
      );
    }

    // Number → number input
    if (typeof value === 'number') {
      return (
        <div className="form-group" key={key}>
          <label>{label}</label>
          <input
            type="number"
            value={value ?? ''}
            onChange={e => handleChange(key, e.target.value)}
          />
        </div>
      );
    }

    // Long text / description → textarea
    if (typeof value === 'string' && value.length > 100 || key === 'description') {
      return (
        <div className="form-group" key={key}>
          <label>{label}</label>
          <textarea
            value={String(value ?? '')}
            onChange={e => handleChange(key, e.target.value)}
            rows={3}
          />
        </div>
      );
    }

    // Array → comma-separated text input
    if (Array.isArray(value)) {
      return (
        <div className="form-group" key={key}>
          <label>{label}</label>
          <input
            type="text"
            value={value.join(', ')}
            onChange={e => handleChange(key, e.target.value)}
          />
        </div>
      );
    }

    // Default → text input
    return (
      <div className="form-group" key={key}>
        <label>{label}</label>
        <input
          type="text"
          value={String(value ?? '')}
          onChange={e => handleChange(key, e.target.value)}
        />
      </div>
    );
  };

  return (
    <div className="edit-form">
      {rows.map((row, i) => (
        row.fullWidth ? (
          <div key={i}>
            {renderField(row.keys[0])}
          </div>
        ) : (
          <div className="form-row" key={i}>
            {row.keys.map(key => renderField(key))}
          </div>
        )
      ))}
    </div>
  );
}

/**
 * Build initial edit data from extracted_data, stripping metadata fields.
 */
export function buildEditData(rawData: Record<string, unknown> | string | null | undefined): Record<string, unknown> {
  if (!rawData) return {};
  // Parse if API returned a JSON string
  const extractedData: Record<string, unknown> = typeof rawData === 'string'
    ? (() => { try { return JSON.parse(rawData); } catch { return {}; } })()
    : rawData;
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(extractedData)) {
    if (!isExcludedField(key) && value !== undefined && value !== null) {
      result[key] = value;
    }
  }
  return result;
}

/**
 * Parse extracted_data that may come from the API as a JSON string.
 */
export function parseExtractedData(data: unknown): Record<string, unknown> {
  if (!data) return {};
  if (typeof data === 'string') {
    try { return JSON.parse(data); } catch { return {}; }
  }
  if (typeof data === 'object' && !Array.isArray(data)) {
    return data as Record<string, unknown>;
  }
  return {};
}

export default DynamicExtractionFields;
