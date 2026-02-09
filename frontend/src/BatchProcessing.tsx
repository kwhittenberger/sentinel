import { useState, useEffect, useCallback, useRef } from 'react';
import type { ExtractedIncidentData, UniversalExtractionData } from './types';
import type { ArticleAuditItem, CategoryFieldsByDomain } from './api';
import { fetchArticleAudit, reExtractArticle, rejectArticle, saveArticleEdits, fetchCategoryFields } from './api';
import { SplitPane } from './SplitPane';
import { ExtractionDetailView } from './ExtractionDetailView';
import { HighlightedArticle, collectHighlightsFromRecord, type SourceSpans } from './articleHighlight';
import { OperationsBar } from './OperationsBar';
import { DynamicExtractionFields, buildEditData, parseExtractedData, PRIORITY_FIELDS, isExcludedField, snakeCaseToLabel } from './DynamicExtractionFields';
import { ArticleContextMenu } from './ArticleContextMenu';

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

const COMMON_REJECT_REASONS = [
  'Not relevant to tracked domains',
  'Duplicate of existing incident',
  'Insufficient detail for incident creation',
  'Opinion/editorial — not a news report',
  'Event outside geographic scope',
  'Event outside time scope',
  'Unable to verify core facts',
];

interface BatchProcessingProps {
  onClose?: () => void;
  onRefresh?: () => void;
  hideOpsBar?: boolean;
}

