import { useState, useEffect, useCallback, useRef } from 'react';

const API_BASE = '/api';

interface StageInfo {
  count: number;
  avg_confidence: number;
}

interface ExtractionStatus {
  stages?: {
    need_extraction: StageInfo;
    not_relevant: StageInfo;
    needs_review: StageInfo;
    ready_to_approve: StageInfo;
  };
  by_extraction_type: Array<{
    type: string;
    count: number;
    avg_confidence: number | null;
  }>;
  by_relevance: Array<{
    relevance: string;
    count: number;
  }>;
  by_schema_type?: Array<{
    schema: string;
    count: number;
  }>;
  total_pending: number;
  needs_upgrade?: number;
}

interface BatchResult {
  success: boolean;
  processed?: number;
  extracted?: number;
  relevant?: number;
  not_relevant?: number;
  errors?: number;
  extract_recommended?: number;
  reject_recommended?: number;
  review_recommended?: number;
  auto_rejected?: number;
  rejected_count?: number;
  auto_approved?: number;
  items?: Array<{
    id: string;
    title: string;
    is_relevant?: boolean;
    confidence?: number;
    category?: string;
    error?: string;
    triage?: {
      recommendation: string;
      reason: string;
      is_specific_incident: boolean;
    };
  }>;
  error?: string;
}

interface QueueManagerProps {
  onRefresh?: () => void;
}

