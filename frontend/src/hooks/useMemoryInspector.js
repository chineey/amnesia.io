import { useState, useEffect, useCallback } from 'react';
import { getProfile, getMemories } from '@/lib/api';

const EMPTY_PROFILE = { facts: [], preferences: [], events: [] };

export function useMemoryInspector(userId, sessionId) {
  const [coreProfile, setCoreProfile] = useState(EMPTY_PROFILE);
  const [allEpisodicMemories, setAllEpisodicMemories] = useState([]);

  const refresh = useCallback(async () => {
    try {
      const [profile, memories] = await Promise.all([
        getProfile(userId),
        getMemories(userId),
      ]);
      setCoreProfile(profile);
      setAllEpisodicMemories(memories);
    } catch (err) {
      console.error('Error refreshing memory inspector:', err);
    }
  }, [userId]);

  useEffect(() => {
    refresh();
  }, [userId, sessionId, refresh]);

  const reset = useCallback(() => {
    setCoreProfile(EMPTY_PROFILE);
    setAllEpisodicMemories([]);
  }, []);

  return { coreProfile, setCoreProfile, allEpisodicMemories, refresh, reset };
}
