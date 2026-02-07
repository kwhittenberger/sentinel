import { useState, useRef, useEffect, useCallback } from 'react';
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

  const sortedDates = [...new Set(incidents.map(i => i.date?.split('T')[0]).filter(Boolean))].sort() as string[];

  const getTimelineIncidents = useCallback(() => {
    if (!timelineEnabled || !timelineDate) return incidents;
    return incidents.filter(i => i.date && i.date.split('T')[0] <= timelineDate);
  }, [incidents, timelineEnabled, timelineDate]);

  const handleTimelineToggle = () => {
    if (!timelineEnabled) {
      setTimelineEnabled(true);
      setTimelineDate(sortedDates[0] || null);
    } else {
      setTimelineEnabled(false);
      setTimelineDate(null);
      setIsPlaying(false);
      if (playIntervalRef.current) {
        clearInterval(playIntervalRef.current);
        playIntervalRef.current = null;
      }
    }
  };

  const handlePlayPause = () => {
    if (isPlaying) {
      setIsPlaying(false);
      if (playIntervalRef.current) {
        clearInterval(playIntervalRef.current);
        playIntervalRef.current = null;
      }
    } else {
      setIsPlaying(true);
      playIntervalRef.current = setInterval(() => {
        setTimelineDate(current => {
          const currentIdx = sortedDates.indexOf(current || '');
          if (currentIdx >= sortedDates.length - 1) {
            setIsPlaying(false);
            if (playIntervalRef.current) clearInterval(playIntervalRef.current);
            return current;
          }
          return sortedDates[currentIdx + 1];
        });
      }, 500);
    }
  };

  // Cleanup interval on unmount
  useEffect(() => {
    return () => {
      if (playIntervalRef.current) {
        clearInterval(playIntervalRef.current);
      }
    };
  }, []);

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
