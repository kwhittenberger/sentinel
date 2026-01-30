import { useState, useEffect, useRef, useCallback } from 'react';
import type { Job } from './types';

interface JobWebSocketState {
  jobs: Job[];
  connected: boolean;
  activeJobs: Job[];
  completedJobs: Job[];
}

/**
 * WebSocket hook for real-time job updates.
 * Connects to ws://{host}/ws/jobs and auto-reconnects on disconnect.
 */
export function useJobWebSocket(): JobWebSocketState {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    // In dev mode (Vite proxy), connect via the API backend port
    const host = window.location.host;
    const ws = new WebSocket(`${protocol}//${host}/ws/jobs`);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        switch (data.type) {
          case 'jobs_snapshot':
          case 'jobs_update':
            setJobs(data.jobs || []);
            break;
          case 'job_updated': {
            // Merge single job update into current list
            const updatedJob = data.job as Job;
            setJobs((prev) => {
              const idx = prev.findIndex((j) => j.id === updatedJob.id);
              if (idx >= 0) {
                const next = [...prev];
                next[idx] = updatedJob;
                return next;
              }
              // New job — prepend
              return [updatedJob, ...prev];
            });
            break;
          }
        }
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
      // Auto-reconnect after 3 seconds
      reconnectTimer.current = setTimeout(connect, 3000);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (wsRef.current) {
        wsRef.current.onclose = null; // Prevent reconnect on intentional close
        wsRef.current.close();
      }
    };
  }, [connect]);

  const activeJobs = jobs.filter(
    (j) => j.status === 'pending' || j.status === 'running'
  );
  const completedJobs = jobs.filter(
    (j) => j.status === 'completed' || j.status === 'failed' || j.status === 'cancelled'
  );

  return { jobs, connected, activeJobs, completedJobs };
}
