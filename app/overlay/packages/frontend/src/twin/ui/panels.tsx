/**
 * The panels that lie over the 3D scene: the fleet list, the panel of one turbine, the alarms with
 * the commands, and the connection check.
 */
import { useEffect, useState } from 'react';

import { PAGE_BUILD } from '../data/build';
import { type LimitView, askedBy, commandWords, groupCommands, groupTarget, limitOf, limitText, statusLevel } from '../data/commands';
import { type PartKey, componentQuestion, componentStatus, faultCount, faultsFirst, gearboxCondition } from '../data/components';
import type { Alarm, CommandEntry, DiagnosticStep, LiveState, TrendPoint, TurbineLive } from '../data/contract';
import type { TwinDataProvider } from '../data/provider';
import { ALARM_OIL_TEMP, ALARM_VIBRATION, EARLY_OIL_TEMP, EARLY_VIBRATION, SITE, WATCH_YAW_ERROR } from '../data/site';
import { STATE_COLOR } from '../scene/turbine';
import { clock, errorText, stateLabel, unitLabel } from './format';

const RATED = SITE.turbineModel.ratedPowerKw;


export function StateChip({ state }: { state: string }) {
  const color = STATE_COLOR[state as keyof typeof STATE_COLOR] ?? STATE_COLOR.UNKNOWN;
  return (
    <span className="twin-chip" style={{ color }}>
      <i style={{ background: color }} />
      {stateLabel(state)}
    </span>
  );
}

export function FleetList({ live, selected, onSelect }: { live: LiveState | null; selected: string | null; onSelect: (id: string) => void }) {
  const byId = new Map<string, TurbineLive>((live?.turbines ?? []).map((t) => [t.id, t]));
  return (
    <aside className="twin-panel twin-fleet" aria-label="Turbines">
      <h2>Turbines</h2>
      <ul>
        {SITE.turbines.map((spec) => {
          const t = byId.get(spec.id);
          const state = t?.state ?? 'UNKNOWN';
          const level = t ? gearboxCondition(t, live?.alarms ?? []) : 0;
          const alarms = faultCount((live?.alarms ?? []).filter((a) => a.turbineId === spec.id));
          return (
            <li key={spec.id}>
              <button type="button" className={spec.id === selected ? 'selected' : ''} onClick={() => onSelect(spec.id)}>
                <i className="dot" style={{ background: STATE_COLOR[state] }} title={stateLabel(state)} />
                <b>{spec.id}</b>
                <span className="bar" aria-hidden="true">
                  <span style={{ width: `${Math.min(100, ((t?.activePower ?? 0) / RATED) * 100)}%`, background: STATE_COLOR[state] }} />
                </span>
                <span className="num">{t ? (t.activePower / 1000).toFixed(1) : '–'}</span>
                {alarms > 0 ? <span className="badge alarm" title={`${alarms} active alarm${alarms > 1 ? 's' : ''}`}>{alarms}</span> : level > 0 ? <span className={`badge level${level}`} title="Gearbox above its early-warning threshold">!</span> : <span className="badge none" />}
              </button>
            </li>
          );
        })}
      </ul>
      <p className="twin-note">Power in MW of {(RATED / 1000).toFixed(1)}</p>
    </aside>
  );
}

