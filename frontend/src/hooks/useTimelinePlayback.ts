import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import type { Incident } from '../types';

export interface TimelinePlaybackReturn {
  timelineEnabled: boolean;
  timelineDate: string | null;
  isPlaying: boolean;
  playIntervalRef: React.RefObject<ReturnType<typeof setInterval> | null>;
  sortedDates: string[];
  getTimelineIncidents: () => Incident[];
  handleTimelineToggle: () => void;
  handlePlayPause: () => void;
  setTimelineDate: React.Dispatch<React.SetStateAction<string | null>>;
  setIsPlaying: React.Dispatch<React.SetStateAction<boolean>>;
}

export function useTimelinePlayback(incidents: Incident[]): TimelinePlaybackReturn {
  const [timelineEnabled, setTimelineEnabled] = useState(false);
  const [timelineDate, setTimelineDate] = useState<string | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const playIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const sortedDates = useMemo(
    () => [...new Set(incidents.map(i => i.date?.split('T')[0]).filter(Boolean))].sort() as string[],
    [incidents]
  );

  // Keep a ref to sortedDates so the interval callback always sees fresh data
  const sortedDatesRef = useRef(sortedDates);
  useEffect(() => {
    sortedDatesRef.current = sortedDates;
  }, [sortedDates]);

  const clearPlayInterval = useCallback(() => {
    if (playIntervalRef.current) {
      clearInterval(playIntervalRef.current);
      playIntervalRef.current = null;
    }
  }, []);

  const getTimelineIncidents = useCallback(() => {
    if (!timelineEnabled || !timelineDate) return incidents;
    return incidents.filter(i => i.date && i.date.split('T')[0] <= timelineDate);
  }, [incidents, timelineEnabled, timelineDate]);

  const handleTimelineToggle = useCallback(() => {
    if (!timelineEnabled) {
      setTimelineEnabled(true);
      setTimelineDate(sortedDates[0] || null);
    } else {
      setTimelineEnabled(false);
      setTimelineDate(null);
      setIsPlaying(false);
      clearPlayInterval();
    }
  }, [timelineEnabled, sortedDates, clearPlayInterval]);

  const handlePlayPause = useCallback(() => {
    if (isPlaying) {
      setIsPlaying(false);
      clearPlayInterval();
    } else {
      setIsPlaying(true);
      clearPlayInterval(); // Clear any stale interval before starting a new one
      playIntervalRef.current = setInterval(() => {
        const dates = sortedDatesRef.current;
        setTimelineDate(current => {
          const currentIdx = dates.indexOf(current || '');
          if (currentIdx >= dates.length - 1) {
            // Reached the end -- stop playback
            setIsPlaying(false);
            clearPlayInterval();
            return current;
          }
          return dates[currentIdx + 1];
        });
      }, 500);
    }
  }, [isPlaying, clearPlayInterval]);

  // Sync interval lifecycle with isPlaying state changes from external callers
  useEffect(() => {
    if (!isPlaying) {
      clearPlayInterval();
    }
  }, [isPlaying, clearPlayInterval]);

  // Cleanup interval on unmount
  useEffect(() => {
    return () => {
      clearPlayInterval();
    };
  }, [clearPlayInterval]);

  return {
    timelineEnabled,
    timelineDate,
    isPlaying,
    playIntervalRef,
    sortedDates,
    getTimelineIncidents,
    handleTimelineToggle,
    handlePlayPause,
    setTimelineDate,
    setIsPlaying,
  };
}
