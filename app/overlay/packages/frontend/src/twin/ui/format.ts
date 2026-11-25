/** Small helpers the panels share for turning values into words. */

export const stateLabel = (state: string): string => state.replace(/_/g, ' ').toLowerCase();

export const clock = (iso: string): string => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};

export const errorText = (error: unknown): string => (error instanceof Error ? error.message : String(error));

/** A unit as the alarm data writes it, as it is read: `degC` is °C and `deg` is °. */
export const unitLabel = (unit: string): string => (unit === 'degC' ? '°C' : unit === 'deg' ? '°' : unit);
