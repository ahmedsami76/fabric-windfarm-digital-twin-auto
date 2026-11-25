/**
 * The 3D scene of the twin. Plain Three.js, no React: `TwinView.tsx` creates one engine, hands it
 * each new set of live values, and disposes of it.
 *
 * What moves is driven by the data: a rotor turns at the reported rotor speed (in real time, so
 * 12 rpm is one turn in five seconds), a nacelle faces its reported direction, blades feather when
 * the turbine stops, the ring on the ground carries the colour of the state, and the nacelle warms
 * in colour as the gearbox goes past its thresholds.
 *
 * A selected turbine can be opened (`setExploded`): the cover lifts off, the components of
 * `exploded.ts` move apart, and each gets a label with its live values and the colour of its condition.
 */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

import { type ComponentStatus, PARTS, type PartKey, componentStatus, faultCount, gearboxCondition } from '../data/components';
import type { LiveState, TurbineLive, TurbineState } from '../data/contract';
import { SITE } from '../data/site';
import { type Exploded, buildExploded } from './exploded';
import { VERTICAL_SCALE, buildGroundRing, buildRibbon, buildTerrain, heightAt, onGround, valueNoise } from './terrain';
import { BLADE_LENGTH, HUB_HEIGHT, LEVEL_COLOR, STATE_COLOR, TURBINE_SCALE, type TurbineView, buildTurbine, downwind, haloColor, haloOpacity, yawFor } from './turbine';

export interface SceneCallbacks {
  onSelect: (turbineId: string | null) => void;
  /** The pointer came over a component of the opened turbine (in the scene or on its label), or left it. */
  onPart?: (part: PartKey | null) => void;
}

/** The turbine that is open, or on its way there or back. */
interface Opened {
  id: string;
  view: TurbineView;
  parts: Exploded;
  /** 0 closed, 1 open: where the movement is, and where it is going. */
  progress: number;
  goal: 0 | 1;
  /** Rotor angle when the opening began, and the angle it comes to rest at, with one blade upright. */
  rotorFrom: number;
  rotorRest: number;
  /** Where the camera stood before, to go back to when the turbine is closed. */
  cameFrom: { position: THREE.Vector3; target: THREE.Vector3 };
  labels: Map<PartKey, HTMLButtonElement>;
  leaders: Map<PartKey, { line: SVGLineElement; dot: SVGCircleElement }>;
  sizes: Map<PartKey, { w: number; h: number }>;
  status: Map<PartKey, ComponentStatus>;
}

interface Target {
  state: TurbineState;
  rpm: number;
  yaw: number;
  pitch: number;
  level: 0 | 1 | 2;
}

interface Flight {
  fromPosition: THREE.Vector3;
  toPosition: THREE.Vector3;
  fromTarget: THREE.Vector3;
  toTarget: THREE.Vector3;
  elapsed: number;
  duration: number;
}

const HORIZON = new THREE.Color('#cfdcea');
const ZENITH = new THREE.Color('#2a6cc0');
// Afternoon sun from the west-north-west: it lights the scene from the left of the first view and
// lays the shadows of the towers across the ridge, towards the viewer.
const SUN_DIRECTION = new THREE.Vector3(-0.78, 0.43, -0.34).normalize();
const NACELLE_TINT = LEVEL_COLOR.map((colour) => new THREE.Color(colour));
const SVG = 'http://www.w3.org/2000/svg';
const smooth = (u: number): number => u * u * (3 - 2 * u);
const clamp01 = (u: number): number => Math.min(1, Math.max(0, u));
const STREAKS = 260;
const STREAK_AREA = 2300;

