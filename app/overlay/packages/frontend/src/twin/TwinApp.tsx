/**
 * The wind farm twin: the 3D scene with its panels. It asks the provider for new values every five
 * seconds and gives them to the scene and the panels.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { TwinView } from './TwinView';
import { type PartKey, faultCount } from './data/components';
import type { LiveState } from './data/contract';
import { type Freshness, STOPPED_HINT, type TwinDataProvider, ageText, freshnessOf, pollDelay } from './data/provider';
import { SITE } from './data/site';
import type { SceneEngine } from './scene/SceneEngine';
import './twin.css';
import { ChatPanel } from './ui/ChatPanel';
import { errorText } from './ui/format';
import { AlarmFeed, Diagnostics, FleetList, TurbinePanel } from './ui/panels';

const COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
const compass = (degrees: number): string => COMPASS[Math.round((((degrees % 360) + 360) % 360) / 22.5) % 16];

function useNow(everyMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), everyMs);
    return () => window.clearInterval(timer);
  }, [everyMs]);
  return now;
}


export function TwinApp({ provider }: { provider: TwinDataProvider }) {
  const [live, setLive] = useState<LiveState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  /** The turbine that is shown taken apart. It closes when another turbine is selected. */
  const [opened, setOpened] = useState<string | null>(null);
  const [hotPart, setHotPart] = useState<PartKey | null>(null);
  const [chatOpen, setChatOpen] = useState(true);
  const [chatRequest, setChatRequest] = useState<{ key: number; question: string } | null>(null);
  const [checking, setChecking] = useState(false);
  const engine = useRef<SceneEngine | null>(null);
  const now = useNow(1000);

  useEffect(() => {
    let stop = false;
    let timer = 0;
    const poll = async () => {
      let failed = false;
      let route: 'eventhouse' | 'lakehouse' | 'sample' | undefined;
      try {
        const state = await provider.getLiveState();
        if (stop) return;
        route = state.route;
        setLive(state);
        setError(null);
      } catch (e) {
        if (stop) return;
        failed = true;
        setError(errorText(e));
      }
      timer = window.setTimeout(poll, pollDelay(route, failed));
    };
    void poll();
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [provider]);

  const kpi = useMemo(() => {
    const turbines = live?.turbines ?? [];
    const producing = turbines.filter((t) => t.activePower > 1).length;
    const powerMw = turbines.reduce((sum, t) => sum + t.activePower, 0) / 1000;
    const wind = live?.weather ?? (turbines.length ? { windSpeed: turbines.reduce((s, t) => s + t.windSpeed, 0) / turbines.length, windDirection: turbines[0].windDirection } : null);
    // Turbines a command holds below rated power: the limits the edge's log calls "in force".
    const limited = live?.commands ? new Set(live.commands.filter((c) => c.command === 'curtail' && c.status === 'in force').map((c) => c.turbineId)).size : null;
    return { producing, powerMw, wind, reporting: turbines.length, limited };
  }, [live]);

  const ageS = live?.asOf ? Math.max(0, Math.round((now - new Date(live.asOf).getTime()) / 1000)) : null;
  const freshness: Freshness = freshnessOf(live, ageS, error !== null);
  const badge: Record<Freshness, string> = {
    loading: 'Connecting…',
    live: `Live · ${ageS ?? 0} s ago`,
    delayed: `Lakehouse copy · ${ageText(ageS)} behind`,
    stale: `Stale · last value ${ageText(ageS)} ago`,
    silent: live?.route === 'lakehouse' ? 'No telemetry in the last hour' : 'No telemetry in the last 10 minutes',
    sample: 'Sample data',
    error: 'Not connected',
  };
  const badgeTitle =
    freshness === 'delayed'
      ? 'These values come from the copies of the tables in the Lakehouse, which are written every few minutes. Open the connection check to see why the Eventhouse is not used.'
      : freshness === 'stale' || freshness === 'silent'
        ? `${STOPPED_HINT} Select the badge for the connection check.`
        : 'Open the connection check';

  const select = useCallback((id: string | null) => {
    setSelected(id);
    setOpened((open) => (open === id ? open : null));
    setHotPart(null);
  }, []);
  const exploded = selected !== null && opened === selected;
  useEffect(() => {
    if (!exploded) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpened(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [exploded]);

  // The chat covers part of the scene: with it opened or closed, an opened turbine is fitted to what is left.
  useEffect(() => {
    engine.current?.reframe();
  }, [chatOpen]);

  const selectedLive = live?.turbines.find((t) => t.id === selected);
  // "Ends in 12 min" counts on the clock the times were written by. For Fabric that is the present; the
  // simulation has a clock of its own, which the preview can move ahead.
  const dataNow = live?.source === 'sample' && live.asOf ? new Date(live.asOf).getTime() : now;
  const ask = (question: string) => {
    setChatOpen(true);
    setChatRequest({ key: Date.now(), question });
  };

  return (
    <div className={selected ? (exploded ? 'twin-root has-selection is-open' : 'twin-root has-selection') : 'twin-root'}>
      <TwinView live={live} selected={selected} exploded={exploded} hotPart={hotPart} onPart={setHotPart} onSelect={select} engineRef={engine} />

      <header className="twin-panel twin-top">
        <div className="twin-title">
          <b>{SITE.site.name}</b>
          <span>
            {SITE.site.operator} · {SITE.turbines.length} × {(SITE.turbineModel.ratedPowerKw / 1000).toFixed(1)} MW
          </span>
        </div>
        <div className="twin-kpi">
          <span>Site power</span>
          <b>
            {live ? kpi.powerMw.toFixed(1) : '–'}
            <small>MW</small>
          </b>
          <i className="meter">
            <i style={{ width: `${Math.min(100, (kpi.powerMw / SITE.site.capacityMw) * 100)}%` }} />
          </i>
        </div>
        <div className="twin-kpi">
          <span>Wind at the met mast</span>
          <b>
            {kpi.wind ? kpi.wind.windSpeed.toFixed(1) : '–'}
            <small>m/s</small>
          </b>
          {kpi.wind ? (
            <em>
              <svg viewBox="-10 -10 20 20" width="14" height="14" style={{ transform: `rotate(${kpi.wind.windDirection + 180}deg)` }} aria-hidden="true">
                <path d="M0,-8 L5,6 L0,3 L-5,6 Z" fill="currentColor" />
              </svg>
              from {compass(kpi.wind.windDirection)}
            </em>
          ) : null}
        </div>
        <div className="twin-kpi">
          <span>Producing</span>
          <b>
            {live ? kpi.producing : '–'}
            <small>of {SITE.turbines.length}</small>
          </b>
        </div>
        <div className="twin-kpi">
          <span>Active alarms</span>
          <b className={live && faultCount(live.alarms) > 0 ? 'bad' : ''}>{live ? faultCount(live.alarms) : '–'}</b>
        </div>
        {kpi.limited !== null ? (
          <div className="twin-kpi" title="Turbines that a command holds below their rated power, from the command log of the edge">
            <span>Limited by command</span>
            <b className={kpi.limited > 0 ? 'limit' : ''}>
              {kpi.limited}
              <small>of {SITE.turbines.length}</small>
            </b>
          </div>
        ) : null}
        <div className="twin-spacer" />
        <button type="button" className={`twin-badge ${freshness}`} onClick={() => setChecking(true)} title={badgeTitle}>
          <i />
          {badge[freshness]}
        </button>
        <button type="button" className="twin-button" onClick={() => { select(null); engine.current?.overview(); }}>
          Whole site
        </button>
      </header>

      <FleetList live={live} selected={selected} onSelect={select} />
      <AlarmFeed alarms={live?.alarms ?? []} commands={live?.commands ?? null} route={live?.route ?? ''} onSelect={select} />
      {selected ? (
        <TurbinePanel
          key={selected}
          turbineId={selected}
          turbine={selectedLive}
          alarms={(live?.alarms ?? []).filter((a) => a.turbineId === selected)}
          commands={live?.commands ?? null}
          route={live?.route ?? ''}
          now={dataNow}
          provider={provider}
          exploded={exploded}
          onExplode={(open) => setOpened(open ? selected : null)}
          hotPart={hotPart}
          onHotPart={setHotPart}
          onClose={() => select(null)}
          onAsk={ask}
        />
      ) : null}
      <ChatPanel provider={provider} request={chatRequest} open={chatOpen} onToggle={() => setChatOpen((o) => !o)} />

      {error && freshness === 'error' ? (
        <button type="button" className="twin-toast" onClick={() => setChecking(true)}>
          The live values could not be read: {error} <u>Open the connection check</u>
        </button>
      ) : null}
      {checking ? <Diagnostics provider={provider} lastError={error} onClose={() => setChecking(false)} /> : null}
    </div>
  );
}
