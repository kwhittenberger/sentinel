import { useState, useEffect, useCallback } from 'react';
import type { ExtractedIncidentData, UniversalExtractionData } from './types';
import { SplitPane } from './SplitPane';
import { ExtractionDetailView } from './ExtractionDetailView';
import { HighlightedArticle, collectHighlightsFromRecord } from './articleHighlight';
import { OperationsBar } from './OperationsBar';
import { DynamicExtractionFields, buildEditData, parseExtractedData } from './DynamicExtractionFields';

const API_BASE = '/api';

interface TieredItem {
  id: string;
  title?: string;
  source_name?: string;
  extraction_confidence: number | null;
  published_date?: string;
  fetched_at?: string;
}

interface FullArticle {
  id: string;
  title?: string;
  source_name?: string;
  source_url?: string;
  content?: string;
  published_date?: string;
  fetched_at?: string;
  extraction_confidence?: number;
  extracted_data?: ExtractedIncidentData;
  status?: string;
}

interface TieredQueue {
  high: TieredItem[];
  medium: TieredItem[];
  low: TieredItem[];
}

interface Suggestion {
  field: string;
  current_value: unknown;
  confidence: number;
  suggestion: unknown;
  reason: string;
}

interface BatchProcessingProps {
  onClose?: () => void;
  onRefresh?: () => void;
  hideOpsBar?: boolean;
}

