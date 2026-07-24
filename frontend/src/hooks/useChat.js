import { useState, useCallback } from 'react';
import { streamChat } from '@/lib/api';

export function useChat({ userId, sessionId, onMetadata, onSettled }) {
  const [messages, setMessages] = useState([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [retrievedEpisodes, setRetrievedEpisodes] = useState([]);
  const [tokenStats, setTokenStats] = useState(null);
  const [redisHistory, setRedisHistory] = useState([]);

  const sendMessage = useCallback(async (text) => {
    const trimmed = text.trim();
    if (!trimmed || isStreaming) return;

    setMessages((prev) => [...prev, { role: 'user', content: trimmed }, { role: 'assistant', content: '' }]);
    setIsStreaming(true);

    let assistantResponse = '';
    try {
      await streamChat({ userId, sessionId, message: trimmed }, (event) => {
        if (event.type === 'metadata') {
          setRetrievedEpisodes(event.retrieved_episodes);
          setTokenStats(event.token_stats);
          setRedisHistory(event.redis_history);
          onMetadata?.(event.core_profile);
        } else if (event.type === 'token') {
          assistantResponse += event.content;
          setMessages((prev) => {
            const updated = [...prev];
            updated[updated.length - 1] = { role: 'assistant', content: assistantResponse };
            return updated;
          });
        }
      });
    } catch (err) {
      console.error(err);
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: 'assistant',
          content: '[Error: Failed to fetch response. Make sure the backend is running.]',
        };
        return updated;
      });
    } finally {
      setIsStreaming(false);
      onSettled?.();
    }
  }, [userId, sessionId, isStreaming, onMetadata, onSettled]);

  const resetChat = useCallback(() => {
    setMessages([]);
    setRetrievedEpisodes([]);
    setTokenStats(null);
    setRedisHistory([]);
  }, []);

  return { messages, isStreaming, retrievedEpisodes, tokenStats, redisHistory, sendMessage, resetChat };
}
