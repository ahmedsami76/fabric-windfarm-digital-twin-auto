import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import { PARTS, type PartKey } from '../overlay/packages/frontend/src/twin/data/components';
import { buildExploded } from '../overlay/packages/frontend/src/twin/scene/exploded';
import { LEVEL_COLOR, STATE_COLOR, buildTurbine, haloColor, haloOpacity } from '../overlay/packages/frontend/src/twin/scene/turbine';

/** A turbine with its inside built, closed (`open` 0) or fully open (1). */
function turbine(open: 0 | 1) {
  const view = buildTurbine('WT-01', new THREE.Vector3(), new THREE.BufferGeometry(), new THREE.BufferGeometry());
  const inside = buildExploded(view);
  for (const m of inside.movers) m.object.position.copy(m.home).addScaledVector(m.travel, open);
  view.group.scale.setScalar(1); // lengths of the checks below are then metres of the turbine
  view.group.updateMatrixWorld(true);
  return { view, inside };
}

/** The box around what is drawn of a component. */
function boxOf(meshes: THREE.Object3D[]): THREE.Box3 {
  const box = new THREE.Box3();
  for (const mesh of meshes) box.expandByObject(mesh);
  return box;
}

const UNDER_THE_COVER: PartKey[] = ['MBR', 'GBX', 'GEN', 'CNV', 'TRF', 'HYD', 'YAW'];

describe('the opened turbine', () => {
  it('has something to show for every component of the data, and a place for its label', () => {
    const { view, inside } = turbine(0);
    expect([...inside.parts.keys()].sort()).toEqual(PARTS.map((p) => p.key).sort());
    for (const part of inside.parts.values()) {
      expect(part.meshes.length, part.key).toBeGreaterThan(0);
      expect(part.tint.length, part.key).toBeGreaterThan(0);
      for (const mesh of part.meshes) expect(mesh.userData.part).toBe(part.key);
      // The point a label points at belongs to the turbine, so it moves with the part.
      let top: THREE.Object3D = part.anchor;
      while (top.parent) top = top.parent;
      expect(top, part.key).toBe(view.group);
      expect(Math.abs(part.label.along) + Math.abs(part.label.up), part.key).toBeGreaterThan(1);
    }
  });

  it('keeps what it adds out of sight until the turbine is opened', () => {
    const { inside } = turbine(0);
    const drawn = inside.added.filter((o) => o.children.length > 0 || (o as THREE.Mesh).isMesh);
    expect(drawn.length).toBe(4); // what is under the cover, and three pitch bearings
    expect(drawn.every((o) => !o.visible)).toBe(true);
  });

  it('holds the machinery under the cover while the turbine is closed', () => {
    const { view, inside } = turbine(0);
    const cover = new THREE.Box3().setFromObject(view.nacelle);
    for (const key of UNDER_THE_COVER) {
      const box = boxOf(inside.parts.get(key)!.meshes);
      expect(cover.containsBox(box), `${key} ${JSON.stringify(box)} in ${JSON.stringify(cover)}`).toBe(true);
    }
  });

  it('pulls the components apart so that none touches another', () => {
    const { view, inside } = turbine(1);
    const boxes = new Map<string, THREE.Box3>(UNDER_THE_COVER.map((key) => [key, boxOf(inside.parts.get(key)!.meshes)]));
    boxes.set('ROT', boxOf([view.hub]));
    // Of the three pitch bearings, the one of the upright blade: boxes around the two that lean say little.
    inside.setUpright(0);
    boxes.set('PIT', boxOf([inside.parts.get('PIT')!.anchor]));
    expect(boxOf([view.blades[0]]).min.y).toBeGreaterThan(boxes.get('PIT')!.max.y);
    const names = [...boxes.keys()];
    for (let a = 0; a < names.length; a++) {
      for (let b = a + 1; b < names.length; b++) {
        expect(boxes.get(names[a])!.intersectsBox(boxes.get(names[b])!), `${names[a]} and ${names[b]}`).toBe(false);
      }
    }
    // All of it lies in the box the camera is placed by; the blades alone reach out of it.
    const { zMin, zMax, yMin, yMax } = inside.bounds;
    const hubHeight = view.yaw.position.y;
    for (const [name, box] of boxes) {
      expect(box.min.z, name).toBeGreaterThanOrEqual(zMin);
      expect(box.max.z, name).toBeLessThanOrEqual(zMax);
      expect(box.min.y - hubHeight, name).toBeGreaterThanOrEqual(yMin);
      expect(box.max.y - hubHeight, name).toBeLessThanOrEqual(yMax);
    }
    const cover = new THREE.Box3().setFromObject(view.nacelle);
    expect(cover.max.y - hubHeight).toBeLessThanOrEqual(yMax);
  });

  it('moves every component under the cover but the gearbox, which the others leave', () => {
    const { inside } = turbine(0);
    const still = inside.movers.filter((m) => m.travel.length() === 0).map((m) => m.object.name);
    expect(still).toEqual(['GBX']);
    for (const m of inside.movers) {
      expect(m.delay).toBeGreaterThanOrEqual(0);
      expect(m.delay).toBeLessThanOrEqual(0.35); // or the part would not have arrived when the opening ends
    }
  });

  it('points the labels of blade set and pitch system at the blade that stands upright', () => {
    const { view, inside } = turbine(1);
    for (const blade of [0, 1, 2, 4, -1]) {
      inside.setUpright(blade);
      const index = ((blade % 3) + 3) % 3;
      expect(inside.parts.get('BLD')!.anchor.parent).toBe(view.blades[index]);
      expect(inside.parts.get('PIT')!.anchor.parent).toBe(view.arms[index]);
    }
  });
});

describe('the ring and the halo on the ground', () => {
  it('gives the halo the colour of the gearbox condition, whatever the state: a running turbine at the alarm level has a red halo', () => {
    expect(haloColor('RUNNING', 1)).toBe(LEVEL_COLOR[1]);
    expect(haloColor('RUNNING', 2)).toBe(LEVEL_COLOR[2]);
    expect(haloColor('DERATED', 2)).toBe(LEVEL_COLOR[2]);
    expect(LEVEL_COLOR[1]).toBe(STATE_COLOR.DERATED); // one amber and one red in the whole picture
    expect(LEVEL_COLOR[2]).toBe(STATE_COLOR.FAULT);
  });
  it('gives the halo the colour of the state when the gearbox is in order', () => {
    expect(haloColor('RUNNING', 0)).toBe(STATE_COLOR.RUNNING);
    expect(haloColor('CURTAILED', 0)).toBe(STATE_COLOR.CURTAILED);
    expect(haloColor('FAULT', 0)).toBe(STATE_COLOR.FAULT);
  });
  it('shows the halo of a turbine in trouble without anyone selecting it, stronger at the alarm level, and hides it on a healthy one', () => {
    expect(haloOpacity('RUNNING', 0, false, false, 0)).toBe(0);
    const early = haloOpacity('RUNNING', 1, false, false, 0);
    const alarm = haloOpacity('RUNNING', 2, false, false, 0);
    expect(early).toBeGreaterThan(0.2);
    expect(alarm).toBeGreaterThan(early);
    expect(haloOpacity('RUNNING', 2, true, true, 0)).toBeGreaterThan(alarm);
    expect(haloOpacity('RUNNING', 0, true, true, 0)).toBeGreaterThan(0);
  });
  it('lets a fault pulse', () => {
    expect(haloOpacity('FAULT', 2, false, false, 1)).toBeGreaterThan(haloOpacity('FAULT', 2, false, false, 0));
  });
});
