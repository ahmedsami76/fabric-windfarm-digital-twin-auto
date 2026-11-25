/**
 * A turbine taken apart: what is under the cover of the nacelle, and how far each component travels
 * when the turbine is opened.
 *
 * The machinery is a drawing, not the drawing of a real machine: a drivetrain with a main bearing, a
 * three-stage gearbox and a generator in line on a bedplate, converter and transformer at the back,
 * a hydraulic unit beside the main shaft, the yaw ring on the tower. Its components are the eleven
 * of the reference data (`data/components.ts`), so each one that is drawn is one the data knows.
 *
 * Frame of the nacelle (the `yaw` group of a turbine): y up, +z towards the wind, the origin on the
 * tower axis at hub height. Lengths are in metres before the turbine is drawn larger.
 */
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

import type { PartKey } from '../data/components';
import { HUB_HEIGHT, type TurbineView } from './turbine';

/** Height of the drivetrain axis over the origin of the nacelle. */
const AXIS_Y = 0.4;

/** An object that moves when the turbine is opened: from `home` by `travel`, starting after `delay` (0 to 0.35 of the way). */
export interface Mover {
  object: THREE.Object3D;
  home: THREE.Vector3;
  travel: THREE.Vector3;
  delay: number;
}

export interface PartView {
  key: PartKey;
  /** The materials that take the colour of the condition, with the colour they have when all is well. */
  tint: { material: THREE.MeshStandardMaterial; base: THREE.Color }[];
  /** The point the label points at. */
  anchor: THREE.Object3D;
  /** Where the label sits, in metres on the page from that point: `along` is towards the rotor, `up` towards the sky. */
  label: { along: number; up: number };
  /** What the pointer can hit. */
  meshes: THREE.Mesh[];
}

export interface Exploded {
  /** Everything that was added to the turbine for this view. Hidden while the turbine is closed. */
  added: THREE.Object3D[];
  movers: Mover[];
  parts: Map<PartKey, PartView>;
  /**
   * Box, in the frame of the nacelle, that holds the opened turbine without the far ends of the blades:
   * the camera is placed to show it.
   */
  bounds: { zMin: number; zMax: number; yMin: number; yMax: number };
  /** Name the blade that stands upright: the labels of blade set and pitch system point at that one. */
  setUpright(blade: number): void;
}

// ------------------------------------------------------------------ geometry

/** A cylinder along the drivetrain (z), centred at (x, y, z). */
const cyl = (radius: number, length: number, z = 0, x = 0, y = 0, around = 32): THREE.BufferGeometry =>
  new THREE.CylinderGeometry(radius, radius, length, around).rotateX(Math.PI / 2).translate(x, y, z);
/** A cylinder that stands upright, centred at (x, y, z). */
const post = (radius: number, height: number, x: number, y: number, z: number, around = 20): THREE.BufferGeometry =>
  new THREE.CylinderGeometry(radius, radius, height, around).translate(x, y, z);
const box = (w: number, h: number, d: number, x = 0, y = 0, z = 0): THREE.BufferGeometry => new THREE.BoxGeometry(w, h, d).translate(x, y, z);
/** A flat ring around the y axis with a rectangular section. */
const ring = (inner: number, outer: number, height: number): THREE.BufferGeometry => {
  const profile = [new THREE.Vector2(inner, -height / 2), new THREE.Vector2(outer, -height / 2), new THREE.Vector2(outer, height / 2), new THREE.Vector2(inner, height / 2), new THREE.Vector2(inner, -height / 2)];
  // Normals per face keep the edges of the section sharp; a lathe would round them off.
  const geometry = new THREE.LatheGeometry(profile, 48).toNonIndexed();
  geometry.computeVertexNormals();
  return geometry;
};
/** Several shapes as one geometry, so that a component is one object to draw and to point at. */
const join = (...parts: THREE.BufferGeometry[]): THREE.BufferGeometry => {
  const merged = mergeGeometries(parts.map((p) => (p.index ? p.toNonIndexed() : p)));
  if (!merged) throw new Error('The shapes of a component could not be joined.');
  return merged;
};