export function BatchProcessing({ onClose, onRefresh, hideOpsBar }: BatchProcessingProps) {
  const [loading, setLoading] = useState(true);
  const [tieredQueue, setTieredQueue] = useState<TieredQueue>({ high: [], medium: [], low: [] });
  const [selectedTier, setSelectedTier] = useState<'high' | 'medium' | 'low' | 'issues'>('high');
  const [selectedItem, setSelectedItem] = useState<TieredItem | null>(null);
  const [fullArticle, setFullArticle] = useState<FullArticle | null>(null);

  // Issues tab state
  const [issuesItems, setIssuesItems] = useState<ArticleAuditItem[]>([]);
  const [issuesLoading, setIssuesLoading] = useState(false);
  const [selectedIssueItem, setSelectedIssueItem] = useState<ArticleAuditItem | null>(null);
  const [issueActionLoading, setIssueActionLoading] = useState(false);
  const issuesLoadedRef = useRef(false);
  const [loadingArticle, setLoadingArticle] = useState(false);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [categoryFieldsData, setCategoryFieldsData] = useState<CategoryFieldsByDomain | null>(null);

  // AbortController for in-flight article/suggestion fetches
  const fetchControllerRef = useRef<AbortController | null>(null);

  // Timer ref for auto-dismissing messages
  const messageTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showMessage = useCallback((msg: { type: 'success' | 'error'; text: string } | null) => {
    if (messageTimerRef.current) {
      clearTimeout(messageTimerRef.current);
      messageTimerRef.current = null;
    }
    setMessage(msg);
    if (msg) {
      messageTimerRef.current = setTimeout(() => {
        setMessage(null);
        messageTimerRef.current = null;
      }, 5000);
    }
  }, []);

  // Clean up message timer on unmount
  useEffect(() => {
    return () => {
      if (messageTimerRef.current) {
        clearTimeout(messageTimerRef.current);
      }
    };
  }, []);

  // Fetch category fields once on mount (for context menu grouping)
  useEffect(() => {
    fetchCategoryFields()
      .then(setCategoryFieldsData)
      .catch(() => {}); // graceful fallback to flat list
  }, []);

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

  // Article content refs for context menu
  const tieredArticleRef = useRef<HTMLDivElement>(null);
  const issuesArticleRef = useRef<HTMLDivElement>(null);

  const handleAssignField = useCallback((fieldKey: string, value: string, append?: boolean) => {
    setEditMode(true);
    setEditData(prev => {
      if (!append) return { ...prev, [fieldKey]: value };
      const existing = prev[fieldKey];
      if (Array.isArray(existing)) return { ...prev, [fieldKey]: [...existing, value] };
      if (typeof existing === 'string' && existing) return { ...prev, [fieldKey]: `${existing}, ${value}` };
      return { ...prev, [fieldKey]: value };
    });
  }, []);

  const handleSave = async () => {
    if (!selectedItem || !editMode) return;
    setProcessing(true);
    try {
      await saveArticleEdits(selectedItem.id, editData);
      showMessage({ type: 'success', text: 'Changes saved' });
    } catch (err) {
      showMessage({ type: 'error', text: `Failed to save: ${err instanceof Error ? err.message : 'Network error'}` });
    } finally {
      setProcessing(false);
    }
  };

  // Duplicate detection dialog state
  const [duplicateInfo, setDuplicateInfo] = useState<{
    articleId: string;
    message: string;
    confidence: number | null;
    existingIncidentId: string | null;
    existingDate: string | null;
    existingLocation: string | null;
    existingName: string | null;
    existingSource: string | null;
  } | null>(null);

  const loadTieredQueue = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE}/admin/queue/tiered`);
      if (response.ok) {
        const data = await response.json();
        setTieredQueue(data);
      }
    } catch {
      showMessage({ type: 'error', text: 'Failed to load queue' });
    } finally {
      setLoading(false);
    }
  }, [showMessage]);

  useEffect(() => {
    loadTieredQueue();
  }, [loadTieredQueue]);

  // Abort in-flight fetches on unmount
  useEffect(() => {
    return () => {
      if (fetchControllerRef.current) {
        fetchControllerRef.current.abort();
      }
    };
  }, []);

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

  const loadFullArticle = async (articleId: string, signal: AbortSignal) => {
    setLoadingArticle(true);
    setFullArticle(null);
    setEditMode(false);
    try {
      const response = await fetch(`${API_BASE}/admin/queue/${articleId}`, { signal });
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
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      // Will show limited info from selectedItem
    } finally {
      if (!signal.aborted) {
        setLoadingArticle(false);
      }
    }
  };

  const loadSuggestions = async (articleId: string, signal: AbortSignal) => {
    setLoadingSuggestions(true);
    setSuggestions([]);
    try {
      const response = await fetch(`${API_BASE}/admin/queue/${articleId}/suggestions`, { signal });
      if (response.ok) {
        const data = await response.json();
        setSuggestions(data.suggestions || []);
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      // Suggestions are optional, don't show error
    } finally {
      if (!signal.aborted) {
        setLoadingSuggestions(false);
      }
    }
  };

  const handleSelectItem = (item: TieredItem) => {
    // Abort any in-flight fetches from previous selection
    if (fetchControllerRef.current) {
      fetchControllerRef.current.abort();
    }
    const controller = new AbortController();
    fetchControllerRef.current = controller;

    setSelectedItem(item);
    setFullArticle(null);
    setEditMode(false);
    setEditData({});
    loadFullArticle(item.id, controller.signal);
    loadSuggestions(item.id, controller.signal);
  };

  const handleApprove = async (forceCreate?: boolean, linkToExistingId?: string) => {
    if (!selectedItem) return;
    setProcessing(true);
    try {
      const overrides = editMode ? editData : undefined;
      const response = await fetch(`${API_BASE}/admin/queue/${selectedItem.id}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          overrides: overrides || null,
          force_create: forceCreate || false,
          link_to_existing_id: linkToExistingId || null,
        }),
      });
      const data = await response.json().catch(() => {
        if (!response.ok) return { error: `Server error (HTTP ${response.status})` };
        return {};
      });

      // Handle duplicate detection
      if (data.error === 'duplicate_detected') {
        setDuplicateInfo({
          articleId: selectedItem.id,
          message: data.message || 'Potential duplicate detected',
          confidence: data.confidence ?? null,
          existingIncidentId: data.existing_incident_id ?? null,
          existingDate: data.existing_date ?? null,
          existingLocation: data.existing_location ?? null,
          existingName: data.existing_name ?? null,
          existingSource: data.existing_source ?? null,
        });
        setProcessing(false);
        return;
      }

      if (response.ok && data.success !== false) {
        showMessage({ type: 'success', text: 'Article approved' });
        const wasIssue = selectedTier === 'issues';
        setSelectedItem(null);
        setSelectedIssueItem(null);
        setFullArticle(null);
        setEditMode(false);
        setEditData({});
        setDuplicateInfo(null);
        setSuggestions([]);
        if (wasIssue) {
          loadIssues();
        } else {
          loadTieredQueue();
        }
        onRefresh?.();
      } else {
        showMessage({ type: 'error', text: data.error || data.detail || 'Failed to approve' });
      }
    } catch (err) {
      showMessage({ type: 'error', text: `Failed to approve: ${err instanceof Error ? err.message : 'Network error'}` });
    } finally {
      setProcessing(false);
    }
  };

  const handleDuplicateLink = () => {
    if (duplicateInfo?.existingIncidentId) {
      setDuplicateInfo(null);
      handleApprove(false, duplicateInfo.existingIncidentId);
    }
  };

  const handleDuplicateCreateNew = () => {
    setDuplicateInfo(null);
    handleApprove(true);
  };

  const handleDuplicateCancel = () => {
    setDuplicateInfo(null);
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
        showMessage({ type: 'success', text: 'Article rejected' });
        const wasIssue = selectedTier === 'issues';
        setSelectedItem(null);
        setSelectedIssueItem(null);
        setFullArticle(null);
        setEditMode(false);
        setEditData({});
        setRejectReason('');
        setSuggestions([]);
        if (wasIssue) {
          loadIssues();
        } else {
          loadTieredQueue();
        }
      } else {
        const data = await response.json().catch(() => null);
        showMessage({ type: 'error', text: `Failed to reject: ${data?.detail || data?.error || `HTTP ${response.status}`}` });
      }
    } catch (err) {
      showMessage({ type: 'error', text: `Failed to reject: ${err instanceof Error ? err.message : 'Network error'}` });
    } finally {
      setProcessing(false);
    }
  };

  const handleBulkApprove = async () => {
    setProcessing(true);
    showMessage(null);
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
      const data = await response.json().catch(() => null);
      if (response.ok && data) {
        if (data.errors > 0) {
          const details = (data.error_details || []).join('\n');
          showMessage({
            type: 'error',
            text: `Approved ${data.approved_count} items, ${data.errors} failed:\n${details}`,
          });
        } else {
          showMessage({ type: 'success', text: `Approved ${data.approved_count} items` });
        }
        loadTieredQueue();
        onRefresh?.();
      } else {
        const detail = data?.detail || data?.message || `HTTP ${response.status}`;
        showMessage({ type: 'error', text: `Bulk approve failed: ${detail}` });
      }
    } catch (err) {
      showMessage({ type: 'error', text: `Bulk approve failed: ${err instanceof Error ? err.message : 'Network error'}` });
    } finally {
      setProcessing(false);
    }
  };

  const handleBulkReject = async () => {
    if (!rejectReason.trim()) return;

    setProcessing(true);
    showMessage(null);
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
      const data = await response.json().catch(() => null);
      if (response.ok && data) {
        showMessage({ type: 'success', text: `Rejected ${data.rejected_count} items` });
        setRejectReason('');
        loadTieredQueue();
      } else {
        const detail = data?.detail || data?.message || `HTTP ${response.status}`;
        showMessage({ type: 'error', text: `Bulk reject failed: ${detail}` });
      }
    } catch (err) {
      showMessage({ type: 'error', text: `Bulk reject failed: ${err instanceof Error ? err.message : 'Network error'}` });
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

  const getTierDescription = (tier: 'high' | 'medium' | 'low' | 'issues'): string => {
    switch (tier) {
      case 'high':
        return 'High confidence (85%+) - Auto-approve candidates';
      case 'medium':
        return 'Medium confidence (50-85%) - Quick review needed';
      case 'low':
        return 'Low confidence (<50%) - Full review required';
      case 'issues':
        return 'Articles needing attention — errors, missing fields, or data quality issues';
    }
  };

  // Issues tab helpers
  const getIssueDescriptions = (article: ArticleAuditItem): string[] => {
    const issues: string[] = [];
    if (article.status === 'error') {
      issues.push('Processing error — needs re-extraction or manual review');
    }
    if (article.status === 'approved' && !article.incident_id) {
      issues.push('Approved but not linked to incident');
    }
    if (article.extraction_format === 'keyword_only') {
      issues.push('Keyword-only extraction (needs LLM re-extraction)');
    }
    if (!article.has_required_fields) {
      issues.push(`Missing required fields: ${article.missing_fields.join(', ')}`);
    }
    return issues;
  };

  const getFormatBadge = (format: string): { label: string; color: string } => {
    switch (format) {
      case 'llm': return { label: 'LLM', color: '#22c55e' };
      case 'keyword_only': return { label: 'Keywords', color: '#ef4444' };
      case 'none': return { label: 'No Extraction', color: '#888' };
      default: return { label: 'Unknown', color: '#888' };
    }
  };

  const getStatusColor = (status: string): string => {
    switch (status) {
      case 'approved': return '#22c55e';
      case 'pending': return '#eab308';
      case 'in_review': return '#3b82f6';
      case 'rejected': return '#ef4444';
      case 'error': return '#ef4444';
      default: return '#888';
    }
  };

  const loadIssues = useCallback(async () => {
    setIssuesLoading(true);
    try {
      const data = await fetchArticleAudit({ issues_only: true });
      setIssuesItems(data.articles || []);
    } catch {
      showMessage({ type: 'error', text: 'Failed to load issues' });
    } finally {
      setIssuesLoading(false);
    }
  }, [showMessage]);

  // Lazy-load issues on first tab selection
  useEffect(() => {
    if (selectedTier === 'issues' && !issuesLoadedRef.current) {
      issuesLoadedRef.current = true;
      loadIssues();
    }
  }, [selectedTier, loadIssues]);

  const handleIssueReExtract = async (articleId: string) => {
    setIssueActionLoading(true);
    try {
      await reExtractArticle(articleId);
      showMessage({ type: 'success', text: 'Re-extraction started' });
      setSelectedIssueItem(null);
      setSelectedItem(null);
      setFullArticle(null);
      setEditMode(false);
      setEditData({});
      setSuggestions([]);
      await loadIssues();
    } catch (err) {
      showMessage({ type: 'error', text: err instanceof Error ? err.message : 'Re-extraction failed' });
    } finally {
      setIssueActionLoading(false);
    }
  };

  const handleIssueReject = async (articleId: string) => {
    if (!rejectReason.trim()) return;
    setIssueActionLoading(true);
    try {
      await rejectArticle(articleId, rejectReason);
      showMessage({ type: 'success', text: 'Article rejected' });
      setSelectedIssueItem(null);
      setSelectedItem(null);
      setFullArticle(null);
      setEditMode(false);
      setEditData({});
      setSuggestions([]);
      setRejectReason('');
      await loadIssues();
    } catch (err) {
      showMessage({ type: 'error', text: err instanceof Error ? err.message : 'Rejection failed' });
    } finally {
      setIssueActionLoading(false);
    }
  };

  const handleSelectIssueItem = (item: ArticleAuditItem) => {
    // Abort any in-flight fetches from previous selection
    if (fetchControllerRef.current) {
      fetchControllerRef.current.abort();
    }
    const controller = new AbortController();
    fetchControllerRef.current = controller;

    setSelectedIssueItem(item);
    setRejectReason('');
    setEditMode(false);

    // Parse and initialize edit data from the issue item's extracted_data
    const parsed = parseExtractedData(item.extracted_data);
    setEditData(buildEditData(parsed));

    // Set selectedItem so handleApprove/handleReject/duplicate detection works
    setSelectedItem({
      id: item.id,
      title: item.title,
      source_name: item.source_name,
      extraction_confidence: item.extraction_confidence,
      published_date: item.published_date ?? undefined,
    });

    // Also populate fullArticle so the approve flow has extraction data
    setFullArticle({
      id: item.id,
      title: item.title,
      source_name: item.source_name,
      source_url: item.source_url,
      content: item.content,
      published_date: item.published_date ?? undefined,
      extraction_confidence: item.extraction_confidence ?? undefined,
      extracted_data: parsed as ExtractedIncidentData,
      status: item.status,
    });

    // Fetch AI suggestions
    loadSuggestions(item.id, controller.signal);
  };

  const currentItems = selectedTier !== 'issues' ? tieredQueue[selectedTier] : [];
  const article = fullArticle || selectedItem;

  return (
    <div className="batch-processing">
      <div className="batch-header">
        <h2>AI-Assisted Queue Processing</h2>
        {onClose && (
          <button className="admin-close-btn" onClick={onClose} aria-label="Close batch processing">&times;</button>
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
              setSelectedIssueItem(null);
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
        <button
          className={`tier-tab ${selectedTier === 'issues' ? 'active' : ''} tier-issues`}
          onClick={() => {
            setSelectedTier('issues');
            setSelectedItem(null);
            setSelectedIssueItem(null);
            setFullArticle(null);
            setEditMode(false);
            setEditData({});
            setSuggestions([]);
          }}
        >
          <span className="tier-name">Issues</span>
          <span className="tier-count">{issuesItems.length}</span>
        </button>
      </div>

      <div className="tier-info">
        <p>{getTierDescription(selectedTier)}</p>
      </div>

      {/* Bulk Actions */}
      <div className="bulk-actions">
        {selectedTier !== 'issues' ? (
          <>
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
          </>
        ) : (
          <button className="action-btn" onClick={() => { issuesLoadedRef.current = false; loadIssues(); }} disabled={issuesLoading}>
            {issuesLoading ? 'Refreshing...' : 'Refresh'}
          </button>
        )}
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

      {/* Duplicate Detection Dialog */}
      {duplicateInfo && (
        <div className="bp-confirm-dialog">
          <div className="bp-confirm-content">
            <p><strong>Potential Duplicate Detected</strong></p>
            <p>{duplicateInfo.message}</p>
            {duplicateInfo.confidence != null && (
              <p>Match confidence: <strong>{(duplicateInfo.confidence * 100).toFixed(0)}%</strong></p>
            )}
            <div className="bp-duplicate-details">
              {duplicateInfo.existingDate && (
                <p>Date: {duplicateInfo.existingDate}</p>
              )}
              {duplicateInfo.existingLocation && (
                <p>Location: {duplicateInfo.existingLocation}</p>
              )}
              {duplicateInfo.existingName && (
                <p>Matched person: {duplicateInfo.existingName}</p>
              )}
              {duplicateInfo.existingSource && (
                <p>Original source: {duplicateInfo.existingSource.length > 80
                  ? duplicateInfo.existingSource.substring(0, 80) + '...'
                  : duplicateInfo.existingSource}</p>
              )}
            </div>
            <div className="bp-confirm-actions">
              {duplicateInfo.existingIncidentId && (
                <button className="action-btn approve" onClick={handleDuplicateLink} disabled={processing}>
                  Link to Existing
                </button>
              )}
              <button className="action-btn primary" onClick={handleDuplicateCreateNew} disabled={processing}>
                Create New Anyway
              </button>
              <button className="action-btn" onClick={handleDuplicateCancel} disabled={processing}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Content */}
      {selectedTier === 'issues' ? (
        <SplitPane
          storageKey="batch-issues"
          defaultLeftWidth={400}
          minLeftWidth={300}
          maxLeftWidth={600}
          left={
            <div className="batch-list">
              {issuesLoading ? (
                <div className="loading">Loading issues...</div>
              ) : issuesItems.length === 0 ? (
                <div className="empty-state">No articles with issues</div>
              ) : (
                issuesItems.map(item => {
                  const formatBadge = getFormatBadge(item.extraction_format);
                  const issues = getIssueDescriptions(item);
                  return (
                    <div
                      key={item.id}
                      className={`batch-item warning ${selectedIssueItem?.id === item.id ? 'selected' : ''}`}
                      onClick={() => handleSelectIssueItem(item)}
                    >
                      <div className="item-header">
                        <span className="item-title">{item.title || 'Untitled'}</span>
                        <span className="warning-icon">&#9888;</span>
                      </div>
                      <div className="item-meta">
                        <span className="badge" style={{ background: getStatusColor(item.status) }}>
                          {item.status}
                        </span>
                        <span className="badge" style={{ background: formatBadge.color }}>
                          {formatBadge.label}
                        </span>
                        {item.extraction_confidence !== null && (
                          <span className="badge" style={{ background: getConfidenceColor(item.extraction_confidence) }}>
                            {(item.extraction_confidence * 100).toFixed(0)}%
                          </span>
                        )}
                      </div>
                      {issues.length > 0 && (
                        <div className="item-issues">
                          {issues.map((issue, idx) => (
                            <div key={idx} className="issue-tag">{'\u2022'} {issue}</div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          }
          right={selectedIssueItem ? (
            <div className="batch-detail queue-detail">
              <div className="detail-header">
                <h3>{selectedIssueItem.title || 'Untitled Article'}</h3>
                <div className="header-actions">
                  {editMode ? (
                    <button className="action-btn small" onClick={() => setEditMode(false)}>
                      Cancel
                    </button>
                  ) : (
                    <button className="action-btn small primary" onClick={() => setEditMode(true)}>
                      Edit
                    </button>
                  )}
                  <span
                    className="confidence-badge"
                    style={{ background: getConfidenceColor(selectedIssueItem.extraction_confidence) }}
                  >
                    {selectedIssueItem.extraction_confidence != null
                      ? `${(selectedIssueItem.extraction_confidence * 100).toFixed(0)}%`
                      : 'N/A'}
                  </span>
                </div>
              </div>

              {/* Issues Summary */}
              {getIssueDescriptions(selectedIssueItem).length > 0 && (
                <div className="detail-section warning-section">
                  <h4>Issues Detected</h4>
                  <ul>
                    {getIssueDescriptions(selectedIssueItem).map((issue, idx) => (
                      <li key={idx}>{issue}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Source Info */}
              <div className="detail-section">
                <h4>Source</h4>
                <p><strong>Source:</strong> {selectedIssueItem.source_name}</p>
                <p>
                  <strong>URL:</strong>{' '}
                  <a href={selectedIssueItem.source_url} target="_blank" rel="noopener noreferrer">
                    {selectedIssueItem.source_url}
                  </a>
                </p>
                <p><strong>Published:</strong> {selectedIssueItem.published_date || 'Unknown'}</p>
                {selectedIssueItem.incident_id && (
                  <p><strong>Incident ID:</strong> {selectedIssueItem.incident_id}</p>
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
                selectedIssueItem.extracted_data && Object.keys(selectedIssueItem.extracted_data).length > 0 && (
                  (selectedIssueItem.extracted_data as Record<string, unknown>)?.incident ||
                  (selectedIssueItem.extracted_data as Record<string, unknown>)?.actors ? (
                    <ExtractionDetailView
                      data={selectedIssueItem.extracted_data as unknown as UniversalExtractionData}
                      articleContent={selectedIssueItem.content}
                      sourceUrl={selectedIssueItem.source_url}
                    />
                  ) : (
                    <div className="detail-section">
                      <h4>Extracted Data</h4>
                      <ExtractionTable data={selectedIssueItem.extracted_data} />
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
              <div className="detail-section">
                <h4>Article Content</h4>
                <div className="article-content" ref={issuesArticleRef}>
                  {selectedIssueItem.content ? (() => {
                    const rawData = parseExtractedData(selectedIssueItem.extracted_data);
                    const spans = rawData?.source_spans as SourceSpans | undefined;
                    return (
                      <HighlightedArticle
                        content={selectedIssueItem.content}
                        highlights={collectHighlightsFromRecord(editData, spans)}
                      />
                    );
                  })() : (
                    <p className="no-data">No content available</p>
                  )}
                </div>
                <ArticleContextMenu
                  containerRef={issuesArticleRef}
                  editData={editData}
                  onAssignField={handleAssignField}
                  categoryFields={categoryFieldsData}
                />
              </div>

              {/* Actions */}
              <div className="detail-actions">
                <div className="detail-actions-row">
                  {editMode && (
                    <button
                      className="action-btn"
                      onClick={handleSave}
                      disabled={processing || issueActionLoading}
                    >
                      {processing ? 'Saving...' : 'Save'}
                    </button>
                  )}
                  <button
                    className="action-btn approve"
                    onClick={() => handleApprove()}
                    disabled={processing || issueActionLoading}
                  >
                    {processing ? 'Processing...' : editMode ? 'Save & Approve' : 'Approve & Create Incident'}
                  </button>
                  {(selectedIssueItem.extraction_format !== 'llm' || !selectedIssueItem.has_required_fields) && (
                    <button
                      className="action-btn"
                      disabled={issueActionLoading || processing}
                      onClick={() => handleIssueReExtract(selectedIssueItem.id)}
                    >
                      {issueActionLoading ? 'Processing...' : 'Re-extract'}
                    </button>
                  )}
                </div>
                {selectedIssueItem.status !== 'rejected' && (
                  <div className="bp-inline-reject">
                    <select
                      className="bp-reject-select"
                      value={COMMON_REJECT_REASONS.includes(rejectReason) ? rejectReason : rejectReason ? '__other__' : ''}
                      onChange={e => setRejectReason(e.target.value === '__other__' ? '' : e.target.value)}
                    >
                      <option value="">Select reason...</option>
                      {COMMON_REJECT_REASONS.map(r => (
                        <option key={r} value={r}>{r}</option>
                      ))}
                      <option value="__other__">Other...</option>
                    </select>
                    {!COMMON_REJECT_REASONS.includes(rejectReason) && (
                      <input
                        type="text"
                        className="bp-reject-input"
                        value={rejectReason}
                        onChange={e => setRejectReason(e.target.value)}
                        placeholder="Enter reason..."
                        onKeyDown={e => { if (e.key === 'Enter' && rejectReason.trim()) handleIssueReject(selectedIssueItem.id); }}
                      />
                    )}
                    <button
                      className="action-btn reject"
                      onClick={() => handleIssueReject(selectedIssueItem.id)}
                      disabled={issueActionLoading || !rejectReason.trim()}
                    >
                      Reject
                    </button>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="batch-detail empty">
              <p>Select an article to view details</p>
            </div>
          )}
        />
      ) : (
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
                      <div className="article-content" ref={tieredArticleRef}>
                        {(() => {
                          const rawData = fullArticle.extracted_data as Record<string, unknown> | undefined;
                          const spans = rawData?.source_spans as SourceSpans | undefined;
                          return (
                            <HighlightedArticle
                              content={fullArticle.content}
                              highlights={collectHighlightsFromRecord(editData, spans)}
                            />
                          );
                        })()}
                      </div>
                      <ArticleContextMenu
                        containerRef={tieredArticleRef}
                        editData={editData}
                        onAssignField={handleAssignField}
                        categoryFields={categoryFieldsData}
                      />
                    </div>
                  )}
                </>
              )}

              <div className="detail-actions">
                <div className="detail-actions-row">
                  {editMode && (
                    <button
                      className="action-btn"
                      onClick={handleSave}
                      disabled={processing}
                    >
                      {processing ? 'Saving...' : 'Save'}
                    </button>
                  )}
                  <button
                    className="action-btn approve"
                    onClick={() => handleApprove()}
                    disabled={processing}
                  >
                    {processing ? 'Processing...' : editMode ? 'Save & Approve' : 'Approve & Create Incident'}
                  </button>
                </div>
                <div className="bp-inline-reject">
                  <select
                    className="bp-reject-select"
                    value={COMMON_REJECT_REASONS.includes(rejectReason) ? rejectReason : rejectReason ? '__other__' : ''}
                    onChange={e => setRejectReason(e.target.value === '__other__' ? '' : e.target.value)}
                  >
                    <option value="">Select reason...</option>
                    {COMMON_REJECT_REASONS.map(r => (
                      <option key={r} value={r}>{r}</option>
                    ))}
                    <option value="__other__">Other...</option>
                  </select>
                  {!COMMON_REJECT_REASONS.includes(rejectReason) && (
                    <input
                      type="text"
                      className="bp-reject-input"
                      value={rejectReason}
                      onChange={e => setRejectReason(e.target.value)}
                      placeholder="Enter reason..."
                      onKeyDown={e => { if (e.key === 'Enter' && rejectReason.trim()) handleReject(); }}
                    />
                  )}
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
      )}
    </div>
  );
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
