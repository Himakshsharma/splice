import { useEffect, useRef, useState } from "react";
import * as THREE from "three";

/**
 * A 3D strip of audio-level bars that visualises a jump cut:
 * a blue playhead sweeps the strip, silent bars collapse, and the kept bars slide together.
 *
 * - mode="loop":        the landing-page illustration (synthetic levels, plays on a loop).
 * - mode="interactive": the results view, fed with the job's real loudness envelope and edit
 *                       decisions; `collapsed` toggles between source and edited layouts and the
 *                       strip can be rotated by dragging.
 */
export interface CutScene3DProps {
  levels: number[]; // 0..1 loudness per bar
  keep: boolean[]; // same length as levels
  mode: "loop" | "interactive";
  collapsed?: boolean;
  className?: string;
  label: string;
}

const COLORS = {
  keepLow: new THREE.Color("#6b5ce0"),
  keepHigh: new THREE.Color("#c4bbff"),
  cut: new THREE.Color("#3b3750"),
  scan: new THREE.Color("#4ea8ff"),
};
const STRIP_WIDTH = 17;
const LOOP_SECONDS = 9.5;

const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

function supportsWebGL(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

export function CutScene3D({ levels, keep, mode, collapsed = false, className, label }: CutScene3DProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const collapsedRef = useRef(collapsed);
  const [failed, setFailed] = useState(false);
  collapsedRef.current = collapsed;

  useEffect(() => {
    const host = hostRef.current;
    if (!host || levels.length === 0) return;
    if (!supportsWebGL()) {
      setFailed(true);
      return;
    }
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
    } catch {
      setFailed(true);
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.appendChild(renderer.domElement);
    renderer.domElement.style.display = "block";
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 100);

    scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    const key = new THREE.DirectionalLight(0xd8d2ff, 1.6);
    key.position.set(-6, 10, 8);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0x4ea8ff, 0.9);
    rim.position.set(8, 2, -6);
    scene.add(rim);

    const group = new THREE.Group();
    scene.add(group);

    // Bars ---------------------------------------------------------------------------
    const n = levels.length;
    const spacing = STRIP_WIDTH / n;
    const keptIndex: number[] = [];
    let k = 0;
    for (let i = 0; i < n; i++) keptIndex.push(keep[i] ? k++ : -1);
    const keptTotal = Math.max(1, k);
    const sourceX = (i: number) => (i - (n - 1) / 2) * spacing;
    const editedX = (i: number) => (keptIndex[i] - (keptTotal - 1) / 2) * spacing;
    const heights = levels.map((l) => 0.12 + clamp01(l) * 3.4);

    const geometry = new THREE.BoxGeometry(1, 1, 1);
    const material = new THREE.MeshStandardMaterial({ roughness: 0.38, metalness: 0.15 });
    const bars = new THREE.InstancedMesh(geometry, material, n);
    bars.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    group.add(bars);
    const baseColors = levels.map((l) => COLORS.keepLow.clone().lerp(COLORS.keepHigh, clamp01(l) ** 0.8));

    // Playhead ------------------------------------------------------------------------------
    const scanMat = new THREE.MeshBasicMaterial({ color: COLORS.scan, transparent: true, opacity: 0.95 });
    const scan = new THREE.Mesh(new THREE.BoxGeometry(0.05, 4.4, 0.05), scanMat);
    const glowMat = new THREE.MeshBasicMaterial({
      color: COLORS.scan,
      transparent: true,
      opacity: 0.16,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const glow = new THREE.Mesh(new THREE.PlaneGeometry(0.9, 4.4), glowMat);
    scan.add(glow);
    scan.visible = mode === "loop";
    group.add(scan);

    const dummy = new THREE.Object3D();
    const tmpColor = new THREE.Color();
    const sinkStart = new Float32Array(n).fill(-1);

    /** sink[i] in 0..1 (1 = fully collapsed), slide in 0..1 (1 = edited layout). */
    const layout = (sink: (i: number) => number, slide: number) => {
      for (let i = 0; i < n; i++) {
        const s = keep[i] ? 0 : sink(i);
        const x = keep[i] ? sourceX(i) + (editedX(i) - sourceX(i)) * slide : sourceX(i);
        const h = heights[i] * (1 - s) + 0.04 * s;
        dummy.position.set(x, 0, keep[i] ? 0 : -s * 0.6);
        dummy.scale.set(spacing * 0.7, h, spacing * 0.7);
        dummy.updateMatrix();
        bars.setMatrixAt(i, dummy.matrix);
        tmpColor.copy(baseColors[i]).lerp(COLORS.cut, keep[i] ? 0 : Math.min(1, s * 1.4));
        bars.setColorAt(i, tmpColor);
      }
      bars.instanceMatrix.needsUpdate = true;
      if (bars.instanceColor) bars.instanceColor.needsUpdate = true;
    };

    // Interaction (interactive mode): drag to rotate --------------------------------------
    let dragX: number | null = null;
    let userYaw = 0;
    const onDown = (e: PointerEvent) => {
      dragX = e.clientX;
      renderer.domElement.setPointerCapture(e.pointerId);
    };
    const onMove = (e: PointerEvent) => {
      if (dragX === null) return;
      userYaw = Math.max(-0.9, Math.min(0.9, userYaw + (e.clientX - dragX) * 0.005));
      dragX = e.clientX;
    };
    const onUp = () => (dragX = null);
    if (mode === "interactive") {
      renderer.domElement.style.cursor = "grab";
      renderer.domElement.style.touchAction = "pan-y";
      renderer.domElement.addEventListener("pointerdown", onDown);
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    }

    // Sizing & visibility ---------------------------------------------------------------
    const resize = () => {
      const w = host.clientWidth;
      const h = host.clientHeight;
      if (!w || !h) return;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      // Fit the strip to ~90% of the width, but never closer than its height allows.
      const tanHalf = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
      // On portrait screens let the strip run off the edges rather than shrinking it to a sliver.
      const fit = camera.aspect < 1 ? 0.55 : 1.1;
      const dist = Math.max((STRIP_WIDTH * fit) / (2 * tanHalf * camera.aspect), 5.6 / (2 * tanHalf));
      camera.position.set(0, dist * 0.26, dist);
      scene.fog = new THREE.Fog(0x0e0d14, dist * 0.85, dist * 2.2);
      camera.lookAt(0, -0.15, 0);
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(host);
    resize();

    let visible = true;
    const io = new IntersectionObserver(([entry]) => (visible = entry.isIntersecting));
    io.observe(host);

    // Animation ---------------------------------------------------------------------------
    const clock = new THREE.Clock();
    let progress = collapsedRef.current ? 1 : 0; // interactive mode
    let frame = 0;

    const renderLoopFrame = (t: number) => {
      const xMin = sourceX(0) - 0.6;
      const xMax = sourceX(n - 1) + 0.6;
      const phase = t % LOOP_SECONDS;
      const scanT = clamp01((phase - 0.6) / 4);
      const scanX = xMin + (xMax - xMin) * ease(scanT);
      const slide = ease(clamp01((phase - 5.0) / 1.6));
      const reset = clamp01((phase - 8.6) / 0.9);
      scan.position.x = scanX;
      scanMat.opacity = 0.95 * (1 - clamp01((phase - 4.6) / 0.5)) * (phase > 0.4 ? 1 : phase / 0.4);
      glowMat.opacity = 0.16 * scanMat.opacity;
      layout((i) => {
        if (reset > 0) return 1 - ease(reset);
        if (scanX > sourceX(i) && sinkStart[i] < 0) sinkStart[i] = phase;
        if (phase < 0.6) sinkStart[i] = -1;
        return sinkStart[i] < 0 ? 0 : ease(clamp01((phase - sinkStart[i]) / 0.45));
      }, slide * (1 - ease(reset)));
      group.rotation.y = Math.sin(t * 0.22) * 0.16 - 0.08;
    };

    const renderInteractiveFrame = (dt: number, t: number) => {
      const target = collapsedRef.current ? 1 : 0;
      progress = reduceMotion ? target : progress + Math.sign(target - progress) * Math.min(Math.abs(target - progress), dt * 0.9);
      const sink = ease(clamp01(progress * 2));
      const slide = ease(clamp01(progress * 2 - 1));
      layout(() => sink, slide);
      const sway = reduceMotion ? 0 : Math.sin(t * 0.2) * 0.06;
      group.rotation.y += (userYaw + sway - 0.12 - group.rotation.y) * 0.12;
    };

    const tick = () => {
      frame = requestAnimationFrame(tick);
      if (!visible) return;
      const dt = Math.min(0.05, clock.getDelta());
      const t = clock.elapsedTime;
      if (mode === "loop") {
        if (reduceMotion) {
          scan.visible = false;
          layout(() => 1, 0);
        } else renderLoopFrame(t);
      } else renderInteractiveFrame(dt, t);
      renderer.render(scene, camera);
    };
    tick();

    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
      io.disconnect();
      renderer.domElement.removeEventListener("pointerdown", onDown);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      scene.traverse((obj: THREE.Object3D) => {
        const mesh = obj as THREE.Mesh;
        mesh.geometry?.dispose();
        const mat = mesh.material as THREE.Material | THREE.Material[] | undefined;
        if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
        else mat?.dispose();
      });
      bars.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [levels, keep, mode]);

  return (
    <div ref={hostRef} className={className} role="img" aria-label={label}>
      {failed && <FlatFallback levels={levels} keep={keep} />}
    </div>
  );
}

/** Used when WebGL is unavailable: the same information, drawn flat. */
function FlatFallback({ levels, keep }: { levels: number[]; keep: boolean[] }) {
  return (
    <div className="flex h-full items-center gap-[2px] px-4">
      {levels.map((l, i) => (
        <span
          key={i}
          className={keep[i] ? "bg-keep" : "bg-line"}
          style={{ flex: 1, height: `${12 + l * 70}%`, borderRadius: 2 }}
        />
      ))}
    </div>
  );
}

/** Deterministic, speech-like levels for the landing-page illustration. */
export function demoStrip(count = 132): { levels: number[]; keep: boolean[] } {
  let seed = 7;
  const rand = () => {
    seed = (seed * 16807) % 2147483647;
    return seed / 2147483647;
  };
  const levels: number[] = [];
  const keep: boolean[] = [];
  const push = (level: number, kept: boolean) => {
    if (levels.length < count) {
      levels.push(level);
      keep.push(kept);
    }
  };
  // leading dead air
  for (let i = 0; i < 6; i++) push(0.02 + rand() * 0.03, false);
  while (levels.length < count) {
    const words = 2 + Math.floor(rand() * 4);
    push(0.05, true); // padding before speech
    for (let w = 0; w < words; w++) {
      const len = 3 + Math.floor(rand() * 5);
      const peak = 0.45 + rand() * 0.55;
      for (let j = 0; j < len; j++) push(peak * Math.sin(((j + 0.5) / len) * Math.PI) * (0.7 + rand() * 0.3), true);
      push(0.08 + rand() * 0.06, true); // natural short pause, kept
    }
    const pause = 5 + Math.floor(rand() * 9);
    for (let j = 0; j < pause; j++) push(0.02 + rand() * 0.04, false);
  }
  return { levels, keep };
}
