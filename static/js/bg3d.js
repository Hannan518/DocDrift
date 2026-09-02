// Antigravity-style 3D background: a thin particle mesh that drifts.
// Loaded only on the landing page; gated to >=1024px and
// prefers-reduced-motion via CSS in main.css (#bg-3d).
// Three.js is loaded from a CDN; the import map is in landing.html.
(async () => {
  'use strict';

  const canvas = document.getElementById('bg-3d');
  if (!canvas) return;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  if (window.innerWidth < 1024) return;

  let THREE;
  try {
    THREE = await import('three');
  } catch (e) {
    // Offline or blocked CDN - silently bail; the page works without the background.
    canvas.remove();
    return;
  }

  const { Scene, PerspectiveCamera, WebGLRenderer, BufferGeometry, Float32BufferAttribute,
          LineSegments, LineBasicMaterial, AdditiveBlending, Vector3, Color } = THREE;

  // ---- Particle field: 200 points connected to nearest neighbours ----
  const N = 200;             // particle count
  const LINK_DIST = 0.35;     // connect particles within this distance
  const SPREAD = 8;           // world extent

  // Seed positions on a 3D sphere surface
  const positions = new Float32Array(N * 3);
  const origPositions = new Float32Array(N * 3);
  for (let i = 0; i < N; i++) {
    const u = Math.random();
    const v = Math.random();
    const theta = 2 * Math.PI * u;
    const phi = Math.acos(2 * v - 1);
    const r = 3 + Math.random() * 0.5;
    const x = r * Math.sin(phi) * Math.cos(theta);
    const y = r * Math.sin(phi) * Math.sin(theta);
    const z = r * Math.cos(phi);
    positions[i * 3]     = x;
    positions[i * 3 + 1] = y;
    positions[i * 3 + 2] = z;
    origPositions[i * 3]     = x;
    origPositions[i * 3 + 1] = y;
    origPositions[i * 3 + 2] = z;
  }

  // ---- Build line-segment pairs from particles within LINK_DIST ----
  const linePositions = [];
  for (let i = 0; i < N; i++) {
    for (let j = i + 1; j < N; j++) {
      const dx = positions[i * 3]     - positions[j * 3];
      const dy = positions[i * 3 + 1] - positions[j * 3 + 1];
      const dz = positions[i * 3 + 2] - positions[j * 3 + 2];
      const d = Math.sqrt(dx*dx + dy*dy + dz*dz);
      if (d < LINK_DIST) {
        linePositions.push(
          positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2],
          positions[j * 3], positions[j * 3 + 1], positions[j * 3 + 2],
        );
      }
    }
  }

  const scene = new Scene();

  const camera = new PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 100);
  camera.position.z = 6;

  const renderer = new WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5)); // cap for perf
  renderer.setSize(window.innerWidth, window.innerHeight, false);
  renderer.setClearColor(0x000000, 0); // transparent - body bg shows through

  // Use a slightly bluish accent that adapts to the theme via CSS variable.
  const accent = getComputedStyle(document.documentElement)
    .getPropertyValue('--accent').trim() || '#6366f1';
  const lineColor = new Color(accent);

  const geom = new BufferGeometry();
  geom.setAttribute('position', new Float32BufferAttribute(linePositions, 3));

  const mat = new LineBasicMaterial({
    color: lineColor,
    transparent: true,
    opacity: 0.35,
    blending: AdditiveBlending,
    depthWrite: false,
  });

  const lines = new LineSegments(geom, mat);
  scene.add(lines);

  // ---- Animation: gentle drift + slow rotation. No mouse interaction
  //      (the canvas is below the snap content; we don't want to steal
  //      scroll or hover from the actual page). ----
  const start = performance.now();
  const drift = new Vector3(0, 0, 0);
  let raf = 0;

  function tick(now) {
    const t = (now - start) / 1000;
    // Subtle sinusoidal drift on the line vertices
    const pos = geom.attributes.position.array;
    for (let i = 0; i < N; i++) {
      const ox = origPositions[i * 3];
      const oy = origPositions[i * 3 + 1];
      const oz = origPositions[i * 3 + 2];
      pos[i * 3]     = ox + Math.sin(t * 0.4 + i * 0.13) * 0.05;
      pos[i * 3 + 1] = oy + Math.cos(t * 0.35 + i * 0.21) * 0.05;
      pos[i * 3 + 2] = oz + Math.sin(t * 0.45 + i * 0.17) * 0.05;
    }
    geom.attributes.position.needsUpdate = true;

    lines.rotation.x = Math.sin(t * 0.05) * 0.15;
    lines.rotation.y = Math.cos(t * 0.04) * 0.2;
    lines.rotation.z += 0.0008;

    renderer.render(scene, camera);
    raf = requestAnimationFrame(tick);
  }
  raf = requestAnimationFrame(tick);

  // ---- Resize handling ----
  let resizeTimer = 0;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight, false);
    }, 120);
  });

  // ---- Pause when the tab is hidden to save battery ----
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      cancelAnimationFrame(raf);
    } else {
      raf = requestAnimationFrame(tick);
    }
  });
})();
