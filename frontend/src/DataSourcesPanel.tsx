import { useState, useEffect, useCallback } from 'react';
import type { Feed } from './types';
import { fetchFeeds, createFeed, deleteFeed as apiDeleteFeed, fetchFeed, toggleFeed } from './api';

const SOURCE_TYPE_LABELS: Record<string, string> = {
  government: 'Government',
  investigative: 'Investigative',
  news: 'News',
  social_media: 'Social Media',
};

const TIER_LABELS: Record<number, string> = {
  1: 'Tier 1 — Official',
  2: 'Tier 2 — Investigative',
  3: 'Tier 3 — News',
  4: 'Tier 4 — Ad-hoc',
};

export function DataSourcesPanel() {
  const [feeds, setFeeds] = useState<Feed[]>([]);
  const [loading, setLoading] = useState(true);
  const [operating, setOperating] = useState<string | null>(null);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [showAddFeed, setShowAddFeed] = useState(false);
  const [newFeed, setNewFeed] = useState({ name: '', url: '', interval_minutes: 60, source_type: 'news', tier: 3 });

  const loadFeeds = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchFeeds();
      setFeeds(data.feeds || []);
    } catch {
      setMessage({ type: 'error', text: 'Failed to load sources' });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadFeeds();
  }, [loadFeeds]);

  const handleToggle = async (feedId: string, active: boolean) => {
    try {
      await toggleFeed(feedId, active);
      setFeeds(prev => prev.map(f => f.id === feedId ? { ...f, active } : f));
    } catch {
      setMessage({ type: 'error', text: 'Failed to toggle source' });
    }
  };

  const handleFetch = async (feedId: string) => {
    setOperating(feedId);
    setMessage(null);
    try {
      const res = await fetchFeed(feedId);
      setMessage({ type: res.success ? 'success' : 'error', text: res.message || (res.success ? 'Fetch triggered' : 'Fetch failed') });
      await loadFeeds();
    } catch {
      setMessage({ type: 'error', text: 'Failed to fetch source' });
    } finally {
      setOperating(null);
    }
  };

  const handleFetchAll = async () => {
    setOperating('fetch-all');
    setMessage(null);
    const activeFeeds = feeds.filter(f => f.active);
    if (activeFeeds.length === 0) {
      setMessage({ type: 'error', text: 'No active sources to fetch' });
      setOperating(null);
      return;
    }
    try {
      const results = await Promise.allSettled(activeFeeds.map(f => fetchFeed(f.id)));
      const succeeded = results.filter(r => r.status === 'fulfilled' && (r as PromiseFulfilledResult<{ success: boolean }>).value.success).length;
      const failed = activeFeeds.length - succeeded;
      setMessage({
        type: failed === 0 ? 'success' : 'error',
        text: `Fetched ${succeeded}/${activeFeeds.length} sources${failed > 0 ? ` (${failed} failed)` : ''}`,
      });
      await loadFeeds();
    } catch {
      setMessage({ type: 'error', text: 'Failed to fetch sources' });
    } finally {
      setOperating(null);
    }
  };

  const handleAddFeed = async () => {
    if (!newFeed.name.trim() || !newFeed.url.trim()) {
      setMessage({ type: 'error', text: 'Name and URL are required' });
      return;
    }
    setOperating('adding');
    setMessage(null);
    try {
      const res = await createFeed(newFeed.name, newFeed.url, newFeed.interval_minutes, newFeed.source_type, newFeed.tier);
      if (res.success) {
        setNewFeed({ name: '', url: '', interval_minutes: 60, source_type: 'news', tier: 3 });
        setShowAddFeed(false);
        setMessage({ type: 'success', text: 'Source added' });
        await loadFeeds();
      } else {
        setMessage({ type: 'error', text: 'Failed to add source' });
      }
    } catch {
      setMessage({ type: 'error', text: 'Failed to add source' });
    } finally {
      setOperating(null);
    }
  };

  const handleDelete = async (feedId: string) => {
    if (!confirm('Delete this source?')) return;
    try {
      await apiDeleteFeed(feedId);
      setFeeds(prev => prev.filter(f => f.id !== feedId));
      setMessage({ type: 'success', text: 'Source deleted' });
    } catch {
      setMessage({ type: 'error', text: 'Failed to delete source' });
    }
  };

  // Group feeds by tier
  const feedsByTier = feeds.reduce<Record<number, Feed[]>>((acc, feed) => {
    const tier = feed.tier || 3;
    if (!acc[tier]) acc[tier] = [];
    acc[tier].push(feed);
    return acc;
  }, {});

  if (loading) {
    return <div className="admin-loading">Loading data sources...</div>;
  }

  return (
    <div className="admin-page">
      <div className="page-header">
        <h2>Data Sources</h2>
        <div className="page-actions">
          <button
            className="action-btn"
            onClick={() => setShowAddFeed(true)}
            disabled={!!operating}
          >
            Add Source
          </button>
          <button
            className="action-btn primary"
            onClick={handleFetchAll}
            disabled={!!operating}
          >
            {operating === 'fetch-all' ? 'Fetching...' : 'Fetch All'}
          </button>
        </div>
      </div>

      {message && (
        <div className={`settings-message ${message.type}`}>
          {message.text}
        </div>
      )}

      {showAddFeed && (
        <div className="content-section">
          <h3>Add New Source</h3>
          <div className="add-feed-form">
            <div className="settings-group">
              <label>Source Name</label>
              <input
                type="text"
                value={newFeed.name}
                onChange={e => setNewFeed({ ...newFeed, name: e.target.value })}
                className="settings-input"
                placeholder="e.g., AP News Immigration"
              />
            </div>
            <div className="settings-group">
              <label>URL</label>
              <input
                type="url"
                value={newFeed.url}
                onChange={e => setNewFeed({ ...newFeed, url: e.target.value })}
                className="settings-input"
                placeholder="https://example.com/feed.rss"
              />
            </div>
            <div className="settings-group">
              <label>Source Type</label>
              <select
                value={newFeed.source_type}
                onChange={e => setNewFeed({ ...newFeed, source_type: e.target.value })}
                className="settings-select"
              >
                <option value="government">Government</option>
                <option value="investigative">Investigative</option>
                <option value="news">News</option>
                <option value="social_media">Social Media</option>
              </select>
            </div>
            <div className="settings-group">
              <label>Tier</label>
              <select
                value={newFeed.tier}
                onChange={e => setNewFeed({ ...newFeed, tier: parseInt(e.target.value) })}
                className="settings-select"
              >
                <option value={1}>Tier 1 — Official</option>
                <option value={2}>Tier 2 — Investigative</option>
                <option value={3}>Tier 3 — News</option>
                <option value={4}>Tier 4 — Ad-hoc</option>
              </select>
            </div>
            <div className="settings-group">
              <label>Fetch Interval (minutes)</label>
              <input
                type="number"
                min="5"
                max="10080"
                value={newFeed.interval_minutes}
                onChange={e => setNewFeed({ ...newFeed, interval_minutes: parseInt(e.target.value) || 60 })}
                className="settings-input"
              />
            </div>
            <div className="form-actions">
              <button className="action-btn primary" onClick={handleAddFeed} disabled={operating === 'adding'}>
                {operating === 'adding' ? 'Adding...' : 'Add Source'}
              </button>
              <button className="action-btn" onClick={() => setShowAddFeed(false)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="page-content">
        {Object.keys(feedsByTier).sort((a, b) => Number(a) - Number(b)).map(tierKey => {
          const tier = Number(tierKey);
          const tierFeeds = feedsByTier[tier];
          return (
            <div key={tier} className="content-section">
              <h3>{TIER_LABELS[tier] || `Tier ${tier}`} ({tierFeeds.length})</h3>
              <div className="sources-grid">
                {tierFeeds.map(feed => (
                  <div key={feed.id} className={`source-card ${feed.active ? '' : 'disabled'}`}>
                    <div className="source-header">
                      <span className="source-name">{feed.name}</span>
                      <label className="toggle-label small">
                        <input
                          type="checkbox"
                          checked={feed.active}
                          onChange={e => handleToggle(feed.id, e.target.checked)}
                        />
                        <span>{feed.active ? 'Active' : 'Inactive'}</span>
                      </label>
                    </div>
                    <div className="feed-url">{feed.url}</div>
                    <div className="feed-meta">
                      <span className={`source-type-badge ${feed.source_type}`}>
                        {SOURCE_TYPE_LABELS[feed.source_type] || feed.source_type}
                      </span>
                      {' '}&middot; Interval: {feed.interval_minutes}m
                      {feed.fetcher_class && <> &middot; Fetcher: {feed.fetcher_class}</>}
                    </div>
                    {feed.last_fetched && (
                      <div className="feed-meta">
                        Last fetched: {new Date(feed.last_fetched).toLocaleString()}
                      </div>
                    )}
                    {feed.last_error && (
                      <div className="feed-meta" style={{ color: 'var(--color-error, #e74c3c)' }}>
                        Error: {feed.last_error}
                      </div>
                    )}
                    <div className="source-footer">
                      <button
                        className="action-btn small"
                        onClick={() => handleFetch(feed.id)}
                        disabled={!!operating}
                      >
                        {operating === feed.id ? 'Fetching...' : 'Fetch'}
                      </button>
                      <button
                        className="action-btn small reject"
                        onClick={() => handleDelete(feed.id)}
                        disabled={!!operating}
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })}

        {feeds.length === 0 && (
          <div className="content-section">
            <p className="no-data">No sources configured. Click "Add Source" to get started.</p>
          </div>
        )}
      </div>
    </div>
  );
}

export default DataSourcesPanel;