export function BatchProcessing({ onClose, onRefresh, hideOpsBar }: BatchProcessingProps) {
  const [loading, setLoading] = useState(true);
  const [tieredQueue, setTieredQueue] = useState<TieredQueue>({ high: [], medium: [], low: [] });
  const [selectedTier, setSelectedTier] = useState<'high' | 'medium' | 'low'>('high');
  const [selectedItem, setSelectedItem] = useState<TieredItem | null>(null);
  const [fullArticle, setFullArticle] = useState<FullArticle | null>(null);
  const [loadingArticle, setLoadingArticle] = useState(false);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Operations bar state - persisted in localStorage
  const [opsExpanded, setOpsExpanded] = useState<boolean>(() => {
    const stored = localStorage.getItem('ops-bar-expanded');
    return stored !== null ? stored === 'true' : true;
  });

  // Edit mode state
  const [editMode, setEditMode] = useState(false);
  const [editData, setEditData] = useState<Record<string, unknown>>({});

  // Confirmation dialog state
  const [confirmAction, setConfirmAction] = useState<{
    type: 'bulk-approve' | 'bulk-reject';
    tier: string;
    count: number;
  } | null>(null);
  const [rejectReason, setRejectReason] = useState('');

  const loadTieredQueue = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE}/admin/queue/tiered`);
      if (response.ok) {
        const data = await response.json();
        setTieredQueue(data);
      }
    } catch {
      setMessage({ type: 'error', text: 'Failed to load queue' });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTieredQueue();
  }, [loadTieredQueue]);

  const handleOpsToggle = useCallback(() => {
    setOpsExpanded(prev => {
      const next = !prev;
      localStorage.setItem('ops-bar-expanded', String(next));
      return next;
    });
  }, []);

  const handleOperationComplete = useCallback(() => {
    loadTieredQueue();
    onRefresh?.();
  }, [loadTieredQueue, onRefresh]);

  const loadFullArticle = async (articleId: string) => {
    setLoadingArticle(true);
    setFullArticle(null);
    setEditMode(false);
    try {
      const response = await fetch(`${API_BASE}/admin/queue/${articleId}`);
      if (response.ok) {
        const data = await response.json();
        // Parse extracted_data — API may return it as a JSON string
        data.extracted_data = parseExtractedData(data.extracted_data);
        setFullArticle(data);
        // Initialize edit data dynamically from all extraction fields
        if (data.extracted_data) {
          setEditData(buildEditData(data.extracted_data));
        }
      }
    } catch {
      // Will show limited info from selectedItem
    } finally {
      setLoadingArticle(false);
    }
  };

  const loadSuggestions = async (articleId: string) => {
    setLoadingSuggestions(true);
    setSuggestions([]);
    try {
      const response = await fetch(`${API_BASE}/admin/queue/${articleId}/suggestions`);
      if (response.ok) {
        const data = await response.json();
        setSuggestions(data.suggestions || []);
      }
    } catch {
      // Suggestions are optional, don't show error
    } finally {
      setLoadingSuggestions(false);
    }
  };

  const handleSelectItem = (item: TieredItem) => {
    setSelectedItem(item);
    setFullArticle(null);
    setEditMode(false);
    setEditData({});
    loadFullArticle(item.id);
    loadSuggestions(item.id);
  };

  const handleApprove = async () => {
    if (!selectedItem) return;
    setProcessing(true);
    try {
      // Pass edit data as overrides if in edit mode or if data was modified
      const overrides = editMode ? editData : undefined;
      const response = await fetch(`${API_BASE}/admin/queue/${selectedItem.id}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(overrides || {}),
      });
      if (response.ok) {
        setMessage({ type: 'success', text: 'Article approved' });
        setSelectedItem(null);
        setFullArticle(null);
        setEditMode(false);
        setEditData({});
        loadTieredQueue();
        onRefresh?.();
      } else {
        setMessage({ type: 'error', text: 'Failed to approve' });
      }
    } catch {
      setMessage({ type: 'error', text: 'Failed to approve' });
    } finally {
      setProcessing(false);
    }
  };

  const handleReject = async (reason?: string) => {
    if (!selectedItem) return;
    const finalReason = reason || rejectReason;
    if (!finalReason) return;

    setProcessing(true);
    try {
      const response = await fetch(`${API_BASE}/admin/queue/${selectedItem.id}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: finalReason }),
      });
      if (response.ok) {
        setMessage({ type: 'success', text: 'Article rejected' });
        setSelectedItem(null);
        setFullArticle(null);
        setEditMode(false);
        setEditData({});
        setRejectReason('');
        loadTieredQueue();
      } else {
        setMessage({ type: 'error', text: 'Failed to reject' });
      }
    } catch {
      setMessage({ type: 'error', text: 'Failed to reject' });
    } finally {
      setProcessing(false);
    }
  };

  const handleBulkApprove = async () => {
    setProcessing(true);
    setMessage(null);
    setConfirmAction(null);
    try {
      const response = await fetch(`${API_BASE}/admin/queue/bulk-approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tier: selectedTier,
          limit: 100,
        }),
      });
      if (response.ok) {
        const data = await response.json();
        setMessage({ type: 'success', text: `Approved ${data.approved_count} items` });
        loadTieredQueue();
        onRefresh?.();
      } else {
        setMessage({ type: 'error', text: 'Bulk approve failed' });
      }
    } catch {
      setMessage({ type: 'error', text: 'Bulk approve failed' });
    } finally {
      setProcessing(false);
    }
  };

  const handleBulkReject = async () => {
    if (!rejectReason.trim()) return;

    setProcessing(true);
    setMessage(null);
    setConfirmAction(null);
    try {
      const response = await fetch(`${API_BASE}/admin/queue/bulk-reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tier: selectedTier,
          reason: rejectReason,
          limit: 100,
        }),
      });
      if (response.ok) {
        const data = await response.json();
        setMessage({ type: 'success', text: `Rejected ${data.rejected_count} items` });
        setRejectReason('');
        loadTieredQueue();
      } else {
        setMessage({ type: 'error', text: 'Bulk reject failed' });
      }
    } catch {
      setMessage({ type: 'error', text: 'Bulk reject failed' });
    } finally {
      setProcessing(false);
    }
  };

  const getConfidenceColor = (confidence: number | null | undefined): string => {
    if (confidence === null || confidence === undefined) return 'var(--text-muted)';
    if (confidence >= 0.85) return '#22c55e';
    if (confidence >= 0.50) return '#eab308';
    return '#ef4444';
  };

  const getTierDescription = (tier: 'high' | 'medium' | 'low'): string => {
    switch (tier) {
      case 'high':
        return 'High confidence (85%+) - Auto-approve candidates';
      case 'medium':
        return 'Medium confidence (50-85%) - Quick review needed';
      case 'low':
        return 'Low confidence (<50%) - Full review required';
    }
  };

  const currentItems = tieredQueue[selectedTier];
  const article = fullArticle || selectedItem;

  return (
    <div className="batch-processing">
      <div className="batch-header">
        <h2>AI-Assisted Queue Processing</h2>
        {onClose && (
          <button className="admin-close-btn" onClick={onClose}>&times;</button>
        )}
      </div>

      {message && (
        <div className={`settings-message ${message.type}`}>
          {message.text}
        </div>
      )}

      {/* Operations Bar */}
      {!hideOpsBar && (
        <OperationsBar
          expanded={opsExpanded}
          onToggle={handleOpsToggle}
          onOperationComplete={handleOperationComplete}
        />
      )}

      {/* Tier Tabs */}
      <div className="tier-tabs">
        {(['high', 'medium', 'low'] as const).map(tier => (
          <button
            key={tier}
            className={`tier-tab ${selectedTier === tier ? 'active' : ''} tier-${tier}`}
            onClick={() => {
              setSelectedTier(tier);
              setSelectedItem(null);
              setFullArticle(null);
              setEditMode(false);
              setEditData({});
              setSuggestions([]);
            }}
          >
            <span className="tier-name">{tier.charAt(0).toUpperCase() + tier.slice(1)}</span>
            <span className="tier-count">{tieredQueue[tier].length}</span>
          </button>
        ))}
      </div>

      <div className="tier-info">
        <p>{getTierDescription(selectedTier)}</p>
      </div>

      {/* Bulk Actions */}
      <div className="bulk-actions">
        <button
          className="action-btn approve"
          onClick={() => setConfirmAction({ type: 'bulk-approve', tier: selectedTier, count: currentItems.length })}
          disabled={processing || currentItems.length === 0 || !!confirmAction}
        >
          {processing ? 'Processing...' : `Approve All ${currentItems.length} Items`}
        </button>
        <button
          className="action-btn reject"
          onClick={() => {
            setRejectReason('');
            setConfirmAction({ type: 'bulk-reject', tier: selectedTier, count: currentItems.length });
          }}
          disabled={processing || currentItems.length === 0 || !!confirmAction}
        >
          Reject All
        </button>
        <button className="action-btn" onClick={loadTieredQueue} disabled={loading}>
          Refresh
        </button>
      </div>

      {/* Inline Confirmation Dialog */}
      {confirmAction && (
        <div className="bp-confirm-dialog">
          <div className="bp-confirm-content">
            {confirmAction.type === 'bulk-approve' ? (
              <>
                <p>
                  Approve all <strong>{confirmAction.count}</strong> items
                  in the <strong>{confirmAction.tier}</strong> confidence tier?
                </p>
                <p className="bp-confirm-note">
                  This will create incidents from the extracted data.
                </p>
                <div className="bp-confirm-actions">
                  <button className="action-btn approve" onClick={handleBulkApprove} disabled={processing}>
                    {processing ? 'Approving...' : 'Confirm Approve'}
                  </button>
                  <button className="action-btn" onClick={() => setConfirmAction(null)} disabled={processing}>
                    Cancel
                  </button>
                </div>
              </>
            ) : (
              <>
                <p>
                  Reject all <strong>{confirmAction.count}</strong> items
                  in the <strong>{confirmAction.tier}</strong> confidence tier?
                </p>
                <div className="bp-reject-reason">
                  <label>Rejection reason:</label>
                  <input
                    type="text"
                    value={rejectReason}
                    onChange={e => setRejectReason(e.target.value)}
                    placeholder="Enter reason for rejection..."
                    autoFocus
                    onKeyDown={e => { if (e.key === 'Enter' && rejectReason.trim()) handleBulkReject(); }}
                  />
                </div>
                <div className="bp-confirm-actions">
                  <button
                    className="action-btn reject"
                    onClick={handleBulkReject}
                    disabled={processing || !rejectReason.trim()}
                  >
                    {processing ? 'Rejecting...' : 'Confirm Reject'}
                  </button>
                  <button className="action-btn" onClick={() => { setConfirmAction(null); setRejectReason(''); }} disabled={processing}>
                    Cancel
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* Content */}
      <SplitPane
        storageKey="batch-processing"
        defaultLeftWidth={350}
        minLeftWidth={250}
        maxLeftWidth={500}
        left={
          <div className="batch-list">
            {loading ? (
              <div className="loading">Loading queue...</div>
            ) : currentItems.length === 0 ? (
              <div className="empty-state">No items in this tier</div>
            ) : (
              currentItems.map(item => (
                <div
                  key={item.id}
                  className={`batch-item ${selectedItem?.id === item.id ? 'selected' : ''}`}
                  onClick={() => handleSelectItem(item)}
                >
                  <div className="item-header">
                    <span className="item-title">{item.title || 'Untitled'}</span>
                    <span
                      className="item-confidence"
                      style={{ color: getConfidenceColor(item.extraction_confidence) }}
                    >
                      {item.extraction_confidence ? `${(item.extraction_confidence * 100).toFixed(0)}%` : '-'}
                    </span>
                  </div>
                  <div className="item-meta">
                    <span>{item.source_name || 'Unknown source'}</span>
                    {item.published_date && <span>{item.published_date}</span>}
                  </div>
                </div>
              ))
            )}
          </div>
        }
        right={selectedItem ? (
          <div className="batch-detail queue-detail">
            <div className="detail-header">
              <h3>{article?.title || 'Untitled Article'}</h3>
              <div className="header-actions">
                {editMode ? (
                  <>
                    <button className="action-btn small" onClick={() => setEditMode(false)}>
                      Cancel
                    </button>
                  </>
                ) : (
                  <button className="action-btn small primary" onClick={() => setEditMode(true)}>
                    Edit
                  </button>
                )}
                <span
                  className="confidence-badge"
                  style={{ background: getConfidenceColor(fullArticle?.extraction_confidence ?? selectedItem.extraction_confidence) }}
                >
                  {(fullArticle?.extraction_confidence ?? selectedItem.extraction_confidence)
                    ? `${((fullArticle?.extraction_confidence ?? selectedItem.extraction_confidence ?? 0) * 100).toFixed(0)}%`
                    : 'N/A'}
                </span>
              </div>
            </div>

            {loadingArticle ? (
              <div className="loading">Loading article details...</div>
            ) : (
              <>
                {/* Source Section */}
                <div className="detail-section">
                  <h4>Source</h4>
                  {fullArticle?.source_url ? (
                    <a href={fullArticle.source_url} target="_blank" rel="noopener noreferrer">
                      {fullArticle.source_url}
                    </a>
                  ) : (
                    <p>{article?.source_name || 'Unknown'}</p>
                  )}
                  {article?.published_date && (
                    <p>Published: {article.published_date}</p>
                  )}
                </div>

                {/* Edit Form or Extracted Data Display */}
                {editMode ? (
                  <div className="detail-section">
                    <h4>Edit Extracted Data</h4>
                    <DynamicExtractionFields
                      data={editData}
                      onChange={setEditData}
                    />
                  </div>
                ) : (
                  /* Extracted Data Section */
                  fullArticle?.extracted_data && (
                    (fullArticle.extracted_data as Record<string, unknown>)?.incident ||
                    (fullArticle.extracted_data as Record<string, unknown>)?.actors ? (
                      <ExtractionDetailView
                        data={fullArticle.extracted_data as unknown as UniversalExtractionData}
                        articleContent={fullArticle.content}
                        sourceUrl={fullArticle.source_url}
                      />
                    ) : (
                      <div className="detail-section">
                        <h4>Extracted Data</h4>
                        <ExtractionTable data={fullArticle.extracted_data as Record<string, unknown>} />
                      </div>
                    )
                  )
                )}

                {/* AI Suggestions */}
                {!editMode && (
                  <div className="detail-section">
                    <h4>AI Suggestions</h4>
                    {loadingSuggestions ? (
                      <p className="loading-text">Loading suggestions...</p>
                    ) : suggestions.length === 0 ? (
                      <p className="no-data">No suggestions - all fields have high confidence</p>
                    ) : (
                      <div className="suggestions-list">
                        {suggestions.map(suggestion => (
                          <div key={suggestion.field} className="suggestion-item">
                            <div className="suggestion-header">
                              <span className="field-name">{suggestion.field}</span>
                              <span
                                className="field-confidence"
                                style={{ color: getConfidenceColor(suggestion.confidence) }}
                              >
                                {(suggestion.confidence * 100).toFixed(0)}%
                              </span>
                            </div>
                            <div className="suggestion-content">
                              <div className="current-value">
                                <span className="label">Current:</span>
                                <span className="value">{String(suggestion.current_value) || 'Empty'}</span>
                              </div>
                              {suggestion.suggestion != null && (
                                <div className="suggested-value">
                                  <span className="label">Suggested:</span>
                                  <span className="value">{String(suggestion.suggestion)}</span>
                                </div>
                              )}
                              <p className="reason">{suggestion.reason}</p>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* Article Content */}
                {fullArticle?.content && (
                  <div className="detail-section">
                    <h4>Article Content</h4>
                    <div className="article-content">
                      <HighlightedArticle
                        content={fullArticle.content}
                        highlights={fullArticle.extracted_data ? collectHighlightsFromRecord(fullArticle.extracted_data as Record<string, unknown>) : []}
                      />
                    </div>
                  </div>
                )}
              </>
            )}

            <div className="detail-actions">
              <button
                className="action-btn approve"
                onClick={handleApprove}
                disabled={processing}
              >
                {processing ? 'Processing...' : editMode ? 'Save & Approve' : 'Approve & Create Incident'}
              </button>
              <div className="bp-inline-reject">
                <input
                  type="text"
                  className="bp-reject-input"
                  value={rejectReason}
                  onChange={e => setRejectReason(e.target.value)}
                  placeholder="Rejection reason..."
                  onKeyDown={e => { if (e.key === 'Enter' && rejectReason.trim()) handleReject(); }}
                />
                <button
                  className="action-btn reject"
                  onClick={() => handleReject()}
                  disabled={processing || !rejectReason.trim()}
                >
                  Reject
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="batch-detail empty">
            <p>Select an item to view details and AI suggestions</p>
          </div>
        )}
      />
    </div>
  );
}

// Priority fields shown first in display order
const PRIORITY_FIELDS = [
  'date', 'state', 'city', 'incident_type', 'description',
  'person_name', 'victim_name', 'offender_name', 'defendant_name',
];

// Metadata fields excluded from display
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

// Dynamic extraction table component
function ExtractionTable({ data: rawData }: { data: Record<string, unknown> | string }) {
  // Safety: parse if the API returned a JSON string
  const data: Record<string, unknown> = typeof rawData === 'string'
    ? (() => { try { return JSON.parse(rawData); } catch { return {}; } })()
    : rawData;

  const getConfidenceColor = (confidence?: number): string => {
    if (!confidence) return 'var(--text-muted)';
    if (confidence >= 0.8) return '#22c55e';
    if (confidence >= 0.5) return '#eab308';
    return '#ef4444';
  };

  // Build ordered field list: priority fields first, then remaining alphabetically
  const allKeys = Object.keys(data).filter(k =>
    !isExcludedField(k) &&
    data[k] !== undefined && data[k] !== null && data[k] !== ''
  );

  const priorityKeys = PRIORITY_FIELDS.filter(k => allKeys.includes(k));
  const remainingKeys = allKeys
    .filter(k => !PRIORITY_FIELDS.includes(k))
    .sort();
  const orderedKeys = [...priorityKeys, ...remainingKeys];

  return (
    <table className="extraction-table">
      <tbody>
        {orderedKeys.map(key => {
          const value = data[key];
          const confKey = `${key}_confidence`;
          const confidence = typeof data[confKey] === 'number' ? data[confKey] as number : undefined;

          let displayValue: string;
          if (typeof value === 'boolean') {
            displayValue = value ? 'Yes' : 'No';
          } else if (Array.isArray(value)) {
            displayValue = value.join(', ');
          } else if (typeof value === 'object' && value !== null) {
            displayValue = JSON.stringify(value);
          } else {
            displayValue = String(value);
          }

          return (
            <tr key={key}>
              <td className="field-label">{snakeCaseToLabel(key)}</td>
              <td className="field-value">{displayValue}</td>
              {confidence !== undefined && (
                <td className="field-confidence" style={{ color: getConfidenceColor(confidence) }}>
                  {(confidence * 100).toFixed(0)}%
                </td>
              )}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export default BatchProcessing;
