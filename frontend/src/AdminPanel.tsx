import { useState, useEffect } from 'react';
import type { AdminStatus, PipelineResult } from './types';
import { fetchAdminStatus, runPipelineFetch, runPipelineProcess, runFullPipeline } from './api';

export function AdminPanel() {
  const [status, setStatus] = useState<AdminStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [operating, setOperating] = useState<string | null>(null);
  const [result, setResult] = useState<PipelineResult | null>(null);

  const loadStatus = async () => {
    setLoading(true);
    try {
      const data = await fetchAdminStatus();
      setStatus(data);
    } catch (err) {
      console.error('Failed to load admin status:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStatus();
  }, []);

  const handleOperation = async (
    operation: string,
    fn: () => Promise<PipelineResult>
  ) => {
    setOperating(operation);
    setResult(null);
    try {
      const res = await fn();
      setResult(res);
      // Refresh status after operation
      await loadStatus();
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

  if (loading && !status) {
    return <div className="admin-panel"><div className="admin-loading">Loading admin status...</div></div>;
  }

  return (
    <div className="admin-panel">
      <h2>Data Pipeline Administration</h2>

      {/* Data Status */}
      <section className="admin-section">
        <h3>Data Status</h3>
        <div className="admin-stats">
          <div className="admin-stat">
            <span className="admin-stat-value">{status?.total_incidents || 0}</span>
            <span className="admin-stat-label">Total Incidents</span>
          </div>
          {status?.by_tier && Object.entries(status.by_tier).map(([tier, count]) => (
            <div key={tier} className="admin-stat">
              <span className="admin-stat-value">{count}</span>
              <span className="admin-stat-label">Tier {tier}</span>
            </div>
          ))}
        </div>
      </section>

      {/* Data Files */}
      <section className="admin-section">
        <h3>Source Files</h3>
        <div className="admin-files">
          {status?.data_files?.map((file) => (
            <div key={file.filename} className="admin-file">
              <span className="admin-file-name">{file.filename}</span>
              <span className="admin-file-meta">
                Tier {file.tier} | {formatBytes(file.size_bytes)} | Modified: {formatDate(file.modified)}
              </span>
            </div>
          ))}
        </div>
      </section>

      {/* Pipeline Controls */}
      <section className="admin-section">
        <h3>Pipeline Operations</h3>
        <div className="admin-controls">
          <button
            className="admin-btn admin-btn-primary"
            onClick={() => handleOperation('run', () => runFullPipeline(false))}
            disabled={!!operating}
          >
            {operating === 'run' ? 'Running...' : 'Run Full Pipeline'}
          </button>
          <button
            className="admin-btn"
            onClick={() => handleOperation('fetch', () => runPipelineFetch())}
            disabled={!!operating}
          >
            {operating === 'fetch' ? 'Fetching...' : 'Fetch All Sources'}
          </button>
          <button
            className="admin-btn"
            onClick={() => handleOperation('process', runPipelineProcess)}
            disabled={!!operating}
          >
            {operating === 'process' ? 'Processing...' : 'Process Data'}
          </button>
        </div>
      </section>

      {/* Available Sources */}
      <section className="admin-section">
        <h3>Available Sources</h3>
        <div className="admin-sources">
          {status?.available_sources?.map((source) => (
            <div key={source.name} className={`admin-source ${source.enabled ? '' : 'disabled'}`}>
              <div className="admin-source-header">
                <span className="admin-source-name">{source.name}</span>
                <span className={`admin-source-badge tier-${source.tier}`}>Tier {source.tier}</span>
                {!source.enabled && <span className="admin-source-badge disabled">Disabled</span>}
              </div>
              <p className="admin-source-desc">{source.description}</p>
              <button
                className="admin-btn admin-btn-small"
                onClick={() => handleOperation(`fetch-${source.name}`, () => runPipelineFetch(source.name, true))}
                disabled={!!operating || !source.enabled}
              >
                {operating === `fetch-${source.name}` ? 'Fetching...' : 'Fetch'}
              </button>
            </div>
          ))}
        </div>
      </section>

      {/* Operation Result */}
      {result && (
        <section className="admin-section">
          <h3>Operation Result</h3>
          <div className={`admin-result ${result.success ? 'success' : 'error'}`}>
            <div className="admin-result-header">
              {result.success ? 'Success' : 'Error'}: {result.operation || 'Unknown operation'}
            </div>
            {result.error && (
              <div className="admin-result-error">{result.error}</div>
            )}
            {result.fetched && (
              <div className="admin-result-detail">
                Fetched: {JSON.stringify(result.fetched)}
              </div>
            )}
            {result.stats && (
              <div className="admin-result-detail">
                <div>Total: {result.stats.total}</div>
                <div>Duplicates removed: {result.stats.duplicates_removed}</div>
                <div>Validation errors: {result.stats.validation_errors}</div>
                <div>Geocoded: {result.stats.geocoded}</div>
              </div>
            )}
            {result.summary && (
              <div className="admin-result-detail">
                <pre>{JSON.stringify(result.summary, null, 2)}</pre>
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
