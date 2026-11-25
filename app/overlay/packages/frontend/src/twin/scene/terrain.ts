/**
 * The ground of the twin. Inside the 6 km square of the site it is the heightmap of the reference
 * data; outside, invented rolling country that carries the eye to the horizon. Around every turbine
 * and building the ground is levelled into a pad, as it is on a real site.
 *
 * World frame: x to the east, y up, z to the south. One unit is one metre. Heights are drawn
 * `VERTICAL_SCALE` times taller than they are, because 130 m of relief over 6 km looks flat.
 */
import * as THREE from 'three';

import { SITE, groundAt } from '../data/site';

export const VERTICAL_SCALE = 2.5;

/** Half the width of the drawn ground, in metres. The site itself reaches to 3000. */
export const WORLD_HALF = 13000;

const HALF = SITE.terrain.sizeM / 2;
const BASE = SITE.terrain.minElevationM;

const smooth = (edge0: number, edge1: number, v: number): number => {
  const t = Math.min(1, Math.max(0, (v - edge0) / (edge1 - edge0)));
  return t * t * (3 - 2 * t);
};

/** Repeatable noise between 0 and 1 on a lattice, and a smooth version of it between lattice points. */
function lattice(ix: number, iy: number): number {
  const s = Math.sin(ix * 127.1 + iy * 311.7) * 43758.5453;
  return s - Math.floor(s);
}
export function valueNoise(x: number, y: number): number {
  const ix = Math.floor(x);
  const iy = Math.floor(y);
  const fx = x - ix;
  const fy = y - iy;
  const ux = fx * fx * (3 - 2 * fx);
  const uy = fy * fy * (3 - 2 * fy);
  const a = lattice(ix, iy) * (1 - ux) + lattice(ix + 1, iy) * ux;
  const b = lattice(ix, iy + 1) * (1 - ux) + lattice(ix + 1, iy + 1) * ux;
  return a * (1 - uy) + b * uy;
}
function fbm(x: number, y: number): number {
  return 0.55 * valueNoise(x, y) + 0.3 * valueNoise(x * 2.1 + 9, y * 2.1 + 4) + 0.15 * valueNoise(x * 4.3 + 2, y * 4.3 + 7);
}

interface Pad {
  x: number;
  y: number;
  elevation: number;
  inner: number;
  outer: number;
}
const PADS: Pad[] = [
  ...SITE.turbines.map((t) => ({ x: t.x, y: t.y, elevation: groundAt(t.x, t.y), inner: 32, outer: 80 })),
  ...SITE.infrastructure.map((p) => ({ x: p.x, y: p.y, elevation: groundAt(p.x, p.y), inner: p.type === 'MetMast' ? 12 : 60, outer: p.type === 'MetMast' ? 40 : 130 })),
];

/** Elevation in metres above sea level at a site position, anywhere in the drawn world. */
export function elevationAt(x: number, y: number): number {
  const cx = Math.min(HALF, Math.max(-HALF, x));
  const cy = Math.min(HALF, Math.max(-HALF, y));
  let elevation = groundAt(cx, cy);
  const outside = Math.hypot(x - cx, y - cy);
  if (outside > 0) {
    const hills = BASE + 25 + 95 * fbm(x / 2600 + 3.1, y / 2600 + 1.7);
    elevation = elevation + (hills - elevation) * smooth(0, 3200, outside);
  } else {
    for (const pad of PADS) {
      const d = Math.hypot(x - pad.x, y - pad.y);
      if (d < pad.outer) elevation += (pad.elevation - elevation) * (1 - smooth(pad.inner, pad.outer, d));
    }
  }
  return elevation;
}

/** World height of the ground at a site position. */
export function heightAt(x: number, y: number): number {
  return (elevationAt(x, y) - BASE) * VERTICAL_SCALE;
}

/** A site position (x east, y north) as a world position on the ground, `above` metres over it. */
export function onGround(x: number, y: number, above = 0): THREE.Vector3 {
  return new THREE.Vector3(x, heightAt(x, y) + above, -y);
}

