// Interactive 2D node field, Framer-style.
//
// A dense network of nodes (~600) connected by lines, all slowly
// drifting. Cursor pushes nearby nodes away and brightens the local
// network (the "firing" feel). Theme-aware: works on both light
// and dark backgrounds with NormalBlending.
//
// Implementation notes:
// - 2D orthographic camera so the field is genuinely flat
// - 600+ nodes at 4-6px each, link distance tuned so the network
//   reads as a dense graph (not a sparse sphere)
// - Connections are LineSegments with per-vertex color, recomputed
//   every 3 frames
// - Cursor effect: repulsion + glow, both tuned to be visible
//   (previous versions had 150 nodes which made the field too
//    sparse to read as a "field" or for cursor effects to register)
//
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
    canvas.remove();
    return;
  }

  const { Scene, OrthographicCamera, WebGLRenderer, BufferGeometry, Float32BufferAttribute,
          LineSegments, LineBasicMaterial, Points, PointsMaterial,
          NormalBlending, Color } = THREE;

  // ---- Configuration ----
  // Density tuned for 1440x900: ~1500 nodes = 1 node per ~860 px.
  // Each node is 4px, so the dot density is high enough to read
  // as a network. Link distance 50px so each node connects to
  // several neighbors.
  const NODE_COUNT       = 1500;
  const LINK_DIST_PX     = 55;
  const MOUSE_RADIUS_PX  = 200;
  const MOUSE_FORCE      = 140;
  const DRIFT_SPEED      = 0.6;
  const RECENTER_FORCE   = 0.02;
  const NODE_SIZE_PX     = 3.5;
  const DAMPING          = 0.94;
  const MAX_SPEED        = 5;
  const CONNECT_REBUILD  = 3;

  // ---- Theme-aware colors ----
  const cssVar = (name) => getComputedStyle(document.documentElement)
    .getPropertyValue(name).trim();

  let isDark = document.documentElement.getAttribute('data-theme') === 'dark';

  function pickColors(dark) {
    return {
      node: new Color(cssVar('--text') || (dark ? '#e8eaf0' : '#171a21')),
      line: new Color('#6366f1'),
      glow: dark ? new Color('#a5b4fc') : new Color('#4338ca'),
    };
  }
  let colors = pickColors(isDark);

  // ---- Seed nodes uniformly across the viewport ----
  let viewW = window.innerWidth;
  let viewH = window.innerHeight;

  const positions  = new Float32Array(NODE_COUNT * 2);
  const velocities = new Float32Array(NODE_COUNT * 2);

  function seedNodes() {
    for (let i = 0; i < NODE_COUNT; i++) {
      positions[i * 2]     = Math.random() * viewW;
      positions[i * 2 + 1] = Math.random() * viewH;
      velocities[i * 2]     = 0;
      velocities[i * 2 + 1] = 0;
    }
  }
  seedNodes();

  // ---- Scene setup ----
  const scene = new Scene();
  const camera = new OrthographicCamera(0, viewW, viewH, 0, -1000, 1000);
  camera.position.z = 1;

  const renderer = new WebGLRenderer({
    canvas,
    antialias: true,
    alpha: true,
    preserveDrawingBuffer: true,
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
  renderer.setSize(viewW, viewH, false);
  renderer.setClearColor(0x000000, 0);

  // ---- Nodes (Points) ----
  const nodeGeom = new BufferGeometry();
  nodeGeom.setAttribute('position', new Float32BufferAttribute(positions, 3));
  const nodeMat = new PointsMaterial({
    color: colors.node,
    size: NODE_SIZE_PX,
    sizeAttenuation: false,
    transparent: true,
    opacity: 0.85,
    depthWrite: false,
  });
  const points = new Points(nodeGeom, nodeMat);
  scene.add(points);

  // ---- Connections (LineSegments) ----
  // With 1500 nodes and link distance 55, average lines per node is
  // ~3-4, so total lines ~3000-4000. We allocate enough capacity.
  const MAX_LINES = NODE_COUNT * 4;
  const lineGeom = new BufferGeometry();
  const linePositions = new Float32Array(MAX_LINES * 6);
  const lineColors    = new Float32Array(MAX_LINES * 6);
  lineGeom.setAttribute('position', new Float32BufferAttribute(linePositions, 3));
  lineGeom.setAttribute('color',    new Float32BufferAttribute(lineColors, 3));
  lineGeom.setDrawRange(0, 0);

  const lineMat = new LineBasicMaterial({
    vertexColors: true,
    transparent: true,
    opacity: 0.7,
    depthWrite: false,
  });
  const lines = new LineSegments(lineGeom, lineMat);
  scene.add(lines);

  // ---- Mouse state ----
  const pointer = { x: -9999, y: -9999, active: false };

  function onPointerMove(e) {
    pointer.x = e.clientX;
    pointer.y = e.clientY;
    pointer.active = true;
  }
  function onPointerLeave() {
    pointer.active = false;
    pointer.x = -9999;
    pointer.y = -9999;
  }
  window.addEventListener('pointermove', onPointerMove, { passive: true });
  window.addEventListener('mousemove', onPointerMove, { passive: true });
  window.addEventListener('pointerleave', onPointerLeave, { passive: true });
  document.addEventListener('mouseleave', onPointerLeave, { passive: true });

  // ---- Node motion ----
  function updateNodes(scale) {
    const cx = viewW * 0.5;
    const cy = viewH * 0.5;
    const pX = pointer.x;
    const pY = pointer.y;
    const pActive = pointer.active;

    for (let i = 0; i < NODE_COUNT; i++) {
      const x = positions[i * 2];
      const y = positions[i * 2 + 1];

      // Random walk impulse
      velocities[i * 2]     += (Math.random() - 0.5) * DRIFT_SPEED * scale;
      velocities[i * 2 + 1] += (Math.random() - 0.5) * DRIFT_SPEED * scale;

      // Soft attractor toward viewport center
      velocities[i * 2]     += (cx - x) * RECENTER_FORCE * scale;
      velocities[i * 2 + 1] += (cy - y) * RECENTER_FORCE * scale;

      // Cursor repulsion
      if (pActive) {
        const dx = x - pX, dy = y - pY;
        const d2 = dx*dx + dy*dy;
        if (d2 < MOUSE_RADIUS_PX * MOUSE_RADIUS_PX && d2 > 0.01) {
          const d = Math.sqrt(d2);
          const falloff = 1 - d / MOUSE_RADIUS_PX;
          const force = MOUSE_FORCE * falloff / d * scale;
          velocities[i * 2]     += dx * force;
          velocities[i * 2 + 1] += dy * force;
        }
      }

      // Damping
      const damp = Math.pow(DAMPING, scale);
      velocities[i * 2]     *= damp;
      velocities[i * 2 + 1] *= damp;

      // Speed clamp
      const speed = Math.sqrt(
        velocities[i*2]*velocities[i*2] +
        velocities[i*2+1]*velocities[i*2+1]
      );
      if (speed > MAX_SPEED) {
        const s = MAX_SPEED / speed;
        velocities[i * 2]     *= s;
        velocities[i * 2 + 1] *= s;
      }

      // Integrate
      let nx = x + velocities[i * 2];
      let ny = y + velocities[i * 2 + 1];

      // Wrap softly at viewport edges
      const margin = 40;
      if (nx < -margin)        nx = viewW + margin;
      else if (nx > viewW + margin) nx = -margin;
      if (ny < -margin)        ny = viewH + margin;
      else if (ny > viewH + margin) ny = -margin;

      positions[i * 2]     = nx;
      positions[i * 2 + 1] = ny;
    }
    nodeGeom.attributes.position.needsUpdate = true;
  }

  // ---- Connection rebuild ----
  let lineCount = 0;

  function rebuildConnections() {
    const ld2 = LINK_DIST_PX * LINK_DIST_PX;
    let p = 0;
    for (let i = 0; i < NODE_COUNT; i++) {
      const ix = positions[i * 2];
      const iy = positions[i * 2 + 1];
      for (let j = i + 1; j < NODE_COUNT; j++) {
        const dx = ix - positions[j * 2];
        const dy = iy - positions[j * 2 + 1];
        const d2 = dx*dx + dy*dy;
        if (d2 < ld2) {
          if (p >= MAX_LINES) break;  // safety guard
          linePositions[p * 6]     = ix;
          linePositions[p * 6 + 1] = iy;
          linePositions[p * 6 + 2] = 0;
          linePositions[p * 6 + 3] = positions[j * 2];
          linePositions[p * 6 + 4] = positions[j * 2 + 1];
          linePositions[p * 6 + 5] = 0;
          p++;
        }
      }
      if (p >= MAX_LINES) break;
    }
    lineCount = p;
    lineGeom.setDrawRange(0, p * 2);
    lineGeom.attributes.position.needsUpdate = true;
  }

  // ---- Per-vertex line color ----
  // Each line endpoint is colored: closer to the pointer = brighter.
  // The pow(glow, 0.7) softens the falloff so the glow is visible
  // over a wider area around the cursor.
  function colorConnections() {
    const pX = pointer.x;
    const pY = pointer.y;
    const pActive = pointer.active;
    const influence = MOUSE_RADIUS_PX * 1.4;

    for (let i = 0; i < lineCount; i++) {
      const ax = linePositions[i * 6],     ay = linePositions[i * 6 + 1];
      const bx = linePositions[i * 6 + 3], by = linePositions[i * 6 + 4];

      const dA = pActive ? Math.hypot(ax - pX, ay - pY) : Infinity;
      const dB = pActive ? Math.hypot(bx - pX, by - pY) : Infinity;
      const glowA = pActive ? Math.max(0, 1 - dA / influence) : 0;
      const glowB = pActive ? Math.max(0, 1 - dB / influence) : 0;

      const ga = Math.pow(glowA, 0.7);
      const gb = Math.pow(glowB, 0.7);
      const rA = colors.line.r * 0.4 + colors.glow.r * ga;
      const gA = colors.line.g * 0.4 + colors.glow.g * ga;
      const bA = colors.line.b * 0.4 + colors.glow.b * ga;
      const rB = colors.line.r * 0.4 + colors.glow.r * gb;
      const gB = colors.line.g * 0.4 + colors.glow.g * gb;
      const bB = colors.line.b * 0.4 + colors.glow.b * gb;

      lineColors[i * 6]     = rA;
      lineColors[i * 6 + 1] = gA;
      lineColors[i * 6 + 2] = bA;
      lineColors[i * 6 + 3] = rB;
      lineColors[i * 6 + 4] = gB;
      lineColors[i * 6 + 5] = bB;
    }
    lineGeom.attributes.color.needsUpdate = true;
  }

  // ---- Render loop ----
  let raf = 0;
  let lastT = performance.now();
  let frame = 0;

  function tick(now) {
    const dt = Math.min((now - lastT) / 1000, 0.05);
    lastT = now;
    frame++;

    const scale = dt * 60;
    updateNodes(scale);
    if (frame % CONNECT_REBUILD === 0) rebuildConnections();
    colorConnections();

    renderer.render(scene, camera);
    raf = requestAnimationFrame(tick);
  }
  raf = requestAnimationFrame(tick);

  // ---- Resize ----
  let resizeTimer = 0;
  function onResize() {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      viewW = window.innerWidth;
      viewH = window.innerHeight;
      camera.left = 0;
      camera.right = viewW;
      camera.top = viewH;
      camera.bottom = 0;
      camera.updateProjectionMatrix();
      renderer.setSize(viewW, viewH, false);
      seedNodes();
    }, 120);
  }
  window.addEventListener('resize', onResize, { passive: true });

  // ---- Pause when hidden ----
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      cancelAnimationFrame(raf);
    } else {
      lastT = performance.now();
      raf = requestAnimationFrame(tick);
    }
  });

  // ---- Watch for theme toggles ----
  const themeObserver = new MutationObserver(() => {
    const nowDark = document.documentElement.getAttribute('data-theme') === 'dark';
    if (nowDark === isDark) return;
    isDark = nowDark;
    colors = pickColors(isDark);
    nodeMat.color.copy(colors.node);
    nodeMat.needsUpdate = true;
  });
  themeObserver.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-theme'],
  });
})();