/** A small line chart. `marks` draws dashed lines at thresholds. */
export function Sparkline({ values, marks = [], color = '#7fd4ff', unit }: { values: number[]; marks?: number[]; color?: string; unit: string }) {
  const width = 280;
  const height = 54;
  if (values.length < 2) return <div className="twin-spark empty">no trend yet</div>;
  const low = Math.min(...values, ...marks);
  const high = Math.max(...values, ...marks);
  const span = high - low || 1;
  const x = (i: number) => (i / (values.length - 1)) * width;
  const y = (v: number) => height - 4 - ((v - low) / span) * (height - 8);
  const path = values.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  return (
    <svg className="twin-spark" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label={`Trend, ${low.toFixed(1)} to ${high.toFixed(1)} ${unit}`}>
      {marks.map((m) => (
        <line key={m} x1="0" x2={width} y1={y(m)} y2={y(m)} className="mark" />
      ))}
      <path d={`${path} L${width},${height} L0,${height} Z`} fill={color} opacity="0.13" />
      <path d={path} fill="none" stroke={color} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function Tile({ label, value, unit, level = 0 }: { label: string; value: string; unit: string; level?: 0 | 1 | 2 }) {
  return (
    <div className={`twin-tile level${level}`}>
      <span>{label}</span>
      <b>
        {value}
        <small>{unit}</small>
      </b>
    </div>
  );
}

/** What holds the turbine below its rated power, and who asked for it. */
function LimitCard({ view, now, route, activePowerKw }: { view: LimitView; now: number; route: string; activePowerKw: number }) {
  const { title, lines } = limitText(view, now, clock, route, activePowerKw);
  return (
    <div className={`twin-limit ${view.kind}`} role="status">
      <svg viewBox="0 0 18 18" width="18" height="18" aria-hidden="true">
        <path d="M2 4.5h14M9 7.5v7M5.6 11.3 9 14.7l3.4-3.4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <div>
        <b>{title}</b>
        {lines.map((line) => (
          <span key={line}>{line}</span>
        ))}
      </div>
    </div>
  );
}

/** The last commands of one turbine, from the edge's command log. */
function TurbineCommands({ commands }: { commands: CommandEntry[] }) {
  if (commands.length === 0) return null;
  return (
    <>
      <h3>
        Commands, last 24 hours <small>from the command log of the edge</small>
      </h3>
      <ul className="twin-commands inline">
        {commands.slice(0, 4).map((c) => (
          <li key={`${c.requestId}-${c.at}-${c.command}`} className={`level${statusLevel(c.status)}`}>
            <b>{commandWords(c)}</b> <em>{c.status}</em>
            <small>
              {clock(c.at)} · {askedBy(c)}
              {c.error ? ` · ${c.error}` : ''}
            </small>
          </li>
        ))}
      </ul>
    </>
  );
}

interface TurbinePanelProps {
  turbine: TurbineLive | undefined;
  turbineId: string;
  alarms: Alarm[];
  /** The edge's command log, or null when this route cannot read it. */
  commands: CommandEntry[] | null;
  /** Where the live values come from, for what the panel says when the log is missing. */
  route: string;
  /** The time, for "ends in 12 min". */
  now: number;
  provider: TwinDataProvider;
  /** The turbine is shown taken apart; the panel then lists its components. */
  exploded: boolean;
  onExplode: (open: boolean) => void;
  /** The component the pointer is on, in the scene or in the list. */
  hotPart: PartKey | null;
  onHotPart: (part: PartKey | null) => void;
  onClose: () => void;
  onAsk: (question: string) => void;
}

/** The components of the opened turbine: condition, name, live values, active alarms, and a question to the data agent. */
function ComponentList({ turbine, turbineId, alarms, hotPart, onHotPart, onAsk }: { turbine: TurbineLive; turbineId: string; alarms: Alarm[]; hotPart: PartKey | null; onHotPart: (part: PartKey | null) => void; onAsk: (question: string) => void }) {
  return (
    <>
      <ul className="twin-parts">
        {componentStatus(turbine, alarms).map((c) => (
          <li key={c.key} className={`level${c.level}${hotPart === c.key ? ' hot' : ''}`} onPointerEnter={() => onHotPart(c.key)} onPointerLeave={() => onHotPart(null)}>
            <i className="dot" />
            <div>
              <b>{c.name}</b>
              <span>{c.values.length > 0 ? c.values.join(' · ') : 'no live signal'}</span>
              {c.alarms.length > 0 ? <em>{c.alarms.join(' · ')}</em> : null}
            </div>
            <button type="button" className="twin-icon" title={`Ask the data agent about the ${c.name.toLowerCase()} of ${turbineId}`} aria-label={`Ask the data agent about the ${c.name.toLowerCase()} of ${turbineId}`} onClick={() => onAsk(componentQuestion(turbineId, c))}>
              <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
                <path d="M2.5 3h11a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H8l-3.2 2.6V11H2.5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
              </svg>
            </button>
          </li>
        ))}
      </ul>
      <p className="twin-note">
        Green: no alarm. Amber: a value worth watching (the gearbox past its early warning, a yaw error over {WATCH_YAW_ERROR.toFixed(0)}°). Red: an alarm of the turbine controller, never a reading alone.
      </p>
    </>
  );
}

export function TurbinePanel({ turbine, turbineId, alarms, commands, route, now, provider, exploded, onExplode, hotPart, onHotPart, onClose, onAsk }: TurbinePanelProps) {
  const [trend, setTrend] = useState<TrendPoint[]>([]);
  const [trendError, setTrendError] = useState<string | null>(null);

  useEffect(() => {
    let stop = false;
    let timer = 0;
    const load = async () => {
      try {
        const points = await provider.getTrend(turbineId, 60);
        if (!stop) {
          setTrend(points);
          setTrendError(null);
        }
      } catch (error) {
        if (!stop) setTrendError(errorText(error));
      }
      if (!stop) timer = window.setTimeout(load, 60_000);
    };
    void load();
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [provider, turbineId]);

  const spec = SITE.turbines.find((t) => t.id === turbineId);
  const t = turbine;
  const vibrationLevel = t ? (t.gearboxVibration >= ALARM_VIBRATION ? 2 : t.gearboxVibration >= EARLY_VIBRATION ? 1 : 0) : 0;
  const oilLevel = t ? (t.gearboxOilTemp >= ALARM_OIL_TEMP ? 2 : t.gearboxOilTemp >= EARLY_OIL_TEMP ? 1 : 0) : 0;
  const limit = limitOf(t, commands, RATED, alarms);
  const mine = (commands ?? []).filter((c) => c.turbineId === turbineId);
  return (
    <aside className="twin-panel twin-turbine" aria-label={`Turbine ${turbineId}`}>
      <header>
        <div>
          <h2>{turbineId}</h2>
          <p>
            {spec?.name} · {SITE.turbineModel.model} · string {spec?.string}
          </p>
        </div>
        <StateChip state={t?.state ?? 'UNKNOWN'} />
        <button type="button" className="twin-icon" onClick={onClose} aria-label="Close the turbine panel">
          ×
        </button>
      </header>
      {t ? (
        <div className="twin-power">
          <b>{(t.activePower / 1000).toFixed(2)}</b>
          <span>MW · {Math.round((t.activePower / RATED) * 100)}% of rated</span>
        </div>
      ) : null}
      {limit && t ? <LimitCard view={limit} now={now} route={route} activePowerKw={t.activePower} /> : null}
      <button type="button" className={exploded ? 'twin-open on' : 'twin-open'} aria-pressed={exploded} onClick={() => onExplode(!exploded)}>
        <svg viewBox="0 0 22 14" width="22" height="14" aria-hidden="true">
          <path d="M1 4.5h4v5H1zM8 2.5h5.5v9H8zM16.5 4h4.5v6h-4.5z" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
        </svg>
        {exploded ? 'Put the turbine back together' : 'Exploded view: take the turbine apart'}
      </button>
      {t && exploded ? <ComponentList turbine={t} turbineId={turbineId} alarms={alarms} hotPart={hotPart} onHotPart={onHotPart} onAsk={onAsk} /> : null}
      {t && !exploded ? (
        <>
          <div className="twin-tiles">
            <Tile label="Wind" value={t.windSpeed.toFixed(1)} unit="m/s" />
            <Tile label="Rotor" value={t.rotorSpeed.toFixed(1)} unit="rpm" />
            <Tile label="Pitch" value={t.pitchAngle.toFixed(1)} unit="°" />
            <Tile label="Yaw error" value={t.yawError.toFixed(1)} unit="°" level={Math.abs(t.yawError) > WATCH_YAW_ERROR ? 1 : 0} />
            <Tile label="Gearbox vibration" value={t.gearboxVibration.toFixed(2)} unit="mm/s" level={vibrationLevel} />
            <Tile label="Gearbox oil" value={t.gearboxOilTemp.toFixed(1)} unit="°C" level={oilLevel} />
            <Tile label="Gearbox bearing" value={t.gearboxBearingTemp.toFixed(1)} unit="°C" />
            <Tile label="Generator winding" value={t.generatorWindingTemp.toFixed(1)} unit="°C" />
            <Tile label="Main bearing" value={t.mainBearingTemp.toFixed(1)} unit="°C" />
          </div>
          <h3>Power, last hour</h3>
          <Sparkline values={trend.map((p) => p.activePower / 1000)} unit="MW" color="#3ddc97" />
          <h3>
            Gearbox vibration, last hour <small>dashed: early warning {EARLY_VIBRATION.toFixed(1)}, alarm {ALARM_VIBRATION.toFixed(1)} mm/s</small>
          </h3>
          <Sparkline values={trend.map((p) => p.gearboxVibration)} marks={[EARLY_VIBRATION, ALARM_VIBRATION]} unit="mm/s" color="#ffb224" />
          {trendError ? <p className="twin-error">Trend: {trendError}</p> : null}
        </>
      ) : null}
      {t ? null : <p className="twin-empty">No telemetry from this turbine in the last 10 minutes.</p>}
      {alarms.length > 0 ? (
        <ul className="twin-alarms inline">
          {alarms.map((a) => (
            <li key={a.id} className={a.severity}>
              <b>{a.code}</b> {a.description}
              <small>
                since {clock(a.raisedAt)}
                {a.sopId ? ` · ${a.sopId}` : ''}
              </small>
            </li>
          ))}
        </ul>
      ) : null}
      {exploded ? null : <TurbineCommands commands={mine} />}
      <div className="twin-actions">
        <button type="button" onClick={() => onAsk(`Has ${turbineId} had gearbox problems before?`)}>
          Ask about its gearbox history
        </button>
        <button type="button" onClick={() => onAsk(`What was the availability of ${turbineId} over the last 90 days, and what were its longest stops?`)}>
          Ask about its availability
        </button>
        {provider.injectFault ? (
          <button type="button" className="warn" onClick={() => provider.injectFault?.(turbineId)}>
            Simulate a gearbox fault (5 minutes)
          </button>
        ) : null}
        {provider.limitTurbine ? (
          <button type="button" className="warn" onClick={() => provider.limitTurbine?.(turbineId)}>
            Simulate an approved limit to 30 % (5 minutes)
          </button>
        ) : null}
      </div>
    </aside>
  );
}

/**
 * The panel at the lower left: the active alarms and, on a second tab, the commands of the last 24 hours
 * as the edge logged them. `commands` is null when the route cannot read the command log.
 */
export function AlarmFeed({ alarms, commands, route, onSelect }: { alarms: Alarm[]; commands: CommandEntry[] | null; route: string; onSelect: (id: string) => void }) {
  const [tab, setTab] = useState<'alarms' | 'commands'>('alarms');
  const groups = groupCommands(commands ?? []);
  const inForce = groups.filter((g) => g.first.command === 'curtail' && g.level === 1).length;
  const faults = faultCount(alarms);
  return (
    <section className="twin-panel twin-alarmfeed" aria-label="Active alarms and commands">
      <div className="twin-tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === 'alarms'} className={tab === 'alarms' ? 'on' : ''} onClick={() => setTab('alarms')}>
          Active alarms <span className={faults ? 'count on' : 'count'} title="Warnings and critical alarms. Notes of the controller, such as a limit by a command, are listed and not counted.">{faults}</span>
        </button>
        <button type="button" role="tab" aria-selected={tab === 'commands'} className={tab === 'commands' ? 'on' : ''} onClick={() => setTab('commands')}>
          Commands <span className={inForce ? 'count limit' : 'count'} title={inForce ? `${inForce} limit${inForce > 1 ? 's' : ''} in force` : undefined}>{commands === null ? '–' : groups.length}</span>
        </button>
      </div>
      {tab === 'alarms' ? (
        alarms.length === 0 ? (
          <p className="twin-note">None. The turbine controllers report no alarm.</p>
        ) : (
          <ul className="twin-alarms">
            {faultsFirst(alarms).slice(0, 6).map((a) => (
              <li key={a.id} className={a.severity}>
                <button type="button" onClick={() => onSelect(a.turbineId)}>
                  <b>{a.turbineId}</b> {a.description}
                  <small>
                    {a.code} · since {clock(a.raisedAt)}
                    {a.value !== null ? ` · ${a.value.toFixed(1)} ${unitLabel(a.unit)}` : ''}
                  </small>
                </button>
              </li>
            ))}
          </ul>
        )
      ) : commands === null ? (
        <p className="twin-note">
          {route === 'lakehouse'
            ? 'The command log is read on the Eventhouse route only. On the copy in the Lakehouse the twin shows a limit without who asked for it.'
            : 'This KQL database has no command log yet. Phase 5c creates it: block 1 of fabric/kql/07-command-log.kql.'}
        </p>
      ) : groups.length === 0 ? (
        <p className="twin-note">None in the last 24 hours. A limit, a stop or a reset shows here with who asked for it, once the edge has logged it.</p>
      ) : (
        <ul className="twin-commands">
          {groups.slice(0, 6).map((g) => (
            <li key={g.key} className={`level${g.level}`}>
              <button type="button" onClick={() => (g.turbines.length === 1 && g.turbines[0].startsWith('WT-') ? onSelect(g.turbines[0]) : undefined)}>
                <b>{groupTarget(g, SITE.turbines.length)}</b> {commandWords(g.first)} <em>{g.status}</em>
                <small>
                  {clock(g.first.at)} · {askedBy(g.first)}
                  {g.first.error ? ` · ${g.first.error}` : ''}
                </small>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function Diagnostics({ provider, lastError, onClose }: { provider: TwinDataProvider; lastError: string | null; onClose: () => void }) {
  const [result, setResult] = useState<{ steps: DiagnosticStep[] | null; failure: string | null; attempt: number }>({ steps: null, failure: null, attempt: 0 });
  const [attempt, setAttempt] = useState(1);
  const running = result.attempt !== attempt;
  const { steps, failure } = result;

  // One check when the dialog opens, and one for every press of "Check again".
  useEffect(() => {
    let stop = false;
    provider.diagnostics().then(
      (found) => {
        if (!stop) setResult({ steps: found, failure: null, attempt });
      },
      (error: unknown) => {
        if (!stop) setResult({ steps: null, failure: errorText(error), attempt });
      }
    );
    return () => {
      stop = true;
    };
  }, [provider, attempt]);

  const status = provider.routeStatus?.();
  const report = [
    `Wind farm twin, connection check, ${new Date().toISOString()}`,
    `Data source: ${provider.kind}`,
    `Page: build ${PAGE_BUILD}`,
    ...(status ? [`Live values come from: ${status.route === 'eventhouse' ? 'the Eventhouse (seconds old)' : status.route === 'lakehouse' ? 'the Lakehouse copy (minutes old)' : 'nowhere yet'}`] : []),
    ...(steps ?? []).map((s) => `${s.skipped ? 'SKIP' : s.ok ? 'PASS' : 'FAIL'}  ${s.step}: ${s.detail}`),
    ...(failure ? [`FAIL  The check itself: ${failure}`] : []),
    ...(status?.route === 'lakehouse' && status.eventhouseSaid ? [`The Eventhouse route last said: ${status.eventhouseSaid}`] : []),
    ...(lastError ? [`Last error of the live values: ${lastError}`] : []),
  ].join('\n');

  return (
    <div className="twin-modal" role="dialog" aria-label="Connection check">
      <div className="twin-panel">
        <header>
          <h2>Connection check</h2>
          <button type="button" className="twin-icon" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>
        <p className="twin-note">Each line is one thing the app needs, tried now. The live values have two routes: the Eventhouse (seconds old, needs a service principal) and the copy in the Lakehouse (minutes old). One of them is enough.</p>
        <pre>{running ? 'Checking…' : report}</pre>
        <div className="twin-actions">
          <button type="button" onClick={() => setAttempt((a) => a + 1)} disabled={running}>
            Check again
          </button>
          <button type="button" onClick={() => void navigator.clipboard?.writeText(report)} disabled={running}>
            Copy the result
          </button>
        </div>
      </div>
    </div>
  );
}
