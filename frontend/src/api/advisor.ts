/**
 * Streaming client for POST /advisor/ask. EventSource only does GET, so we POST
 * and read the text/event-stream body ourselves, dispatching SSE events as they
 * arrive (the reasoning renders progressively).
 */
import { getAccessToken, refreshAccessToken } from './client';
import type { AdviceVerdict } from './types';

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

export interface AskHandlers {
  onDelta?: (accumulated: string) => void; // accumulated partial tool JSON
  onVerdict: (verdict: AdviceVerdict) => void;
  onError: (message: string) => void;
  onDone?: () => void;
}

interface SseEvent {
  event: string;
  data: Record<string, unknown>;
}

function parseBlock(block: string): SseEvent | null {
  let event = 'message';
  const dataLines: string[] = [];
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return null;
  try {
    return { event, data: JSON.parse(dataLines.join('\n')) as Record<string, unknown> };
  } catch {
    return null;
  }
}

export async function askAdvisor(
  body: { question: string; amount_cents?: number | null },
  handlers: AskHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const send = async (allowRetry: boolean): Promise<Response> => {
    const token = getAccessToken();
    const res = await fetch(`${API_URL}/advisor/ask`, {
      method: 'POST',
      credentials: 'include',
      signal,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
    });
    if (res.status === 401 && allowRetry && (await refreshAccessToken())) {
      return send(false);
    }
    return res;
  };

  const res = await send(true);
  if (!res.ok || !res.body) {
    handlers.onError('Frank is unavailable right now.');
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let partial = '';

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split('\n\n');
    buffer = blocks.pop() ?? '';
    for (const block of blocks) {
      const ev = parseBlock(block);
      if (!ev) continue;
      if (ev.event === 'delta') {
        partial += String(ev.data.partial ?? '');
        handlers.onDelta?.(partial);
      } else if (ev.event === 'verdict') {
        handlers.onVerdict(ev.data as unknown as AdviceVerdict);
      } else if (ev.event === 'error') {
        handlers.onError(String(ev.data.detail ?? 'Frank could not form a verdict.'));
      } else if (ev.event === 'done') {
        handlers.onDone?.();
      }
    }
  }
}

/** Best-effort extraction from the streaming partial JSON, for live preview only. */
export function previewFromPartial(buffer: string): {
  verdict: AdviceVerdict['verdict'] | null;
  headline: string;
  reasoning: string;
} {
  const unescape = (s: string) =>
    s.replace(/\\"/g, '"').replace(/\\n/g, '\n').replace(/\\\\/g, '\\');
  const verdict = buffer.match(/"verdict"\s*:\s*"(go|wait|skip|your_call)"/);
  const headline = buffer.match(/"headline"\s*:\s*"((?:[^"\\]|\\.)*)"/);
  const reasoning = buffer.match(/"reasoning"\s*:\s*"((?:[^"\\]|\\.)*)/);
  return {
    verdict: verdict ? (verdict[1] as AdviceVerdict['verdict']) : null,
    headline: headline ? unescape(headline[1]) : '',
    reasoning: reasoning ? unescape(reasoning[1]) : '',
  };
}
