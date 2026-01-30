import { useState, useCallback } from 'react';
import type { Job, JobStageProgress } from './types';
import { useJobWebSocket } from './useJobWebSocket';
import { QueueStatusBar } from './QueueStatusBar';
import { createJob, cancelJob, deleteJob, retryJob, unstickJob } from './api';
import './JobDashboard.css';

// --- Quick action definitions ---
const QUICK_ACTIONS = [
  { type: 'full_pipeline', label: 'Run Full Pipeline', primary: true },
  { type: 'fetch', label: 'Fetch Sources', primary: false },
  { type: 'batch_extract', label: 'Batch Extract', primary: false },
  { type: 'batch_enrich', label: 'Batch Enrich', primary: false },
] as const;

// --- Pipeline stage parsing ---
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

  // Determine which stage is active
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

// --- Helpers ---
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

// --- Status filter tabs ---
const STATUS_TABS = ['all', 'completed', 'failed', 'cancelled'] as const;

export function JobDashboard() {
  const { activeJobs, completedJobs, connected } = useJobWebSocket();
  const [launching, setLaunching] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [historyFilter, setHistoryFilter] = useState<string>('all');

  const clearMessage = useCallback(() => {
    setTimeout(() => setActionMessage(null), 4000);
  }, []);

  // --- Quick Action Handlers ---
  const handleQuickAction = async (jobType: string) => {
    setLaunching(jobType);
    setActionMessage(null);
    try {
      const result = await createJob(jobType);
      setActionMessage({ type: 'success', text: `Job created: ${result.job_id}` });
      clearMessage();
    } catch {
      setActionMessage({ type: 'error', text: `Failed to create ${jobType} job` });
      clearMessage();
    } finally {
      setLaunching(null);
    }
  };

  const handleCancel = async (jobId: string) => {
    if (!confirm('Cancel this job?')) return;
    try {
      await cancelJob(jobId);
      setActionMessage({ type: 'success', text: 'Job cancelled' });
      clearMessage();
    } catch {
      setActionMessage({ type: 'error', text: 'Failed to cancel job' });
      clearMessage();
    }
  };

  const handleDelete = async (jobId: string) => {
    if (!confirm('Permanently delete this job record?')) return;
    try {
      await deleteJob(jobId);
      setActionMessage({ type: 'success', text: 'Job deleted' });
      clearMessage();
    } catch (err) {
      setActionMessage({ type: 'error', text: err instanceof Error ? err.message : 'Delete failed' });
      clearMessage();
    }
  };

  const handleRetry = async (jobId: string) => {
    try {
      const result = await retryJob(jobId);
      setActionMessage({ type: 'success', text: `Retry created: ${result.new_job_id}` });
      clearMessage();
    } catch (err) {
      setActionMessage({ type: 'error', text: err instanceof Error ? err.message : 'Retry failed' });
      clearMessage();
    }
  };

  const handleUnstick = async (jobId: string) => {
    if (!confirm('Reset this stale job to pending and re-dispatch?')) return;
    try {
      await unstickJob(jobId);
      setActionMessage({ type: 'success', text: 'Job unstuck and re-dispatched' });
      clearMessage();
    } catch (err) {
      setActionMessage({ type: 'error', text: err instanceof Error ? err.message : 'Unstick failed' });
      clearMessage();
    }
  };

  // --- Filter history ---
  const filteredHistory = historyFilter === 'all'
    ? completedJobs
    : completedJobs.filter((j) => j.status === historyFilter);

  return (
    <div className="job-dashboard">
      <div className="dashboard-header">
        <div className="dashboard-title-row">
          <h2>Job Dashboard</h2>
          <span className={`ws-indicator ${connected ? 'connected' : 'disconnected'}`}>
            {connected ? 'Live' : 'Disconnected'}
          </span>
        </div>
        {actionMessage && (
          <div className={`jd-message ${actionMessage.type}`}>
            {actionMessage.text}
          </div>
        )}
      </div>

      {/* Section 1: Quick Actions */}
      <section className="jd-section">
        <h3 className="jd-section-title">Quick Actions</h3>
        <div className="jd-quick-actions">
          {QUICK_ACTIONS.map((action) => (
            <button
              key={action.type}
              className={`action-btn ${action.primary ? 'primary' : ''}`}
              onClick={() => handleQuickAction(action.type)}
              disabled={launching !== null}
            >
              {launching === action.type ? 'Launching...' : action.label}
            </button>
          ))}
        </div>
      </section>

      {/* Section 2: Queue Status */}
      <section className="jd-section">
        <h3 className="jd-section-title">Queue Status</h3>
        <QueueStatusBar />
      </section>

      {/* Section 3: Active Jobs */}
      <section className="jd-section">
        <h3 className="jd-section-title">
          Active Jobs
          {activeJobs.length > 0 && (
            <span className="jd-count-badge">{activeJobs.length}</span>
          )}
        </h3>
        {activeJobs.length === 0 ? (
          <p className="jd-empty">No active jobs</p>
        ) : (
          <div className="jd-active-grid">
            {activeJobs.map((job) => {
              const stages = parseJobStages(job);
              const pct = getProgressPercent(job);
              return (
                <div key={job.id} className="jd-job-card">
                  <div className="jd-card-header">
                    <span className="jd-card-type">{job.job_type.replace(/_/g, ' ')}</span>
                    <div className="jd-card-badges">
                      {job.queue && (
                        <span className="jd-queue-badge">{job.queue}</span>
                      )}
                      <span className="jd-status-badge" style={{ color: getStatusColor(job.status) }}>
                        {job.status}
                      </span>
                    </div>
                  </div>

                  {/* Pipeline stage visualization */}
                  {stages && (
                    <div className="jd-stages">
                      {stages.map((stage, i) => (
                        <div key={stage.name} className="jd-stage-row">
                          <span className={`jd-stage-dot ${stage.status}`} />
                          <span className={`jd-stage-label ${stage.status}`}>{stage.label}</span>
                          {i < stages.length - 1 && <span className="jd-stage-connector" />}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Progress bar */}
                  {job.total != null && job.total > 0 && (
                    <div className="jd-progress">
                      <div className="jd-progress-bar">
                        <div className="jd-progress-fill" style={{ width: `${pct}%` }} />
                      </div>
                      <span className="jd-progress-text">
                        {job.progress || 0}/{job.total} ({pct}%)
                      </span>
                    </div>
                  )}

                  {job.message && (
                    <div className="jd-card-message">{job.message}</div>
                  )}

                  <div className="jd-card-meta">
                    <span>Duration: {formatDuration(job.started_at)}</span>
                    {(job.retry_count ?? 0) > 0 && (
                      <span>Retries: {job.retry_count}/{job.max_retries ?? 3}</span>
                    )}
                  </div>

                  <div className="jd-card-actions">
                    <button
                      className="action-btn small reject"
                      onClick={() => handleCancel(job.id)}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Section 4: Job History */}
      <section className="jd-section">
        <h3 className="jd-section-title">Job History</h3>
        <div className="jd-history-tabs">
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
          <p className="jd-empty">No jobs in this category</p>
        ) : (
          <div className="jd-history-table-wrap">
            <table className="jd-history-table">
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Status</th>
                  <th>Progress</th>
                  <th>Queue</th>
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
                    <td>{job.queue || '-'}</td>
                    <td>{formatDuration(job.started_at, job.completed_at)}</td>
                    <td>{job.completed_at ? formatDate(job.completed_at) : '-'}</td>
                    <td className="jd-error-cell">
                      {job.error && (
                        <span className="jd-error-text" title={job.error}>
                          {job.error.length > 60 ? job.error.substring(0, 60) + '...' : job.error}
                        </span>
                      )}
                    </td>
                    <td className="jd-action-cell">
                      {job.status === 'failed' && (
                        <button className="action-btn small primary" onClick={() => handleRetry(job.id)}>
                          Retry
                        </button>
                      )}
                      {job.status === 'running' && (
                        <button className="action-btn small" onClick={() => handleUnstick(job.id)}>
                          Unstick
                        </button>
                      )}
                      {(job.status === 'completed' || job.status === 'failed' || job.status === 'cancelled') && (
                        <button className="action-btn small reject" onClick={() => handleDelete(job.id)}>
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
      </section>
    </div>
  );
}

export default JobDashboard;
