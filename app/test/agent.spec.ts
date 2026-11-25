/**
 * The function's own little MCP client against the reference MCP server of the protocol's SDK, set up
 * as a published data agent is: one tool that takes a question. Both ways a server may answer are
 * covered, as JSON and as an event stream.
 */
import { randomUUID } from 'node:crypto';
import http from 'node:http';
import type { AddressInfo } from 'node:net';

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { isInitializeRequest } from '@modelcontextprotocol/sdk/types.js';
import { afterEach, describe, expect, it } from 'vitest';
import { z } from 'zod';

import { AgentError, askDataAgent, parseJsonRpc, questionArgument } from '../overlay/packages/functions/src/agent';

interface AgentOptions {
  json: boolean;
  argument?: string;
  fail?: boolean;
  delayMs?: number;
}

const servers: http.Server[] = [];
afterEach(async () => {
  await Promise.all(servers.splice(0).map((s) => new Promise((resolve) => { s.closeAllConnections(); s.close(resolve); })));
});

async function dataAgent(options: AgentOptions): Promise<{ url: string; sessions: () => number }> {
  const transports = new Map<string, StreamableHTTPServerTransport>();
  const server = http.createServer(async (req, res) => {
    if (req.headers.authorization !== 'Bearer fabric-token') {
      res.writeHead(401, { 'content-type': 'application/json' }).end(JSON.stringify({ error: 'invalid token' }));
      return;
    }
    const chunks: Buffer[] = [];
    for await (const chunk of req) chunks.push(chunk as Buffer);
    const body: unknown = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    const sessionId = req.headers['mcp-session-id'] as string | undefined;
    let transport = sessionId ? transports.get(sessionId) : undefined;
    if (!transport && isInitializeRequest(body)) {
      const mcp = new McpServer({ name: 'WindFarmDataAgent', version: '1.0.0' });
      mcp.registerTool(
        'WindFarmDataAgent',
        { description: 'Answers questions about the wind farm.', inputSchema: { [options.argument ?? 'userQuestion']: z.string() } },
        async (args: Record<string, string>) => {
          if (options.delayMs) await new Promise((resolve) => setTimeout(resolve, options.delayMs));
          const question = Object.values(args)[0];
          return options.fail ? { isError: true, content: [{ type: 'text' as const, text: 'The capacity is paused.' }] } : { content: [{ type: 'text' as const, text: `You asked: ${question}` }, { type: 'text' as const, text: 'WT-07 stands out.' }] };
        }
      );
      const created = new StreamableHTTPServerTransport({ sessionIdGenerator: () => randomUUID(), enableJsonResponse: options.json, onsessioninitialized: (id) => { transports.set(id, created); } });
      await mcp.connect(created);
      transport = created;
    }
    if (!transport) {
      res.writeHead(400).end('no session');
      return;
    }
    await transport.handleRequest(req, res, body);
  });
  servers.push(server);
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  return { url: `http://127.0.0.1:${(server.address() as AddressInfo).port}/v1/mcp/workspaces/w/dataagents/a/agent`, sessions: () => transports.size };
}

describe('asking the data agent', () => {
  for (const json of [true, false]) {
    it(`gets the answer when the server answers ${json ? 'as JSON' : 'as an event stream'}`, async () => {
      const agent = await dataAgent({ json });
      const answer = await askDataAgent(agent.url, 'fabric-token', '  Which turbine stands out?  ', fetch);
      expect(answer.text).toBe('You asked: Which turbine stands out?\nWT-07 stands out.');
      expect(answer.seconds).toBeGreaterThanOrEqual(0);
      expect(agent.sessions()).toBe(1); // the session of initialize was used for the later requests
    });
  }

  it('finds the argument of the tool whatever it is called', async () => {
    const agent = await dataAgent({ json: true, argument: 'question' });
    expect((await askDataAgent(agent.url, 'fabric-token', 'Hello', fetch)).text).toContain('You asked: Hello');
    expect(questionArgument({ name: 't', inputSchema: { properties: { a: {}, question: {} } } })).toBe('question');
    expect(questionArgument({ name: 't', inputSchema: { properties: { b: {}, a: {} }, required: ['a'] } })).toBe('a');
    expect(() => questionArgument({ name: 't' })).toThrow(AgentError);
  });

  it('reports a refused token with the status and without the token', async () => {
    const agent = await dataAgent({ json: true });
    const failure = askDataAgent(agent.url, 'stolen-token', 'Hello', fetch);
    await expect(failure).rejects.toThrow(/answered 401 to initialize/);
    await expect(failure).rejects.not.toThrow(/stolen-token/);
  });

  it('reports an error of the agent as an error', async () => {
    const agent = await dataAgent({ json: false, fail: true });
    await expect(askDataAgent(agent.url, 'fabric-token', 'Hello', fetch)).rejects.toThrow(/reported an error: The capacity is paused/);
  });

  it('gives up after its time limit', async () => {
    const agent = await dataAgent({ json: true, delayMs: 3000 });
    await expect(askDataAgent(agent.url, 'fabric-token', 'Hello', fetch, 400)).rejects.toThrow(/did not answer within 0 seconds|did not answer within/);
  });

  it('refuses an empty and an overlong question before calling anyone', async () => {
    const never = (() => { throw new Error('must not be called'); }) as unknown as typeof fetch;
    await expect(askDataAgent('http://unused', 't', '   ', never)).rejects.toThrow(/empty/);
    await expect(askDataAgent('http://unused', 't', 'x'.repeat(1001), never)).rejects.toThrow(/longer than 1000/);
  });

  it('says when the agent cannot be reached', async () => {
    await expect(askDataAgent('http://127.0.0.1:9/agent', 'fabric-token', 'Hello', fetch)).rejects.toThrow(/could not be reached/);
  });
});

describe('reading a JSON-RPC answer', () => {
  it('takes plain JSON, the matching event of a stream, and nothing from an acknowledgement', () => {
    expect(parseJsonRpc('{"jsonrpc":"2.0","id":1,"result":{"ok":true}}', 1)?.result).toEqual({ ok: true });
    const stream = 'event: message\ndata: {"jsonrpc":"2.0","method":"notifications/progress","params":{}}\n\nevent: message\ndata: {"jsonrpc":"2.0","id":4,"result":{"n":4}}\n\n';
    expect(parseJsonRpc(stream, 4)?.result).toEqual({ n: 4 });
    expect(parseJsonRpc('', 1)).toBeNull();
    expect(parseJsonRpc('Accepted', 1)).toBeNull();
  });
});
