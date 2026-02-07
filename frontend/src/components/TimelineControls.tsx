interface TimelineControlsProps {
  isPlaying: boolean;
  onPlayPause: () => void;
  sortedDates: string[];
  timelineDate: string | null;
  onDateChange: (date: string) => void;
  displayedCount: number;
  totalCount: number;
}

export function TimelineControls({
  isPlaying,
  onPlayPause,
  sortedDates,
  timelineDate,
  onDateChange,
  displayedCount,
  totalCount,
}: TimelineControlsProps) {
  return (
    <div className="timeline-controls">
      <button className="timeline-btn" onClick={onPlayPause}>
        {isPlaying ? 'Pause' : 'Play'}
      </button>
      <input
        type="range"
        className="timeline-slider"
        min={0}
        max={sortedDates.length - 1}
        value={sortedDates.indexOf(timelineDate || '')}
        onChange={(e) => {
          onDateChange(sortedDates[parseInt(e.target.value)]);
        }}
      />
      <span className="timeline-date">{timelineDate || 'N/A'}</span>
      <span className="timeline-count">
        {displayedCount} / {totalCount} incidents
      </span>
    </div>
  );
}
