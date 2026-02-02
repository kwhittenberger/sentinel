import { useState, useEffect, useCallback } from 'react';
import type { AdminStatus, PipelineResult } from './types';
import { fetchAdminStatus, runPipelineFetch } from './api';

export function DataSourcesPanel() {
  const [status, setStatus] = useState<AdminStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [operating, setOperating] = useState<string | null>(null);
  const [result, setResult] = useState<PipelineResult | null>(null);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchAdminStatus().catch(() => null);
      if (data) setStatus(data);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  const handleOperation = async (
    operation: string,
    fn: () => Promise<PipelineResult>
  ) => {
    setOperating(operation);
    setResult(null);
    try {
      const res = await fn();
      setResult(res);
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

  if (loading) {
    return <div className="admin-loading">Loading data sources...</div>;
  }

  return (
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

      {result && (
        <div className={`settings-message ${result.success ? 'success' : 'error'}`}>
          {result.success ? 'Fetch completed successfully' : result.error || 'Operation failed'}
        </div>
      )}

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
  );
}

export default DataSourcesPanel;