interface Shapes {
  bedplate: THREE.BufferGeometry;
  mainBearing: THREE.BufferGeometry;
  mainShaft: THREE.BufferGeometry;
  gearbox: THREE.BufferGeometry;
  gearboxDetail: THREE.BufferGeometry;
  generator: THREE.BufferGeometry;
  generatorDetail: THREE.BufferGeometry;
  converter: THREE.BufferGeometry;
  converterDetail: THREE.BufferGeometry;
  transformer: THREE.BufferGeometry;
  transformerDetail: THREE.BufferGeometry;
  hydraulic: THREE.BufferGeometry;
  hydraulicDetail: THREE.BufferGeometry;
  yaw: THREE.BufferGeometry;
  yawDetail: THREE.BufferGeometry;
  pitch: THREE.BufferGeometry;
}

let shapes: Shapes | undefined;

/** The shapes are the same for every turbine and are made once. Each is drawn around the origin of its own component. */
function geometries(): Shapes {
  if (shapes) return shapes;
  const around = (count: number, radius: number, start = 0): [number, number][] =>
    Array.from({ length: count }, (_, i) => {
      const a = start + (i / count) * Math.PI * 2;
      return [Math.cos(a) * radius, Math.sin(a) * radius];
    });
  shapes = {
    // Bedplate: a plate on two girders, with a cross-member under the torque arms of the gearbox.
    bedplate: join(box(2.7, 0.3, 13.0, 0, -1.43, -2.5), box(0.35, 0.5, 13.0, -1.0, -1.83, -2.5), box(0.35, 0.5, 13.0, 1.0, -1.83, -2.5), box(4.5, 0.3, 1.0, 0, -1.43, -0.15)),

    // Main bearing: a housing on a pedestal, around the main shaft.
    mainBearing: join(cyl(1.15, 1.1), cyl(1.3, 0.12, 0.5), cyl(1.3, 0.12, -0.5), box(2.3, 1.0, 0.9, 0, -1.22, 0)),
    mainShaft: join(cyl(0.5, 4.0, -0.2), cyl(0.95, 0.22, 1.7), ...around(8, 0.74).map(([x, y]) => cyl(0.07, 0.3, 1.7, x, y, 8))),

    // Gearbox: a wide planetary stage at the front, a second one, and the high-speed stage as a block
    // with the shaft to the generator coming out of it off the axis.
    gearbox: join(
      cyl(1.5, 1.5, 0.85, 0, 0, 40),
      cyl(1.2, 1.3, -0.55, 0, 0, 40),
      cyl(1.62, 0.12, 0.12, 0, 0, 40),
      cyl(1.62, 0.12, 1.58, 0, 0, 40),
      box(2.0, 2.2, 0.9, 0.2, 0.2, -1.65),
      box(3.9, 0.5, 0.55, 0, -0.15, 0.85)
    ),
    gearboxDetail: join(
      cyl(0.36, 0.9, 0.85, -1.95, -0.15, 16),
      cyl(0.36, 0.9, 0.85, 1.95, -0.15, 16),
      box(0.5, 1.35, 0.5, -1.95, -1.025, 0.85),
      box(0.5, 1.35, 0.5, 1.95, -1.025, 0.85),
      cyl(0.26, 1.3, -0.6, 0.75, 1.45, 16), // oil filter
      cyl(0.2, 0.9, -2.5, 0.45, 0.55, 16), // shaft to the generator
      cyl(0.62, 0.07, -2.45, 0.45, 0.55, 28), // brake disc
      box(0.3, 0.45, 0.35, 0.45, 1.15, -2.45), // brake caliper
      ...around(12, 1.38, 0.2).map(([x, y]) => cyl(0.06, 0.2, 1.62, x, y, 8))
    ),

    // Generator: a ribbed barrel on feet, with a cooler on top.
    generator: join(
      cyl(1.25, 2.6, 0, 0, 0, 40),
      cyl(1.0, 0.35, 1.47),
      cyl(1.0, 0.35, -1.47),
      ...[-0.9, -0.45, 0, 0.45, 0.9].map((z) => cyl(1.31, 0.07, z, 0, 0, 40)),
      box(0.3, 1.2, 2.0, -0.8, -1.5, 0),
      box(0.3, 1.2, 2.0, 0.8, -1.5, 0),
      box(2.3, 0.18, 2.3, 0, -2.15, 0),
      box(0.8, 0.5, 0.9, -1.0, 0.95, 0.3)
    ),
    generatorDetail: join(box(1.7, 0.6, 2.0, 0, 1.6, 0), ...[-0.6, 0, 0.6].map((z) => box(1.76, 0.4, 0.08, 0, 1.6, z)), cyl(0.17, 1.0, 1.95, 0, 0, 16)),

    // Converter: a cabinet with a door seam and a vent on each side.
    converter: join(box(1.0, 2.0, 1.8)),
    converterDetail: join(
      ...[-0.51, 0.51].flatMap((x) => [box(0.03, 1.8, 0.03, x, 0, 0), box(0.03, 0.3, 1.3, x, 0.72, 0), box(0.05, 0.22, 0.05, x, 0, 0.2), box(0.05, 0.22, 0.05, x, 0, -0.2)]),
      box(0.6, 0.12, 1.3, 0, 1.06, 0)
    ),

    // Transformer: a tank with cooling fins on both sides and three bushings on top.
    transformer: join(box(0.9, 1.6, 1.8), ...[-0.72, -0.48, -0.24, 0, 0.24, 0.48, 0.72].flatMap((z) => [box(0.26, 1.3, 0.05, 0.58, 0, z), box(0.26, 1.3, 0.05, -0.58, 0, z)])),
    transformerDetail: join(...[-0.5, 0, 0.5].map((z) => post(0.1, 0.5, 0, 1.05, z, 12)), ...[-0.5, 0, 0.5].map((z) => post(0.16, 0.09, 0, 0.98, z, 12))),

    // Hydraulic unit: a tank with the pump motor lying on it and two accumulators standing on it.
    hydraulic: join(box(1.0, 0.8, 1.2)),
    hydraulicDetail: join(cyl(0.2, 0.8, 0.05, -0.2, 0.6, 16), post(0.17, 0.7, 0.27, 0.75, -0.32, 16), post(0.17, 0.7, 0.27, 0.75, 0.14, 16)),

    yaw: ring(1.8, 2.3, 0.36),
    yawDetail: join(...around(4, 2.05, Math.PI / 4).map(([x, z]) => post(0.24, 0.9, x, 0.6, z, 16))),

    // Pitch system of one blade: the bearing ring at the blade root with its drive. +y is along the blade.
    pitch: join(ring(1.22, 1.62, 0.3), box(0.36, 0.55, 0.36, 1.32, -0.4, 0)),
  };
  return shapes;
}

