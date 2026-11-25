/**
 * The React side of the 3D scene: makes one `SceneEngine` for the life of the component and passes
 * it the live values and the selection.
 */
import { type RefObject, useEffect, useRef } from 'react';

import type { PartKey } from './data/components';
import type { LiveState } from './data/contract';
import { SceneEngine } from './scene/SceneEngine';

interface TwinViewProps {
  live: LiveState | null;
  selected: string | null;
  /** The selected turbine is shown taken apart into its components. */
  exploded: boolean;
  /** The component to mark in the opened turbine, and what to call when the pointer marks one in the scene. */
  hotPart: PartKey | null;
  onPart: (part: PartKey | null) => void;
  onSelect: (turbineId: string | null) => void;
  /** Receives the engine, so that the page can ask for the overview camera. */
  engineRef: RefObject<SceneEngine | null>;
}

export function TwinView({ live, selected, exploded, hotPart, onPart, onSelect, engineRef }: TwinViewProps) {
  const host = useRef<HTMLDivElement>(null);
  // The engine lives longer than one render: it calls whatever `onSelect` and `onPart` are current.
  const select = useRef(onSelect);
  const part = useRef(onPart);
  useEffect(() => {
    select.current = onSelect;
    part.current = onPart;
  });

  useEffect(() => {
    if (!host.current) return undefined;
    const engine = new SceneEngine(host.current, { onSelect: (id) => select.current(id), onPart: (key) => part.current(key) });
    engineRef.current = engine;
    // For looking at the scene from the browser console and from the screenshot script.
    (window as unknown as { __twin?: SceneEngine }).__twin = engine;
    return () => {
      engineRef.current = null;
      engine.dispose();
    };
  }, [engineRef]);

  useEffect(() => {
    if (live) engineRef.current?.update(live);
  }, [live, engineRef]);

  useEffect(() => {
    engineRef.current?.select(selected);
  }, [selected, engineRef]);

  // After the selection, so that the engine knows which turbine the camera belongs to.
  useEffect(() => {
    engineRef.current?.setExploded(exploded ? selected : null);
  }, [exploded, selected, engineRef]);

  useEffect(() => {
    engineRef.current?.highlightPart(hotPart);
  }, [hotPart, engineRef]);

  return <div ref={host} className="twin-view" />;
}
