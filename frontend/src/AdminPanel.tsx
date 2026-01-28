import { useState, useEffect, useCallback } from 'react';
import type { AdminStatus, PipelineResult } from './types';
import {
  fetchAdminStatus,
  runPipelineFetch,
  runPipelineProcess,
  runFullPipeline,
  fetchQueueStats,
  fetchPipelineConfig,
  fetchLLMStatus,
} from './api';
import { SettingsPanel } from './SettingsPanel';
import { IncidentBrowser } from './IncidentBrowser';
import { JobManager } from './JobManager';
import { AnalyticsDashboard } from './AnalyticsDashboard';
import { BatchProcessing } from './BatchProcessing';
import { CurationQueue } from './CurationQueue';
import './AdminPanel.css';

type AdminView = 'dashboard' | 'queue' | 'batch' | 'pipeline' | 'sources' | 'incidents' | 'jobs' | 'analytics' | 'settings';

interface QueueStats {
  pending: number;
  in_review: number;
  approved: number;
  rejected: number;
}

interface PipelineConfig {
  duplicate_detection: {
    title_similarity_threshold: number;
    strategies_enabled: Record<string, boolean>;
  };
  auto_approval: {
    min_confidence_auto_approve: number;
    enable_auto_approve: boolean;
    enable_auto_reject: boolean;
  };
  llm_extraction: {
    available: boolean;
  };
}

interface AdminPanelProps {
  onClose?: () => void;
  onRefresh?: () => void;
}

