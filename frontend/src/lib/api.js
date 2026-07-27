/**
 * Thin wrappers around the backend REST + SSE endpoints. Keeps the manual
 * SSE-parsing loop in one place instead of duplicated across components.
 */
import { authHeaders } from '@/lib/auth';

async function parseSSEStream(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const dataStr = line.slice(6).trim();
      if (!dataStr) continue;
      try {
        onEvent(JSON.parse(dataStr));
      } catch {
        // Ignore occasional partial-buffer JSON parse glitches
      }
    }
  }
}

export async function getProfile() {
  const res = await fetch('/api/profile', { headers: { ...authHeaders() } });
  if (!res.ok) throw new Error('Failed to load profile');
  return res.json();
}

export async function getMemories() {
  const res = await fetch('/api/memories', { headers: { ...authHeaders() } });
  if (!res.ok) throw new Error('Failed to load memories');
  return res.json();
}

export async function purgeMemories() {
  const res = await fetch('/api/memories', { method: 'DELETE', headers: { ...authHeaders() } });
  if (!res.ok) throw new Error('Failed to purge memories');
  return res.json();
}

export async function endSession(sessionId) {
  const res = await fetch('/api/session/end', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!res.ok) throw new Error('Failed to end session');
  return res.json();
}

export async function streamChat({ sessionId, message }, onEvent) {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ session_id: sessionId, message }),
  });
  if (!response.ok) throw new Error(`Chat API error: ${response.statusText}`);
  await parseSSEStream(response, onEvent);
}

export async function streamEvalRun(onEvent) {
  const response = await fetch('/api/eval/run', {
    method: 'POST',
    headers: { ...authHeaders() },
  });
  if (!response.ok) throw new Error('Failed to run simulation');
  await parseSSEStream(response, onEvent);
}
