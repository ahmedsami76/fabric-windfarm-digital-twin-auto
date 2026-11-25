/**
 * Entry of the standalone preview: the twin on its built-in simulation, with nothing from Rayfin or
 * Fabric. `npm run preview` bundles it into `preview/windfarm-twin-preview.html`.
 */
import { createRoot } from 'react-dom/client';

import { TwinApp } from './overlay/packages/frontend/src/twin/TwinApp';
import { createSampleProvider, sampleWindSpeed } from './overlay/packages/frontend/src/twin/data/sampleProvider';

// The simulation runs on the clock of the browser, plus what `advance` has added: the screenshot
// script uses that to look at a fault two minutes after it started without waiting two minutes.
let ahead = 0;
const provider = createSampleProvider(() => Date.now() + ahead);
(window as unknown as { __preview?: unknown }).__preview = {
  provider,
  advance: (seconds: number) => {
    ahead += seconds * 1000;
  },
  /**
   * Seconds until the simulated wind reaches this speed and holds it for two minutes. The screenshot
   * script uses it to show a limit in a wind in which it holds the power down.
   */
  secondsToWind: (speed: number): number => {
    const at = (s: number): number => sampleWindSpeed(Date.now() + ahead + s * 1000);
    for (let s = 0; s < 4 * 3600; s += 5) {
      if (at(s) >= speed && at(s + 60) >= speed && at(s + 120) >= speed) return s;
    }
    return 0;
  },
};
createRoot(document.getElementById('root') as HTMLElement).render(<TwinApp provider={provider} />);