/** Grid lines: close together over the site, further apart towards the edge of the world. */
function axis(count: number): number[] {
  const values: number[] = [];
  for (let i = 0; i < count; i++) {
    const u = (i / (count - 1)) * 2 - 1;
    const a = Math.abs(u);
    const inner = 0.62;
    const distance = a <= inner ? (a / inner) * HALF : HALF + ((a - inner) / (1 - inner)) ** 1.7 * (WORLD_HALF - HALF);
    values.push(Math.sign(u) * distance);
  }
  return values;
}

const DRY_GRASS = new THREE.Color('#b09a5c');
const PALE_GRASS = new THREE.Color('#d3c189');
const SCRUB = new THREE.Color('#5f6d3c');
const SOIL = new THREE.Color('#a9683f');
const ROCK = new THREE.Color('#bfae8d');

/**
 * A tile of grain for the ground: mottled light and dark with specks of tuft and stone. It is drawn
 * here instead of loaded, so the app ships no image and needs no network.
 */
function grainTexture(): THREE.CanvasTexture {
  const size = 512;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const context = canvas.getContext('2d') as CanvasRenderingContext2D;
  const image = context.createImageData(size, size);
  const wrap = (v: number, period: number) => ((v % period) + period) % period;
  // Noise that repeats at the edge of the tile, so the tiles join without a seam.
  const tiled = (x: number, y: number, cells: number): number => {
    const fx = (x / size) * cells;
    const fy = (y / size) * cells;
    const ix = Math.floor(fx);
    const iy = Math.floor(fy);
    const ux = (fx - ix) * (fx - ix) * (3 - 2 * (fx - ix));
    const uy = (fy - iy) * (fy - iy) * (3 - 2 * (fy - iy));
    const at = (i: number, j: number) => lattice(wrap(i, cells) + cells * 7, wrap(j, cells) + cells * 13);
    return (at(ix, iy) * (1 - ux) + at(ix + 1, iy) * ux) * (1 - uy) + (at(ix, iy + 1) * (1 - ux) + at(ix + 1, iy + 1) * ux) * uy;
  };
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const mottle = 0.5 * tiled(x, y, 6) + 0.3 * tiled(x, y, 17) + 0.2 * tiled(x, y, 53);
      const speck = lattice(x * 3 + 11, y * 5 + 3);
      let v = 0.8 + 0.3 * mottle;
      if (speck > 0.985) v *= 0.68; // a tuft
      else if (speck < 0.012) v *= 1.14; // a stone
      const k = (y * size + x) * 4;
      image.data[k] = Math.min(255, v * 232);
      image.data[k + 1] = Math.min(255, v * 230);
      image.data[k + 2] = Math.min(255, v * 222);
      image.data[k + 3] = 255;
    }
  }
  context.putImageData(image, 0, 0);
  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 8;
  return texture;
}

