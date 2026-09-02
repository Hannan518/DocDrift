// Interactive neural-network "node field" background.
// Inspired by the Framer Node Field: small distinct nodes connected
// by subtle lines, all slowly drifting, with mouse repulsion that
// brightens the local network. Designed to read clearly on BOTH light
// and dark backgrounds: we use NormalBlending with theme-aware colors
// (not AdditiveBlending) so the line color reads as a soft accent
// tone on white and as a gentle glow on black.
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

  const { Scene, PerspectiveCamera, WebGLRenderer, BufferGeometry, Float32BufferAttribute,
          LineSegments, LineBasicMaterial, Points, PointsMaterial,
          NormalBlending, Vector2, Vector3, Color } = THREE;

  // ---- Configuration ----
  const NODE_COUNT     = 90;     // node count
  const SPREAD         = 8.0;    // world extent
  const LINK_DIST      = 1.45;   // link distance (the "net" density)
  const MOUSE_RADIUS   = 2.0;    // how far the mouse effect reaches
  const MOUSE_FORCE    = 0.5;    // how hard nodes get pushed
  const DRIFT_SPEED    = 0.04;   // base random-walk speed
  const RECENTER_FORCE = 0.015;  // soft pull toward origin
  const NODE_SIZE_PX   = 5.5;    // visible distinct dot

  // ---- Theme-aware colors ----
  // Read CSS variables and pick the right pair: on a light background,
  // the line must be DARKER than the bg to be visible; on a dark bg,
  // it must be LIGHTER. We don't use AdditiveBlending for lines because
  // that produces white on white (invisible) on light bgs.
  const cssVar = (name) => getComputedStyle(document.documentElement)
    .getPropertyValue(name).trim();

  let isDark = document.documentElement.getAttribute('data-theme') === 'dark';

  // Base line color: subtle indigo on light, soft glow on dark
  const lineBase = isDark
    ? new Color(cssVar('--accent') || '#818cf8')  // darker accent color on light bg
    : new Color(cssVar('--accent') || '#4f46e5'); // brighter on dark
  // Node color: the bg-side color (so the dot core is visible against its bg)
  const nodeColor = isDark
    ? new Color(cssVar('--text') || '#e8eaf0')    // light dot on dark bg
    : new Color(cssVar('--text') || '#171a21');   // dark dot on light bg
  // Hover/glow color: bright accent (used for pointer proximity boost)
  const glowColor = isDark
    ? new Color('#c4b5fd')                          // bright purple on dark
    : new Color('#4338ca');                          // deep indigo on light

  // ---- Seed nodes in a soft sphere (slightly flattened on Y) ----
  const positions = new Float32Array(NODE_COUNT * 3);
  const velocities = new Float32Array(NODE_COUNT * 3);
  for (let i = 0; i < NODE_COUNT; i++) {
    const r = Math.cbrt(Math.random()) * SPREAD * 0.65;
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    positions[i * 3]     = r * Math.sin(phi) * Math.cos(theta);
    positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta) * 0.65;
    positions[i * 3 + 2] = r * Math.cos(phi);
  }

  // ---- Scene ----
  const scene = new Scene();
  const camera = new PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 100);
  camera.position.z = 7.5;

  const renderer = new WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
  renderer.setSize(window.innerWidth, window.innerHeight, false);
  renderer.setClearColor(0x000000, 0);

  // ---- Nodes (Points) ----
  // Use Points with sizeAttenuation:false so the dot is a fixed
  // pixel size regardless of zoom - looks like a clean dot in
  // both light and dark themes.
  const nodeGeom = new BufferGeometry();
  nodeGeom.setAttribute('position', new Float32BufferAttribute(positions, 3));
  const nodeMat = new PointsMaterial({
    color: nodeColor,
    size: NODE_SIZE_PX,
    sizeAttenuation: false,
    transparent: true,
    opacity: 0.95,
    depthWrite: false,
  });
  const points = new Points(nodeGeom, nodeMat);
  scene.add(points);

  // ---- Connections (LineSegments) ----
  // Pre-allocate worst-case capacity. Real line count varies.
  const MAX_LINES = NODE_COUNT * (NODE_COUNT - 1) / 2;
  const lineGeom = new BufferGeometry();
  const linePositions = new Float32Array(MAX_LINES * 6);
  const lineColors    = new Float32Array(MAX_LINES * 6);
  lineGeom.setAttribute('position', new Float32BufferAttribute(linePositions, 3));
  lineGeom.setAttribute('color',    new Float32BufferAttribute(lineColors, 3));
  lineGeom.setDrawRange(0, 0);

  const lineMat = new LineBasicMaterial({
    vertexColors: true,
    transparent: true,
    opacity: 0.9,            // overall material opacity (per-vertex color tints further)
    depthWrite: false,
  });
  const lines = new LineSegments(lineGeom, lineMat);
  scene.add(lines);

  // ---- Mouse state ----
  // Smoothly eased pointer projected to world space.
  const pointer = new Vector2(0, 0);
  const pointerTarget = new Vector2(0, 0);
  let pointerActive = false;
  const pointerWorld = new Vector3(0, 0, 0);

  window.addEventListener('pointermove', (e) => {
    const x = (e.clientX / window.innerWidth) * 2 - 1;
    const y = -((e.clientY / window.innerHeight) * 2 - 1);
    pointerTarget.set(x, y);
    pointerActive = true;
  }, { passive: true });
  document.addEventListener('mouseleave', () => { pointerActive = false; }, { passive: true });
  document.addEventListener('pointerleave', () => { pointerActive = false; }, { passive: true });

  // ---- Node motion ----
  function updateNodes(dt) {
    // Ease the pointer toward its target
    pointer.lerp(pointerTarget, 0.08);

    // Pointer projects into world space at z=0 for repulsion
    const px = pointer.x * 5.5;
    const py = pointer.y * 3.5;
    const pz = 0;

    for (let i = 0; i < NODE_COUNT; i++) {
      const x = positions[i * 3];
      const y = positions[i * 3 + 1];
      const z = positions[i * 3 + 2];

      // Random walk impulse
      velocities[i * 3]     += (Math.random() - 0.5) * DRIFT_SPEED * dt;
      velocities[i * 3 + 1] += (Math.random() - 0.5) * DRIFT_SPEED * dt;
      velocities[i * 3 + 2] += (Math.random() - 0.5) * DRIFT_SPEED * dt;

      // Soft attractor toward origin (so the field doesn't drift away)
      velocities[i * 3]     -= x * RECENTER_FORCE * dt;
      velocities[i * 3 + 1] -= y * RECENTER_FORCE * dt;
      velocities[i * 3 + 2] -= z * RECENTER_FORCE * dt;

      // Mouse repulsion - inverse-distance falloff
      if (pointerActive) {
        const dx = x - px, dy = y - py, dz = z - pz;
        const d2 = dx*dx + dy*dy + dz*dz;
        if (d2 < MOUSE_RADIUS * MOUSE_RADIUS && d2 > 0.0001) {
          const d = Math.sqrt(d2);
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

      // Speed clamp
      const speed = Math.sqrt(
        velocities[i*3]*velocities[i*3] +
        velocities[i*3+1]*velocities[i*3+1] +
        velocities[i*3+2]*velocities[i*3+2]
      );
      if (speed > 0.45) {
        const s = 0.45 / speed;
        velocities[i * 3]     *= s;
        velocities[i * 3 + 1] *= s;
        velocities[i * 3 + 2] *= s;
      }

      // Integrate
      positions[i * 3]     += velocities[i * 3]     * dt;
      positions[i * 3 + 1] += velocities[i * 3 + 1] * dt;
      positions[i * 3 + 2] += velocities[i * 3 + 2] * dt;

      // Soft world boundary - reflect back
      const r = Math.sqrt(
        positions[i*3]*positions[i*3] +
        positions[i*3+1]*positions[i*3+1] +
        positions[i*3+2]*positions[i*3+2]
      );
      if (r > SPREAD * 1.4) {
        const s = (SPREAD * 1.4) / r;
        positions[i * 3]     *= s;
        positions[i * 3 + 1] *= s;
        positions[i * 3 + 2] *= s;
        velocities[i * 3]     *= -0.4;
        velocities[i * 3 + 1] *= -0.4;
        velocities[i * 3 + 2] *= -0.4;
      }
    }
    nodeGeom.attributes.position.needsUpdate = true;
  }

  // ---- Rebuild connections ----
  // Only every 3rd frame - connections stay stable between rebuilds
  // (the user can't see a 50ms delay). Saves ~70% of the work.
  let lineCount = 0;
  const CONNECT_REBUILD = 3;

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
        const d2 = dx*dx + dy*dy + dz*dz;
        if (d2 < LINK_DIST * LINK_DIST) {
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

  // ---- Color the lines per frame ----
  // Each line's color is set per-vertex so we can have a brightness
  // gradient across the line (closer to the pointer = brighter, with
  // a subtle gradient between the two endpoints). This is what gives
  // the network its "firing" feel when the pointer hovers.
  function colorConnections() {
    pointerWorld.set(pointer.x * 5.5, pointer.y * 3.5, 0);

    for (let i = 0; i < lineCount; i++) {
      const ax = linePositions[i * 6],     ay = linePositions[i * 6 + 1], az = linePositions[i * 6 + 2];
      const bx = linePositions[i * 6 + 3], by = linePositions[i * 6 + 4], bz = linePositions[i * 6 + 5];

      // Midpoint distance to pointer (for the glow calculation)
      const mx = (ax + bx) * 0.5, my = (ay + by) * 0.5, mz = (az + bz) * 0.5;
      const dx = mx - pointerWorld.x, dy = my - pointerWorld.y, dz = mz - pointerWorld.z;
      const dPointer = Math.sqrt(dx*dx + dy*dy + dz*dz);

      // Per-endpoint distance to pointer (for the gradient effect)
      const dA = Math.sqrt(
        (ax - pointerWorld.x)**2 +
        (ay - pointerWorld.y)**2 +
        (az - pointerWorld.z)**2
      );
      const dB = Math.sqrt(
        (bx - pointerWorld.x)**2 +
        (by - pointerWorld.y)**2 +
        (bz - pointerWorld.z)**2
      );

      // Per-endpoint glow: 0 far from pointer, 1 right next to it
      const glowA = pointerActive ? Math.max(0, 1 - dA / (MOUSE_RADIUS * 1.3)) : 0;
      const glowB = pointerActive ? Math.max(0, 1 - dB / (MOUSE_RADIUS * 1.3)) : 0;

      // Base line opacity varies with how close the midpoint is -
      // farther lines are dimmer, closer lines are more visible.
      // This makes the network feel like it has depth.
      const distanceFade = Math.max(0.15, 1 - dPointer / (MOUSE_RADIUS * 2.5));

      // Color formula: base line color * distanceFade + glow color * glow
      // On both light and dark themes, the result is visible.
      const rA = (lineBase.r * distanceFade + glowColor.r * glowA);
      const gA = (lineBase.g * distanceFade + glowColor.g * glowA);
      const bA = (lineBase.b * distanceFade + glowColor.b * glowA);
      const rB = (lineBase.r * distanceFade + glowColor.r * glowB);
      const gB = (lineBase.g * distanceFade + glowColor.g * glowB);
      const bB = (lineBase.b * distanceFade + glowColor.b * glowB);

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

    updateNodes(dt * 60);
    if (frame % CONNECT_REBUILD === 0) rebuildConnections();
    colorConnections();

    // Subtle whole-field rotation - the network slowly turns
    lines.rotation.y = Math.sin(now / 9000) * 0.08;
    points.rotation.y = lines.rotation.y;
    lines.rotation.x = Math.cos(now / 12000) * 0.05;
    points.rotation.x = lines.rotation.x;

    renderer.render(scene, camera);
    raf = requestAnimationFrame(tick);
  }
  raf = requestAnimationFrame(tick);

  // ---- Resize ----
  let resizeTimer = 0;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight, false);
    }, 120);
  });

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
  // The toggle button sets data-theme on the html element. When that
  // changes, recompute colors and re-upload them to the GPU so the
  // background adapts without a reload.
  const themeObserver = new MutationObserver(() => {
    const nowDark = document.documentElement.getAttribute('data-theme') === 'dark';
    if (nowDark === isDark) return;
    // Theme flipped - re-read CSS vars and re-pick colors.
    // (We keep the same render loop; just update the color objects.)
    isDark = nowDark;
    const newAccent = new Color(cssVar('--accent') || (nowDark ? '#818cf8' : '#4f46e5'));
    const newText = new Color(cssVar('--text') || (nowDark ? '#e8eaf0' : '#171a21'));
    const newGlow = nowDark ? new Color('#c4b5fd') : new Color('#4338ca');
    lineBase.copy(newAccent);
    nodeColor.copy(newText);
    glowColor.copy(newGlow);
    nodeMat.color.copy(nodeColor);
    nodeMat.needsUpdate = true;
  });
  themeObserver.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-theme'],
  });
})();
