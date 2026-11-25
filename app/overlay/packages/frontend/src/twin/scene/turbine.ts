/**
 * One wind turbine of the twin, built from the dimensions of the turbine model: a tapered tower, a
 * nacelle that turns into the wind, and a rotor of three twisted blades that pitch.
 *
 * Local frame of a turbine: y up, the base at the origin. The nacelle group looks along +z, which is
 * turned towards the direction the wind comes from.
 */
import * as THREE from 'three';

import type { TurbineState } from '../data/contract';
import { SITE } from '../data/site';

const MODEL = SITE.turbineModel;
export const HUB_HEIGHT = MODEL.hubHeightM;
export const BLADE_LENGTH = MODEL.rotorDiameterM / 2 - 2;

/**
 * Turbines are drawn this many times their size. At true size a 180 m machine on a 4 km site is a
 * white hairline; drawn larger it reads from the view of the whole site. Positions are true.
 */
export const TURBINE_SCALE = 1.8;

/** The paint of tower, hub and blades. */
export const WHITE = '#eef0f1';

/** Colour of each state, used for the ring on the ground and the label. */
export const STATE_COLOR: Record<TurbineState, string> = {
  RUNNING: '#3ddc97',
  DERATED: '#ffb224',
  CURTAILED: '#5aa9ff',
  IDLE: '#9aa7b4',
  PAUSED: '#9aa7b4',
  STOPPED: '#9aa7b4',
  STOPPED_HIGH_WIND: '#c59bff',
  MAINTENANCE: '#5aa9ff',
  FAULT: '#ff4d5e',
  UNKNOWN: '#6b7682',
};

/** Colour of a gearbox condition: none (the white of the nacelle), early warning, alarm level. */
export const LEVEL_COLOR: readonly [string, string, string] = ['#e9ecee', '#ffb224', '#ff4d5e'];

/**
 * The colour of the wide halo on the ground. It carries the condition of the gearbox when there is
 * one to show, amber for the early warning and red at the alarm level, and the colour of the state
 * otherwise. The narrow ring inside it always carries the state. So a turbine that still runs with
 * its gearbox at the alarm level shows a green ring in a red halo: running, and in trouble.
 */
export function haloColor(state: TurbineState, level: number): string {
  if (level >= 2) return LEVEL_COLOR[2];
  if (level === 1) return LEVEL_COLOR[1];
  return STATE_COLOR[state];
}

/** How strongly the halo shows, between 0 and 1. A fault pulses; `pulse` runs from 0 to 1. */
export function haloOpacity(state: TurbineState, level: number, selected: boolean, hovered: boolean, pulse: number): number {
  if (state === 'FAULT') return 0.1 + 0.4 * pulse;
  if (level >= 2) return selected ? 0.5 : 0.4;
  if (level === 1) return selected ? 0.42 : 0.28;
  if (selected) return 0.38;
  if (state === 'DERATED') return 0.24;
  return hovered ? 0.18 : 0;
}