export function buildTerrain(): THREE.Mesh {
  const lines = axis(241);
  const n = lines.length;
  const positions = new Float32Array(n * n * 3);
  const uvs = new Float32Array(n * n * 2);
  for (let j = 0; j < n; j++) {
    for (let i = 0; i < n; i++) {
      const x = lines[i];
      const y = lines[j];
      const k = (j * n + i) * 3;
      positions[k] = x;
      positions[k + 1] = heightAt(x, y);
      positions[k + 2] = -y;
      uvs[(j * n + i) * 2] = x / 190;
      uvs[(j * n + i) * 2 + 1] = y / 190;
    }
  }
  const indices: number[] = [];
  for (let j = 0; j < n - 1; j++) {
    for (let i = 0; i < n - 1; i++) {
      const a = j * n + i;
      const b = a + 1;
      const c = a + n;
      const d = c + 1;
      indices.push(a, b, d, a, d, c);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('uv', new THREE.BufferAttribute(uvs, 2));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();

  // Colour by height, slope and two scales of patchiness: scrub in the draws, pale grass on the
  // ridge, red soil and rock where the ground is steep.
  const normals = geometry.getAttribute('normal');
  const colors = new Float32Array(n * n * 3);
  const relief = (SITE.terrain.maxElevationM - BASE) * VERTICAL_SCALE;
  const color = new THREE.Color();
  for (let v = 0; v < n * n; v++) {
    const x = positions[v * 3];
    const h = positions[v * 3 + 1] / relief;
    const z = positions[v * 3 + 2];
    const slope = 1 - normals.getY(v);
    const patch = fbm(x / 420, z / 420);
    const fine = valueNoise(x / 55, z / 55);
    color.copy(SCRUB).lerp(DRY_GRASS, smooth(0.08, 0.46, h + (patch - 0.5) * 0.7));
    color.lerp(PALE_GRASS, smooth(0.5, 0.92, h + (patch - 0.5) * 0.35));
    color.lerp(SOIL, smooth(0.035, 0.11, slope) * 0.75);
    color.lerp(ROCK, smooth(0.1, 0.2, slope) * 0.6);
    color.multiplyScalar(0.84 + 0.22 * fine + 0.16 * (patch - 0.5));
    colors[v * 3] = color.r;
    colors[v * 3 + 1] = color.g;
    colors[v * 3 + 2] = color.b;
  }
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

  const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ vertexColors: true, map: grainTexture(), roughness: 1, metalness: 0 }));
  mesh.receiveShadow = true;
  mesh.name = 'terrain';
  return mesh;
}

/** A strip of the given width that follows the ground along a line of site positions. */
export function buildRibbon(points: number[][], width: number, lift: number, material: THREE.Material): THREE.Mesh {
  const path: THREE.Vector2[] = [];
  for (let s = 0; s < points.length - 1; s++) {
    const a = new THREE.Vector2(points[s][0], points[s][1]);
    const b = new THREE.Vector2(points[s + 1][0], points[s + 1][1]);
    const steps = Math.max(1, Math.ceil(a.distanceTo(b) / 18));
    for (let i = s === 0 ? 0 : 1; i <= steps; i++) path.push(a.clone().lerp(b, i / steps));
  }
  const positions: number[] = [];
  const indices: number[] = [];
  for (let i = 0; i < path.length; i++) {
    const before = path[Math.max(0, i - 1)];
    const after = path[Math.min(path.length - 1, i + 1)];
    const along = after.clone().sub(before).normalize();
    const across = new THREE.Vector2(-along.y, along.x).multiplyScalar(width / 2);
    for (const side of [1, -1]) {
      const x = path[i].x + across.x * side;
      const y = path[i].y + across.y * side;
      // The strip lies on the higher of its edge and its centre line, so it never dips into a slope.
      positions.push(x, Math.max(heightAt(x, y), heightAt(path[i].x, path[i].y)) + lift, -y);
    }
    if (i > 0) {
      const k = i * 2;
      indices.push(k - 2, k - 1, k, k - 1, k + 1, k);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  const mesh = new THREE.Mesh(geometry, material);
  mesh.receiveShadow = true;
  return mesh;
}

/** A flat ring around a site position that follows the ground, `lift` metres above it. World coordinates. */
export function buildGroundRing(x: number, y: number, inner: number, outer: number, lift: number): THREE.BufferGeometry {
  const segments = 96;
  const positions: number[] = [];
  const indices: number[] = [];
  for (let i = 0; i <= segments; i++) {
    const a = (i / segments) * Math.PI * 2;
    for (const radius of [inner, outer]) {
      const px = x + Math.cos(a) * radius;
      const py = y + Math.sin(a) * radius;
      positions.push(px, heightAt(px, py) + lift, -py);
    }
    if (i > 0) {
      const k = i * 2;
      indices.push(k - 2, k, k - 1, k - 1, k, k + 1);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setIndex(indices);
  return geometry;
}