function mulberry(seed: number): () => number {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const shortestTurn = (from: number, to: number): number => {
  const d = (to - from) % (Math.PI * 2);
  return d > Math.PI ? d - Math.PI * 2 : d < -Math.PI ? d + Math.PI * 2 : d;
};

export class SceneEngine {
  /** Resolves when the first frame has been drawn. */
  readonly ready: Promise<void>;

  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene = new THREE.Scene();
  private readonly camera: THREE.PerspectiveCamera;
  private readonly controls: OrbitControls;
  private readonly labels: HTMLDivElement;
  private readonly sky: THREE.Mesh;
  private readonly turbines = new Map<string, TurbineView>();
  private readonly targets = new Map<string, Target>();
  private readonly labelNodes = new Map<string, HTMLButtonElement>();
  private readonly anchors = new Map<string, THREE.Vector3>();
  private readonly labelSizes = new Map<string, { w: number; h: number }>();
  private readonly leaders: SVGSVGElement;
  private readonly insides = new Map<string, Exploded>();
  private opened: Opened | undefined;
  /** The panels that lie over the scene, in its pixels. The labels of the components keep out of them. */
  private panels: { left: number; right: number; top: number; bottom: number }[] = [];
  private hotPart: PartKey | null = null;
  private latest: LiveState | null = null;
  private readonly proxies: THREE.Object3D[] = [];
  private readonly streaks: THREE.LineSegments;
  private readonly streakSeeds: Float32Array;
  private readonly resizeObserver: ResizeObserver;
  private readonly raycaster = new THREE.Raycaster();
  private readonly clock = new THREE.Clock();

  private wind = { speed: 8, direction: SITE.site.prevailingWindDirectionDeg };
  private sun: THREE.DirectionalLight | undefined;
  private shrubs: THREE.InstancedMesh | undefined;
  /** 0 is the full picture; 1 to 3 give up sharpness, shadows and detail on a slow graphics device. */
  private quality = 0;
  /** `?fullquality` in the address keeps the full picture whatever the frame time. */
  private readonly adaptive = !new URLSearchParams(window.location.search).has('fullquality');
  private frameTimes: number[] = [];
  private lastFrameAt = 0;
  /** Pixels by which the picture is moved to the right of the middle of the page. */
  private viewShift = 0;
  private selected: string | null = null;
  private hovered: string | null = null;
  private flight: Flight | undefined;
  private frame = 0;
  private pointerDown: { x: number; y: number } | undefined;
  private disposed = false;
  private resolveReady: () => void = () => undefined;

  constructor(
    private readonly container: HTMLElement,
    private readonly callbacks: SceneCallbacks
  ) {
    this.ready = new Promise<void>((resolve) => (this.resolveReady = resolve));

    this.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.toneMapping = THREE.NeutralToneMapping;
    this.renderer.toneMappingExposure = 1.06;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.domElement.className = 'twin-canvas';
    container.appendChild(this.renderer.domElement);

    this.labels = document.createElement('div');
    this.labels.className = 'twin-labels';
    container.appendChild(this.labels);
    this.leaders = document.createElementNS(SVG, 'svg');
    this.leaders.setAttribute('class', 'twin-leaders');
    this.labels.appendChild(this.leaders);

    this.camera = new THREE.PerspectiveCamera(38, 1, 10, 90000);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.minDistance = 45;
    this.controls.maxDistance = 9500;
    this.controls.maxPolarAngle = Math.PI / 2 - 0.06;
    this.controls.zoomSpeed = 0.9;
    this.controls.addEventListener('start', () => (this.flight = undefined));

    this.scene.fog = new THREE.Fog(HORIZON, 5200, 21000);
    this.sky = this.buildSky();
    this.scene.add(this.sky);
    this.buildLights();
    this.scene.add(buildTerrain());
    this.buildRoads();
    this.buildInfrastructure();
    this.buildVegetation();
    this.buildTurbines();
    const streaks = this.buildStreaks();
    this.streaks = streaks.lines;
    this.streakSeeds = streaks.seeds;
    this.scene.add(this.streaks);

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
    this.resize();
    const overview = this.overviewPose();
    this.camera.position.copy(overview.position);
    this.controls.target.copy(overview.target);

    const canvas = this.renderer.domElement;
    canvas.addEventListener('pointerdown', this.onPointerDown);
    canvas.addEventListener('pointerup', this.onPointerUp);
    canvas.addEventListener('pointermove', this.onPointerMove);
    this.renderer.setAnimationLoop(this.tick);
  }

  /** Apply a new set of live values. Turbines that are missing from it turn grey and stand still. */
  update(state: LiveState): void {
    this.latest = state;
    const live = new Map<string, TurbineLive>(state.turbines.map((t) => [t.id, t]));
    for (const [id, view] of this.turbines) {
      const t = live.get(id);
      const producing = t !== undefined && (t.state === 'RUNNING' || t.state === 'DERATED' || t.state === 'CURTAILED');
      const target: Target = t
        ? {
            state: t.state,
            rpm: t.rotorSpeed,
            yaw: yawFor(t.nacelleDirection),
            pitch: THREE.MathUtils.degToRad(producing ? Math.min(t.pitchAngle, 30) : 86),
            level: gearboxCondition(t, state.alarms),
          }
        : { state: 'UNKNOWN', rpm: 0, yaw: view.yaw.rotation.y, pitch: THREE.MathUtils.degToRad(86), level: 0 };
      this.targets.set(id, target);
      view.ringMaterial.color.set(STATE_COLOR[target.state]);
      view.haloMaterial.color.set(haloColor(target.state, target.level));

      const node = this.labelNodes.get(id);
      if (node) {
        const alarms = faultCount(state.alarms.filter((a) => a.turbineId === id));
        node.dataset.state = target.state;
        node.classList.toggle('has-alarm', alarms > 0);
        const value = node.querySelector('span');
        if (value) value.textContent = t ? (producing ? `${(t.activePower / 1000).toFixed(1)} MW` : t.state.replace(/_/g, ' ').toLowerCase()) : 'no data';
        this.labelSizes.delete(id); // the text may have a new width
      }
    }
    if (state.weather) this.wind = { speed: state.weather.windSpeed, direction: state.weather.windDirection };
    else if (state.turbines.length > 0) {
      const n = state.turbines.length;
      this.wind = { speed: state.turbines.reduce((s, t) => s + t.windSpeed, 0) / n, direction: state.turbines[0].windDirection };
    }
    if (this.opened) this.describeParts(this.opened);
  }

  /** Mark a turbine as selected and fly the camera to it. `null` clears the selection. */
  select(turbineId: string | null, fly = true): void {
    if (this.selected === turbineId) return;
    this.selected = turbineId;
    for (const [id, node] of this.labelNodes) node.classList.toggle('selected', id === turbineId);
    const view = turbineId ? this.turbines.get(turbineId) : undefined;
    if (!view || !fly) return;
    const pose = this.selectPose(view);
    this.fly(pose.position, pose.target);
  }

  /**
   * Open a turbine into its components and fly to it, or close the one that is open (`null`). The
   * turbine is opened where it stands, with the values it has: nothing about it is stopped but its rotor.
   */
  setExploded(turbineId: string | null): void {
    const current = this.opened;
    if (turbineId === null) {
      if (!current || current.goal === 0) return;
      current.goal = 0;
      current.rotorFrom = current.rotorRest; // it starts turning again from where it rests
      this.setHot(null);
      if (this.selected === current.id) this.fly(current.cameFrom.position, current.cameFrom.target);
      return;
    }
    if (current?.id === turbineId) {
      if (current.goal === 1) return;
      current.goal = 1;
      const pose = this.openedPose(current);
      this.fly(pose.position, pose.target);
      return;
    }
    if (current) this.close(current); // one turbine at a time: the other goes back together at once
    const view = this.turbines.get(turbineId);
    if (!view) return;
    let parts = this.insides.get(turbineId);
    if (!parts) {
      parts = buildExploded(view);
      this.insides.set(turbineId, parts);
    }
    for (const object of parts.added) object.visible = true;
    // The rotor comes to rest at the next angle, the way it turns, at which a blade stands upright.
    const third = (Math.PI * 2) / 3;
    const rotorFrom = view.rotor.rotation.z;
    const rotorRest = Math.floor(rotorFrom / third) * third;
    parts.setUpright(Math.round(-rotorRest / third));
    // If the camera is still on its way to the turbine, the place to go back to is where it was going.
    const cameFrom = this.flight
      ? { position: this.flight.toPosition.clone(), target: this.flight.toTarget.clone() }
      : { position: this.camera.position.clone(), target: this.controls.target.clone() };
    const opened: Opened = { id: turbineId, view, parts, progress: 0, goal: 1, rotorFrom, rotorRest, cameFrom, labels: new Map(), leaders: new Map(), sizes: new Map(), status: new Map() };
    for (const part of PARTS) {
      const node = document.createElement('button');
      node.type = 'button';
      node.className = 'twin-part';
      node.tabIndex = -1;
      node.dataset.part = part.key;
      node.dataset.level = '0';
      node.append(document.createElement('b'), document.createElement('span'));
      node.addEventListener('pointerenter', () => this.setHot(part.key));
      node.addEventListener('pointerleave', () => this.setHot(null));
      this.labels.appendChild(node);
      opened.labels.set(part.key, node);
      const line = document.createElementNS(SVG, 'line');
      const dot = document.createElementNS(SVG, 'circle');
      dot.setAttribute('r', '3');
      this.leaders.append(line, dot);
      opened.leaders.set(part.key, { line, dot });
    }
    this.opened = opened;
    this.labels.classList.add('parts-open');
    this.describeParts(opened);
    const pose = this.openedPose(opened);
    this.fly(pose.position, pose.target, 1.9);
  }

  /** Fit the opened turbine to the page again, after a panel has been opened or closed. */
  reframe(): void {
    const opened = this.opened;
    this.readPanels();
    if (!opened || opened.goal === 0 || opened.progress < 1) return;
    const pose = this.openedPose(opened);
    this.fly(pose.position, pose.target, 1.0);
  }

  /** Mark a component of the opened turbine, as the pointer over it would. For the list in the panel. */
  highlightPart(part: PartKey | null): void {
    this.hotPart = this.opened ? part : null;
    for (const [key, node] of this.opened?.labels ?? []) node.classList.toggle('hot', key === this.hotPart);
  }

  /** The turbine that is open or opening, for the tests and the console. */
  get openedTurbine(): string | null {
    return this.opened && this.opened.goal === 1 ? this.opened.id : null;
  }

  /** Fly back to the view of the whole site. */
  overview(): void {
    const pose = this.overviewPose();
    this.fly(pose.position, pose.target);
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    if (this.opened) this.close(this.opened);
    this.renderer.setAnimationLoop(null);
    this.resizeObserver.disconnect();
    const canvas = this.renderer.domElement;
    canvas.removeEventListener('pointerdown', this.onPointerDown);
    canvas.removeEventListener('pointerup', this.onPointerUp);
    canvas.removeEventListener('pointermove', this.onPointerMove);
    this.controls.dispose();
    this.scene.traverse((object) => {
      const mesh = object as THREE.Mesh;
      mesh.geometry?.dispose?.();
      const material = mesh.material as THREE.Material | THREE.Material[] | undefined;
      if (Array.isArray(material)) material.forEach((m) => m.dispose());
      else material?.dispose?.();
    });
    this.renderer.dispose();
    canvas.remove();
    this.labels.remove();
  }

  // ---------------------------------------------------------------- building

  /** Where the camera stands to look at one turbine as a whole. */
  private selectPose(view: TurbineView): { position: THREE.Vector3; target: THREE.Vector3 } {
    const hub = view.hubWorld;
    const away = this.camera.position.clone().sub(hub).setY(0);
    if (away.lengthSq() < 1) away.set(0, 0, 1);
    away.normalize();
    const distance = 430 * TURBINE_SCALE;
    // The panels cover the right and the bottom of the page: stand a little to the right of the line to
    // the turbine and look below its hub, which puts it left of centre and clear of them.
    const aside = new THREE.Vector3(away.z, 0, -away.x).multiplyScalar(distance * 0.17);
    const position = hub.clone().add(away.multiplyScalar(distance)).add(new THREE.Vector3(0, 70, 0)).add(aside);
    return { position, target: hub.clone().add(new THREE.Vector3(0, -62 * TURBINE_SCALE, 0)).add(aside) };
  }

  /** The part of the page that no panel covers, in pixels of the scene. */
  private freeArea(): { left: number; top: number; width: number; height: number } {
    const host = this.container.getBoundingClientRect();
    const root = this.container.parentElement;
    const panel = (selector: string): DOMRect | null => {
      const rect = root?.querySelector(selector)?.getBoundingClientRect();
      return rect && rect.width > 0 && rect.height > 0 ? rect : null;
    };
    let left = 0;
    let top = 0;
    let right = host.width;
    let bottom = host.height;
    const bar = panel('.twin-top');
    if (bar) top = bar.bottom - host.top;
    const fleet = panel('.twin-fleet');
    if (fleet) left = fleet.right - host.left;
    const turbine = panel('.twin-turbine');
    if (turbine) right = turbine.left - host.left;
    for (const below of [panel('.twin-chat'), panel('.twin-alarmfeed')]) {
      if (below && below.top - host.top > top + 200) bottom = Math.min(bottom, below.top - host.top);
    }
    // On a small window the panels leave nothing: then the scene takes the page and lies under them.
    if (right - left < 420) [left, right] = [0, host.width];
    if (bottom - top < 300) bottom = host.height;
    return { left: left + 10, top: top + 8, width: right - left - 20, height: bottom - top - 16 };
  }

  /**
   * Where the camera stands to look at the opened turbine: beside the nacelle, on the side it is on
   * already, a little to the back and a little above, at the distance at which the parts and their
   * labels fill the part of the page the panels leave free. From behind, the drivetrain is the near
   * thing and the rotor with its long blades the far one.
   */
  private openedPose(opened: Opened): { position: THREE.Vector3; target: THREE.Vector3 } {
    const yaw = opened.view.yaw.rotation.y;
    const origin = opened.view.hubWorld;
    const beside = new THREE.Vector3(Math.cos(yaw), 0, -Math.sin(yaw));
    const front = new THREE.Vector3(Math.sin(yaw), 0, Math.cos(yaw));
    const side = this.camera.position.clone().sub(origin).dot(beside) < 0 ? -1 : 1;
    const azimuth = THREE.MathUtils.degToRad(-16);
    const elevation = THREE.MathUtils.degToRad(13);
    const back = beside.clone().multiplyScalar(side * Math.cos(elevation) * Math.cos(azimuth)).addScaledVector(front, Math.cos(elevation) * Math.sin(azimuth));
    back.y = Math.sin(elevation);
    back.normalize();
    const right = new THREE.Vector3(0, 1, 0).cross(back).normalize();
    const up = back.clone().cross(right);

    const box = opened.parts.bounds;
    const free = this.freeArea();
    const wide = (box.zMax - box.zMin) * Math.abs(right.dot(front)) + 4 * Math.abs(right.dot(beside));
    const high = (box.yMax - box.yMin) * up.y + 4 * Math.abs(up.dot(beside));
    // Labels stand beyond the parts: about 95 pixels on the side of the rotor, 65 at the back, 80 below.
    const perMetre = THREE.MathUtils.clamp(Math.min((free.width - 184) / wide, (free.height - 114) / high), 9, 46);
    const perWorldMetre = perMetre / TURBINE_SCALE;
    const distance = this.container.clientHeight / (2 * Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2)) * perWorldMetre);
    const centre = origin
      .clone()
      .addScaledVector(front, ((box.zMin + box.zMax) / 2) * TURBINE_SCALE)
      .add(new THREE.Vector3(0, ((box.yMin + box.yMax) / 2) * TURBINE_SCALE, 0));
    // Where the middle of the parts is to appear, and where the axis of the camera meets the page.
    const wantX = free.left + free.width / 2 + (right.dot(front) > 0 ? -15 : 15);
    const wantY = free.top + free.height / 2 - 33;
    const axisX = this.container.clientWidth / 2 + this.viewShift;
    const axisY = this.container.clientHeight / 2;
    const target = centre.addScaledVector(right, (axisX - wantX) / perWorldMetre).addScaledVector(up, (wantY - axisY) / perWorldMetre);
    return { position: target.clone().addScaledVector(back, distance), target };
  }

  private overviewPose(): { position: THREE.Vector3; target: THREE.Vector3 } {
    // From the south-west, along the ridge: the rotors face this way when the wind is the prevailing one.
    const target = new THREE.Vector3(-600, 290, 340);
    const position = new THREE.Vector3(-3050, 960, 3500);
    const aspect = this.camera.aspect || 1.6;
    if (aspect < 1.5) position.sub(target).multiplyScalar(1.5 / aspect).add(target); // step back on a narrow window
    return { position, target };
  }

  private buildSky(): THREE.Mesh {
    const material = new THREE.ShaderMaterial({
      side: THREE.BackSide,
      depthWrite: false,
      fog: false,
      uniforms: {
        zenith: { value: ZENITH },
        horizon: { value: HORIZON },
        sunDirection: { value: SUN_DIRECTION },
        sunColor: { value: new THREE.Color('#fff1d6') },
        time: { value: 0 },
      },
      vertexShader: /* glsl */ `
        varying vec3 vDirection;
        void main() {
          vDirection = normalize(position);
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }`,
      fragmentShader: /* glsl */ `
        uniform vec3 zenith;
        uniform vec3 horizon;
        uniform vec3 sunDirection;
        uniform vec3 sunColor;
        uniform float time;
        varying vec3 vDirection;
        float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
        float noise(vec2 p) {
          vec2 i = floor(p);
          vec2 f = fract(p);
          f = f * f * (3.0 - 2.0 * f);
          return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x), f.y);
        }
        float fbm(vec2 p) {
          float v = 0.0;
          float a = 0.5;
          for (int i = 0; i < 5; i++) { v += a * noise(p); p = p * 2.03 + 7.1; a *= 0.5; }
          return v;
        }
        void main() {
          vec3 d = normalize(vDirection);
          vec3 color = mix(horizon, zenith, pow(clamp(d.y, 0.0, 1.0), 0.4));
          float s = max(dot(d, sunDirection), 0.0);
          color += sunColor * (pow(s, 1200.0) * 5.0 + pow(s, 28.0) * 0.2 + pow(s, 5.0) * 0.07);
          // Fair-weather clouds: noise on a flat layer overhead, thinning out towards the horizon.
          if (d.y > 0.01) {
            vec2 uv = d.xz / (d.y + 0.22) * 1.6 + vec2(time * 0.0035, time * 0.0012);
            float cover = smoothstep(0.5, 0.72, fbm(uv)) * smoothstep(0.0, 0.06, d.y);
            float shade = 0.82 + 0.18 * fbm(uv * 2.7 + 3.0);
            color = mix(color, vec3(shade) * (0.9 + 0.25 * pow(s, 3.0)), cover * 0.9);
          }
          gl_FragColor = vec4(color, 1.0);
          #include <tonemapping_fragment>
          #include <colorspace_fragment>
        }`,
    });
    const sky = new THREE.Mesh(new THREE.SphereGeometry(60000, 32, 16), material);
    sky.frustumCulled = false;
    sky.renderOrder = -1;
    return sky;
  }

  private buildLights(): void {
    const sun = new THREE.DirectionalLight('#fff2dc', 3.1);
    sun.position.copy(SUN_DIRECTION).multiplyScalar(7000);
    sun.target.position.set(0, 0, 0);
    sun.castShadow = true;
    sun.shadow.mapSize.set(4096, 4096);
    const s = sun.shadow.camera;
    s.left = -3300;
    s.right = 3300;
    s.top = 3300;
    s.bottom = -3300;
    s.near = 500;
    s.far = 14000;
    sun.shadow.bias = -0.0004;
    sun.shadow.normalBias = 2.5;
    this.sun = sun;
    this.scene.add(sun, sun.target);
    this.scene.add(new THREE.HemisphereLight('#c4dbf7', '#8f7c58', 1.3));
  }

  private buildRoads(): void {
    const gravel = new THREE.MeshStandardMaterial({ color: '#d9cba6', roughness: 1, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -4, polygonOffsetUnits: -4 });
    for (const road of SITE.roads) this.scene.add(buildRibbon(road.points, road.type === 'entrance' ? 14 : 11, 0.5, gravel));
    const pad = new THREE.CircleGeometry(30, 40).rotateX(-Math.PI / 2);
    for (const t of SITE.turbines) {
      const mesh = new THREE.Mesh(pad, gravel);
      mesh.position.copy(onGround(t.x, t.y, 0.45));
      mesh.receiveShadow = true;
      this.scene.add(mesh);
    }
  }

  private buildInfrastructure(): void {
    const box = (w: number, h: number, d: number, color: string, x: number, y: number, z: number, parent: THREE.Object3D, shadow = true): THREE.Mesh => {
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), new THREE.MeshStandardMaterial({ color, roughness: 0.85, metalness: 0.05 }));
      mesh.position.set(x, y + h / 2, z);
      mesh.castShadow = shadow;
      mesh.receiveShadow = true;
      parent.add(mesh);
      return mesh;
    };
    for (const place of SITE.infrastructure) {
      const group = new THREE.Group();
      group.position.copy(onGround(place.x, place.y));
      this.scene.add(group);
      if (place.type === 'Substation') {
        box(120, 0.8, 84, '#bdb7a8', 0, 0, 0, group, false);
        for (const dx of [-24, 24]) {
          box(11, 8, 7, '#566068', dx, 0.8, -8, group);
          box(13, 5.5, 1.2, '#7b858d', dx, 1.4, -13, group);
          box(2.2, 3.5, 2.2, '#c9c2b2', dx - 3, 8.8, -8, group);
          box(2.2, 3.5, 2.2, '#c9c2b2', dx + 3, 8.8, -8, group);
        }
        for (const dx of [-42, -14, 14, 42]) {
          box(0.9, 16, 0.9, '#8d979e', dx, 0.8, 18, group);
          box(0.9, 16, 0.9, '#8d979e', dx, 0.8, 30, group);
          box(0.9, 0.9, 13, '#8d979e', dx, 16.4, 24, group);
        }
        box(86, 0.5, 0.5, '#6f7980', 0, 15.4, 24, group, false);
        box(18, 5.5, 10, '#dcd7cb', 40, 0.8, -26, group);
      } else if (place.type === 'Building') {
        box(60, 0.6, 46, '#bdb7a8', 0, 0, 0, group, false);
        box(36, 8, 18, '#cfd3d6', -6, 0.6, -4, group);
        box(37, 1.1, 19, '#5f6a73', -6, 8.6, -4, group);
        box(10, 4.5, 8, '#dcd7cb', 20, 0.6, 10, group);
      } else {
        const height = 102;
        box(0.9, height, 0.9, '#d4d8db', 0, 0, 0, group);
        for (const y of [60, 98]) box(7, 0.3, 0.3, '#d4d8db', 2.5, y, 0, group, false);
        const wire = new THREE.LineBasicMaterial({ color: '#aeb6bb', transparent: true, opacity: 0.4 });
        for (let g = 0; g < 3; g++) {
          const a = (g / 3) * Math.PI * 2 + 0.5;
          const foot = new THREE.Vector3(Math.cos(a) * 62, 0, Math.sin(a) * 62);
          foot.y = heightAt(place.x + foot.x, place.y - foot.z) - group.position.y;
          for (const top of [58, 96]) {
            group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, top, 0), foot]), wire));
          }
        }
      }
      this.addLabel(place.id, place.name, onGround(place.x, place.y, place.type === 'MetMast' ? 116 : 30), false);
    }
  }

  private buildVegetation(): void {
    const random = mulberry(SITE.terrain.grid * 7919);
    const segments = SITE.roads.flatMap((r) => r.points.slice(1).map((p, i) => [r.points[i], p]));
    const nearRoad = (x: number, y: number): boolean =>
      segments.some(([a, b]) => {
        const dx = b[0] - a[0];
        const dy = b[1] - a[1];
        const t = Math.min(1, Math.max(0, ((x - a[0]) * dx + (y - a[1]) * dy) / (dx * dx + dy * dy || 1)));
        return Math.hypot(x - (a[0] + t * dx), y - (a[1] + t * dy)) < 16;
      });
    const relief = SITE.terrain.maxElevationM - SITE.terrain.minElevationM;
    const matrices: THREE.Matrix4[] = [];
    const colors: THREE.Color[] = [];
    const palette = ['#4f5c2b', '#5f6c33', '#737540', '#43542a', '#6a6a3a'];
    const smoothClump = (v: number): number => Math.min(1, Math.max(0, (v - 0.34) / 0.3));
    for (let tries = 0; tries < 90000 && matrices.length < 15000; tries++) {
      const x = (random() * 2 - 1) * 4600;
      const y = (random() * 2 - 1) * 4600;
      const low = 1 - heightAt(x, y) / (relief * VERTICAL_SCALE);
      // Mesquite and juniper stand in clumps and fill the draws; the ridge is nearly bare.
      const clump = valueNoise(x / 260 + 5, y / 260 + 9) * 0.6 + valueNoise(x / 70, y / 70) * 0.4;
      if (random() > (0.08 + 0.92 * low * low) * smoothClump(clump)) continue;
      if (SITE.turbines.some((t) => Math.hypot(t.x - x, t.y - y) < 75)) continue;
      if (SITE.infrastructure.some((p) => Math.hypot(p.x - x, p.y - y) < 120)) continue;
      if (nearRoad(x, y)) continue;
      const size = 2.2 + random() * random() * 6;
      const height = size * (0.6 + random() * 0.5);
      matrices.push(new THREE.Matrix4().compose(onGround(x, y, height * 0.35), new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), random() * 6.28), new THREE.Vector3(size, height, size)));
      colors.push(new THREE.Color(palette[Math.floor(random() * palette.length)]).multiplyScalar(0.8 + random() * 0.4));
    }
    // 20 triangles a shrub, and no shadow of their own: fifteen thousand of them must stay cheap.
    const shrubs = new THREE.InstancedMesh(new THREE.IcosahedronGeometry(1, 0), new THREE.MeshStandardMaterial({ roughness: 1, flatShading: true }), matrices.length);
    matrices.forEach((m, i) => {
      shrubs.setMatrixAt(i, m);
      shrubs.setColorAt(i, colors[i]);
    });
    shrubs.receiveShadow = true;
    this.shrubs = shrubs;
    this.scene.add(shrubs);
  }

  private buildTurbines(): void {
    for (const spec of SITE.turbines) {
      const view = buildTurbine(spec.id, onGround(spec.x, spec.y), buildGroundRing(spec.x, spec.y, 46, 60, 1.6), buildGroundRing(spec.x, spec.y, 60, 104, 1.4));
      this.scene.add(view.ring, view.halo);
      view.yaw.rotation.y = yawFor(SITE.site.prevailingWindDirectionDeg);
      view.rotor.rotation.z = (spec.x * 0.013 + spec.y * 0.007) % (Math.PI * 2);
      this.turbines.set(spec.id, view);
      this.proxies.push(view.proxy);
      this.scene.add(view.group);
      this.addLabel(spec.id, spec.id, view.hubWorld.clone().add(new THREE.Vector3(0, BLADE_LENGTH * 0.62 * TURBINE_SCALE, 0)), true);
    }
  }

  private addLabel(id: string, title: string, anchor: THREE.Vector3, turbine: boolean): void {
    const node = document.createElement('button');
    node.type = 'button';
    node.className = turbine ? 'twin-label' : 'twin-label place';
    node.dataset.state = 'UNKNOWN';
    const name = document.createElement('b');
    name.textContent = title;
    node.appendChild(name);
    if (turbine) {
      node.appendChild(document.createElement('span'));
      node.addEventListener('click', () => this.callbacks.onSelect(id));
    } else {
      node.tabIndex = -1;
    }
    this.anchors.set(id, anchor);
    this.labels.appendChild(node);
    this.labelNodes.set(id, node);
  }

  private buildStreaks(): { lines: THREE.LineSegments; seeds: Float32Array } {
    const random = mulberry(20211);
    const seeds = new Float32Array(STREAKS * 4);
    for (let i = 0; i < STREAKS; i++) {
      seeds[i * 4] = (random() * 2 - 1) * STREAK_AREA;
      seeds[i * 4 + 1] = (random() * 2 - 1) * STREAK_AREA;
      seeds[i * 4 + 2] = 70 + random() * 260;
      seeds[i * 4 + 3] = 0.6 + random() * 0.8;
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(STREAKS * 6), 3));
    // Head opaque, tail clear: each streak reads as a short stroke in the direction of the wind.
    const colors = new Float32Array(STREAKS * 8);
    for (let i = 0; i < STREAKS; i++) colors.set([1, 1, 1, 1, 1, 1, 1, 0], i * 8);
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 4));
    const lines = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.3, depthWrite: false }));
    lines.frustumCulled = false;
    return { lines, seeds };
  }

  // ---------------------------------------------------------------- running

  private fly(position: THREE.Vector3, target: THREE.Vector3, duration = 1.5): void {
    this.flight = { fromPosition: this.camera.position.clone(), toPosition: position, fromTarget: this.controls.target.clone(), toTarget: target, elapsed: 0, duration };
  }

  private resize(): void {
    const width = Math.max(1, this.container.clientWidth);
    const height = Math.max(1, this.container.clientHeight);
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    // The fleet list covers the left edge: move the picture a little to the right of centre.
    if (this.opened) this.readPanels();
    this.viewShift = width > 900 ? Math.min(110, width * 0.07) : 0;
    if (this.viewShift > 0) this.camera.setViewOffset(width, height, -this.viewShift, 0, width, height);
    else this.camera.clearViewOffset();
    this.camera.updateProjectionMatrix();
  }

  private readonly tick = (): void => {
    const dt = Math.min(this.clock.getDelta(), 0.1);
    const time = this.clock.elapsedTime;

    if (this.flight) {
      const f = this.flight;
      f.elapsed += dt;
      const u = Math.min(1, f.elapsed / f.duration);
      const e = u * u * (3 - 2 * u);
      this.camera.position.lerpVectors(f.fromPosition, f.toPosition, e);
      this.controls.target.lerpVectors(f.fromTarget, f.toTarget, e);
      if (u >= 1) this.flight = undefined;
    }
    this.controls.update();
    // Keep the camera above the ground it is over.
    const floor = heightAt(this.camera.position.x, -this.camera.position.z) + 12;
    if (this.camera.position.y < floor) this.camera.position.y = floor;
    this.sky.position.copy(this.camera.position);
    (this.sky.material as THREE.ShaderMaterial).uniforms.time.value = time;

    for (const [id, view] of this.turbines) {
      const target = this.targets.get(id);
      if (!target) continue;
      const data = view.rotor.userData as { rpm?: number };
      if (this.opened?.id === id) {
        data.rpm = 0; // the rotor of an opened turbine is held; closed again, it runs up from standstill
      } else {
        data.rpm = (data.rpm ?? 0) + (target.rpm - (data.rpm ?? 0)) * (1 - Math.exp(-dt * 0.9));
        view.rotor.rotation.z -= ((data.rpm * Math.PI * 2) / 60) * dt;
      }
      view.yaw.rotation.y += shortestTurn(view.yaw.rotation.y, target.yaw) * (1 - Math.exp(-dt * 0.7));
      for (const blade of view.blades) blade.rotation.y += (target.pitch - blade.rotation.y) * (1 - Math.exp(-dt * 1.2));
      // The cover of an opened turbine is glass, and the gearbox under it carries the colour itself.
      view.nacelleMaterial.color.lerp(NACELLE_TINT[this.opened?.id === id && this.opened.goal === 1 ? 0 : target.level], 1 - Math.exp(-dt * 2));

      const isSelected = id === this.selected;
      const emphasis = isSelected || id === this.hovered;
      const pulse = 0.5 + 0.5 * Math.sin(time * 7.5);
      const fault = target.state === 'FAULT';
      view.ringMaterial.opacity = fault ? 0.55 + 0.45 * pulse : emphasis ? 1 : 0.82;
      view.haloMaterial.opacity = haloOpacity(target.state, target.level, isSelected, emphasis, pulse);
    }

    if (this.opened) this.moveParts(this.opened, dt, time);
    this.moveStreaks(dt);
    this.renderer.render(this.scene, this.camera);
    if (!this.opened || this.opened.progress < 0.6) this.placeLabels();
    if (this.opened) this.placeParts(this.opened);
    if (this.frame++ === 1) this.resolveReady();
    this.watchFrameTime();
  };

  // ---------------------------------------------------------------- the opened turbine

  /** Where the panels are now. Read when the values or the page change, which is when a panel can change, not with every frame. */
  private readPanels(): void {
    const host = this.container.getBoundingClientRect();
    const nodes = this.container.parentElement?.querySelectorAll('.twin-panel, .twin-chat-toggle') ?? [];
    this.panels = [...nodes]
      .map((node) => node.getBoundingClientRect())
      .filter((r) => r.width > 0 && r.height > 0)
      .map((r) => ({ left: r.left - host.left - 5, right: r.right - host.left + 5, top: r.top - host.top - 5, bottom: r.bottom - host.top + 5 }));
  }

  /** Write the live values of each component on its label and note its condition. */
  private describeParts(opened: Opened): void {
    this.readPanels();
    const turbine = this.latest?.turbines.find((t) => t.id === opened.id);
    const status = turbine ? componentStatus(turbine, this.latest?.alarms ?? []) : [];
    opened.status = new Map(status.map((s) => [s.key, s]));
    for (const part of PARTS) {
      const node = opened.labels.get(part.key);
      if (!node) continue;
      const now = opened.status.get(part.key);
      const text = now ? now.values.slice(0, 2).join(' · ') : 'no data';
      const [name, values] = [node.children[0] as HTMLElement, node.children[1] as HTMLElement];
      if (name.textContent !== part.name || values.textContent !== text) {
        name.textContent = part.name;
        values.textContent = text;
        values.style.display = text ? '' : 'none';
        opened.sizes.delete(part.key); // the text may have a new width
      }
      node.dataset.level = String(now?.level ?? 0);
      const leader = opened.leaders.get(part.key);
      leader?.line.setAttribute('data-level', node.dataset.level);
      leader?.dot.setAttribute('data-level', node.dataset.level);
    }
  }

  /** One step of the opening or closing: positions, the cover, the rotor and the colours of the conditions. */
  private moveParts(opened: Opened, dt: number, time: number): void {
    opened.progress = clamp01(opened.progress + (opened.goal === 1 ? dt / 1.8 : -dt / 1.1));
    const { view, parts, progress } = opened;
    for (const m of parts.movers) m.object.position.copy(m.home).addScaledVector(m.travel, smooth(clamp01(progress * 1.35 - m.delay)));

    // The cover turns to glass as it lifts.
    const glass = smooth(clamp01(progress * 1.7));
    this.seeThrough(view.nacelleMaterial, progress > 0);
    view.nacelleMaterial.opacity = 1 - 0.74 * glass;
    view.nacelleMaterial.depthWrite = glass < 0.5;
    view.rotor.rotation.z = THREE.MathUtils.lerp(opened.rotorFrom, opened.rotorRest, smooth(clamp01(progress * 1.5)));

    const pulse = 0.5 + 0.5 * Math.sin(time * 7.5);
    const ease = 1 - Math.exp(-dt * 6);
    for (const [key, part] of parts.parts) {
      const level = opened.goal === 1 ? (opened.status.get(key)?.level ?? 0) : 0;
      const hot = key === this.hotPart;
      for (const { material, base } of part.tint) {
        const color = level === 0 ? base : NACELLE_TINT[level];
        material.color.lerp(color, ease);
        // A little light of their own keeps the parts readable on the side away from the sun.
        const glow = (level === 2 ? 0.3 + 0.25 * pulse : level === 1 ? 0.24 : 0.07) + (hot ? 0.2 : 0);
        material.emissive.copy(material.color).multiplyScalar(glow * smooth(progress));
      }
    }
    this.labels.classList.toggle('parts-shown', opened.goal === 1 && progress > 0.8);
    if (progress === 0 && opened.goal === 0) this.close(opened);
  }

  /** Put the turbine back together at once and take its labels away. */
  private close(opened: Opened): void {
    const { view, parts } = opened;
    for (const m of parts.movers) m.object.position.copy(m.home);
    for (const object of parts.added) object.visible = false;
    this.seeThrough(view.nacelleMaterial, false);
    view.nacelleMaterial.opacity = 1;
    view.nacelleMaterial.depthWrite = true;
    for (const part of parts.parts.values()) {
      for (const { material, base } of part.tint) {
        material.color.copy(base);
        material.emissive.setScalar(0);
      }
    }
    for (const node of opened.labels.values()) node.remove();
    for (const { line, dot } of opened.leaders.values()) {
      line.remove();
      dot.remove();
    }
    this.labels.classList.remove('parts-open', 'parts-shown');
    if (this.opened === opened) this.opened = undefined;
    this.setHot(null);
  }

  /** Whether a material is drawn with its opacity. The shader is built for one or the other, so a change rebuilds it. */
  private seeThrough(material: THREE.Material, on: boolean): void {
    if (material.transparent === on) return;
    material.transparent = on;
    material.needsUpdate = true;
  }

  private setHot(part: PartKey | null): void {
    if (part === this.hotPart) return;
    this.highlightPart(part);
    this.callbacks.onPart?.(this.hotPart);
  }

  /** Put the label of each component beside it, with a line to it. */
  private placeParts(opened: Opened): void {
    if (opened.progress < 0.6) return;
    const width = this.container.clientWidth;
    const height = this.container.clientHeight;
    const toPage = (world: THREE.Vector3): { x: number; y: number; ahead: boolean } => {
      const v = world.clone().project(this.camera);
      return { x: (v.x * 0.5 + 0.5) * width, y: (-v.y * 0.5 + 0.5) * height, ahead: v.z > -1 && v.z < 1 };
    };
    // On the page: which way the rotor lies, and how many pixels a metre of the turbine takes.
    const origin = opened.view.yaw.getWorldPosition(new THREE.Vector3());
    const yaw = opened.view.yaw.rotation.y;
    const at = toPage(origin);
    const ahead = toPage(origin.clone().add(new THREE.Vector3(Math.sin(yaw), 0, Math.cos(yaw)).multiplyScalar(TURBINE_SCALE)));
    const above = toPage(origin.clone().addScaledVector(this.camera.up.clone().applyQuaternion(this.camera.quaternion), TURBINE_SCALE));
    const rotorSide = ahead.x < at.x ? -1 : 1;
    const perMetre = Math.hypot(above.x - at.x, above.y - at.y);

    const placed: { left: number; right: number; top: number; bottom: number }[] = [];
    const world = new THREE.Vector3();
    for (const part of PARTS) {
      const view = opened.parts.parts.get(part.key);
      const node = opened.labels.get(part.key);
      const leader = opened.leaders.get(part.key);
      if (!view || !node || !leader) continue;
      const anchor = toPage(view.anchor.getWorldPosition(world));
      const seen = anchor.ahead && anchor.x > -40 && anchor.x < width + 40 && anchor.y > -40 && anchor.y < height + 40;
      node.style.display = seen ? '' : 'none';
      leader.line.style.display = seen ? '' : 'none';
      leader.dot.style.display = seen ? '' : 'none';
      if (!seen) continue;
      let size = opened.sizes.get(part.key);
      if (!size) {
        size = { w: node.offsetWidth, h: node.offsetHeight };
        opened.sizes.set(part.key, size);
      }
      // The label keeps clear of the part by its own half size, whatever the zoom.
      const { along, up } = view.label;
      let x = anchor.x + rotorSide * (along * perMetre + Math.sign(along) * (size.w / 2));
      let y = anchor.y - (up * perMetre + Math.sign(up) * (size.h / 2));
      x = Math.min(width - size.w / 2 - 6, Math.max(size.w / 2 + 6, x));
      y = Math.min(height - size.h / 2 - 6, Math.max(size.h / 2 + 6, y));
      // A label that would lie under a panel comes back towards its part, by the shortest way out.
      let step = up < 0 || (up === 0 && anchor.y > at.y) ? 1 : -1;
      for (const panel of this.panels) {
        if (x - size.w / 2 >= panel.right || x + size.w / 2 <= panel.left || y - size.h / 2 >= panel.bottom || y + size.h / 2 <= panel.top) continue;
        const ways = [
          { dx: 0, dy: panel.top - (y + size.h / 2), open: anchor.y < panel.top },
          { dx: 0, dy: panel.bottom - (y - size.h / 2), open: anchor.y > panel.bottom },
          { dx: panel.left - (x + size.w / 2), dy: 0, open: anchor.x < panel.left },
          { dx: panel.right - (x - size.w / 2), dy: 0, open: anchor.x > panel.right },
        ].filter((way) => way.open);
        if (ways.length === 0) continue; // the part itself lies under the panel
        const way = ways.reduce((a, b) => (Math.abs(a.dx) + Math.abs(a.dy) <= Math.abs(b.dx) + Math.abs(b.dy) ? a : b));
        x += way.dx;
        y += way.dy;
        if (way.dy !== 0) step = way.dy < 0 ? -1 : 1;
      }
      // A label that would cover one already placed moves on, away from the drivetrain.
      for (let attempt = 0; attempt < 8; attempt++) {
        const hit = placed.find((r) => x - size.w / 2 < r.right && x + size.w / 2 > r.left && y - size.h / 2 < r.bottom && y + size.h / 2 > r.top);
        if (!hit) break;
        y = step > 0 ? hit.bottom + size.h / 2 + 4 : hit.top - size.h / 2 - 4;
      }
      const box = { left: x - size.w / 2, right: x + size.w / 2, top: y - size.h / 2, bottom: y + size.h / 2 };
      placed.push(box);
      node.style.transform = `translate(${box.left.toFixed(1)}px, ${box.top.toFixed(1)}px)`;
      // The line runs from the part to the nearest point of the label.
      const endX = Math.min(box.right, Math.max(box.left, anchor.x));
      const endY = Math.min(box.bottom, Math.max(box.top, anchor.y));
      leader.line.setAttribute('x1', anchor.x.toFixed(1));
      leader.line.setAttribute('y1', anchor.y.toFixed(1));
      leader.line.setAttribute('x2', endX.toFixed(1));
      leader.line.setAttribute('y2', endY.toFixed(1));
      leader.dot.setAttribute('cx', anchor.x.toFixed(1));
      leader.dot.setAttribute('cy', anchor.y.toFixed(1));
    }
  }

  /** The quality level in use, for the console and the tests. */
  get qualityLevel(): number {
    return this.quality;
  }

  /**
   * Steps the picture down when frames take too long: first to one pixel per CSS pixel and a smaller
   * shadow map, then to no shadows, half the shrubs and no wind streaks, last to a coarser picture. A
   * computer without a graphics card, or a remote desktop, then still gets a twin that answers to the mouse.
   */
  private watchFrameTime(): void {
    const now = performance.now();
    const took = now - this.lastFrameAt;
    this.lastFrameAt = now;
    if (!this.adaptive || this.quality >= 3 || this.frame < 12 || document.hidden || took > 10000) return;
    this.frameTimes.push(took);
    if (this.frameTimes.length < 24) return;
    const average = this.frameTimes.reduce((a, b) => a + b, 0) / this.frameTimes.length;
    this.frameTimes = [];
    if (average < 55) return;
    this.quality += 1;
    this.renderer.setPixelRatio(this.quality === 3 ? 0.6 : 1);
    if (this.sun && this.quality < 3) {
      if (this.quality === 1) {
        this.sun.shadow.mapSize.set(2048, 2048);
        this.sun.shadow.map?.dispose();
        this.sun.shadow.map = null;
      } else {
        this.sun.castShadow = false;
        this.renderer.shadowMap.enabled = false;
        this.scene.traverse((object) => {
          const material = (object as THREE.Mesh).material as THREE.Material | THREE.Material[] | undefined;
          for (const m of Array.isArray(material) ? material : material ? [material] : []) m.needsUpdate = true;
        });
      }
    }
    if (this.quality === 2) {
      if (this.shrubs) this.shrubs.count = Math.floor(this.shrubs.count / 2);
      this.streaks.visible = false;
    }
    this.resize();
    console.info(`Wind farm twin: frames took ${Math.round(average)} ms, picture quality lowered to level ${this.quality}.`);
  }

  private moveStreaks(dt: number): void {
    const along = downwind(this.wind.direction);
    const speed = this.wind.speed * 13;
    const length = 40 + this.wind.speed * 11;
    const positions = this.streaks.geometry.getAttribute('position') as THREE.BufferAttribute;
    for (let i = 0; i < STREAKS; i++) {
      const k = i * 4;
      let x = this.streakSeeds[k] + along.x * speed * dt * this.streakSeeds[k + 3];
      let z = this.streakSeeds[k + 1] + along.z * speed * dt * this.streakSeeds[k + 3];
      if (x > STREAK_AREA) x -= STREAK_AREA * 2;
      if (x < -STREAK_AREA) x += STREAK_AREA * 2;
      if (z > STREAK_AREA) z -= STREAK_AREA * 2;
      if (z < -STREAK_AREA) z += STREAK_AREA * 2;
      this.streakSeeds[k] = x;
      this.streakSeeds[k + 1] = z;
      const y = heightAt(x, -z) + this.streakSeeds[k + 2];
      positions.setXYZ(i * 2, x, y, z);
      positions.setXYZ(i * 2 + 1, x - along.x * length, y, z - along.z * length);
    }
    positions.needsUpdate = true;
    (this.streaks.material as THREE.LineBasicMaterial).opacity = Math.min(0.34, 0.08 + this.wind.speed * 0.02);
  }

  private placeLabels(): void {
    const width = this.container.clientWidth;
    const height = this.container.clientHeight;
    const v = new THREE.Vector3();
    const shown: { node: HTMLButtonElement; x: number; y: number; scale: number; distance: number; id: string }[] = [];
    for (const [id, node] of this.labelNodes) {
      const anchor = this.anchors.get(id);
      if (!anchor) continue;
      v.copy(anchor).project(this.camera);
      const distance = this.camera.position.distanceTo(anchor);
      const visible = v.z > -1 && v.z < 1 && Math.abs(v.x) < 1.1 && Math.abs(v.y) < 1.1 && (!node.classList.contains('place') || distance < 6500);
      node.style.display = visible ? '' : 'none';
      if (visible) shown.push({ node, id, x: (v.x * 0.5 + 0.5) * width, y: (-v.y * 0.5 + 0.5) * height, scale: THREE.MathUtils.clamp(1.12 - distance / 11000, 0.74, 1.08), distance });
    }
    // Nearest first. A label that would cover one already placed moves up until it is clear.
    shown.sort((a, b) => a.distance - b.distance);
    const placed: { left: number; right: number; top: number; bottom: number }[] = [];
    for (const label of shown) {
      let size = this.labelSizes.get(label.id);
      if (!size) {
        size = { w: label.node.offsetWidth, h: label.node.offsetHeight };
        this.labelSizes.set(label.id, size);
      }
      const w = size.w * label.scale;
      const h = size.h * label.scale;
      let y = label.y;
      for (let attempt = 0; attempt < 6; attempt++) {
        const hit = placed.find((r) => label.x - w / 2 < r.right && label.x + w / 2 > r.left && y - h < r.bottom && y > r.top);
        if (!hit) break;
        y = hit.top - 3;
      }
      placed.push({ left: label.x - w / 2, right: label.x + w / 2, top: y - h, bottom: y });
      label.node.style.transform = `translate(-50%, -100%) translate(${label.x.toFixed(1)}px, ${y.toFixed(1)}px) scale(${label.scale.toFixed(3)})`;
      label.node.style.zIndex = String(100000 - Math.round(label.distance));
    }
  }

  // ---------------------------------------------------------------- pointer

  private pick(event: PointerEvent): string | null {
    const rect = this.renderer.domElement.getBoundingClientRect();
    const point = new THREE.Vector2(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(point, this.camera);
    const hit = this.raycaster.intersectObjects(this.proxies, false)[0];
    return hit ? (hit.object.userData.turbineId as string) : null;
  }

  private readonly onPointerDown = (event: PointerEvent): void => {
    this.pointerDown = { x: event.clientX, y: event.clientY };
  };

  private readonly onPointerUp = (event: PointerEvent): void => {
    const down = this.pointerDown;
    this.pointerDown = undefined;
    if (!down || Math.hypot(event.clientX - down.x, event.clientY - down.y) > 5) return; // a drag, not a click
    const id = this.pick(event);
    if (id) this.callbacks.onSelect(id);
  };

  private readonly onPointerMove = (event: PointerEvent): void => {
    if (this.pointerDown) return;
    this.hovered = this.pick(event);
    const part = this.pickPart(event);
    this.setHot(part);
    this.renderer.domElement.style.cursor = this.hovered || part ? 'pointer' : 'grab';
  };

  /** The component of the opened turbine under the pointer. */
  private pickPart(event: PointerEvent): PartKey | null {
    const opened = this.opened;
    if (!opened || opened.goal === 0 || opened.progress < 0.9) return null;
    const rect = this.renderer.domElement.getBoundingClientRect();
    const point = new THREE.Vector2(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(point, this.camera);
    const meshes = [...opened.parts.parts.values()].flatMap((p) => p.meshes);
    const hit = this.raycaster.intersectObjects(meshes, false)[0];
    return hit ? (hit.object.userData.part as PartKey) : null;
  }
}

/** Heights the labels and the detail camera use, exported for the tests. */
export const SCENE_DIMENSIONS = { hubHeight: HUB_HEIGHT, bladeLength: BLADE_LENGTH };
