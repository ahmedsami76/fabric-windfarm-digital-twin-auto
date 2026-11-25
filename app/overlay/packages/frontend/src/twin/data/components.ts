/**
 * The components of a turbine as the twin shows them when the turbine is opened: which live values
 * belong to each, and what condition each is in.
 *
 * The codes and names are those of the reference data (`ref_components`), so a part named here is a
 * part the data agent and the ontology know.
 *
 * Condition has two steps, and each means one thing:
 *   2  the turbine controller has a warning or critical alarm on this component right now
 *   1  no alarm, but a value is past a level worth watching: the gearbox thresholds the operations
 *      agent uses for its early warning, and the twin's own level for the yaw error
 * A reading above the controller's limit without an alarm is step 1: the controller has not confirmed it.
 * Alarms of severity `info` (a cable untwist, a stop by the operator) colour nothing.
 */
import type { Alarm, TurbineLive } from './contract';
import { WATCH_YAW_ERROR, gearboxWatch } from './site';

export type PartKey = 'BLD' | 'PIT' | 'ROT' | 'MBR' | 'GBX' | 'GEN' | 'CNV' | 'TRF' | 'HYD' | 'YAW' | 'TWR';

export interface Part {
  key: PartKey;
  name: string;
  /** How an alarm names the component (`ref_alarm_codes.component`), in lower case, as a prefix. */
  alarmName: string;
}

/** From the rotor back along the drivetrain, then what stands beside and below it. */
export const PARTS: readonly Part[] = [
  { key: 'BLD', name: 'Blade set', alarmName: 'blade' },
  { key: 'PIT', name: 'Pitch system', alarmName: 'pitch' },
  { key: 'ROT', name: 'Rotor hub', alarmName: 'rotor' },
  { key: 'MBR', name: 'Main bearing', alarmName: 'main bearing' },
  { key: 'GBX', name: 'Gearbox', alarmName: 'gearbox' },
  { key: 'GEN', name: 'Generator', alarmName: 'generator' },
  { key: 'CNV', name: 'Converter', alarmName: 'converter' },
  { key: 'TRF', name: 'Transformer', alarmName: 'transformer' },
  { key: 'HYD', name: 'Hydraulic unit', alarmName: 'hydraulic' },
  { key: 'YAW', name: 'Yaw system', alarmName: 'yaw' },
  { key: 'TWR', name: 'Tower', alarmName: 'tower' },
];

export interface ComponentStatus {
  key: PartKey;
  name: string;
  /** The live values of the component, the most telling first. Empty when it reports none. */
  values: string[];
  level: 0 | 1 | 2;
  /** Codes of the warning and critical alarms that are active on it. */
  alarms: string[];
}

// A value that is missing shows as a dash. That happens when the page is newer than the functions it
// asks: a signal the page has learned to show is then not in the answer yet.
const shown = (v: number | undefined, digits: number): string => (typeof v === 'number' && Number.isFinite(v) ? v.toFixed(digits) : '–');
const one = (v: number | undefined): string => shown(v, 1);
const whole = (v: number | undefined): string => shown(v, 0);

function valuesOf(key: PartKey, t: TurbineLive): string[] {
  switch (key) {
    case 'BLD': return [];
    case 'PIT': return [`pitch ${one(t.pitchAngle)}°`];
    case 'ROT': return [`${one(t.rotorSpeed)} rpm`];
    case 'MBR': return [`${whole(t.mainBearingTemp)} °C`];
    case 'GBX': return [`${one(t.gearboxVibration)} mm/s`, `oil ${whole(t.gearboxOilTemp)} °C`, `bearing ${whole(t.gearboxBearingTemp)} °C`, `${one(t.gearboxOilPressure)} bar`];
    case 'GEN': return [`winding ${whole(t.generatorWindingTemp)} °C`, `bearing ${whole(t.generatorBearingTemp)} °C`];
    case 'CNV': return [`${shown(t.activePower / 1000, 2)} MW`];
    case 'TRF': return [`${whole(t.transformerTemp)} °C`];
    case 'HYD': return [`${whole(t.hydraulicPressure)} bar`];
    case 'YAW': return [`yaw error ${one(t.yawError)}°`];
    case 'TWR': return [`${one(t.towerVibration)} mm/s`];
  }
}

/** The part an alarm belongs to, from the component name it carries. Controller, grid and SCADA alarms belong to none. */
export function partOfAlarm(alarm: Pick<Alarm, 'component'>): PartKey | null {
  const name = alarm.component.trim().toLowerCase();
  if (!name) return null;
  return PARTS.find((p) => name.startsWith(p.alarmName))?.key ?? null;
}

/**
 * A warning or a critical alarm: something is wrong with the turbine. The controller also raises notes
 * of severity `info` for things somebody did or the weather does, such as a stop by an operator, a
 * limit by a command or a cable untwist. Those are listed and never counted or shown in red: a limit
 * a person asked for is not an alarm (seen on 25 November 2026, when a limit sent by hand put a red
 * "1" into the top bar).
 */
export const isFault = (alarm: Alarm): boolean => alarm.severity === 'warning' || alarm.severity === 'critical';

/** How many alarms count: the warnings and the critical ones. */
export const faultCount = (alarms: Alarm[]): number => alarms.filter(isFault).length;

/** The alarms for a list: what is wrong first, the notes after it, each in the order they came in. */
export const faultsFirst = (alarms: Alarm[]): Alarm[] => [...alarms.filter(isFault), ...alarms.filter((a) => !isFault(a))];

/** Every component of one turbine with its values and condition. `alarms` may hold other turbines' too. */
export function componentStatus(turbine: TurbineLive, alarms: Alarm[]): ComponentStatus[] {
  const mine = alarms.filter((a) => a.turbineId === turbine.id && isFault(a));
  return PARTS.map((part) => {
    const active = mine.filter((a) => partOfAlarm(a) === part.key);
    const watch =
      part.key === 'GBX' ? gearboxWatch(turbine.gearboxVibration, turbine.gearboxOilTemp) : part.key === 'YAW' && Math.abs(turbine.yawError) > WATCH_YAW_ERROR ? 1 : 0;
    return {
      key: part.key,
      name: part.name,
      values: valuesOf(part.key, turbine),
      level: active.length > 0 ? 2 : watch,
      alarms: active.map((a) => a.code),
    };
  });
}

/** What the turbine panel asks the data agent about one component. */
export function componentQuestion(turbineId: string, part: Pick<Part, 'name'>): string {
  return `What stops and work orders has the ${part.name.toLowerCase()} of ${turbineId} had?`;
}

/**
 * Condition of the gearbox of one turbine, for the halo on the ground, the nacelle and the list of
 * turbines: 2 when the controller has a warning or critical alarm on the gearbox, 1 when a reading is
 * past the early warning, 0 otherwise. `alarms` may hold other turbines' too.
 */
export function gearboxCondition(turbine: TurbineLive, alarms: Alarm[]): 0 | 1 | 2 {
  const alarmed = alarms.some(
    (a) => a.turbineId === turbine.id && isFault(a) && partOfAlarm(a) === 'GBX',
  );
  return alarmed ? 2 : gearboxWatch(turbine.gearboxVibration, turbine.gearboxOilTemp);
}
