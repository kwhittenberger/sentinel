import { useState, useEffect, useCallback, useRef } from 'react';
import type { ExtractionStatus, Job, JobStageProgress } from './types';
import {
  fetchExtractionStatus,
  runBatchExtract,
  runTriage,
  runAutoApprove,
  createJob,
  cancelJob,
  deleteJob,
  retryJob,
  unstickJob,
  rejectNotRelevant,
  upgradeSchema,
} from './api';
import type { BatchResult } from './api';
import { useJobWebSocket } from './useJobWebSocket';

// --- Pipeline stage parsing (from JobDashboard) ---
const PIPELINE_STAGES: { name: string; label: string; pattern: RegExp }[] = [
  { name: 'fetch', label: 'Fetch', pattern: /step\s*1|fetch/i },
  { name: 'enrich', label: 'Enrich', pattern: /step\s*2|enrich/i },
  { name: 'extract', label: 'Extract', pattern: /step\s*3|extract/i },
];

function parseJobStages(job: Job): JobStageProgress[] | null {
  if (job.job_type !== 'full_pipeline') return null;

  const msg = job.message || '';
  const stages: JobStageProgress[] = PIPELINE_STAGES.map((def) => ({
    name: def.name,
    label: def.label,
    status: 'pending' as const,
  }));

  let activeIndex = -1;
  for (let i = PIPELINE_STAGES.length - 1; i >= 0; i--) {
    if (PIPELINE_STAGES[i].pattern.test(msg)) {
      activeIndex = i;
      break;
    }
  }

  if (job.status === 'completed') {
    stages.forEach((s) => (s.status = 'completed'));
  } else if (job.status === 'failed') {
    for (let i = 0; i < stages.length; i++) {
      stages[i].status = i < activeIndex ? 'completed' : i === activeIndex ? 'failed' : 'pending';
    }
  } else if (activeIndex >= 0) {
    for (let i = 0; i < stages.length; i++) {
      stages[i].status = i < activeIndex ? 'completed' : i === activeIndex ? 'running' : 'pending';
    }
  }

  return stages;
}

// --- Helpers (from JobDashboard) ---
function getStatusColor(status: string): string {
  switch (status) {
    case 'completed': return 'var(--success-color)';
    case 'running': return 'var(--primary-color)';
    case 'pending': return 'var(--warning-color)';
    case 'failed': return 'var(--danger-color)';
    case 'cancelled': return 'var(--text-muted)';
    default: return 'var(--text-muted)';
  }
}

