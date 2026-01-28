import { useState, useEffect, useCallback } from 'react';

const API_BASE = '/api';

interface Job {
  id: string;
  job_type: string;
  status: string;
  progress?: number;
  total?: number;
  message?: string;
  params?: Record<string, unknown>;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  error?: string;
}

interface JobManagerProps {
  onClose?: () => void;
}

const JOB_TYPES = [
  { value: 'fetch', label: 'Fetch Sources', description: 'Fetch articles from configured sources' },
  { value: 'process', label: 'Process Articles', description: 'Run extraction and validation on pending articles' },
  { value: 'batch_extract', label: 'Batch Extract', description: 'Run LLM extraction on a batch of articles' },
  { value: 'batch_enrich', label: 'Batch Enrich', description: 'Enrich articles with additional data' },
  { value: 'full_pipeline', label: 'Full Pipeline', description: 'Run complete fetch, extract, and approval pipeline' },
];

export function JobManager({ onClose }: JobManagerProps) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newJobType, setNewJobType] = useState('fetch');
  const [newJobParams, setNewJobParams] = useState<Record<string, unknown>>({});
  const [creating, setCreating] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const loadJobs = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (statusFilter) params.set('status', statusFilter);
      params.set('limit', '100');

      const response = await fetch(`${API_BASE}/admin/jobs?${params}`);
      if (response.ok) {
        const data = await response.json();
        setJobs(data.jobs || []);
      }
    } catch (err) {
      setMessage({ type: 'error', text: 'Failed to load jobs' });
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  // Initial load
  useEffect(() => {
    loadJobs();
  }, [loadJobs]);

  // Separate effect for polling - only poll when there are active jobs
  useEffect(() => {
    const hasActiveJobs = jobs.some(j => j.status === 'running' || j.status === 'pending');
    if (!hasActiveJobs) return;

    const interval = setInterval(() => {
      loadJobs();
    }, 5000);
    return () => clearInterval(interval);
  }, [jobs.length, loadJobs]); // Only re-run when job count changes

  const createJob = async () => {
    setCreating(true);
    setMessage(null);
    try {
      const response = await fetch(`${API_BASE}/admin/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_type: newJobType,
          params: Object.keys(newJobParams).length > 0 ? newJobParams : null,
        }),
      });
      if (response.ok) {
        const data = await response.json();
        setMessage({ type: 'success', text: `Job created: ${data.job_id}` });
        setShowCreateModal(false);
        setNewJobParams({});
        loadJobs();
      } else {
        setMessage({ type: 'error', text: 'Failed to create job' });
      }
    } catch {
      setMessage({ type: 'error', text: 'Failed to create job' });
    } finally {
      setCreating(false);
    }
  };

  const cancelJob = async (jobId: string) => {
    if (!confirm('Cancel this job?')) return;
    try {
      await fetch(`${API_BASE}/admin/jobs/${jobId}`, { method: 'DELETE' });
      loadJobs();
      setMessage({ type: 'success', text: 'Job cancelled' });
    } catch {
      setMessage({ type: 'error', text: 'Failed to cancel job' });
    }
  };

  const getStatusColor = (status: string): string => {
    switch (status) {
      case 'completed': return '#22c55e';
      case 'running': return '#3b82f6';
      case 'pending': return '#eab308';
      case 'failed': return '#ef4444';
      case 'cancelled': return '#6b7280';
      default: return 'var(--text-muted)';
    }
  };

  const formatDate = (dateStr: string): string => {
    return new Date(dateStr).toLocaleString();
  };

  const getProgressPercent = (job: Job): number => {
    if (!job.total || job.total === 0) return 0;
    return Math.round((job.progress || 0) / job.total * 100);
  };

  const runningJobs = jobs.filter(j => j.status === 'running' || j.status === 'pending');
  const completedJobs = jobs.filter(j => j.status === 'completed' || j.status === 'failed' || j.status === 'cancelled');

  return (
    <div className="job-manager">
      <div className="manager-header">
        <h2>Job Queue</h2>
        <div className="header-actions">
          <button className="action-btn primary" onClick={() => setShowCreateModal(true)}>
            Create Job
          </button>
          {onClose && (
            <button className="admin-close-btn" onClick={onClose}>&times;</button>
          )}
        </div>
      </div>

      {message && (
        <div className={`settings-message ${message.type}`}>
          {message.text}
        </div>
      )}

      <div className="manager-toolbar">
        <div className="filter-group">
          {['', 'pending', 'running', 'completed', 'failed', 'cancelled'].map(status => (
            <button
              key={status}
              className={`filter-btn ${statusFilter === status ? 'active' : ''}`}
              onClick={() => setStatusFilter(status)}
            >
              {status || 'All'}
            </button>
          ))}
        </div>
        <button className="action-btn small" onClick={loadJobs} disabled={loading}>
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      <div className="jobs-container">
        {runningJobs.length > 0 && (
          <div className="jobs-section">
            <h3>Active Jobs</h3>
            <div className="jobs-list">
              {runningJobs.map(job => (
                <div key={job.id} className="job-card active">
                  <div className="job-header">
                    <span className="job-type">{job.job_type}</span>
                    <span className="job-status" style={{ color: getStatusColor(job.status) }}>
                      {job.status}
                    </span>
                  </div>
                  {job.total && job.total > 0 && (
                    <div className="job-progress">
                      <div className="progress-bar">
                        <div
                          className="progress-fill"
                          style={{ width: `${getProgressPercent(job)}%` }}
                        />
                      </div>
                      <span className="progress-text">
                        {job.progress || 0} / {job.total} ({getProgressPercent(job)}%)
                      </span>
                    </div>
                  )}
                  {job.message && (
                    <div className="job-message">{job.message}</div>
                  )}
                  <div className="job-meta">
                    <span>Created: {formatDate(job.created_at)}</span>
                    {job.started_at && <span>Started: {formatDate(job.started_at)}</span>}
                  </div>
                  <div className="job-actions">
                    <button
                      className="action-btn small reject"
                      onClick={() => cancelJob(job.id)}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="jobs-section">
          <h3>Job History</h3>
          {loading && jobs.length === 0 ? (
            <div className="loading">Loading jobs...</div>
          ) : completedJobs.length === 0 ? (
            <div className="empty-state">No jobs found</div>
          ) : (
            <table className="jobs-table">
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Status</th>
                  <th>Progress</th>
                  <th>Created</th>
                  <th>Completed</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody>
                {completedJobs.map(job => (
                  <tr key={job.id}>
                    <td>{job.job_type}</td>
                    <td>
                      <span className="status-badge" style={{ color: getStatusColor(job.status) }}>
                        {job.status}
                      </span>
                    </td>
                    <td>
                      {job.total ? `${job.progress || 0}/${job.total}` : '-'}
                    </td>
                    <td>{formatDate(job.created_at)}</td>
                    <td>{job.completed_at ? formatDate(job.completed_at) : '-'}</td>
                    <td className="error-cell">
                      {job.error && (
                        <span className="error-text" title={job.error}>
                          {job.error.substring(0, 50)}...
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {showCreateModal && (
        <div className="modal-overlay">
          <div className="modal">
            <div className="modal-header">
              <h3>Create New Job</h3>
              <button className="admin-close-btn" onClick={() => setShowCreateModal(false)}>
                &times;
              </button>
            </div>
            <div className="modal-content">
              <div className="form-group">
                <label>Job Type</label>
                <select
                  value={newJobType}
                  onChange={e => setNewJobType(e.target.value)}
                  className="settings-select"
                >
                  {JOB_TYPES.map(type => (
                    <option key={type.value} value={type.value}>
                      {type.label}
                    </option>
                  ))}
                </select>
                <p className="form-hint">
                  {JOB_TYPES.find(t => t.value === newJobType)?.description}
                </p>
              </div>

              {(newJobType === 'batch_extract' || newJobType === 'batch_enrich') && (
                <>
                  <div className="form-group">
                    <label>Category</label>
                    <select
                      value={(newJobParams.category as string) || ''}
                      onChange={e => setNewJobParams({ ...newJobParams, category: e.target.value || undefined })}
                      className="settings-select"
                    >
                      <option value="">All</option>
                      <option value="enforcement">Enforcement</option>
                      <option value="crime">Crime</option>
                    </select>
                  </div>
                  <div className="form-group">
                    <label>Limit</label>
                    <input
                      type="number"
                      min={1}
                      max={500}
                      value={(newJobParams.limit as number) || 50}
                      onChange={e => setNewJobParams({ ...newJobParams, limit: parseInt(e.target.value) || 50 })}
                      className="settings-input"
                    />
                  </div>
                </>
              )}
            </div>
            <div className="modal-footer">
              <button className="action-btn" onClick={() => setShowCreateModal(false)}>
                Cancel
              </button>
              <button className="action-btn primary" onClick={createJob} disabled={creating}>
                {creating ? 'Creating...' : 'Create Job'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default JobManager;