export function AdminPanel({ onClose, onRefresh }: AdminPanelProps) {
  const [view, setView] = useState<AdminView>('dashboard');
  const [status, setStatus] = useState<AdminStatus | null>(null);
  const [queueStats, setQueueStats] = useState<QueueStats | null>(null);
  const [pipelineConfig, setPipelineConfig] = useState<PipelineConfig | null>(null);
  const [llmStatus, setLlmStatus] = useState<{ available: boolean; model: string | null } | null>(null);
  const [loading, setLoading] = useState(true);
  const [operating, setOperating] = useState<string | null>(null);
  const [result, setResult] = useState<PipelineResult | null>(null);


  const loadDashboard = useCallback(async () => {
    setLoading(true);
    try {
      const [statusData, statsData, configData, llmData] = await Promise.all([
        fetchAdminStatus().catch(() => null),
        fetchQueueStats().catch(() => null),
        fetchPipelineConfig().catch(() => null),
        fetchLLMStatus().catch(() => null),
      ]);
      if (statusData) setStatus(statusData);
      if (statsData) setQueueStats(statsData);
      if (configData) setPipelineConfig(configData as unknown as PipelineConfig);
      if (llmData) setLlmStatus(llmData);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

  const handleOperation = async (
    operation: string,
    fn: () => Promise<PipelineResult>
  ) => {
    setOperating(operation);
    setResult(null);
    try {
      const res = await fn();
      setResult(res);
      await loadDashboard();
    } catch (err) {
      setResult({ success: false, error: String(err) });
    } finally {
      setOperating(null);
    }
  };

  const formatBytes = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  };

  const formatDate = (isoDate: string) => {
    return new Date(isoDate).toLocaleString();
  };

  return (
    <div className="unified-admin">
      {/* Sidebar Navigation */}
      <nav className="admin-nav">
        <div className="admin-nav-header">
          <h2>Admin Panel</h2>
          {onClose && (
            <button className="admin-close-btn" onClick={onClose}>&times;</button>
          )}
        </div>

        <div className="admin-nav-items">
          <button
            className={`admin-nav-item ${view === 'dashboard' ? 'active' : ''}`}
            onClick={() => setView('dashboard')}
          >
            <span className="nav-icon">📊</span>
            Dashboard
          </button>
          <button
            className={`admin-nav-item ${view === 'queue' ? 'active' : ''}`}
            onClick={() => setView('queue')}
          >
            <span className="nav-icon">📋</span>
            Curation Queue
            {queueStats && queueStats.pending > 0 && (
              <span className="nav-badge">{queueStats.pending}</span>
            )}
          </button>
          <button
            className={`admin-nav-item ${view === 'batch' ? 'active' : ''}`}
            onClick={() => setView('batch')}
          >
            <span className="nav-icon">🤖</span>
            Batch Processing
          </button>
          <button
            className={`admin-nav-item ${view === 'incidents' ? 'active' : ''}`}
            onClick={() => setView('incidents')}
          >
            <span className="nav-icon">📁</span>
            Incidents
          </button>
          <button
            className={`admin-nav-item ${view === 'jobs' ? 'active' : ''}`}
            onClick={() => setView('jobs')}
          >
            <span className="nav-icon">⏳</span>
            Jobs
          </button>
          <button
            className={`admin-nav-item ${view === 'analytics' ? 'active' : ''}`}
            onClick={() => setView('analytics')}
          >
            <span className="nav-icon">📈</span>
            Analytics
          </button>
          <button
            className={`admin-nav-item ${view === 'pipeline' ? 'active' : ''}`}
            onClick={() => setView('pipeline')}
          >
            <span className="nav-icon">⚙️</span>
            Pipeline
          </button>
          <button
            className={`admin-nav-item ${view === 'sources' ? 'active' : ''}`}
            onClick={() => setView('sources')}
          >
            <span className="nav-icon">📡</span>
            Data Sources
          </button>
          <button
            className={`admin-nav-item ${view === 'settings' ? 'active' : ''}`}
            onClick={() => setView('settings')}
          >
            <span className="nav-icon">🔧</span>
            Settings
          </button>
        </div>

        {/* Pipeline Status */}
        <div className="admin-nav-status">
          <h4>System Status</h4>
          <div className="status-indicators">
            <div className="status-row">
              <span className={`status-dot ${llmStatus?.available ? 'active' : ''}`}></span>
              <span>LLM Extraction</span>
            </div>
            <div className="status-row">
              <span className={`status-dot ${pipelineConfig?.auto_approval?.enable_auto_approve ? 'active' : ''}`}></span>
              <span>Auto-Approval</span>
            </div>
            <div className="status-row">
              <span className={`status-dot ${pipelineConfig?.duplicate_detection?.strategies_enabled?.title ? 'active' : ''}`}></span>
              <span>Deduplication</span>
            </div>
          </div>
        </div>
      </nav>

      {/* Main Content */}
      <main className="admin-main">
        {/* Dashboard View */}
        {view === 'dashboard' && (
          <div className="admin-page">
            <div className="page-header">
              <h2>Dashboard</h2>
              <div className="page-actions">
                <button
                  className="action-btn primary"
                  onClick={() => handleOperation('pipeline', () => runFullPipeline(false))}
                  disabled={!!operating}
                >
                  {operating === 'pipeline' ? 'Running...' : 'Run Full Pipeline'}
                </button>
                <button
                  className="action-btn"
                  onClick={() => handleOperation('fetch', () => runPipelineFetch())}
                  disabled={!!operating}
                >
                  {operating === 'fetch' ? 'Fetching...' : 'Fetch New Data'}
                </button>
              </div>
            </div>

            {loading ? (
              <div className="admin-loading">Loading...</div>
            ) : (
              <div className="page-content">
                {/* Stats Grid */}
                <div className="dashboard-stats">
                  <div className="stat-card">
                    <div className="stat-value">{status?.total_incidents || 0}</div>
                    <div className="stat-label">Total Incidents</div>
                  </div>
                  <div className="stat-card highlight clickable" onClick={() => setView('queue')}>
                    <div className="stat-value">{queueStats?.pending || 0}</div>
                    <div className="stat-label">Pending Review</div>
                  </div>
                  <div className="stat-card success">
                    <div className="stat-value">{queueStats?.approved || 0}</div>
                    <div className="stat-label">Approved</div>
                  </div>
                  <div className="stat-card danger">
                    <div className="stat-value">{queueStats?.rejected || 0}</div>
                    <div className="stat-label">Rejected</div>
                  </div>
                </div>

                {/* Two column layout for tier breakdown and operation result */}
                <div className="dashboard-grid">
                  {/* Tier Breakdown */}
                  {status?.by_tier && (
                    <div className="dashboard-card">
                      <h3>Incidents by Tier</h3>
                      <div className="tier-bars">
                        {Object.entries(status.by_tier).map(([tier, count]) => (
                          <div key={tier} className="tier-bar">
                            <div className="tier-label">Tier {tier}</div>
                            <div className="tier-progress">
                              <div
                                className={`tier-fill tier-${tier}`}
                                style={{ width: `${Math.min(100, (count / (status.total_incidents || 1)) * 100)}%` }}
                              ></div>
                            </div>
                            <div className="tier-count">{count}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Operation Result */}
                  <div className="dashboard-card">
                    <h3>Last Operation</h3>
                    {result ? (
                      <div className={`operation-result ${result.success ? 'success' : 'error'}`}>
                        <div className="result-header">
                          {result.success ? '✓' : '✗'} {result.operation || 'Operation'} - {result.success ? 'Success' : 'Failed'}
                        </div>
                        {result.error && <div className="result-error">{result.error}</div>}
                        {result.stats && (
                          <div className="result-stats">
                            <span>Total: {result.stats.total}</span>
                            <span>Duplicates: {result.stats.duplicates_removed}</span>
                            <span>Errors: {result.stats.validation_errors}</span>
                          </div>
                        )}
                      </div>
                    ) : (
                      <p className="no-data">No recent operations</p>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Curation Queue View */}
        {view === 'queue' && (
          <CurationQueue onRefresh={loadDashboard} />
        )}

        {/* Pipeline View */}
        {view === 'pipeline' && (
          <div className="admin-page">
            <div className="page-header">
              <h2>Pipeline Management</h2>
              <div className="page-actions">
                <button
                  className="action-btn primary"
                  onClick={() => handleOperation('full-pipeline', () => runFullPipeline(false))}
                  disabled={!!operating}
                >
                  {operating === 'full-pipeline' ? 'Running...' : 'Run Full Pipeline'}
                </button>
                <button
                  className="action-btn"
                  onClick={() => handleOperation('fetch', () => runPipelineFetch())}
                  disabled={!!operating}
                >
                  {operating === 'fetch' ? 'Fetching...' : 'Fetch Sources'}
                </button>
                <button
                  className="action-btn"
                  onClick={() => handleOperation('process', runPipelineProcess)}
                  disabled={!!operating}
                >
                  {operating === 'process' ? 'Processing...' : 'Process Data'}
                </button>
              </div>
            </div>

            <div className="page-content">
              {/* Pipeline Stages */}
              <div className="pipeline-stages">
                <div className="stage-card">
                  <div className="stage-header">
                    <span className={`stage-dot ${pipelineConfig?.duplicate_detection?.strategies_enabled?.title ? 'active' : ''}`}></span>
                    <h3>Duplicate Detection</h3>
                  </div>
                  <div className="stage-config">
                    <div className="config-row">
                      <span>Title Similarity</span>
                      <span>{((pipelineConfig?.duplicate_detection?.title_similarity_threshold || 0) * 100).toFixed(0)}%</span>
                    </div>
                    <div className="config-row">
                      <span>Strategies</span>
                      <span>
                        {Object.entries(pipelineConfig?.duplicate_detection?.strategies_enabled || {})
                          .filter(([, v]) => v)
                          .map(([k]) => k)
                          .join(', ') || 'None'}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="stage-card">
                  <div className="stage-header">
                    <span className={`stage-dot ${llmStatus?.available ? 'active' : ''}`}></span>
                    <h3>LLM Extraction</h3>
                  </div>
                  <div className="stage-config">
                    <div className="config-row">
                      <span>Status</span>
                      <span className={llmStatus?.available ? 'text-success' : 'text-danger'}>
                        {llmStatus?.available ? 'Available' : 'Unavailable'}
                      </span>
                    </div>
                    {llmStatus?.model && (
                      <div className="config-row">
                        <span>Model</span>
                        <span>{llmStatus.model}</span>
                      </div>
                    )}
                  </div>
                </div>

                <div className="stage-card">
                  <div className="stage-header">
                    <span className={`stage-dot ${pipelineConfig?.auto_approval?.enable_auto_approve ? 'active' : ''}`}></span>
                    <h3>Auto-Approval</h3>
                  </div>
                  <div className="stage-config">
                    <div className="config-row">
                      <span>Auto-Approve</span>
                      <span>{pipelineConfig?.auto_approval?.enable_auto_approve ? 'Enabled' : 'Disabled'}</span>
                    </div>
                    <div className="config-row">
                      <span>Min Confidence</span>
                      <span>{((pipelineConfig?.auto_approval?.min_confidence_auto_approve || 0) * 100).toFixed(0)}%</span>
                    </div>
                    <div className="config-row">
                      <span>Auto-Reject</span>
                      <span>{pipelineConfig?.auto_approval?.enable_auto_reject ? 'Enabled' : 'Disabled'}</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Operation Result */}
              {result && (
                <div className={`operation-result ${result.success ? 'success' : 'error'}`}>
                  <div className="result-header">
                    {result.success ? '✓' : '✗'} {result.operation || 'Operation'}
                  </div>
                  {result.error && <div className="result-error">{result.error}</div>}
                  {result.stats && (
                    <div className="result-stats">
                      <div>Total processed: {result.stats.total}</div>
                      <div>Duplicates removed: {result.stats.duplicates_removed}</div>
                      <div>Validation errors: {result.stats.validation_errors}</div>
                      <div>Geocoded: {result.stats.geocoded}</div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Data Sources View */}
        {view === 'sources' && (
          <div className="admin-page">
            <div className="page-header">
              <h2>Data Sources</h2>
              <div className="page-actions">
                <button
                  className="action-btn primary"
                  onClick={() => handleOperation('fetch-all', () => runPipelineFetch())}
                  disabled={!!operating}
                >
                  {operating === 'fetch-all' ? 'Fetching...' : 'Fetch All Sources'}
                </button>
              </div>
            </div>

            <div className="page-content">
              {/* Sources Grid */}
              <div className="content-section">
                <h3>Available Sources</h3>
                <div className="sources-grid">
                  {status?.available_sources?.map(source => (
                    <div key={source.name} className={`source-card ${source.enabled ? '' : 'disabled'}`}>
                      <div className="source-header">
                        <span className="source-name">{source.name}</span>
                        <span className={`tier-badge tier-${source.tier}`}>Tier {source.tier}</span>
                      </div>
                      <p className="source-desc">{source.description}</p>
                      <div className="source-footer">
                        <button
                          className="action-btn small"
                          onClick={() => handleOperation(`fetch-${source.name}`, () => runPipelineFetch(source.name, true))}
                          disabled={!!operating || !source.enabled}
                        >
                          {operating === `fetch-${source.name}` ? 'Fetching...' : 'Fetch'}
                        </button>
                        {!source.enabled && <span className="disabled-label">Disabled</span>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Data Files */}
              {status?.data_files && status.data_files.length > 0 && (
                <div className="content-section">
                  <h3>Data Files</h3>
                  <div className="table-container">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>File</th>
                          <th>Tier</th>
                          <th>Size</th>
                          <th>Modified</th>
                        </tr>
                      </thead>
                      <tbody>
                        {status.data_files.map(file => (
                          <tr key={file.filename}>
                            <td>{file.filename}</td>
                            <td><span className={`tier-badge tier-${file.tier}`}>Tier {file.tier}</span></td>
                            <td>{formatBytes(file.size_bytes)}</td>
                            <td>{formatDate(file.modified)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Batch Processing View */}
        {view === 'batch' && (
          <BatchProcessing onRefresh={() => { loadDashboard(); onRefresh?.(); }} />
        )}

        {/* Incidents Browser View */}
        {view === 'incidents' && (
          <IncidentBrowser />
        )}

        {/* Job Manager View */}
        {view === 'jobs' && (
          <JobManager />
        )}

        {/* Analytics Dashboard View */}
        {view === 'analytics' && (
          <AnalyticsDashboard />
        )}

        {/* Settings View */}
        {view === 'settings' && (
          <SettingsPanel />
        )}
      </main>
    </div>
  );
}

export default AdminPanel;
