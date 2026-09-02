// Interactive neural-network particle field background.
// Nodes drift with bounded random walks; lines connect nodes within
// LINK_DIST. Mouse repels nearby nodes and brightens the local lines,
// giving the "neural firing" feel.
//
// Three.js is loaded from a CDN via the importmap in landing.html.
// Gated to >=1024px viewports and prefers-reduced-motion via CSS
// (#bg-3d); this script bails early if those conditions fail.
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
    // Offline or blocked CDN - bail silently. The page works without the bg.
    canvas.remove();
    return;
  }

  const { Scene, PerspectiveCamera, WebGLRenderer, BufferGeometry, Float32BufferAttribute,
          LineSegments, LineBasicMaterial, Points, PointsMaterial, AdditiveBlending,
          Vector3, Vector2, Color, CircleGeometry } = THREE;

  // ---- Configuration ----
  const NODE_COUNT      = 120;   // particle count
  const SPREAD          = 7.0;   // initial world extent
  const LINK_DIST       = 1.4;   // connection distance
  const MOUSE_RADIUS    = 1.8;   // how far the mouse effect reaches
  const MOUSE_FORCE     = 0.35;  // how hard nodes get pushed
  const DRIFT_SPEED     = 0.04;  // base random-walk speed
  const RECENTER_FORCE  = 0.015; // soft pull toward origin
  const NODE_SIZE_PX    = 2.4;   // node point size

  // ---- Seed nodes in a soft sphere ----
  const positions = new Float32Array(NODE_COUNT * 3);
  const velocities = new Float32Array(NODE_COUNT * 3);
  for (let i = 0; i < NODE_COUNT; i++) {
    // Distribute with slight bias toward the center so the field is denser
    const r = Math.cbrt(Math.random()) * SPREAD * 0.7;
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    positions[i * 3]     = r * Math.sin(phi) * Math.cos(theta);
    positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta) * 0.6;  // flatter Y
    positions[i * 3 + 2] = r * Math.cos(phi);
  }

  // ---- Three.js scene ----
  const scene = new Scene();
  const camera = new PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 100);
  camera.position.z = 7;

  const renderer = new WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
  renderer.setSize(window.innerWidth, window.innerHeight, false);
  renderer.setClearColor(0x000000, 0);

  // Theme-aware colors: the canvas lives behind the page so it should
  // pick up the current theme's accent.
  const cssVar = (name) => getComputedStyle(document.documentElement)
    .getPropertyValue(name).trim();
  const accent = new Color(cssVar('--accent') || '#6366f1');
  const accentSoft = accent.clone().multiplyScalar(0.7);

  // ---- Nodes (Points) ----
  const nodeGeom = new BufferGeometry();
  nodeGeom.setAttribute('position', new Float32BufferAttribute(positions, 3));
  const nodeMat = new PointsMaterial({
    color: 0xffffff,
    size: NODE_SIZE_PX,
    sizeAttenuation: false,
    transparent: true,
    opacity: 0.9,
    blending: AdditiveBlending,
    depthWrite: false,
  });
  const points = new Points(nodeGeom, nodeMat);
  scene.add(points);

  // ---- Connection lines (LineSegments, dynamic geometry) ----
  // Allocate enough capacity for worst-case density. Real line count is
  // recomputed each frame from the current node positions.
  const MAX_LINES = NODE_COUNT * (NODE_COUNT - 1) / 2;
  const lineGeom = new BufferGeometry();
  const linePositions = new Float32Array(MAX_LINES * 6);    // 2 verts * 3 floats per line
  const lineColors    = new Float32Array(MAX_LINES * 6);    // per-vertex color
  lineGeom.setAttribute('position', new Float32BufferAttribute(linePositions, 3));
  lineGeom.setAttribute('color',    new Float32BufferAttribute(lineColors, 3));
  lineGeom.setDrawRange(0, 0);  // updated each frame

  const lineMat = new LineBasicMaterial({
    vertexColors: true,
    transparent: true,
    opacity: 0.55,
    blending: AdditiveBlending,
    depthWrite: false,
  });
  const lines = new LineSegments(lineGeom, lineMat);
  scene.add(lines);

  // ---- Mouse parallax ----
  // We don't raycast (overkill for this) - we use a normalized 2D
  // pointer position and a depth-estimate constant. Nodes within
  // MOUSE_RADIUS of the projected pointer get repelled.
  const pointer = new Vector2(0, 0);
  const pointerTarget = new Vector2(0, 0);
  let pointerActive = false;

  function onPointerMove(e) {
    // Normalize to [-1, 1] with Y inverted (screen Y is down).
    const x = (e.clientX / window.innerWidth) * 2 - 1;
    const y = -((e.clientY / window.innerHeight) * 2 - 1);
    pointerTarget.set(x, y);
    pointerActive = true;
  }
  function onPointerLeave() { pointerActive = false; }

  window.addEventListener('pointermove', onPointerMove, { passive: true });
  window.addEventListener('pointerleave', onPointerLeave, { passive: true });
  document.addEventListener('mouseleave', onPointerLeave, { passive: true });

  // ---- Rebuild connections on the fly ----
  // We rebuild only every CONNECT_REBUILD frames to save CPU. Connections
  // stay stable for ~50ms which is invisible to the eye.
  let lastConnectPositions = new Float32Array(NODE_COUNT * 3);
  let lineCount = 0;
  const CONNECT_REBUILD = 3;  // frames between rebuilds

  function rebuildConnections() {
    let p = 0;
    for (let i = 0; i < NODE_COUNT; i++) {
      const ix = positions[i * 3];
      const iy = positions[i * 3 + 1];
      const iz = positions[i * 3 + 2];
      for (let j = i + 1; j < NODE_COUNT; j++) {
        const dx = ix - positions[j * 3];
        const dy = iy - positions[j * 3 + 1];
        const dz = iz - positions[j * 3 + 2];
        const d = Math.sqrt(dx*dx + dy*dy + dz*dz);
        if (d < LINK_DIST) {
          linePositions[p * 6]     = ix;
          linePositions[p * 6 + 1] = iy;
          linePositions[p * 6 + 2] = iz;
          linePositions[p * 6 + 3] = positions[j * 3];
          linePositions[p * 6 + 4] = positions[j * 3 + 1];
          linePositions[p * 6 + 5] = positions[j * 3 + 2];
          p++;
        }
      }
    }
    lineCount = p;
    lineGeom.setDrawRange(0, p * 2);
    lineGeom.attributes.position.needsUpdate = true;
  }

  // ---- Color the lines based on distance and proximity to pointer ----
  // Closer connections are brighter; the pointer's halo makes
  // local lines glow.
  const pointerWorld = new Vector3(0, 0, 0);
  function colorConnections() {
    // Approximate the pointer in world space at z=0
    pointerWorld.set(pointer.x * 5, pointer.y * 3, 0);
    for (let i = 0; i < lineCount; i++) {
      const ax = linePositions[i * 6],     ay = linePositions[i * 6 + 1], az = linePositions[i * 6 + 2];
      const bx = linePositions[i * 6 + 3], by = linePositions[i * 6 + 4], bz = linePositions[i * 6 + 5];
      const mx = (ax + bx) * 0.5, my = (ay + by) * 0.5, mz = (az + bz) * 0.5;
      const dx = mx - pointerWorld.x, dy = my - pointerWorld.y, dz = mz - pointerWorld.z;
      const dPointer = Math.sqrt(dx*dx + dy*dy + dz*dz);
      // Pointer glow: 0 at MOUSE_RADIUS, 1 at 0
      const glow = pointerActive
        ? Math.max(0, 1 - dPointer / MOUSE_RADIUS)
        : 0;
      // Line color: base accent, brightened by glow
      const r = accent.r * (0.4 + glow * 0.8);
      const g = accent.g * (0.4 + glow * 0.8);
      const b = accent.b * (0.4 + glow * 0.8);
      // Per-vertex so we can have an additive gradient effect
      const glowA = Math.max(0, 1 - dPointer / (MOUSE_RADIUS * 1.2));
      const rA = accent.r * (0.3 + glowA * 0.6);
      const gA = accent.g * (0.3 + glowA * 0.6);
      const bA = accent.b * (0.3 + glowA * 0.6);
      lineColors[i * 6]     = rA;
      lineColors[i * 6 + 1] = gA;
      lineColors[i * 6 + 2] = bA;
      lineColors[i * 6 + 3] = r;
      lineColors[i * 6 + 4] = g;
      lineColors[i * 6 + 5] = b;
    }
    lineGeom.attributes.color.needsUpdate = true;
  }

  // ---- Node motion: bounded random walk + mouse repulsion + recenter ----
  // Pointer projects into world space at z=0 for repulsion math.
  function updateNodes(dt) {
    // Smoothly ease the pointer toward its target
    pointer.lerp(pointerTarget, 0.08);

    // Use pointer as a world-space 3D point for repulsion
    const px = pointer.x * 5;
    const py = pointer.y * 3;
    const pz = 0;

    for (let i = 0; i < NODE_COUNT; i++) {
      const x = positions[i * 3];
      const y = positions[i * 3 + 1];
      const z = positions[i * 3 + 2];

      // Random walk impulse
      velocities[i * 3]     += (Math.random() - 0.5) * DRIFT_SPEED * dt;
      velocities[i * 3 + 1] += (Math.random() - 0.5) * DRIFT_SPEED * dt;
      velocities[i * 3 + 2] += (Math.random() - 0.5) * DRIFT_SPEED * dt;

      // Soft attractor toward the origin
      velocities[i * 3]     -= x * RECENTER_FORCE * dt;
      velocities[i * 3 + 1] -= y * RECENTER_FORCE * dt;
      velocities[i * 3 + 2] -= z * RECENTER_FORCE * dt;

      // Mouse repulsion (only if pointer is active)
      if (pointerActive) {
        const dx = x - px, dy = y - py, dz = z - pz;
        const d = Math.sqrt(dx*dx + dy*dy + dz*dz);
        if (d < MOUSE_RADIUS && d > 0.001) {
          const force = MOUSE_FORCE * (1 - d / MOUSE_RADIUS) / d;
          velocities[i * 3]     += dx * force;
          velocities[i * 3 + 1] += dy * force;
          velocities[i * 3 + 2] += dz * force;
        }
      }

      // Damping
      velocities[i * 3]     *= 0.985;
      velocities[i * 3 + 1] *= 0.985;
      velocities[i * 3 + 2] *= 0.985;

      // Clamp to a soft world boundary so nodes don't escape
      const speed = Math.sqrt(
        velocities[i*3]*velocities[i*3] +
        velocities[i*3+1]*velocities[i*3+1] +
        velocities[i*3+2]*velocities[i*3+2]
      );
      if (speed > 0.4) {
        const scale = 0.4 / speed;
        velocities[i * 3]     *= scale;
        velocities[i * 3 + 1] *= scale;
        velocities[i * 3 + 2] *= scale;
      }

      positions[i * 3]     += velocities[i * 3]     * dt;
      positions[i * 3 + 1] += velocities[i * 3 + 1] * dt;
      positions[i * 3 + 2] += velocities[i * 3 + 2] * dt;

      // Soft world boundary: nudge back if a node escapes
      const r = Math.sqrt(
        positions[i*3]*positions[i*3] +
        positions[i*3+1]*positions[i*3+1] +
        positions[i*3+2]*positions[i*3+2]
      );
      if (r > SPREAD * 1.5) {
        const scale = (SPREAD * 1.5) / r;
        positions[i * 3]     *= scale;
        positions[i * 3 + 1] *= scale;
        positions[i * 3 + 2] *= scale;
        // Reflect velocity
        velocities[i * 3]     *= -0.4;
        velocities[i * 3 + 1] *= -0.4;
        velocities[i * 3 + 2] *= -0.4;
      }
    }

    nodeGeom.attributes.position.needsUpdate = true;
  }

  // ---- Render loop ----
  let raf = 0;
  let lastT = performance.now();
  let frame = 0;

  function tick(now) {
    const dt = Math.min((now - lastT) / 1000, 0.05);  // cap dt at 50ms
    lastT = now;
    frame++;

    updateNodes(dt * 60);  // scale so 1 = 1 frame at 60fps
    if (frame % CONNECT_REBUILD === 0) rebuildConnections();
    colorConnections();

    // Subtle scene rotation - whole field gently turns
    lines.rotation.y = Math.sin(now / 8000) * 0.08;
    points.rotation.y = lines.rotation.y;
    lines.rotation.x = Math.cos(now / 11000) * 0.04;
    points.rotation.x = lines.rotation.x;

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

  // ---- Pause when the tab is hidden ----
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      cancelAnimationFrame(raf);
    } else {
      lastT = performance.now();
      raf = requestAnimationFrame(tick);
    }
  });
})();