function formatDuration(startedAt?: string, completedAt?: string): string {
  if (!startedAt) return '-';
  const start = new Date(startedAt).getTime();
  const end = completedAt ? new Date(completedAt).getTime() : Date.now();
  const secs = Math.floor((end - start) / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  const remSecs = secs % 60;
  return `${mins}m ${remSecs}s`;
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleString();
}

function getProgressPercent(job: Job): number {
  if (!job.total || job.total === 0) return 0;
  return Math.round(((job.progress || 0) / job.total) * 100);
}

const STATUS_TABS = ['all', 'completed', 'failed', 'cancelled'] as const;

interface OperationsBarProps {
  expanded: boolean;
  onToggle: () => void;
  onOperationComplete: () => void;
}

export function OperationsBar({ expanded, onToggle, onOperationComplete }: OperationsBarProps) {
  const [status, setStatus] = useState<ExtractionStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [batchSize, setBatchSize] = useState(10);
  const [processing, setProcessing] = useState<string | null>(null);
  const [confirmAction, setConfirmAction] = useState<string | null>(null);
  const [resultMessage, setResultMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const resultTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // Jobs section state
  const [jobHistoryOpen, setJobHistoryOpen] = useState(false);
  const [historyFilter, setHistoryFilter] = useState<string>('all');

  const { activeJobs, completedJobs } = useJobWebSocket();
  const prevActiveIdsRef = useRef<Set<string>>(new Set());

  const loadStatus = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchExtractionStatus();
      setStatus(data);
    } catch {
      // Silent fail - status will show as loading
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  // Detect extraction job completions via WebSocket
  useEffect(() => {
    const currentActiveIds = new Set(activeJobs.map((j: Job) => j.id));
    const prevIds = prevActiveIdsRef.current;

    for (const id of prevIds) {
      if (!currentActiveIds.has(id)) {
        const completed = completedJobs.find((j: Job) => j.id === id && j.job_type === 'batch_extract');
        if (completed) {
          loadStatus();
          onOperationComplete();
        }
      }
    }
    prevActiveIdsRef.current = currentActiveIds;
  }, [activeJobs, completedJobs, loadStatus, onOperationComplete]);

  const showResult = (type: 'success' | 'error', text: string) => {
    if (resultTimerRef.current) clearTimeout(resultTimerRef.current);
    setResultMessage({ type, text });
    resultTimerRef.current = setTimeout(() => setResultMessage(null), 5000);
  };

  const handleRunPipeline = async () => {
    setConfirmAction(null);
    setProcessing('pipeline');

    try {
      const triageData: BatchResult = await runTriage(batchSize, true);
      if (!triageData.success) {
        showResult('error', triageData.error || 'Triage failed');
        return;
      }

      const extractCount = triageData.extract_recommended || 0;
      let extractData: BatchResult | null = null;
      if (extractCount > 0) {
        extractData = await runBatchExtract(extractCount);
      }

      let approveData: BatchResult | null = null;
      if (extractData?.extracted && extractData.extracted > 0) {
        approveData = await runAutoApprove(batchSize);
      }

      const parts: string[] = [];
      if (triageData.processed) parts.push(`Triaged: ${triageData.processed}`);
      if (triageData.auto_rejected) parts.push(`Rejected: ${triageData.auto_rejected}`);
      if (extractData?.extracted) parts.push(`Extracted: ${extractData.extracted}`);
      if (approveData?.auto_approved) parts.push(`Approved: ${approveData.auto_approved}`);
      if (approveData?.auto_rejected) parts.push(`Auto-rejected: ${approveData.auto_rejected}`);

      showResult('success', parts.join(' | ') || 'Pipeline complete');
      await loadStatus();
      onOperationComplete();
    } catch (err) {
      showResult('error', String(err));
    } finally {
      setProcessing(null);
    }
  };

  const handleQueueAll = async () => {
    setConfirmAction(null);
    setProcessing('queue-all');

    try {
      const data = await createJob('batch_extract', { limit: needsExtraction });
      if (data.success) {
        showResult('success', `Background job created (${needsExtraction} items)`);
      } else {
        showResult('error', 'Failed to create job');
      }
    } catch (err) {
      showResult('error', String(err));
    } finally {
      setProcessing(null);
    }
  };

  const handleAutoApprove = async () => {
    setConfirmAction(null);
    setProcessing('auto-approve');

    try {
      const data = await runAutoApprove(batchSize);
      if (data.success) {
        const parts: string[] = [];
        if (data.auto_approved) parts.push(`Approved: ${data.auto_approved}`);
        if (data.auto_rejected) parts.push(`Rejected: ${data.auto_rejected}`);
        if (data.needs_review) parts.push(`Review: ${data.needs_review}`);
        if (data.errors) parts.push(`Errors: ${data.errors}`);
        showResult('success', parts.join(' | ') || 'No articles to evaluate');
        await loadStatus();
        onOperationComplete();
      } else {
        showResult('error', data.error || 'Auto-approve failed');
      }
    } catch (err) {
      showResult('error', String(err));
    } finally {
      setProcessing(null);
    }
  };

  const handleRejectNotRelevant = async () => {
    setConfirmAction(null);
    setProcessing('reject-not-relevant');

    try {
      const data = await rejectNotRelevant();
      if (data.success) {
        showResult('success', `Rejected: ${data.rejected_count || 0} not-relevant articles`);
        await loadStatus();
        onOperationComplete();
      } else {
        showResult('error', data.error || 'Reject failed');
      }
    } catch (err) {
      showResult('error', String(err));
    } finally {
      setProcessing(null);
    }
  };

  const handleUpgradeSchema = async () => {
    setConfirmAction(null);
    setProcessing('upgrade-schema');

    try {
      const data = await upgradeSchema(batchSize);
      if (data.success) {
        const parts: string[] = [];
        if (data.extracted) parts.push(`Upgraded: ${data.extracted}`);
        if (data.errors) parts.push(`Errors: ${data.errors}`);
        showResult('success', parts.join(' | ') || 'Schema upgrade complete');
        await loadStatus();
        onOperationComplete();
      } else {
        showResult('error', data.error || 'Schema upgrade failed');
      }
    } catch (err) {
      showResult('error', String(err));
    } finally {
      setProcessing(null);
    }
  };

  // --- Job action handlers (from JobDashboard) ---
  const handleCancelJob = async (jobId: string) => {
    if (!confirm('Cancel this job?')) return;
    try {
      await cancelJob(jobId);
      showResult('success', 'Job cancelled');
    } catch {
      showResult('error', 'Failed to cancel job');
    }
  };

  const handleDeleteJob = async (jobId: string) => {
    if (!confirm('Permanently delete this job record?')) return;
    try {
      await deleteJob(jobId);
      showResult('success', 'Job deleted');
    } catch (err) {
      showResult('error', err instanceof Error ? err.message : 'Delete failed');
    }
  };

  const handleRetryJob = async (jobId: string) => {
    try {
      const result = await retryJob(jobId);
      showResult('success', `Retry created: ${result.new_job_id}`);
    } catch (err) {
      showResult('error', err instanceof Error ? err.message : 'Retry failed');
    }
  };

  const handleUnstickJob = async (jobId: string) => {
    if (!confirm('Reset this stale job to pending and re-dispatch?')) return;
    try {
      await unstickJob(jobId);
      showResult('success', 'Job unstuck and re-dispatched');
    } catch (err) {
      showResult('error', err instanceof Error ? err.message : 'Unstick failed');
    }
  };

  const stages = status?.stages;
  const needsExtraction = stages?.need_extraction.count ?? 0;
  const notRelevantCount = stages?.not_relevant.count ?? 0;
  const needsReviewCount = stages?.needs_review.count ?? 0;
  const readyToApproveCount = stages?.ready_to_approve.count ?? 0;
  const needsUpgrade = status?.needs_upgrade ?? 0;

  // Find active extraction job from WebSocket (for disabling queue buttons)
  const activeExtractJob = activeJobs.find((j: Job) => j.job_type === 'batch_extract');

  const confirmMessage = () => {
    switch (confirmAction) {
      case 'pipeline':
        return <span>Run full pipeline on <strong>{batchSize}</strong> items? (Triage &rarr; Extract &rarr; Auto-approve)</span>;
      case 'auto-approve':
        return <span>Auto-approve up to <strong>{batchSize}</strong> extracted articles against current thresholds?</span>;
      case 'reject-not-relevant':
        return <span>Reject all <strong>{notRelevantCount}</strong> articles marked not relevant?</span>;
      case 'upgrade-schema':
        return <span>Upgrade <strong>{batchSize}</strong> items to universal extraction schema?</span>;
      case 'queue-all':
        return <span>Queue all <strong>{needsExtraction}</strong> items for background extraction?</span>;
      default:
        return null;
    }
  };

  const confirmHandler = () => {
    switch (confirmAction) {
      case 'pipeline': return handleRunPipeline();
      case 'auto-approve': return handleAutoApprove();
      case 'reject-not-relevant': return handleRejectNotRelevant();
      case 'upgrade-schema': return handleUpgradeSchema();
      case 'queue-all': return handleQueueAll();
    }
  };

  // Extraction type labels and colors
  const extractionTypeColor = (type: string) => {
    switch (type) {
      case 'full_extraction': return '#22c55e';
      case 'keyword_only': return '#eab308';
      case 'no_extraction': return '#ef4444';
      default: return '#6b7280';
    }
  };

  const extractionTypeLabel = (type: string) => {
    switch (type) {
      case 'full_extraction': return 'Full LLM';
      case 'keyword_only': return 'Keyword';
      case 'no_extraction': return 'None';
      default: return type;
    }
  };

  // Filter job history
  const filteredHistory = historyFilter === 'all'
    ? completedJobs
    : completedJobs.filter((j) => j.status === historyFilter);

  return (
    <div className={`ops-bar ${expanded ? 'ops-bar-expanded' : 'ops-bar-collapsed'}`}>
      {/* Collapsed / Header Row */}
      <div className="ops-header" onClick={onToggle}>
        <button className="ops-toggle" aria-label={expanded ? 'Collapse operations' : 'Expand operations'}>
          {expanded ? '\u25BE' : '\u25B8'}
        </button>
        <span className="ops-title">Operations</span>
        <div className="ops-stats-row">
          <span className="ops-stat" title="Need Extraction">
            <span className="ops-stat-label">Extraction:</span>
            <span className="ops-stat-value">{loading ? '...' : needsExtraction}</span>
          </span>
          <span className="ops-stat-sep">|</span>
          <span className="ops-stat" title="Needs Review">
            <span className="ops-stat-label">Review:</span>
            <span className="ops-stat-value">{loading ? '...' : needsReviewCount}</span>
          </span>
          <span className="ops-stat-sep">|</span>
          <span className="ops-stat" title="Ready to Approve">
            <span className="ops-stat-label">Ready:</span>
            <span className="ops-stat-value">{loading ? '...' : readyToApproveCount}</span>
          </span>
          {activeJobs.length > 0 && (
            <>
              <span className="ops-stat-sep">|</span>
              <span className="ops-stat" title="Active Jobs">
                <span className="ops-stat-label">Jobs:</span>
                <span className="ops-stat-value" style={{ color: 'var(--primary-color)' }}>{activeJobs.length}</span>
              </span>
            </>
          )}
        </div>
        {!expanded && (
          <div className="ops-collapsed-actions" onClick={e => e.stopPropagation()}>
            <button
              className="action-btn primary small"
              onClick={() => setConfirmAction('pipeline')}
              disabled={!!processing || needsExtraction === 0 || !!activeExtractJob}
            >
              {processing === 'pipeline' ? 'Running...' : 'Run Pipeline'}
            </button>
            <button
              className="action-btn small"
              onClick={() => setConfirmAction('queue-all')}
              disabled={!!processing || needsExtraction === 0 || !!activeExtractJob}
              style={needsExtraction > 0 ? { background: '#059669', borderColor: '#059669', color: 'white' } : undefined}
            >
              Queue All
            </button>
          </div>
        )}
      </div>

      {/* Expanded Content */}
      {expanded && (
        <div className="ops-content">
          {/* Pipeline Flow Visualization */}
          <div className="ops-flow">
            <div className={`ops-flow-step ${needsExtraction > 0 ? 'active' : ''}`}>
              <span className="ops-flow-count">{needsExtraction}</span>
              <span className="ops-flow-label">Need Extraction</span>
            </div>
            <span className="ops-flow-arrow">&rarr;</span>
            <div className={`ops-flow-step ${needsReviewCount > 0 ? 'warning' : ''}`}>
              <span className="ops-flow-count">{needsReviewCount}</span>
              <span className="ops-flow-label">Needs Review</span>
            </div>
            <span className="ops-flow-arrow">&rarr;</span>
            <div className={`ops-flow-step ${readyToApproveCount > 0 ? 'success' : ''}`}>
              <span className="ops-flow-count">{readyToApproveCount}</span>
              <span className="ops-flow-label">Ready to Approve</span>
            </div>
            {notRelevantCount > 0 && (
              <>
                <span className="ops-flow-divider">|</span>
                <div className="ops-flow-step not-relevant">
                  <span className="ops-flow-count">{notRelevantCount}</span>
                  <span className="ops-flow-label">Not Relevant</span>
                </div>
              </>
            )}
          </div>

          {/* Extraction Type Breakdown */}
          {status?.by_extraction_type && status.by_extraction_type.length > 0 && (
            <div className="ops-extraction-types">
              <span className="ops-extraction-types-label">Extraction types:</span>
              {status.by_extraction_type.map(et => (
                <span key={et.type} className="ops-extraction-type-item">
                  <span className="ops-et-dot" style={{ background: extractionTypeColor(et.type) }} />
                  {extractionTypeLabel(et.type)}: {et.count}
                </span>
              ))}
            </div>
          )}

          {/* Action Buttons */}
          <div className="ops-controls-row">
            <div className="ops-batch-select">
              <label>Batch Size:</label>
              <select value={batchSize} onChange={e => setBatchSize(Number(e.target.value))}>
                <option value={5}>5</option>
                <option value={10}>10</option>
                <option value={20}>20</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
              </select>
            </div>
            <div className="ops-actions">
              <button
                className="action-btn primary"
                onClick={() => setConfirmAction('pipeline')}
                disabled={!!processing || needsExtraction === 0 || !!confirmAction || !!activeExtractJob}
              >
                {processing === 'pipeline' ? 'Running Pipeline...' : `Run Full Pipeline (${batchSize})`}
              </button>
              <button
                className="action-btn"
                onClick={() => setConfirmAction('auto-approve')}
                disabled={!!processing || readyToApproveCount === 0 || !!confirmAction}
              >
                {processing === 'auto-approve' ? 'Approving...' : `Auto-Approve (${readyToApproveCount})`}
              </button>
              <button
                className="action-btn reject"
                onClick={() => setConfirmAction('reject-not-relevant')}
                disabled={!!processing || notRelevantCount === 0 || !!confirmAction}
              >
                {processing === 'reject-not-relevant' ? 'Rejecting...' : `Reject Not Relevant (${notRelevantCount})`}
              </button>
              <button
                className="action-btn"
                onClick={() => setConfirmAction('queue-all')}
                disabled={!!processing || needsExtraction === 0 || !!confirmAction || !!activeExtractJob}
                style={needsExtraction > 0 && !activeExtractJob ? { background: '#059669', borderColor: '#059669', color: 'white' } : undefined}
              >
                {processing === 'queue-all' ? 'Queuing...' : `Queue All ${needsExtraction}`}
              </button>
              <button className="action-btn small" onClick={loadStatus} disabled={loading}>
                {loading ? '...' : 'Refresh'}
              </button>
            </div>
          </div>

          {/* Schema Upgrade */}
          {needsUpgrade > 0 && (
            <div className="ops-upgrade-row">
              <span className="ops-upgrade-text">
                {needsUpgrade} items need schema upgrade to universal format
              </span>
              <button
                className="action-btn small"
                onClick={() => setConfirmAction('upgrade-schema')}
                disabled={!!processing || !!confirmAction}
              >
                {processing === 'upgrade-schema' ? 'Upgrading...' : `Upgrade (${batchSize})`}
              </button>
            </div>
          )}

          {/* Inline Confirmation */}
          {confirmAction && (
            <div className="ops-confirm">
              <div className="ops-confirm-content">
                {confirmMessage()}
                <div className="ops-confirm-buttons">
                  <button className="action-btn small" onClick={() => setConfirmAction(null)}>Cancel</button>
                  <button
                    className="action-btn primary small"
                    onClick={confirmHandler}
                  >
                    Confirm
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Active Jobs (all types) */}
          {activeJobs.length > 0 && (
            <div className="ops-active-jobs">
              {activeJobs.map((job) => {
                const jobStages = parseJobStages(job);
                const pct = getProgressPercent(job);
                return (
                  <div key={job.id} className="ops-job-banner">
                    <div className="ops-job-header">
                      <span className="ops-job-icon">&#9203;</span>
                      <strong>{job.job_type.replace(/_/g, ' ')}</strong>
                      {job.queue && <span className="ops-job-queue">{job.queue}</span>}
                      <span className="ops-job-pct">
                        {job.total ? `${job.progress || 0}/${job.total} (${pct}%)` : 'Starting...'}
                      </span>
                    </div>

                    {/* Pipeline stage visualization */}
                    {jobStages && (
                      <div className="jd-stages">
                        {jobStages.map((stage, i) => (
                          <div key={stage.name} className="jd-stage-row">
                            <span className={`jd-stage-dot ${stage.status}`} />
                            <span className={`jd-stage-label ${stage.status}`}>{stage.label}</span>
                            {i < jobStages.length - 1 && <span className="jd-stage-connector" />}
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Progress bar */}
                    {job.total != null && job.total > 0 && (
                      <div className="ops-job-progress-bar">
                        <div
                          className="ops-job-progress-fill"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    )}

                    {job.message && (
                      <div className="ops-job-message">{job.message}</div>
                    )}

                    <div className="ops-job-footer">
                      <span className="ops-job-meta">
                        Duration: {formatDuration(job.started_at)}
                        {(job.retry_count ?? 0) > 0 && ` | Retries: ${job.retry_count}/${job.max_retries ?? 3}`}
                      </span>
                      <button
                        className="action-btn small reject"
                        onClick={() => handleCancelJob(job.id)}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Job History Toggle */}
          <div
            className="ops-jobs-toggle"
            onClick={() => setJobHistoryOpen(!jobHistoryOpen)}
          >
            <span className="ops-jobs-toggle-icon">{jobHistoryOpen ? '\u25BE' : '\u25B8'}</span>
            <span>Job History ({completedJobs.length})</span>
          </div>

          {/* Job History Table */}
          {jobHistoryOpen && (
            <div className="ops-jobs-section">
              <div className="ops-history-tabs">
                {STATUS_TABS.map((tab) => (
                  <button
                    key={tab}
                    className={`filter-btn ${historyFilter === tab ? 'active' : ''}`}
                    onClick={() => setHistoryFilter(tab)}
                  >
                    {tab === 'all' ? 'All' : tab.charAt(0).toUpperCase() + tab.slice(1)}
                  </button>
                ))}
              </div>

              {filteredHistory.length === 0 ? (
                <p className="ops-jobs-empty">No jobs in this category</p>
              ) : (
                <div className="ops-history-table-wrap">
                  <table className="ops-history-table">
                    <thead>
                      <tr>
                        <th>Type</th>
                        <th>Status</th>
                        <th>Progress</th>
                        <th>Duration</th>
                        <th>Completed</th>
                        <th>Error</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredHistory.map((job) => (
                        <tr key={job.id}>
                          <td>{job.job_type.replace(/_/g, ' ')}</td>
                          <td>
                            <span style={{ color: getStatusColor(job.status) }}>
                              {job.status}
                            </span>
                          </td>
                          <td>
                            {job.total ? `${job.progress || 0}/${job.total}` : '-'}
                          </td>
                          <td>{formatDuration(job.started_at, job.completed_at)}</td>
                          <td>{job.completed_at ? formatDate(job.completed_at) : '-'}</td>
                          <td className="ops-error-cell">
                            {job.error && (
                              <span className="ops-error-text" title={job.error}>
                                {job.error.length > 60 ? job.error.substring(0, 60) + '...' : job.error}
                              </span>
                            )}
                          </td>
                          <td className="ops-action-cell">
                            {job.status === 'failed' && (
                              <button className="action-btn small primary" onClick={() => handleRetryJob(job.id)}>
                                Retry
                              </button>
                            )}
                            {job.status === 'running' && (
                              <button className="action-btn small" onClick={() => handleUnstickJob(job.id)}>
                                Unstick
                              </button>
                            )}
                            {(job.status === 'completed' || job.status === 'failed' || job.status === 'cancelled') && (
                              <button className="action-btn small reject" onClick={() => handleDeleteJob(job.id)}>
                                Delete
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Result Toast */}
      {resultMessage && (
        <div className={`ops-toast ops-toast-${resultMessage.type}`} onClick={() => setResultMessage(null)}>
          {resultMessage.type === 'success' ? '\u2713' : '\u2717'} {resultMessage.text}
        </div>
      )}
    </div>
  );
}

export default OperationsBar;
