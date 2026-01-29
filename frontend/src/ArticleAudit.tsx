import { useState, useEffect } from 'react';
import { SplitPane } from './SplitPane';

const API_BASE = '/api';

interface ArticleAuditItem {
  id: string;
  title: string;
  source_name: string;
  source_url: string;
  status: 'pending' | 'approved' | 'rejected';
  extraction_confidence: number | null;
  extraction_format: 'keyword_only' | 'llm' | 'none';
  incident_id: string | null;
  has_required_fields: boolean;
  missing_fields: string[];
  published_date: string | null;
  created_at: string;
  extracted_data: any;
  content: string;
}

interface ArticleAuditStats {
  total: number;
  by_status: Record<string, number>;
  by_format: Record<string, number>;
  approved_without_incident: number;
  approved_keyword_only: number;
}

export function ArticleAudit() {
  const [articles, setArticles] = useState<ArticleAuditItem[]>([]);
  const [stats, setStats] = useState<ArticleAuditStats | null>(null);
  const [selectedArticle, setSelectedArticle] = useState<ArticleAuditItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [formatFilter, setFormatFilter] = useState<string>('all');
  const [issuesOnly, setIssuesOnly] = useState(false);

  const fetchArticles = async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (statusFilter !== 'all') params.set('status', statusFilter);
      if (formatFilter !== 'all') params.set('format', formatFilter);
      if (issuesOnly) params.set('issues_only', 'true');

      const response = await fetch(`${API_BASE}/admin/articles/audit?${params}`);
      if (!response.ok) throw new Error('Failed to fetch articles');
      const data = await response.json();
      setArticles(data.articles || []);
      setStats(data.stats || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchArticles();
  }, [statusFilter, formatFilter, issuesOnly]);

  const getStatusColor = (status: string): string => {
    switch (status) {
      case 'approved': return '#22c55e';
      case 'pending': return '#eab308';
      case 'rejected': return '#ef4444';
      default: return '#888';
    }
  };

  const getFormatBadge = (format: string): { label: string; color: string } => {
    switch (format) {
      case 'llm':
        return { label: 'LLM', color: '#22c55e' };
      case 'keyword_only':
        return { label: 'Keywords', color: '#ef4444' };
      case 'none':
        return { label: 'No Extraction', color: '#888' };
      default:
        return { label: 'Unknown', color: '#888' };
    }
  };

  const getConfidenceColor = (confidence: number | null): string => {
    if (!confidence) return '#888';
    if (confidence >= 0.8) return '#22c55e';
    if (confidence >= 0.5) return '#eab308';
    return '#ef4444';
  };

  const hasIssues = (article: ArticleAuditItem): boolean => {
    return (
      (article.status === 'approved' && !article.incident_id) ||
      (article.status === 'approved' && article.extraction_format === 'keyword_only') ||
      (article.status === 'approved' && !article.has_required_fields)
    );
  };

  const getIssueDescription = (article: ArticleAuditItem): string[] => {
    const issues: string[] = [];
    if (article.status === 'approved' && !article.incident_id) {
      issues.push('Approved but not linked to incident');
    }
    if (article.status === 'approved' && article.extraction_format === 'keyword_only') {
      issues.push('Keyword-only extraction (needs LLM re-extraction)');
    }
    if (article.status === 'approved' && !article.has_required_fields) {
      issues.push(`Missing fields: ${article.missing_fields.join(', ')}`);
    }
    return issues;
  };

  if (loading && !articles.length) {
    return <div className="admin-page"><div className="loading">Loading articles...</div></div>;
  }

  return (
    <div className="admin-page article-audit-page">
      <div className="page-header">
        <h2>Article Audit</h2>
        <div className="page-actions">
          <button className="action-btn" onClick={fetchArticles} disabled={loading}>
            Refresh
          </button>
        </div>
      </div>

      {stats && (
        <div className="stats-grid" style={{ marginBottom: '1rem' }}>
          <div className="stat-card">
            <div className="stat-label">Total Articles</div>
            <div className="stat-value">{stats.total}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Pending</div>
            <div className="stat-value">{stats.by_status.pending || 0}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Approved</div>
            <div className="stat-value">{stats.by_status.approved || 0}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Rejected</div>
            <div className="stat-value">{stats.by_status.rejected || 0}</div>
          </div>
          <div className="stat-card warning">
            <div className="stat-label">⚠️ Approved (No Incident)</div>
            <div className="stat-value">{stats.approved_without_incident}</div>
          </div>
          <div className="stat-card warning">
            <div className="stat-label">⚠️ Approved (Keyword Only)</div>
            <div className="stat-value">{stats.approved_keyword_only}</div>
          </div>
        </div>
      )}

      <div className="filter-bar">
        <div className="filter-group">
          <label>Status:</label>
          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
            <option value="all">All</option>
            <option value="pending">Pending</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
          </select>
        </div>
        <div className="filter-group">
          <label>Format:</label>
          <select value={formatFilter} onChange={e => setFormatFilter(e.target.value)}>
            <option value="all">All</option>
            <option value="llm">LLM Extracted</option>
            <option value="keyword_only">Keyword Only</option>
            <option value="none">No Extraction</option>
          </select>
        </div>
        <div className="filter-group">
          <label>
            <input
              type="checkbox"
              checked={issuesOnly}
              onChange={e => setIssuesOnly(e.target.checked)}
            />
            Issues Only
          </label>
        </div>
      </div>

      {error && (
        <div className="settings-message error" style={{ margin: '1rem 0' }}>
          Error: {error}
        </div>
      )}

      <div className="page-content">
        {articles.length === 0 ? (
          <div className="empty-state">
            <p>No articles match the selected filters</p>
          </div>
        ) : (
          <SplitPane
            storageKey="article-audit"
            defaultLeftWidth={400}
            minLeftWidth={300}
            maxLeftWidth={600}
            left={
              <div className="batch-list">
                {articles.map(article => {
                  const formatBadge = getFormatBadge(article.extraction_format);
                  const issues = getIssueDescription(article);
                  const showWarning = hasIssues(article);

                  return (
                    <div
                      key={article.id}
                      className={`batch-item ${selectedArticle?.id === article.id ? 'selected' : ''} ${showWarning ? 'warning' : ''}`}
                      onClick={() => setSelectedArticle(article)}
                    >
                      <div className="item-header">
                        <span className="item-title">{article.title || 'Untitled'}</span>
                        {showWarning && <span className="warning-icon">⚠️</span>}
                      </div>
                      <div className="item-meta">
                        <span
                          className="badge"
                          style={{ background: getStatusColor(article.status) }}
                        >
                          {article.status}
                        </span>
                        <span
                          className="badge"
                          style={{ background: formatBadge.color }}
                        >
                          {formatBadge.label}
                        </span>
                        {article.extraction_confidence !== null && (
                          <span
                            className="badge"
                            style={{ background: getConfidenceColor(article.extraction_confidence) }}
                          >
                            {(article.extraction_confidence * 100).toFixed(0)}%
                          </span>
                        )}
                        {article.incident_id && (
                          <span className="badge" style={{ background: '#3b82f6' }}>
                            📎 Linked
                          </span>
                        )}
                      </div>
                      {issues.length > 0 && (
                        <div className="item-issues">
                          {issues.map((issue, idx) => (
                            <div key={idx} className="issue-tag">• {issue}</div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            }
            right={selectedArticle ? (
              <div className="batch-detail">
                <div className="detail-header">
                  <h3>{selectedArticle.title || 'Untitled Article'}</h3>
                </div>

                <div className="detail-section">
                  <h4>Status</h4>
                  <div className="detail-badges">
                    <span
                      className="badge large"
                      style={{ background: getStatusColor(selectedArticle.status) }}
                    >
                      {selectedArticle.status.toUpperCase()}
                    </span>
                    <span
                      className="badge large"
                      style={{ background: getFormatBadge(selectedArticle.extraction_format).color }}
                    >
                      {getFormatBadge(selectedArticle.extraction_format).label}
                    </span>
                    {selectedArticle.extraction_confidence !== null && (
                      <span
                        className="badge large"
                        style={{ background: getConfidenceColor(selectedArticle.extraction_confidence) }}
                      >
                        Confidence: {(selectedArticle.extraction_confidence * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                </div>

                {hasIssues(selectedArticle) && (
                  <div className="detail-section warning-section">
                    <h4>⚠️ Issues Detected</h4>
                    <ul>
                      {getIssueDescription(selectedArticle).map((issue, idx) => (
                        <li key={idx}>{issue}</li>
                      ))}
                    </ul>
                  </div>
                )}

                <div className="detail-section">
                  <h4>Source</h4>
                  <p><strong>Source:</strong> {selectedArticle.source_name}</p>
                  <p>
                    <strong>URL:</strong>{' '}
                    <a href={selectedArticle.source_url} target="_blank" rel="noopener noreferrer">
                      {selectedArticle.source_url}
                    </a>
                  </p>
                  <p><strong>Published:</strong> {selectedArticle.published_date || 'Unknown'}</p>
                  {selectedArticle.incident_id && (
                    <p><strong>Incident ID:</strong> {selectedArticle.incident_id}</p>
                  )}
                </div>

                {selectedArticle.extraction_format === 'keyword_only' && (
                  <div className="detail-section">
                    <h4>Keyword Extraction (Legacy)</h4>
                    <pre style={{ fontSize: '0.85rem', overflow: 'auto' }}>
                      {JSON.stringify(selectedArticle.extracted_data, null, 2)}
                    </pre>
                  </div>
                )}

                {selectedArticle.extraction_format === 'llm' && selectedArticle.extracted_data && (
                  <div className="detail-section">
                    <h4>LLM Extraction</h4>
                    <div className="extraction-summary">
                      <p><strong>Category:</strong> {selectedArticle.extracted_data.category || 'N/A'}</p>
                      <p><strong>Date:</strong> {selectedArticle.extracted_data.date || 'N/A'}</p>
                      <p><strong>State:</strong> {selectedArticle.extracted_data.state || 'N/A'}</p>
                      <p><strong>City:</strong> {selectedArticle.extracted_data.city || 'N/A'}</p>
                      <p><strong>Incident Type:</strong> {selectedArticle.extracted_data.incident_type || 'N/A'}</p>
                      {selectedArticle.missing_fields.length > 0 && (
                        <p><strong>Missing:</strong> {selectedArticle.missing_fields.join(', ')}</p>
                      )}
                    </div>
                  </div>
                )}

                <div className="detail-section">
                  <h4>Article Content</h4>
                  <div className="article-content" style={{ maxHeight: '300px', overflow: 'auto', fontSize: '0.9rem' }}>
                    {selectedArticle.content || 'No content available'}
                  </div>
                </div>
              </div>
            ) : (
              <div className="batch-detail empty">
                <p>Select an article to view details</p>
              </div>
            )}
          />
        )}
      </div>
    </div>
  );
}

export default ArticleAudit;
