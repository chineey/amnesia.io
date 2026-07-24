/**
 * Thin wrappers around the backend REST + SSE endpoints. Keeps the manual
 * SSE-parsing loop in one place instead of duplicated across components.
 */

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

export async function getProfile(userId) {
  const res = await fetch(`/api/profile?user_id=${userId}`);
  if (!res.ok) throw new Error('Failed to load profile');
  return res.json();
}

export async function getMemories(userId) {
  const res = await fetch(`/api/memories?user_id=${userId}`);
  if (!res.ok) throw new Error('Failed to load memories');
  return res.json();
}

export async function purgeMemories(userId) {
  const res = await fetch(`/api/memories?user_id=${userId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error('Failed to purge memories');
  return res.json();
}

export async function endSession(userId, sessionId) {
  const res = await fetch('/api/session/end', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId, session_id: sessionId }),
  });
  if (!res.ok) throw new Error('Failed to end session');
  return res.json();
}

export async function streamChat({ userId, sessionId, message }, onEvent) {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId, session_id: sessionId, message }),
  });
  if (!response.ok) throw new Error(`Chat API error: ${response.statusText}`);
  await parseSSEStream(response, onEvent);
}

export async function streamEvalRun({ userId }, onEvent) {
  const response = await fetch('/api/eval/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId }),
  });
  if (!response.ok) throw new Error('Failed to run simulation');
  await parseSSEStream(response, onEvent);
}
