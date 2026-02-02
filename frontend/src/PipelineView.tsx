import { useState, useCallback } from 'react';
import { OperationsBar } from './OperationsBar';
import { BatchProcessing } from './BatchProcessing';
import { ArticleAudit } from './ArticleAudit';
import { DataSourcesPanel } from './DataSourcesPanel';
import { EnrichmentPanel } from './EnrichmentPanel';

type PipelineTab = 'queue' | 'audit' | 'sources' | 'enrichment';

const TABS: { key: PipelineTab; label: string }[] = [
  { key: 'queue', label: 'Queue' },
  { key: 'audit', label: 'Audit' },
  { key: 'sources', label: 'Sources' },
  { key: 'enrichment', label: 'Enrichment' },
];

interface PipelineViewProps {
  onRefresh?: () => void;
}

export function PipelineView({ onRefresh }: PipelineViewProps) {
  const [activeTab, setActiveTab] = useState<PipelineTab>('queue');
  const [opsExpanded, setOpsExpanded] = useState<boolean>(() => {
    const stored = localStorage.getItem('ops-bar-expanded');
    return stored !== null ? stored === 'true' : true;
  });

  const handleOpsToggle = useCallback(() => {
    setOpsExpanded(prev => {
      const next = !prev;
      localStorage.setItem('ops-bar-expanded', String(next));
      return next;
    });
  }, []);

  const handleOperationComplete = useCallback(() => {
    onRefresh?.();
  }, [onRefresh]);

  return (
    <div className="pipeline-view">
      <OperationsBar
        expanded={opsExpanded}
        onToggle={handleOpsToggle}
        onOperationComplete={handleOperationComplete}
      />

      <div className="pipeline-tabs">
        {TABS.map(tab => (
          <button
            key={tab.key}
            className={`pipeline-tab ${activeTab === tab.key ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="pipeline-tab-content">
        {activeTab === 'queue' && <BatchProcessing hideOpsBar onRefresh={onRefresh} />}
        {activeTab === 'audit' && <ArticleAudit />}
        {activeTab === 'sources' && <DataSourcesPanel />}
        {activeTab === 'enrichment' && <EnrichmentPanel />}
      </div>
    </div>
  );
}

export default PipelineView;