// ------------------------------------------------------------------ building

/** Colours of the components when all is well: cool greys and blues, so that amber and red stand for something. */
const BASE: Record<Exclude<PartKey, 'BLD' | 'ROT' | 'TWR'>, string> = {
  PIT: '#8b98a8',
  MBR: '#96a3b0',
  GBX: '#6c8bab',
  GEN: '#5c9199',
  CNV: '#aab5c0',
  TRF: '#7b8797',
  HYD: '#8795ab',
  YAW: '#74818f',
};
const STEEL = '#c4ccd3';
const DARK = '#48525d';

/**
 * Builds the inside of a turbine and says how it comes apart. Nothing moves yet, and what is added
 * stays hidden: `SceneEngine` moves the parts and shows them.
 */
export function buildExploded(view: TurbineView): Exploded {
  const g = geometries();
  const added: THREE.Object3D[] = [];
  const movers: Mover[] = [];
  const parts = new Map<PartKey, PartView>();

  const material = (color: string, metalness = 0.12): THREE.MeshStandardMaterial => new THREE.MeshStandardMaterial({ color, roughness: 0.55, metalness });
  const steel = material(STEEL, 0.2);
  const dark = material(DARK, 0.15);
  const mesh = (geometry: THREE.BufferGeometry, mat: THREE.Material): THREE.Mesh => new THREE.Mesh(geometry, mat);

  const inner = new THREE.Group();
  inner.name = 'inside';
  inner.visible = false;
  view.yaw.add(inner);
  added.push(inner);
  inner.add(mesh(g.bedplate, dark));

  const mover = (object: THREE.Object3D, travel: [number, number, number], delay: number): void => {
    movers.push({ object, home: object.position.clone(), travel: new THREE.Vector3(...travel), delay });
  };
  const part = (key: PartKey, tinted: THREE.MeshStandardMaterial[], anchor: THREE.Object3D, label: [number, number], meshes: THREE.Mesh[]): void => {
    for (const m of meshes) m.userData.part = key;
    parts.set(key, { key, tint: tinted.map((m) => ({ material: m, base: m.color.clone() })), anchor, label: { along: label[0], up: label[1] }, meshes });
  };

  /** A component under the cover: a body that takes the colour of its condition, and details that do not. */
  const component = (
    key: keyof typeof BASE,
    at: [number, number, number],
    body: THREE.BufferGeometry,
    detail: THREE.BufferGeometry | null,
    detailMaterial: THREE.Material,
    travel: [number, number, number],
    delay: number,
    label: [number, number],
    anchorAt: [number, number, number] = [0, 0, 0]
  ): THREE.Group => {
    const group = new THREE.Group();
    group.name = key;
    group.position.set(...at);
    const tinted = material(BASE[key]);
    const meshes = [mesh(body, tinted)];
    if (detail) meshes.push(mesh(detail, detailMaterial));
    group.add(...meshes);
    const anchor = new THREE.Object3D();
    anchor.position.set(...anchorAt);
    group.add(anchor);
    inner.add(group);
    mover(group, travel, delay);
    part(key, [tinted], anchor, label, meshes);
    return group;
  };

  // The drivetrain stays in line and is pulled apart along its axis; the gearbox stays where it is.
  component('MBR', [0, AXIS_Y, 2.9], g.mainBearing, g.mainShaft, steel, [0, 0, 2.8], 0.12, [0, 3.1]);
  component('GBX', [0, AXIS_Y, -1.0], g.gearbox, g.gearboxDetail, steel, [0, 0, 0], 0, [0, 3.75], [0, 0, -0.25]);
  component('GEN', [0.45, AXIS_Y + 0.55, -5.3], g.generator, g.generatorDetail, steel, [0, 0, -2.9], 0.12, [0, 3.9]);
  // What stands beside the drivetrain comes down into a row under it, on the line of the tower.
  component('CNV', [-0.78, -0.28, -7.95], g.converter, g.converterDetail, dark, [0.78, -3.22, 2.5], 0.2, [0, -3.0]);
  component('TRF', [0.8, -0.48, -7.95], g.transformer, g.transformerDetail, steel, [-0.8, -3.12, -0.95], 0.2, [-0.9, -3.0]);
  component('HYD', [-0.85, -0.88, 1.5], g.hydraulic, g.hydraulicDetail, dark, [0.85, -2.62, 1.7], 0.2, [1.2, -2.4]);
  // The yaw ring slides down the tower.
  component('YAW', [0, -1.75, 0], g.yaw, g.yawDetail, steel, [0, -2.15, 0], 0.16, [0, -2.3]);

  // The rotor leaves to the front, and each blade leaves the hub along its own axis with its pitch bearing between.
  mover(view.tilt, [0, 0, 5.8], 0.06);
  const pitchMaterial = material(BASE.PIT);
  const rings: THREE.Mesh[] = [];
  const bladeAnchors: THREE.Object3D[] = [];
  view.arms.forEach((arm, b) => {
    const pitch = mesh(g.pitch, pitchMaterial);
    pitch.position.set(0, 2.25, 0);
    pitch.visible = false;
    arm.add(pitch);
    added.push(pitch);
    rings.push(pitch);
    mover(pitch, [0, 1.6, 0], 0.26);
    mover(view.blades[b], [0, 3.2, 0], 0.26);
    const anchor = new THREE.Object3D();
    anchor.position.set(0, 3.8, 0); // on the axis of the blade, so that pitching the blade does not move it
    view.blades[b].add(anchor);
    added.push(anchor);
    bladeAnchors.push(anchor);
  });
  const hubAnchor = new THREE.Object3D();
  view.hub.add(hubAnchor);
  added.push(hubAnchor);
  part('PIT', [pitchMaterial], rings[0], [4.6, 0], rings);
  part('BLD', [view.bladeMaterial], bladeAnchors[0], [4.1, 0], view.blades);
  part('ROT', [view.hubMaterial], hubAnchor, [4.9, 0], [view.hub]);

  // The cover lifts off. It is not a component of the data and gets no label.
  mover(view.nacelle, [0, 4.6, 0], 0);

  const towerAnchor = new THREE.Object3D();
  towerAnchor.position.set(0, HUB_HEIGHT - 9.0, 0);
  view.group.add(towerAnchor);
  added.push(towerAnchor);
  part('TWR', [view.towerMaterial], towerAnchor, [-1.6, 0], [view.tower]);

  return {
    added,
    movers,
    parts,
    bounds: { zMin: -10.0, zMax: 16.0, yMin: -4.6, yMax: 7.7 },
    setUpright(blade: number): void {
      const b = ((blade % 3) + 3) % 3;
      parts.get('PIT')!.anchor = rings[b];
      parts.get('BLD')!.anchor = bladeAnchors[b];
    },
  };
}
