import { useState, useCallback } from 'react';
import { SplitPane } from './SplitPane';

const API_BASE = '';

interface ArticleExtraction {
  id: string;
  article_id: string;
  extraction_data: Record<string, any>;
  classification_hints: Array<{ domain_slug: string; category_slug: string; confidence: number }>;
  entity_count: number | null;
  event_count: number | null;
  overall_confidence: number | null;
  extraction_notes: string | null;
  provider: string | null;
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  latency_ms: number | null;
  status: string;
  error_message: string | null;
  created_at: string;
}

interface SchemaResult {
  id: string;
  article_extraction_id: string;
  schema_id: string;
  schema_name?: string;
  domain_slug?: string;
  category_slug?: string;
  extracted_data: Record<string, any>;
  confidence: number | null;
  validation_errors: Array<{ field: string; error: string }>;
  provider: string | null;
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  latency_ms: number | null;
  used_original_text: boolean;
  status: string;
  error_message: string | null;
  created_at: string;
}

interface ExtractionStatus {
  article_id: string;
  article_title: string;
  extraction_pipeline: string;
  latest_extraction_id: string | null;
  stage1_extractions: ArticleExtraction[];
  stage2_results: SchemaResult[];
}

export function TwoStageExtractionView() {
  const [articleId, setArticleId] = useState('');
  const [status, setStatus] = useState<ExtractionStatus | null>(null);
  const [selectedExtraction, setSelectedExtraction] = useState<ArticleExtraction | null>(null);
  const [selectedResult, setSelectedResult] = useState<SchemaResult | null>(null);
  const [highlightEntity, setHighlightEntity] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [operating, setOperating] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadStatus = useCallback(async (id?: string) => {
    const targetId = id || articleId;
    if (!targetId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/admin/two-stage/status/${targetId}`);
      if (!res.ok) throw new Error(await res.text());
      const data: ExtractionStatus = await res.json();
      setStatus(data);
      // Auto-select latest extraction
      if (data.stage1_extractions.length > 0) {
        setSelectedExtraction(data.stage1_extractions[0]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load');
    } finally {
      setLoading(false);
    }
  }, [articleId]);

  const runStage1 = async (force = false) => {
    if (!articleId) return;
    setOperating('stage1');
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/admin/two-stage/extract-stage1`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ article_id: articleId, force }),
      });
      if (!res.ok) throw new Error(await res.text());
      await loadStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Stage 1 failed');
    } finally {
      setOperating(null);
    }
  };

  const runStage2 = async (extractionId: string, schemaIds?: string[]) => {
    setOperating('stage2');
    setError(null);
    try {
      const body: Record<string, any> = { article_extraction_id: extractionId };
      if (schemaIds) body.schema_ids = schemaIds;
      const res = await fetch(`${API_BASE}/api/admin/two-stage/extract-stage2`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(await res.text());
      await loadStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Stage 2 failed');
    } finally {
      setOperating(null);
    }
  };

  const runFullPipeline = async (force = false) => {
    if (!articleId) return;
    setOperating('full');
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/admin/two-stage/extract-full`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ article_id: articleId, force_stage1: force }),
      });
      if (!res.ok) throw new Error(await res.text());
      await loadStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Pipeline failed');
    } finally {
      setOperating(null);
    }
  };

  const reextractSchema = async (extractionId: string, schemaId: string) => {
    setOperating(`reextract-${schemaId}`);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/admin/two-stage/reextract`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ article_extraction_id: extractionId, schema_id: schemaId }),
      });
      if (!res.ok) throw new Error(await res.text());
      await loadStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Re-extract failed');
    } finally {
      setOperating(null);
    }
  };

  const formatConfidence = (c: number | null) => c !== null ? `${(c * 100).toFixed(0)}%` : '--';

  const extraction = selectedExtraction;
  const entities = extraction?.extraction_data?.entities;
  const events = extraction?.extraction_data?.events;

  return (
    <div className="admin-page">
      <div className="page-header">
        <h2>Two-Stage Extraction</h2>
        <div className="page-actions" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <input
            type="text"
            placeholder="Article UUID..."
            value={articleId}
            onChange={e => setArticleId(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && loadStatus()}
            style={{
              padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border-color)',
              fontSize: 13, background: 'var(--bg-primary)', width: 320,
            }}
          />
          <button className="action-btn" onClick={() => loadStatus()} disabled={loading || !articleId}>
            {loading ? 'Loading...' : 'Load'}
          </button>
          <button className="action-btn primary" onClick={() => runFullPipeline()} disabled={!!operating || !articleId}>
            {operating === 'full' ? 'Running...' : 'Run Full Pipeline'}
          </button>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {status && (
        <>
          {/* Article info bar */}
          <div style={{ padding: '8px 16px', background: 'var(--bg-secondary)', borderRadius: 8, marginBottom: 12, display: 'flex', gap: 16, alignItems: 'center', fontSize: 13 }}>
            <span><strong>Article:</strong> {status.article_title || status.article_id}</span>
            <span className={`badge ${status.extraction_pipeline === 'two_stage' ? 'status-active' : 'inactive'}`}>
              {status.extraction_pipeline}
            </span>
            <span>Stage 1 runs: {status.stage1_extractions.length}</span>
            <span>Stage 2 results: {status.stage2_results.length}</span>
          </div>

          <SplitPane
            storageKey="two-stage-extraction"
            defaultLeftWidth={500}
            minLeftWidth={350}
            maxLeftWidth={800}
            left={
              <div className="list-panel" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                {/* Stage 1 Section */}
                <div className="detail-section">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <h4>Stage 1: Entity Extraction</h4>
                    <div style={{ display: 'flex', gap: 4 }}>
                      <button className="action-btn small" onClick={() => runStage1(false)} disabled={!!operating}>
                        {operating === 'stage1' ? 'Running...' : 'Run'}
                      </button>
                      <button className="action-btn small" onClick={() => runStage1(true)} disabled={!!operating}>
                        Force
                      </button>
                    </div>
                  </div>

                  {extraction ? (
                    <>
                      {/* Status bar */}
                      <div style={{ display: 'flex', gap: 8, marginTop: 8, fontSize: 12, flexWrap: 'wrap' }}>
                        <span className={`badge ${extraction.status === 'completed' ? 'status-active' : extraction.status === 'failed' ? 'crime' : 'inactive'}`}>
                          {extraction.status}
                        </span>
                        <span>Entities: {extraction.entity_count ?? '--'}</span>
                        <span>Events: {extraction.event_count ?? '--'}</span>
                        <span>Confidence: {formatConfidence(extraction.overall_confidence)}</span>
                        {extraction.latency_ms && <span>{extraction.latency_ms}ms</span>}
                        {extraction.model && <span>{extraction.model}</span>}
                      </div>

                      {/* Classification Hints */}
                      {extraction.classification_hints && extraction.classification_hints.length > 0 && (
                        <div style={{ marginTop: 8 }}>
                          <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 4 }}>Classification Hints</div>
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                            {extraction.classification_hints.map((h, i) => (
                              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
                                <span className="badge extraction">{h.domain_slug}/{h.category_slug}</span>
                                <div style={{ width: 60, height: 6, background: 'var(--border-color)', borderRadius: 3, overflow: 'hidden' }}>
                                  <div style={{ width: `${h.confidence * 100}%`, height: '100%', background: h.confidence >= 0.7 ? '#22c55e' : h.confidence >= 0.3 ? '#f59e0b' : '#ef4444', borderRadius: 3 }} />
                                </div>
                                <span style={{ fontSize: 11 }}>{formatConfidence(h.confidence)}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Persons */}
                      {entities?.persons && entities.persons.length > 0 && (
                        <div style={{ marginTop: 10 }}>
                          <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 4 }}>Persons ({entities.persons.length})</div>
                          {entities.persons.map((p: any) => (
                            <div
                              key={p.id}
                              style={{
                                padding: '6px 8px', marginBottom: 4, borderRadius: 6, fontSize: 12,
                                background: highlightEntity === p.id ? 'rgba(59, 130, 246, 0.15)' : 'var(--bg-secondary)',
                                cursor: 'pointer', border: highlightEntity === p.id ? '1px solid #3b82f6' : '1px solid transparent',
                              }}
                              onClick={() => setHighlightEntity(highlightEntity === p.id ? null : p.id)}
                            >
                              <div style={{ fontWeight: 500 }}>{p.name} <span style={{ color: 'var(--text-secondary)', fontWeight: 400 }}>({p.id})</span></div>
                              <div style={{ display: 'flex', gap: 4, marginTop: 2, flexWrap: 'wrap' }}>
                                {(p.roles || []).map((r: string) => (
                                  <span key={r} className="badge" style={{ fontSize: 10, padding: '1px 5px' }}>{r}</span>
                                ))}
                                {p.immigration_status && <span className="badge crime" style={{ fontSize: 10, padding: '1px 5px' }}>{p.immigration_status}</span>}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Organizations */}
                      {entities?.organizations && entities.organizations.length > 0 && (
                        <div style={{ marginTop: 10 }}>
                          <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 4 }}>Organizations ({entities.organizations.length})</div>
                          {entities.organizations.map((o: any) => (
                            <div
                              key={o.id}
                              style={{
                                padding: '4px 8px', marginBottom: 3, borderRadius: 6, fontSize: 12,
                                background: highlightEntity === o.id ? 'rgba(59, 130, 246, 0.15)' : 'var(--bg-secondary)',
                                cursor: 'pointer',
                              }}
                              onClick={() => setHighlightEntity(highlightEntity === o.id ? null : o.id)}
                            >
                              <span style={{ fontWeight: 500 }}>{o.name}</span>
                              {o.org_type && <span style={{ color: 'var(--text-secondary)', marginLeft: 6 }}>{o.org_type}</span>}
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Locations */}
                      {entities?.locations && entities.locations.length > 0 && (
                        <div style={{ marginTop: 10 }}>
                          <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 4 }}>Locations ({entities.locations.length})</div>
                          {entities.locations.map((l: any) => (
                            <div key={l.id} style={{ padding: '4px 8px', marginBottom: 3, borderRadius: 6, fontSize: 12, background: 'var(--bg-secondary)' }}>
                              <span style={{ fontWeight: 500 }}>{l.name}</span>
                              {l.state && <span style={{ marginLeft: 6 }}>{l.city ? `${l.city}, ` : ''}{l.state}</span>}
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Events */}
                      {events && events.length > 0 && (
                        <div style={{ marginTop: 10 }}>
                          <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 4 }}>Events ({events.length})</div>
                          {events.map((e: any) => {
                            const hasHighlighted = highlightEntity && (
                              (e.participants || []).some((p: any) => p.entity_id === highlightEntity) ||
                              e.location_id === highlightEntity
                            );
                            return (
                              <div
                                key={e.id}
                                style={{
                                  padding: '6px 8px', marginBottom: 4, borderRadius: 6, fontSize: 12,
                                  background: hasHighlighted ? 'rgba(59, 130, 246, 0.1)' : 'var(--bg-secondary)',
                                  border: hasHighlighted ? '1px solid rgba(59, 130, 246, 0.3)' : '1px solid transparent',
                                }}
                              >
                                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                                  <span className="badge extraction" style={{ fontSize: 10, padding: '1px 5px' }}>{e.event_type}</span>
                                  {e.is_primary_event && <span className="badge status-active" style={{ fontSize: 10, padding: '1px 5px' }}>primary</span>}
                                  {e.date && <span>{e.date}</span>}
                                </div>
                                {e.description && <div style={{ marginTop: 2, color: 'var(--text-secondary)' }}>{e.description}</div>}
                                {e.participants && e.participants.length > 0 && (
                                  <div style={{ marginTop: 2, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                                    {e.participants.map((p: any, i: number) => (
                                      <span key={i} style={{ fontSize: 11, color: highlightEntity === p.entity_id ? '#3b82f6' : 'var(--text-secondary)' }}>
                                        {p.entity_id}:{p.role}
                                      </span>
                                    ))}
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}

                      {/* Notes */}
                      {extraction.extraction_notes && (
                        <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-secondary)', fontStyle: 'italic' }}>
                          {extraction.extraction_notes}
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="empty-state" style={{ padding: 16 }}><p>No Stage 1 extraction yet. Click Run to start.</p></div>
                  )}
                </div>
              </div>
            }
            right={
              <div className="detail-panel" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {/* Stage 2 Header */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h4 style={{ margin: 0 }}>Stage 2: Schema Results ({status.stage2_results.length})</h4>
                  {extraction && (
                    <button
                      className="action-btn small primary"
                      onClick={() => runStage2(extraction.id)}
                      disabled={!!operating || extraction.status !== 'completed'}
                    >
                      {operating === 'stage2' ? 'Running...' : 'Run Stage 2'}
                    </button>
                  )}
                </div>

                {status.stage2_results.length === 0 ? (
                  <div className="empty-state"><p>No Stage 2 results yet. Run Stage 2 after Stage 1 completes.</p></div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {status.stage2_results.map(r => (
                      <div
                        key={r.id}
                        style={{
                          padding: '10px 12px', borderRadius: 8,
                          background: selectedResult?.id === r.id ? 'rgba(59, 130, 246, 0.08)' : 'var(--bg-secondary)',
                          border: selectedResult?.id === r.id ? '1px solid #3b82f6' : '1px solid var(--border-color)',
                          cursor: 'pointer',
                        }}
                        onClick={() => setSelectedResult(selectedResult?.id === r.id ? null : r)}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                            <span style={{ fontWeight: 600, fontSize: 13 }}>
                              {r.schema_name || `${r.domain_slug}/${r.category_slug}`}
                            </span>
                            <span className={`badge ${r.status === 'completed' ? 'status-active' : r.status === 'failed' ? 'crime' : 'inactive'}`}>
                              {r.status}
                            </span>
                          </div>
                          <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12 }}>
                            <span>Conf: {formatConfidence(r.confidence)}</span>
                            {r.latency_ms && <span>{r.latency_ms}ms</span>}
                            {extraction && (
                              <button
                                className="action-btn small"
                                onClick={(e) => { e.stopPropagation(); reextractSchema(extraction.id, r.schema_id); }}
                                disabled={!!operating}
                                style={{ fontSize: 11 }}
                              >
                                {operating === `reextract-${r.schema_id}` ? '...' : 'Re-extract'}
                              </button>
                            )}
                          </div>
                        </div>

                        {/* Validation errors */}
                        {r.validation_errors && r.validation_errors.length > 0 && (
                          <div style={{ marginTop: 4, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                            {r.validation_errors.map((ve, i) => (
                              <span key={i} className="badge crime" style={{ fontSize: 10, padding: '1px 5px' }}>
                                {ve.field}: {ve.error}
                              </span>
                            ))}
                          </div>
                        )}

                        {/* Expanded extracted data */}
                        {selectedResult?.id === r.id && (
                          <div style={{ marginTop: 8 }}>
                            {r.error_message && (
                              <div style={{ color: '#ef4444', fontSize: 12, marginBottom: 8 }}>{r.error_message}</div>
                            )}
                            <pre className="schema-prompt-preview" style={{ margin: 0, maxHeight: 400, overflow: 'auto' }}>
                              {JSON.stringify(r.extracted_data, null, 2)}
                            </pre>
                            <div style={{ display: 'flex', gap: 8, marginTop: 6, fontSize: 11, color: 'var(--text-secondary)' }}>
                              {r.model && <span>Model: {r.model}</span>}
                              {r.input_tokens && <span>In: {r.input_tokens}</span>}
                              {r.output_tokens && <span>Out: {r.output_tokens}</span>}
                              {r.used_original_text && <span className="badge" style={{ fontSize: 10, padding: '1px 5px' }}>used article text</span>}
                            </div>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            }
          />
        </>
      )}

      {!status && !loading && (
        <div className="empty-state" style={{ padding: 32 }}>
          <p>Enter an article UUID and click Load to view extraction pipeline status, or click Run Full Pipeline to execute both stages.</p>
        </div>
      )}
    </div>
  );
}

export default TwoStageExtractionView;