/** A blade along +y: round at the root, widest at a fifth of its length, thin and narrow at the tip. */
function bladeGeometry(): THREE.BufferGeometry {
  const stations = 18;
  const around = 14;
  const positions: number[] = [];
  const indices: number[] = [];
  for (let s = 0; s <= stations; s++) {
    const u = s / stations;
    const r = 1.6 + u * BLADE_LENGTH;
    const chord = u < 0.2 ? 2.8 + (4.6 - 2.8) * Math.sin((u / 0.2) * (Math.PI / 2)) : 4.6 - (4.6 - 0.7) * ((u - 0.2) / 0.8) ** 0.85;
    const thickness = chord * (u < 0.12 ? 1 - (u / 0.12) * 0.62 : 0.38 - 0.22 * ((u - 0.12) / 0.88));
    const twist = THREE.MathUtils.degToRad(15 * (1 - u) ** 1.6);
    for (let a = 0; a < around; a++) {
      const angle = (a / around) * Math.PI * 2;
      // An ellipse pulled forward into a rough aerofoil: the trailing edge is sharper than the nose.
      const cx = Math.cos(angle) * (chord / 2) * (Math.cos(angle) < 0 ? 1.15 : 0.85) - chord * 0.12;
      const cz = Math.sin(angle) * (thickness / 2);
      positions.push(cx * Math.cos(twist) - cz * Math.sin(twist), r, cx * Math.sin(twist) + cz * Math.cos(twist));
    }
  }
  for (let s = 0; s < stations; s++) {
    for (let a = 0; a < around; a++) {
      const p = s * around + a;
      const q = s * around + ((a + 1) % around);
      indices.push(p, p + around, q, q, p + around, q + around);
    }
  }
  const tip = positions.length / 3;
  positions.push(0, 1.6 + BLADE_LENGTH + 0.4, 0);
  for (let a = 0; a < around; a++) indices.push(stations * around + a, tip, stations * around + ((a + 1) % around));
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}

let shared: { tower: THREE.BufferGeometry; nacelle: THREE.BufferGeometry; hub: THREE.BufferGeometry; blade: THREE.BufferGeometry; proxy: THREE.BufferGeometry } | undefined;

function geometries() {
  if (!shared) {
    const tower = new THREE.CylinderGeometry(1.7, 2.9, HUB_HEIGHT - 1.5, 28, 1).translate(0, (HUB_HEIGHT - 1.5) / 2, 0);
    const nacelle = new THREE.CapsuleGeometry(2.5, 9, 8, 20).rotateX(Math.PI / 2).scale(1, 1.05, 1).translate(0, 0.4, -2.2);
    const hub = new THREE.SphereGeometry(2.3, 24, 16).scale(1, 1, 1.5);
    const proxy = new THREE.CylinderGeometry(BLADE_LENGTH * 0.75, 14, HUB_HEIGHT + BLADE_LENGTH, 10).translate(0, (HUB_HEIGHT + BLADE_LENGTH) / 2, 0);
    shared = { tower, nacelle, hub, blade: bladeGeometry(), proxy };
  }
  return shared;
}

export interface TurbineView {
  id: string;
  group: THREE.Group;
  tower: THREE.Mesh;
  /** Turns the nacelle into the wind. Its origin is on the tower axis at hub height. */
  yaw: THREE.Group;
  /** The cover of the nacelle. */
  nacelle: THREE.Mesh;
  /** Carries the rotor in front of the tower, leaning back. */
  tilt: THREE.Group;
  rotor: THREE.Group;
  hub: THREE.Mesh;
  /** One per blade, turned to its place around the hub: +y of an arm points along its blade. */
  arms: THREE.Group[];
  blades: THREE.Mesh[];
  nacelleMaterial: THREE.MeshStandardMaterial;
  /** Tower, hub and blades each have a material of their own, so that each can take a colour. */
  towerMaterial: THREE.MeshStandardMaterial;
  hubMaterial: THREE.MeshStandardMaterial;
  bladeMaterial: THREE.MeshStandardMaterial;
  ring: THREE.Mesh;
  halo: THREE.Mesh;
  ringMaterial: THREE.MeshBasicMaterial;
  haloMaterial: THREE.MeshBasicMaterial;
  proxy: THREE.Mesh;
  /** World position of the hub, for the label. */
  hubWorld: THREE.Vector3;
}

/**
 * `ring` and `halo` are the two flat shapes on the ground around the base. The ring carries the colour
 * of the state, the halo the condition of the gearbox (`haloColor`). The caller makes them to fit the
 * ground and they are not scaled with the turbine.
 */
