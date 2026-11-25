/**
 * The chat with the Fabric data agent. A question goes to the function `askAgent`, which waits for
 * the whole answer: functions cannot stream. So the panel shows how long the agent has been working.
 */
import { type FormEvent, useEffect, useRef, useState } from 'react';

import type { TwinDataProvider } from '../data/provider';
import { errorText } from './format';

interface Message {
  id: number;
  from: 'user' | 'agent' | 'error';
  text: string;
  seconds?: number;
}

const SUGGESTIONS = [
  'Which turbine stands out from the fleet right now on gearbox temperature and vibration?',
  'What was the availability of each turbine over the last 90 days?',
  'Which turbine lost the most energy to component faults in the last 12 months?',
];

interface ChatPanelProps {
  provider: TwinDataProvider;
  /** A question sent from another panel. `key` changes with every request, so the same text can be asked twice. */
  request: { key: number; question: string } | null;
  open: boolean;
  onToggle: () => void;
}

export function ChatPanel({ provider, request, open, onToggle }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState('');
  const [waitingSince, setWaitingSince] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const nextId = useRef(1);
  const end = useRef<HTMLDivElement>(null);
  const busy = waitingSince !== null;

  const ask = async (question: string) => {
    const asked = question.trim();
    if (!asked || busy) return;
    setDraft('');
    setMessages((m) => [...m, { id: nextId.current++, from: 'user', text: asked }]);
    setWaitingSince(Date.now());
    try {
      const answer = await provider.ask(asked);
      setMessages((m) => [...m, { id: nextId.current++, from: 'agent', text: answer.text, seconds: answer.seconds }]);
    } catch (error) {
      setMessages((m) => [...m, { id: nextId.current++, from: 'error', text: errorText(error) }]);
    }
    setWaitingSince(null);
  };

  useEffect(() => {
    if (request) void ask(request.question);
    // Only a new request from outside starts a question.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request?.key]);

  useEffect(() => {
    if (waitingSince === null) return undefined;
    setElapsed(0);
    const timer = window.setInterval(() => setElapsed(Math.round((Date.now() - waitingSince) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [waitingSince]);

  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' });
  }, [messages, busy, open]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void ask(draft);
  };

  if (!open) {
    return (
      <button type="button" className="twin-chat-toggle" onClick={onToggle}>
        Ask the data agent
      </button>
    );
  }
  return (
    <section className="twin-panel twin-chat" aria-label="Chat with the data agent">
      <header>
        <h2>Ask the wind farm</h2>
        <span className="twin-note">{provider.kind === 'fabric' ? 'Fabric data agent' : 'sample mode'}</span>
        <button type="button" className="twin-icon" onClick={onToggle} aria-label="Hide the chat">
          –
        </button>
      </header>
      <div className="twin-messages" aria-live="polite">
        {messages.length === 0 ? (
          <div className="twin-suggestions">
            <p className="twin-note">Questions about history go to the Lakehouse, questions about right now to the live data.</p>
            {SUGGESTIONS.map((s) => (
              <button type="button" key={s} onClick={() => void ask(s)} disabled={busy}>
                {s}
              </button>
            ))}
          </div>
        ) : null}
        {messages.map((m) => (
          <div key={m.id} className={`twin-message ${m.from}`}>
            {m.text}
            {m.seconds !== undefined ? <small>answered in {m.seconds.toFixed(0)} s</small> : null}
          </div>
        ))}
        {busy ? (
          <div className="twin-message agent waiting">
            The data agent is working… {elapsed} s
            <small>It writes and runs a query. Half a minute is usual, and it can take a few minutes.</small>
          </div>
        ) : null}
        <div ref={end} />
      </div>
      <form onSubmit={submit}>
        <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Ask about production, availability, alarms, repairs…" maxLength={1000} aria-label="Your question" />
        <button type="submit" disabled={busy || draft.trim().length === 0}>
          Ask
        </button>
      </form>
    </section>
  );
}
