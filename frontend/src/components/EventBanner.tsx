import type { Event } from '../types';

interface EventBannerProps {
  event: Event;
  onClear: () => void;
}

export function EventBanner({ event, onClear }: EventBannerProps) {
  return (
    <div className="event-banner">
      <div className="event-banner-header">
        <div className="event-banner-title">
          <h3>{event.name}</h3>
          <div className="event-banner-meta">
            {event.event_type && (
              <span className="event-banner-type">{event.event_type.replace(/_/g, ' ')}</span>
            )}
            <span className="event-banner-dates">
              {event.start_date?.split('T')[0]}
              {event.end_date && ` \u2014 ${event.end_date.split('T')[0]}`}
              {event.ongoing && ' (ongoing)'}
            </span>
            {event.primary_city && event.primary_state && (
              <span className="event-banner-location">{event.primary_city}, {event.primary_state}</span>
            )}
            <span className="event-banner-count">{event.incident_count} incident{event.incident_count !== 1 ? 's' : ''}</span>
          </div>
        </div>
        <button className="event-banner-close" onClick={onClear}>
          Clear Event
        </button>
      </div>
      {event.ai_summary && (
        <p className="event-banner-summary">{event.ai_summary}</p>
      )}
      {!event.ai_summary && event.description && (
        <p className="event-banner-summary">{event.description}</p>
      )}
      {event.actors && event.actors.length > 0 && (
        <div className="event-banner-actors">
          {event.actors.map((actor, idx) => (
            <span key={`${actor.id}-${actor.role}-${idx}`} className={`event-banner-actor event-banner-actor-${actor.role}`}>
              {actor.canonical_name}
              <span className="event-banner-actor-role">{actor.role.replace(/_/g, ' ')}</span>
            </span>
          ))}
        </div>
      )}
      {event.tags && event.tags.length > 0 && (
        <div className="event-banner-tags">
          {event.tags.map(tag => (
            <span key={tag} className="event-banner-tag">{tag}</span>
          ))}
        </div>
      )}
    </div>
  );
}