export function buildTurbine(id: string, base: THREE.Vector3, ringGeometry: THREE.BufferGeometry, haloGeometry: THREE.BufferGeometry): TurbineView {
  const g = geometries();
  const group = new THREE.Group();
  group.position.copy(base);
  group.scale.setScalar(TURBINE_SCALE);
  group.name = id;

  const white = (): THREE.MeshStandardMaterial => new THREE.MeshStandardMaterial({ color: WHITE, roughness: 0.48, metalness: 0.05 });
  const towerMaterial = white();
  const hubMaterial = white();
  const bladeMaterial = white();
  const tower = new THREE.Mesh(g.tower, towerMaterial);
  tower.castShadow = true;
  tower.receiveShadow = true;
  group.add(tower);

  const foundation = new THREE.Mesh(new THREE.CylinderGeometry(7.5, 8.5, 1.2, 24).translate(0, 0.5, 0), new THREE.MeshStandardMaterial({ color: '#a9a69d', roughness: 0.95 }));
  foundation.receiveShadow = true;
  group.add(foundation);

  const yaw = new THREE.Group();
  yaw.position.y = HUB_HEIGHT;
  group.add(yaw);

  const nacelleMaterial = new THREE.MeshStandardMaterial({ color: '#e9ecee', roughness: 0.45, metalness: 0.08 });
  const nacelle = new THREE.Mesh(g.nacelle, nacelleMaterial);
  nacelle.castShadow = true;
  yaw.add(nacelle);

  // The rotor sits in front of the tower and leans back five degrees, as real rotors do.
  const tilt = new THREE.Group();
  tilt.position.set(0, 0.4, 6.4);
  tilt.rotation.x = THREE.MathUtils.degToRad(-5);
  yaw.add(tilt);
  const rotor = new THREE.Group();
  tilt.add(rotor);
  const hub = new THREE.Mesh(g.hub, hubMaterial);
  hub.castShadow = true;
  rotor.add(hub);
  const arms: THREE.Group[] = [];
  const blades: THREE.Mesh[] = [];
  for (let b = 0; b < 3; b++) {
    const arm = new THREE.Group();
    arm.rotation.z = (b * 2 * Math.PI) / 3;
    const blade = new THREE.Mesh(g.blade, bladeMaterial);
    blade.castShadow = true;
    arm.add(blade);
    rotor.add(arm);
    arms.push(arm);
    blades.push(blade);
  }

  const ringMaterial = new THREE.MeshBasicMaterial({ color: STATE_COLOR.UNKNOWN, transparent: true, opacity: 0.9, depthWrite: false, side: THREE.DoubleSide });
  const ring = new THREE.Mesh(ringGeometry, ringMaterial);
  ring.renderOrder = 2;
  const haloMaterial = new THREE.MeshBasicMaterial({ color: STATE_COLOR.UNKNOWN, transparent: true, opacity: 0, depthWrite: false, side: THREE.DoubleSide });
  const halo = new THREE.Mesh(haloGeometry, haloMaterial);
  halo.renderOrder = 1;

  // An unseen shape around tower and rotor that the pointer hits, so a turbine is easy to pick.
  const proxy = new THREE.Mesh(g.proxy, new THREE.MeshBasicMaterial({ visible: false }));
  proxy.userData.turbineId = id;
  group.add(proxy);

  return {
    id, group, tower, yaw, nacelle, tilt, rotor, hub, arms, blades, nacelleMaterial, towerMaterial, hubMaterial, bladeMaterial,
    ring, halo, ringMaterial, haloMaterial, proxy, hubWorld: base.clone().add(new THREE.Vector3(0, HUB_HEIGHT * TURBINE_SCALE, 0)),
  };
}

/** Turn of the nacelle group, in radians, that points it at a compass direction (degrees from north). */
export function yawFor(directionDeg: number): number {
  return Math.PI - THREE.MathUtils.degToRad(directionDeg);
}

/** Unit vector, in the world, that the wind blows along when it comes from a compass direction. */
export function downwind(directionDeg: number): THREE.Vector3 {
  const r = THREE.MathUtils.degToRad(directionDeg);
  return new THREE.Vector3(-Math.sin(r), 0, Math.cos(r));
}
