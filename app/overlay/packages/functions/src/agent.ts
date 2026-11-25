/**
 * Asks the published Fabric data agent one question.
 *
 * A published data agent is a Model Context Protocol server with one tool. This file speaks that
 * protocol over plain HTTP, in the order the Rayfin guidance for data agents gives (skill
 * `fabric-data-agent` of the Universal App template, version 2.0.1): `initialize`,
 * `notifications/initialized`, `tools/list`, `tools/call`. An answer may come as JSON or as an event
 * stream; the session header is passed on when the server sends one.
 *
 * Nothing here writes a question, an answer or a token to the log.
 */
import { AGENT_TIMEOUT_MS, MAX_ANSWER_CHARS, MAX_QUESTION_CHARS } from './config.js';
import type { AgentAnswer } from './contract.js';
import { brief } from './fabric.js';

interface JsonRpcResponse {
  id?: number | string | null;
  result?: unknown;
  error?: { code?: number; message?: string };
}

export class AgentError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'AgentError';
  }
}

/** The JSON-RPC message in a response body: the body itself, or the last `data:` line of an event stream. */
export function parseJsonRpc(body: string, id?: number): JsonRpcResponse | null {
  const trimmed = body.trim();
  if (!trimmed) return null;
  const events = trimmed
    .split(/\r?\n/)
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice('data:'.length).trim())
    .filter((line) => line.length > 0);
  const candidates = events.length > 0 ? events : [trimmed];
  let last: JsonRpcResponse | null = null;
  for (const candidate of candidates) {
    try {
      const parsed: unknown = JSON.parse(candidate);
      if (parsed && typeof parsed === 'object') {
        const message = parsed as JsonRpcResponse;
        if (id !== undefined && message.id === id) return message; // the answer to this request
        if ('result' in message || 'error' in message) last = message;
      }
    } catch {
      // a line that is not JSON, such as a keep-alive comment
    }
  }
  return last;
}

interface Session {
  endpoint: string;
  token: string;
  fetch: typeof fetch;
  signal: AbortSignal;
  sessionId?: string;
  nextId: number;
}

async function post(session: Session, method: string, params: unknown, expectAnswer: boolean): Promise<unknown> {
  const id = expectAnswer ? session.nextId++ : undefined;
  const response = await session.fetch(session.endpoint, {
    method: 'POST',
    headers: {
      Accept: 'application/json, text/event-stream',
      Authorization: `Bearer ${session.token}`,
      'Content-Type': 'application/json',
      'MCP-Protocol-Version': '2025-03-26',
      ...(session.sessionId ? { 'Mcp-Session-Id': session.sessionId } : {}),
    },
    body: JSON.stringify({ jsonrpc: '2.0', ...(id !== undefined ? { id } : {}), method, ...(params !== undefined ? { params } : {}) }),
    signal: session.signal,
  });
  session.sessionId = response.headers.get('mcp-session-id') ?? session.sessionId;
  const body = await response.text();
  if (!response.ok) {
    throw new AgentError(`The data agent answered ${response.status} to ${method}: ${brief(body)}`);
  }
  if (!expectAnswer) return undefined; // a notification is acknowledged, for example with "Accepted"
  const message = parseJsonRpc(body, id);
  if (!message) throw new AgentError(`The data agent sent no answer to ${method}.`);
  if (message.error) throw new AgentError(`The data agent refused ${method}: ${brief(message.error.message ?? 'no message')}`);
  return message.result;
}

interface Tool {
  name: string;
  inputSchema?: { properties?: Record<string, unknown>; required?: string[] };
}

/** The name of the argument that carries the question: `question` if the tool has it, else its first one. */
export function questionArgument(tool: Tool): string {
  const names = Object.keys(tool.inputSchema?.properties ?? {});
  if (names.includes('question')) return 'question';
  const required = tool.inputSchema?.required?.[0];
  const name = required ?? names[0];
  if (!name) throw new AgentError(`The tool ${tool.name} of the data agent declares no argument.`);
  return name;
}

export async function askDataAgent(
  endpoint: string,
  token: string,
  question: string,
  fetchImpl: typeof fetch,
  timeoutMs: number = AGENT_TIMEOUT_MS
): Promise<AgentAnswer> {
  const asked = question.trim();
  if (!asked) throw new AgentError('The question is empty.');
  if (asked.length > MAX_QUESTION_CHARS) throw new AgentError(`The question is longer than ${MAX_QUESTION_CHARS} characters.`);

  const started = Date.now();
  const session: Session = { endpoint, token, fetch: fetchImpl, signal: AbortSignal.timeout(timeoutMs), nextId: 1 };
  try {
    await post(session, 'initialize', {
      protocolVersion: '2025-03-26',
      capabilities: {},
      clientInfo: { name: 'windfarm-twin', version: '1.0.0' },
    }, true);
    await post(session, 'notifications/initialized', undefined, false);

    const listed = (await post(session, 'tools/list', {}, true)) as { tools?: Tool[] } | undefined;
    const tool = listed?.tools?.[0];
    if (!tool) throw new AgentError('The data agent offers no tool. Is it published?');

    const result = (await post(session, 'tools/call', {
      name: tool.name,
      arguments: { [questionArgument(tool)]: asked },
    }, true)) as { content?: { type?: string; text?: string }[]; isError?: boolean } | undefined;

    const text = (result?.content ?? [])
      .filter((block) => block.type === 'text' && typeof block.text === 'string')
      .map((block) => block.text as string)
      .join('\n')
      .trim();
    if (result?.isError) throw new AgentError(`The data agent reported an error: ${brief(text || 'no message')}`);
    if (!text) throw new AgentError('The data agent answered without text.');
    return { text: text.slice(0, MAX_ANSWER_CHARS), seconds: Math.round((Date.now() - started) / 100) / 10 };
  } catch (error) {
    if (error instanceof AgentError) throw error;
    if (error instanceof Error && (error.name === 'TimeoutError' || error.name === 'AbortError')) {
      throw new AgentError(`The data agent did not answer within ${Math.round(timeoutMs / 1000)} seconds.`);
    }
    throw new AgentError(`The data agent could not be reached: ${brief(error)}`);
  }
}