export function QueueManager({ onRefresh }: QueueManagerProps) {
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<ExtractionStatus | null>(null);
  const [processing, setProcessing] = useState<string | null>(null);
  const [result, setResult] = useState<BatchResult | null>(null);
  const [batchSize, setBatchSize] = useState(10);
  const [autoReject, setAutoReject] = useState(false);
  const [confirmAction, setConfirmAction] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [progressMessage, setProgressMessage] = useState('');
  const [activeJob, setActiveJob] = useState<{id: string; progress: number; total: number; message: string; status: string} | null>(null);

  const pollCountRef = useRef(0);
  const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const progressIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const unmountedRef = useRef(false);

  // Cleanup all timers on unmount
  useEffect(() => {
    unmountedRef.current = false;
    return () => {
      unmountedRef.current = true;
      if (pollTimeoutRef.current) {
        clearTimeout(pollTimeoutRef.current);
        pollTimeoutRef.current = null;
      }
      if (progressIntervalRef.current) {
        clearInterval(progressIntervalRef.current);
        progressIntervalRef.current = null;
      }
    };
  }, []);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE}/admin/queue/extraction-status`);
      if (response.ok) {
        const data = await response.json();
        setStatus(data);
      }
    } catch (err) {
      console.error('Failed to load status:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  // Poll job status - defined first so checkForActiveJob can reference it
  const pollJobStatus = useCallback(async (jobId: string) => {
    try {
      const response = await fetch(`${API_BASE}/admin/jobs/${jobId}`);
      if (response.ok) {
        const job = await response.json();
        setActiveJob({
          id: jobId,
          progress: job.progress || 0,
          total: job.total || 0,
          message: job.message || 'Processing...',
          status: job.status,
        });

        // Keep polling if still running
        if (job.status === 'running' || job.status === 'pending') {
          // Refresh status cards every 10th poll (~20 seconds)
          pollCountRef.current += 1;
          if (pollCountRef.current % 10 === 0) {
            loadStatus();
          }
          if (!unmountedRef.current) {
            pollTimeoutRef.current = setTimeout(() => pollJobStatus(jobId), 2000);
          }
        } else {
          // Job finished - refresh everything
          pollCountRef.current = 0;
          loadStatus();
          onRefresh?.();
        }
      }
    } catch (err) {
      console.error('Failed to poll job status:', err);
    }
  }, [loadStatus, onRefresh]);

  // Check for existing running extraction jobs on load
  const checkForActiveJob = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/admin/jobs?status=running`);
      if (response.ok) {
        const data = await response.json();
        const extractJob = data.jobs?.find((j: { job_type: string }) => j.job_type === 'batch_extract');
        if (extractJob) {
          setActiveJob({
            id: extractJob.id,
            progress: extractJob.progress || 0,
            total: extractJob.total || 0,
            message: extractJob.message || 'Processing...',
            status: extractJob.status,
          });
          // Start polling
          pollJobStatus(extractJob.id);
        }
      }
    } catch (err) {
      console.error('Failed to check for active jobs:', err);
    }
  }, [pollJobStatus]);

  useEffect(() => {
    loadStatus();
    checkForActiveJob();
  }, [loadStatus, checkForActiveJob]);

  const runBatchExtract = async () => {
    setProcessing('extract');
    setResult(null);

    const estimatedTime = batchSize * 2;
    const completeProgress = startProgress(estimatedTime, 'Running universal extraction...');

    try {
      const response = await fetch(`${API_BASE}/admin/queue/batch-extract`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ limit: batchSize }),
      });
      const data = await response.json();
      completeProgress();
      setResult(data);
      await loadStatus();
      onRefresh?.();
    } catch (err) {
      completeProgress();
      setResult({ success: false, error: String(err) });
    } finally {
      setProcessing(null);
      setProgressMessage('');
    }
  };

  const runUpgradeLegacy = async () => {
    setConfirmAction(null);
    setProcessing('upgrade');
    setResult(null);

    const estimatedTime = batchSize * 2;
    const completeProgress = startProgress(estimatedTime, 'Upgrading to universal schema...');

    try {
      const response = await fetch(`${API_BASE}/admin/queue/batch-extract`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ limit: batchSize, re_extract: true }),
      });
      const data = await response.json();
      completeProgress();
      setResult(data);
      await loadStatus();
      onRefresh?.();
    } catch (err) {
      completeProgress();
      setResult({ success: false, error: String(err) });
    } finally {
      setProcessing(null);
      setProgressMessage('');
    }
  };

  const runTriage = async () => {
    setProcessing('triage');
    setResult(null);

    const estimatedTime = batchSize * 0.5;
    const completeProgress = startProgress(estimatedTime, 'Running quick triage...');

    try {
      const response = await fetch(`${API_BASE}/admin/queue/triage`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ limit: batchSize, auto_reject: autoReject }),
      });
      const data = await response.json();
      completeProgress();
      setResult(data);
      await loadStatus();
      onRefresh?.();
    } catch (err) {
      completeProgress();
      setResult({ success: false, error: String(err) });
    } finally {
      setProcessing(null);
      setProgressMessage('');
    }
  };

  const startProgress = (estimatedSeconds: number, message: string) => {
    setProgress(0);
    setProgressMessage(message);
    const interval = 100; // Update every 100ms
    const increment = 100 / (estimatedSeconds * 1000 / interval);

    // Clear any existing progress interval before starting a new one
    if (progressIntervalRef.current) {
      clearInterval(progressIntervalRef.current);
    }

    const timer = setInterval(() => {
      setProgress(prev => {
        if (prev >= 95) {
          clearInterval(timer);
          progressIntervalRef.current = null;
          return 95; // Cap at 95% until complete
        }
        return prev + increment;
      });
    }, interval);

    progressIntervalRef.current = timer;

    return () => {
      clearInterval(timer);
      progressIntervalRef.current = null;
      setProgress(100);
    };
  };

  const runFullPipeline = async () => {
    setConfirmAction(null);
    setProcessing('pipeline');
    setResult(null);

    const estimatedTime = batchSize * 2.5; // ~2.5 seconds per item for full pipeline
    const completeProgress = startProgress(estimatedTime, 'Running triage...');

    try {
      // Step 1: Triage with auto-reject
      setProgressMessage('Step 1/3: Triaging articles...');
      const triageResponse = await fetch(`${API_BASE}/admin/queue/triage`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ limit: batchSize, auto_reject: true }),
      });
      const triageData = await triageResponse.json();

      if (!triageData.success) {
        completeProgress();
        setResult(triageData);
        return;
      }

      // Step 2: Extract the ones recommended for extraction
      const extractCount = triageData.extract_recommended || 0;
      let extractData = null;

      if (extractCount > 0) {
        setProgressMessage(`Step 2/3: Extracting ${extractCount} articles...`);
        const extractResponse = await fetch(`${API_BASE}/admin/queue/batch-extract`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ limit: extractCount }),
        });
        extractData = await extractResponse.json();
      }

      // Step 3: Auto-approve high confidence items
      setProgressMessage('Step 3/3: Auto-approving high confidence...');
      let approveData = null;
      try {
        const approveResponse = await fetch(`${API_BASE}/admin/queue/bulk-approve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tier: 'high', limit: batchSize }),
        });
        approveData = await approveResponse.json();
      } catch {
        // Auto-approve is optional, don't fail the whole pipeline
      }

      completeProgress();

      // Combine results
      setResult({
        success: true,
        processed: triageData.processed || 0,
        extract_recommended: triageData.extract_recommended,
        reject_recommended: triageData.reject_recommended,
        review_recommended: triageData.review_recommended,
        auto_rejected: triageData.auto_rejected,
        extracted: extractData?.extracted || 0,
        relevant: extractData?.relevant || 0,
        not_relevant: extractData?.not_relevant || 0,
        auto_approved: approveData?.approved || 0,
        items: extractData?.items || triageData.items,
      });

      await loadStatus();
      onRefresh?.();
    } catch (err) {
      completeProgress();
      setResult({ success: false, error: String(err) });
    } finally {
      setProcessing(null);
      setProgressMessage('');
    }
  };

  const queueAllForExtraction = async () => {
    setConfirmAction(null);
    setProcessing('queue-all');
    setResult(null);

    try {
      const response = await fetch(`${API_BASE}/admin/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_type: 'batch_extract',
          params: { limit: needsExtraction }
        }),
      });
      const data = await response.json();

      if (data.success) {
        // Start tracking the job
        setActiveJob({
          id: data.job_id,
          progress: 0,
          total: needsExtraction,
          message: 'Starting extraction...',
          status: 'pending',
        });
        // Start polling for updates
        pollTimeoutRef.current = setTimeout(() => pollJobStatus(data.job_id), 1000);
      } else {
        setResult({ success: false, error: data.error });
      }
    } catch (err) {
      setResult({ success: false, error: String(err) });
    } finally {
      setProcessing(null);
    }
  };

  const rejectNotRelevant = async () => {
    setConfirmAction(null);
    setProcessing('reject');
    setResult(null);

    const completeProgress = startProgress(3, 'Rejecting not relevant items...');

    try {
      const response = await fetch(`${API_BASE}/admin/queue/bulk-reject-by-criteria`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reject_not_relevant: true }),
      });
      const data = await response.json();
      completeProgress();
      setResult(data);
      await loadStatus();
      onRefresh?.();
    } catch (err) {
      completeProgress();
      setResult({ success: false, error: String(err) });
    } finally {
      setProcessing(null);
      setProgressMessage('');
    }
  };

  const getTypeLabel = (type: string): string => {
    switch (type) {
      case 'full_extraction': return 'Full LLM Extraction';
      case 'keyword_only': return 'Keyword Matching Only';
      case 'no_extraction': return 'No Extraction';
      case 'other': return 'Other';
      default: return type;
    }
  };

  const getTypeColor = (type: string): string => {
    switch (type) {
      case 'full_extraction': return '#22c55e';
      case 'keyword_only': return '#eab308';
      case 'no_extraction': return '#ef4444';
      default: return '#6b7280';
    }
  };

  // Use new stages API if available, fall back to legacy
  const stages = status?.stages;
  const needsExtraction = stages?.need_extraction.count ??
    status?.by_extraction_type.find(t => t.type === 'keyword_only')?.count ?? 0;
  const notRelevantCount = stages?.not_relevant.count ??
    status?.by_relevance.find(r => r.relevance === 'not_relevant')?.count ?? 0;
  const needsReviewCount = stages?.needs_review.count ?? 0;
  const readyToApproveCount = stages?.ready_to_approve.count ??
    status?.by_relevance.find(r => r.relevance === 'relevant')?.count ?? 0;

  return (
    <div className="queue-manager">
      <div className="page-header">
        <h2>Queue Manager</h2>
        <button className="action-btn" onClick={loadStatus} disabled={loading}>
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      {/* Queue Description */}
      <p className="qm-description">
        New articles from RSS feeds awaiting LLM extraction and curation review.
      </p>

      {/* Active Job Banner */}
      {activeJob && (
        <div className={`qm-active-job ${activeJob.status === 'completed' ? 'completed' : activeJob.status === 'failed' ? 'failed' : 'running'}`}>
          <div className="qm-job-header">
            <span className="qm-job-status-icon">
              {activeJob.status === 'running' || activeJob.status === 'pending' ? '⏳' :
               activeJob.status === 'completed' ? '✓' : '✗'}
            </span>
            <strong>Background Extraction Job</strong>
            {activeJob.status === 'completed' && (
              <button className="action-btn small" onClick={() => setActiveJob(null)}>Dismiss</button>
            )}
          </div>
          <div className="qm-job-progress">
            <div className="qm-job-progress-bar">
              <div
                className="qm-job-progress-fill"
                style={{ width: `${activeJob.total > 0 ? (activeJob.progress / activeJob.total) * 100 : 0}%` }}
              />
            </div>
            <div className="qm-job-progress-text">
              {activeJob.progress} / {activeJob.total} items ({activeJob.total > 0 ? Math.round((activeJob.progress / activeJob.total) * 100) : 0}%)
            </div>
          </div>
          <div className="qm-job-message">{activeJob.message}</div>
        </div>
      )}

      {/* Pipeline Flow Visualization */}
      <div className="qm-flow">
        <div className={`qm-flow-step ${needsExtraction > 0 ? 'active' : 'done'}`}>
          <div className="qm-flow-count">{needsExtraction}</div>
          <div className="qm-flow-label">Need Extraction</div>
        </div>
        <div className="qm-flow-arrow">→</div>
        <div className={`qm-flow-step ${needsReviewCount > 0 ? 'warning' : ''}`}>
          <div className="qm-flow-count">{needsReviewCount}</div>
          <div className="qm-flow-label">Needs Review</div>
        </div>
        <div className="qm-flow-arrow">→</div>
        <div className={`qm-flow-step ${readyToApproveCount > 0 ? 'success' : ''}`}>
          <div className="qm-flow-count">{readyToApproveCount}</div>
          <div className="qm-flow-label">Ready to Approve</div>
        </div>
      </div>

      {/* Status Overview - Stage counts */}
      <div className="qm-status-grid">
        <div className="qm-stat-card warning">
          <div className="qm-stat-value">{needsExtraction}</div>
          <div className="qm-stat-label">Need Extraction</div>
        </div>
        <div className="qm-stat-card info">
          <div className="qm-stat-value">{needsReviewCount}</div>
          <div className="qm-stat-label">Needs Review</div>
          {stages?.needs_review.avg_confidence ? (
            <div className="qm-stat-meta">{(stages.needs_review.avg_confidence * 100).toFixed(0)}% avg</div>
          ) : null}
        </div>
        <div className="qm-stat-card success">
          <div className="qm-stat-value">{readyToApproveCount}</div>
          <div className="qm-stat-label">Ready to Approve</div>
        </div>
        <div className="qm-stat-card danger">
          <div className="qm-stat-value">{notRelevantCount}</div>
          <div className="qm-stat-label">Not Relevant</div>
        </div>
      </div>

      {/* Extraction Status Breakdown */}
      {status && status.by_extraction_type.length > 0 && (
        <div className="qm-section">
          <h3>Extraction Status</h3>
          <div className="qm-type-bars">
            {status.by_extraction_type.map(item => (
              <div key={item.type} className="qm-type-bar">
                <div className="qm-type-label">
                  <span style={{ color: getTypeColor(item.type) }}>{getTypeLabel(item.type)}</span>
                  <span className="qm-type-count">{item.count}</span>
                </div>
                <div className="qm-progress">
                  <div
                    className="qm-progress-fill"
                    style={{
                      width: `${(item.count / status.total_pending) * 100}%`,
                      background: getTypeColor(item.type),
                    }}
                  />
                </div>
                {item.avg_confidence !== null && (
                  <div className="qm-type-meta">
                    Avg confidence: {(item.avg_confidence * 100).toFixed(0)}%
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Batch Operations */}
      <div className="qm-section">
        <h3>Batch Operations</h3>

        <div className="qm-controls">
          <div className="qm-control-group">
            <label>Batch Size:</label>
            <select value={batchSize} onChange={e => setBatchSize(Number(e.target.value))}>
              <option value={5}>5 items</option>
              <option value={10}>10 items</option>
              <option value={20}>20 items</option>
              <option value={50}>50 items</option>
              <option value={100}>100 items</option>
            </select>
          </div>
          <div className="qm-control-group">
            <label>
              <input
                type="checkbox"
                checked={autoReject}
                onChange={e => setAutoReject(e.target.checked)}
              />
              Auto-reject during triage
            </label>
          </div>
        </div>

        {/* Progress Bar */}
        {processing && (
          <div className="qm-progress-section">
            <div className="qm-progress-bar">
              <div
                className="qm-progress-bar-fill"
                style={{ width: `${progress}%` }}
              />
            </div>
            <div className="qm-progress-info">
              <span className="qm-progress-message">{progressMessage}</span>
              <span className="qm-progress-percent">{Math.round(progress)}%</span>
            </div>
          </div>
        )}

        {/* Inline Confirmation */}
        {confirmAction && (
          <div className="qm-confirm-dialog">
            <div className="qm-confirm-content">
              {confirmAction === 'pipeline' && (
                <>
                  <strong>Run Full Pipeline on {batchSize} items?</strong>
                  <p>This will: Triage → Auto-reject irrelevant → Extract → Auto-approve high confidence</p>
                </>
              )}
              {confirmAction === 'reject' && (
                <>
                  <strong>Reject all not relevant items?</strong>
                  <p>This will permanently reject all items marked as not relevant.</p>
                </>
              )}
              {confirmAction === 'queue-all' && (
                <>
                  <strong>Queue all {needsExtraction} items for background extraction?</strong>
                  <p>This will create a background job. Monitor progress in the Jobs tab.</p>
                  <p><small>Estimated time: ~{Math.ceil(needsExtraction * 2 / 60)} minutes</small></p>
                </>
              )}
              <div className="qm-confirm-buttons">
                <button className="action-btn" onClick={() => setConfirmAction(null)}>
                  Cancel
                </button>
                <button
                  className="action-btn primary"
                  onClick={() => {
                    if (confirmAction === 'pipeline') runFullPipeline();
                    if (confirmAction === 'reject') rejectNotRelevant();
                    if (confirmAction === 'queue-all') queueAllForExtraction();
                  }}
                >
                  Confirm
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Full Pipeline Button */}
        <div className="qm-pipeline-action">
          <button
            className="action-btn primary large"
            onClick={() => setConfirmAction('pipeline')}
            disabled={!!processing || needsExtraction === 0 || !!confirmAction || !!activeJob}
          >
            {processing === 'pipeline' ? 'Running Pipeline...' : `Run Full Pipeline (${batchSize} items)`}
          </button>
          {activeJob ? (
            <p className="qm-pipeline-desc" style={{ color: 'var(--text-secondary)' }}>
              Disabled while background job is running
            </p>
          ) : (
            <p className="qm-pipeline-desc">
              Triage → Auto-reject → Extract → Auto-approve high confidence
            </p>
          )}
        </div>

        {/* Queue All Button */}
        <div className="qm-pipeline-action">
          {activeJob ? (
            <div className="qm-job-running-notice">
              <span className="qm-job-running-icon">⏳</span>
              <span>Background extraction job is running. See progress above.</span>
            </div>
          ) : (
            <>
              <button
                className="action-btn large"
                onClick={() => setConfirmAction('queue-all')}
                disabled={!!processing || needsExtraction === 0 || !!confirmAction}
                style={{ background: '#059669', borderColor: '#059669', color: 'white' }}
              >
                {processing === 'queue-all' ? 'Queuing...' : `Queue All ${needsExtraction} for Background Extraction`}
              </button>
              <p className="qm-pipeline-desc">
                Creates a background job to extract all items.
                <br />
                <small>Estimated time: ~{Math.ceil(needsExtraction * 2 / 60)} minutes</small>
              </p>
            </>
          )}
        </div>

        <div className="qm-actions-divider">
          <span>Or run individual steps:</span>
        </div>

        <div className="qm-actions">
          <div className="qm-action-card">
            <div className="qm-step-number">1</div>
            <h4>Quick Triage</h4>
            <p>Fast relevance check to identify articles worth full extraction vs. those to reject.</p>
            <p className="qm-estimate">
              ~{Math.ceil(batchSize * 0.5)} seconds for {batchSize} items
            </p>
            <button
              className="action-btn"
              onClick={runTriage}
              disabled={!!processing || needsExtraction === 0 || !!activeJob}
            >
              {processing === 'triage' ? 'Triaging...' : `Triage ${batchSize} Items`}
            </button>
          </div>

          <div className="qm-action-card">
            <div className="qm-step-number">2</div>
            <h4>Bulk Reject</h4>
            <p>Reject all items that have been marked as not relevant after triage or extraction.</p>
            <button
              className="action-btn danger"
              onClick={() => setConfirmAction('reject')}
              disabled={!!processing || !!confirmAction || !!activeJob}
            >
              {processing === 'reject' ? 'Rejecting...' : 'Reject Not Relevant'}
            </button>
          </div>

          <div className="qm-action-card">
            <div className="qm-step-number">3</div>
            <h4>Universal Extraction</h4>
            <p>Extract ALL actors, events, and details from unprocessed articles.</p>
            <p className="qm-estimate">
              ~{Math.ceil(batchSize * 2)} seconds for {batchSize} items
            </p>
            <button
              className="action-btn primary"
              onClick={runBatchExtract}
              disabled={!!processing || needsExtraction === 0 || !!activeJob}
            >
              {processing === 'extract' ? 'Extracting...' : `Extract ${batchSize} Items`}
            </button>
          </div>
        </div>
      </div>

      {/* Results */}
      {result && (
        <div className={`qm-result ${result.success ? 'success' : 'error'}`}>
          <h4>{result.success ? 'Operation Complete' : 'Operation Failed'}</h4>

          {result.error && <p className="qm-error">{result.error}</p>}

          {result.processed !== undefined && (
            <div className="qm-result-stats">
              <span>Processed: {result.processed}</span>
              {result.extracted !== undefined && <span>Extracted: {result.extracted}</span>}
              {result.relevant !== undefined && <span>Relevant: {result.relevant}</span>}
              {result.not_relevant !== undefined && <span>Not Relevant: {result.not_relevant}</span>}
              {result.errors !== undefined && result.errors > 0 && <span>Errors: {result.errors}</span>}
              {result.extract_recommended !== undefined && <span>Extract: {result.extract_recommended}</span>}
              {result.reject_recommended !== undefined && <span>Reject: {result.reject_recommended}</span>}
              {result.review_recommended !== undefined && <span>Review: {result.review_recommended}</span>}
              {result.auto_rejected !== undefined && result.auto_rejected > 0 && <span>Auto-rejected: {result.auto_rejected}</span>}
              {result.auto_approved !== undefined && result.auto_approved > 0 && <span className="success">Auto-approved: {result.auto_approved}</span>}
            </div>
          )}

          {result.rejected_count !== undefined && (
            <p>Rejected {result.rejected_count} items</p>
          )}

          {result.items && result.items.length > 0 && (
            <div className="qm-result-items">
              <h5>Processed Items:</h5>
              <div className="qm-items-list">
                {result.items.map(item => (
                  <div key={item.id} className={`qm-item ${item.error ? 'error' : item.is_relevant === false ? 'not-relevant' : item.is_relevant ? 'relevant' : ''}`}>
                    <span className="qm-item-title">{item.title}</span>
                    {item.is_relevant !== undefined && (
                      <span className={`qm-item-badge ${item.is_relevant ? 'relevant' : 'not-relevant'}`}>
                        {item.is_relevant ? 'Relevant' : 'Not Relevant'}
                      </span>
                    )}
                    {item.category && <span className="qm-item-category">{item.category}</span>}
                    {item.confidence && <span className="qm-item-confidence">{(item.confidence * 100).toFixed(0)}%</span>}
                    {item.triage && (
                      <span className={`qm-item-badge ${item.triage.recommendation}`}>
                        {item.triage.recommendation}
                      </span>
                    )}
                    {item.error && <span className="qm-item-error">{item.error}</span>}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Maintenance Section */}
      <div className="qm-section qm-maintenance">
        <h3>Maintenance</h3>
        <p className="qm-maintenance-desc">
          {(status?.needs_upgrade ?? 0) > 0 ? (
            <>{status?.needs_upgrade} items were extracted with an older schema. Upgrade them to the universal schema to capture all actors and events.</>
          ) : (
            <>All extracted items are using the current universal schema.</>
          )}
        </p>

        {confirmAction === 'upgrade' && (
          <div className="qm-confirm-dialog">
            <div className="qm-confirm-content">
              <strong>Upgrade {batchSize} items to universal schema?</strong>
              <p>This will re-run extraction on previously processed items.</p>
              <div className="qm-confirm-buttons">
                <button className="action-btn" onClick={() => setConfirmAction(null)}>
                  Cancel
                </button>
                <button className="action-btn primary" onClick={runUpgradeLegacy}>
                  Confirm
                </button>
              </div>
            </div>
          </div>
        )}

        <button
          className="action-btn"
          onClick={() => setConfirmAction('upgrade')}
          disabled={!!processing || !!confirmAction || (status?.needs_upgrade ?? 0) === 0}
        >
          {processing === 'upgrade' ? 'Upgrading...' : `Upgrade ${Math.min(batchSize, status?.needs_upgrade ?? 0)} Items`}
        </button>
      </div>
    </div>
  );
}

export default QueueManager;
