import { useState, useEffect } from 'react';
import type { QueueMetrics } from './types';
import { fetchMetricsOverview } from './api';

interface QueueStatusBarProps {
  compact?: boolean;
}

const QUEUE_LABELS: Record<string, string> = {
  default: 'Default',
  fetch: 'Fetch',
  extraction: 'Extraction',
  enrichment: 'Enrichment',
};

function getQueueColor(active: number, reserved: number): string {
  if (active === 0 && reserved === 0) return '#22c55e'; // green — idle
  if (reserved > 5) return '#f97316'; // orange — backing up
  return '#3b82f6'; // blue — active
}

export function QueueStatusBar({ compact = false }: QueueStatusBarProps) {
  const [metrics, setMetrics] = useState<QueueMetrics | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const data = await fetchMetricsOverview();
        if (!cancelled) {
          setMetrics(data);
          setError(!!data.error);
        }
      } catch {
        if (!cancelled) setError(true);
      }
    };
    load();
    const interval = setInterval(load, 10_000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  if (error && !metrics) {
    return (
      <div className={`queue-status-bar ${compact ? 'compact' : ''}`}>
        <span className="queue-status-label">Queues:</span>
        <span className="queue-pill offline">offline</span>
      </div>
    );
  }

  if (!metrics) {
    return (
      <div className={`queue-status-bar ${compact ? 'compact' : ''}`}>
        <span className="queue-status-label">Queues:</span>
        <span className="queue-pill loading">loading...</span>
      </div>
    );
  }

  const queueNames = Object.keys(metrics.queues).sort();
  const { totals } = metrics;

  return (
    <div className={`queue-status-bar ${compact ? 'compact' : ''}`}>
      {!compact && (
        <span className="queue-status-label">Queues:</span>
      )}
      <div className="queue-pills">
        {queueNames.map((name) => {
          const q = metrics.queues[name];
          const color = getQueueColor(q.active, q.reserved);
          const label = QUEUE_LABELS[name] || name;
          return (
            <span
              key={name}
              className="queue-pill"
              style={{ borderColor: color, color }}
              title={`${label}: ${q.active} active, ${q.reserved} reserved, ${q.workers.length} workers`}
            >
              {compact ? name.slice(0, 3) : label}
              :{q.active}/{q.reserved}
            </span>
          );
        })}
      </div>
      {!compact && (
        <span className="queue-workers-badge" title="Total connected workers">
          {totals.total_workers} worker{totals.total_workers !== 1 ? 's' : ''}
        </span>
      )}
    </div>
  );
}
