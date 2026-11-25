/**
 * The wind farm twin as the page of the Fabric app. This file replaces the welcome screen of the
 * Universal App template; sign-in stays with the template's `AuthGate`, which wraps it.
 *
 * `?sample` in the address shows the twin on simulated values, without reading anything from Fabric.
 */
import { useMemo } from 'react';

import { TwinApp } from './twin/TwinApp';
import { createFabricProvider } from './twin/data/fabricProvider';
import { sampleRequested } from './twin/data/provider';
import { createSampleProvider } from './twin/data/sampleProvider';

function App() {
  const provider = useMemo(() => (sampleRequested() ? createSampleProvider() : createFabricProvider()), []);
  return <TwinApp provider={provider} />;
}

export default App;
