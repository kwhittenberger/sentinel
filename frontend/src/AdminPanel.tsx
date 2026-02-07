import { useState, useEffect, useCallback } from 'react';
import type { AdminStatus } from './types';
import {
  fetchAdminStatus,
  fetchQueueStats,
  fetchPipelineConfig,
  fetchLLMStatus,
} from './api';
import { SettingsPanel } from './SettingsPanel';
import { IncidentBrowser } from './IncidentBrowser';
import { QueueStatusBar } from './QueueStatusBar';
import { AnalyticsDashboard } from './AnalyticsDashboard';
import { IncidentTypeManager } from './IncidentTypeManager';
import { PromptManager } from './PromptManager';
import { EventBrowser } from './EventBrowser';
import { ActorBrowser } from './ActorBrowser';
import { DomainManager } from './DomainManager';
import { CaseManager } from './CaseManager';
import { ProsecutorDashboard } from './ProsecutorDashboard';
import { RecidivismDashboard } from './RecidivismDashboard';
import { PipelineView } from './PipelineView';
import './AdminPanel.css';

type AdminView = 'dashboard' | 'pipeline' | 'incidents' | 'analytics' | 'settings' | 'types' | 'prompts' | 'events' | 'actors' | 'domains' | 'cases' | 'prosecutors' | 'recidivism';

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

  return (
    <div className="unified-admin">
      {/* Sidebar Navigation */}
      <nav className="admin-nav">
        <div className="admin-nav-header">
          <h2>Admin Panel</h2>
          {onClose && (
            <button className="admin-close-btn" onClick={onClose} aria-label="Close admin panel">&times;</button>
          )}
        </div>

        <div className="admin-nav-items">
          {/* Overview */}
          <button
            className={`admin-nav-item ${view === 'dashboard' ? 'active' : ''}`}
            onClick={() => setView('dashboard')}
          >
            <span className="nav-icon">📊</span>
            Dashboard
          </button>

          {/* Pipeline Section */}
          <div className="admin-nav-divider">
            <span>Pipeline</span>
          </div>
          <button
            className={`admin-nav-item ${view === 'pipeline' ? 'active' : ''}`}
            onClick={() => setView('pipeline')}
          >
            <span className="nav-icon">🤖</span>
            Pipeline
          </button>
          {/* Data Section */}
          <div className="admin-nav-divider">
            <span>Data</span>
          </div>
          <button
            className={`admin-nav-item ${view === 'incidents' ? 'active' : ''}`}
            onClick={() => setView('incidents')}
          >
            <span className="nav-icon">📁</span>
            Incidents
          </button>
          <button
            className={`admin-nav-item ${view === 'actors' ? 'active' : ''}`}
            onClick={() => setView('actors')}
          >
            <span className="nav-icon">👥</span>
            Actors
          </button>
          <button
            className={`admin-nav-item ${view === 'events' ? 'active' : ''}`}
            onClick={() => setView('events')}
          >
            <span className="nav-icon">📅</span>
            Events
          </button>
          <button
            className={`admin-nav-item ${view === 'cases' ? 'active' : ''}`}
            onClick={() => setView('cases')}
          >
            <span className="nav-icon">⚖️</span>
            Cases
          </button>
          <button
            className={`admin-nav-item ${view === 'prosecutors' ? 'active' : ''}`}
            onClick={() => setView('prosecutors')}
          >
            <span className="nav-icon">🏛️</span>
            Prosecutors
          </button>
          <button
            className={`admin-nav-item ${view === 'recidivism' ? 'active' : ''}`}
            onClick={() => setView('recidivism')}
          >
            <span className="nav-icon">🔄</span>
            Recidivism
          </button>

          {/* System Section */}
          <div className="admin-nav-divider">
            <span>System</span>
          </div>
          <button
            className={`admin-nav-item ${view === 'domains' ? 'active' : ''}`}
            onClick={() => setView('domains')}
          >
            <span className="nav-icon">🏷️</span>
            Domains
          </button>
          <button
            className={`admin-nav-item ${view === 'types' ? 'active' : ''}`}
            onClick={() => setView('types')}
          >
            <span className="nav-icon">📝</span>
            Incident Types
          </button>
          <button
            className={`admin-nav-item ${view === 'prompts' ? 'active' : ''}`}
            onClick={() => setView('prompts')}
          >
            <span className="nav-icon">💬</span>
            Prompts
          </button>
          <button
            className={`admin-nav-item ${view === 'analytics' ? 'active' : ''}`}
            onClick={() => setView('analytics')}
          >
            <span className="nav-icon">📈</span>
            Analytics
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
          <div className="sidebar-queue-status">
            <QueueStatusBar compact />
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
                  onClick={() => setView('pipeline')}
                >
                  Open Pipeline
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
                  <div className="stat-card highlight clickable" onClick={() => setView('pipeline')}>
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

                  {/* Quick Links */}
                  <div className="dashboard-card">
                    <h3>Quick Links</h3>
                    <div className="quick-actions">
                      <button className="action-btn" onClick={() => setView('pipeline')}>Pipeline</button>
                      <button className="action-btn" onClick={() => setView('analytics')}>Analytics</button>
                      <button className="action-btn" onClick={() => setView('incidents')}>Incidents</button>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Pipeline View (unified: Queue, Audit, Sources, Enrichment) */}
        {view === 'pipeline' && (
          <PipelineView onRefresh={() => { loadDashboard(); onRefresh?.(); }} />
        )}

        {/* Incidents Browser View */}
        {view === 'incidents' && (
          <IncidentBrowser />
        )}

        {/* Analytics Dashboard View */}
        {view === 'analytics' && (
          <AnalyticsDashboard />
        )}

        {/* Settings View */}
        {view === 'settings' && (
          <SettingsPanel />
        )}

        {/* Incident Types View */}
        {view === 'types' && (
          <IncidentTypeManager />
        )}

        {/* Prompts View */}
        {view === 'prompts' && (
          <PromptManager />
        )}

        {/* Events View */}
        {view === 'events' && (
          <EventBrowser />
        )}

        {/* Actors View */}
        {view === 'actors' && (
          <ActorBrowser />
        )}

        {/* Domain Management View */}
        {view === 'domains' && (
          <DomainManager />
        )}

        {/* Case Management View */}
        {view === 'cases' && (
          <CaseManager />
        )}

        {/* Prosecutor Dashboard View */}
        {view === 'prosecutors' && (
          <ProsecutorDashboard />
        )}

        {/* Recidivism Dashboard View */}
        {view === 'recidivism' && (
          <RecidivismDashboard />
        )}
      </main>
    </div>
  );
}

export default AdminPanel;
