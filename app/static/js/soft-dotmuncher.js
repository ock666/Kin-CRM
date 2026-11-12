/* Dot Muncher — a cozy Pac-Man-style maze chase for Kin's regulation toolkit.
 *
 * Classic mechanics (score, three lives, four ghosts, power pellets) but kept
 * warm: gentle copy, muted palette, and a pace that never turns punishing.
 * The maze is authored as its left half and mirrored at load so it stays
 * perfectly symmetrical.
 */
(function () {
  "use strict";

  var root = document.getElementById("game-root");
  if (!root) return;

  // ------------------------------------------------------------------ maze
  // Left half: 11 columns x 23 rows. # wall, . dot, o power pellet,
  // ' ' empty walkable, - ghost door, G ghost-house interior.
  var LH = [
    "###########",
    "#..........",
    "#.###.###.#",
    "#o#...#...#",
    "#.#.###.#.#",
    "#.#.#...#.#",
    "#.#.#.#.#.#",
    "#...#.#.#.#",
    "###.#.#....",
    "#...#.#.##-",
    "#.#.#.#.#GG",
    " ...#.#.#GG",
    "#.#.#.#.#GG",
    "#.#.#.#.###",
    "#.#.#......",
    "#.#.#####..",
    "#..........",
    "#.###.###.#",
    "#o#...#...#",
    "#.#.#.#.#.#",
    "#..........",
    "#.........#",
    "###########"
  ];
  var W = 21, H = 23, TUNNEL = 11;
  var grid = [];
  for (var y = 0; y < H; y++) {
    var r = LH[y], full = r;
    for (var x = r.length - 2; x >= 0; x--) full += r[x];
    grid.push(full.split(""));
  }

  var startTile = { x: 10, y: 20 };
  var doorTile = { x: 10, y: 9 };
  var aboveDoor = { x: 10, y: 8 };
  var fruitTile = { x: 10, y: 16 };

  // ------------------------------------------------------------------ DOM
  root.innerHTML =
    '<div class="card" style="text-align:center;">' +
      '<div class="dm-hud">' +
        '<span class="text-sm text-muted">score <strong id="dm-score">0</strong></span>' +
        '<span class="text-sm text-muted">level <strong id="dm-level">1</strong></span>' +
        '<span class="text-sm text-muted">lives <strong id="dm-lives">🟡 3</strong></span>' +
      '</div>' +
      '<p id="dm-status" class="text-sm text-muted mb-1" aria-live="polite"></p>' +
      '<canvas id="dm-canvas" aria-label="Dot Muncher maze"></canvas>' +
      '<div class="dm-controls" id="dm-controls" style="display:none;">' +
        '<button type="button" data-dm="up" style="grid-column:2;grid-row:1;" aria-label="Up" title="Up">↑</button>' +
        '<button type="button" data-dm="left" style="grid-column:1;grid-row:2;" aria-label="Left" title="Left">←</button>' +
        '<button type="button" data-dm="down" style="grid-column:2;grid-row:2;" aria-label="Down" title="Down">↓</button>' +
        '<button type="button" data-dm="right" style="grid-column:3;grid-row:2;" aria-label="Right" title="Right">→</button>' +
      '</div>' +
      '<button id="dm-start" class="btn btn-sm btn-primary" type="button">Start</button>' +
      '<p class="help-text mt-1 mb-0">Keys: ← ↑ ↓ → or WASD to move · p or esc to pause</p>' +
    '</div>';

  var canvas = document.getElementById("dm-canvas");
  var scoreEl = document.getElementById("dm-score");
  var levelEl = document.getElementById("dm-level");
  var livesEl = document.getElementById("dm-lives");
  var statusEl = document.getElementById("dm-status");
  var startBtn = document.getElementById("dm-start");
  var controlsEl = document.getElementById("dm-controls");
  var ctx = canvas.getContext("2d");

  // ------------------------------------------------------------------ theme
  var C = {
    wall: "#5b6d9e",
    wallEdge: "#7385bb",
    dot: "#d8c9a8",
    power: "#e6c56b",
    pac: "#f0c75e",
    ghost: { blinky: "#e28a7b", pinky: "#d9a0c9", inky: "#8fb4e8", clyde: "#e6b96a" },
    fright: "#7f9fd9",
    frightFlash: "#e2d8f0",
    eye: "#f5efe2",
    pupil: "#2b2b3a",
    fruit: "#e2788a"
  };

  var reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ------------------------------------------------------------------ state
  var score = 0, lives = 3, level = 1;
  var state = "ready"; // ready | playing | paused | dying | levelclear | gameover
  var dotsLeft = 0, totalDots = 0;
  var frightened = 0;
  var ghostChain = 0;
  var fruit = { active: false, timer: 0, eaten: false };
  var fruitTriggers = [];
  var deathTimer = 0, levelclearTimer = 0;
  var modeTimer = 7, modeIsScatter = true;
  var nowMs = 0, last = 0;

  var pacman = null, ghosts = [];

  // ------------------------------------------------------------------ helpers
  var DIR = {
    UP: { x: 0, y: -1 }, DOWN: { x: 0, y: 1 },
    LEFT: { x: -1, y: 0 }, RIGHT: { x: 1, y: 0 }
  };
  var DIRS = [DIR.UP, DIR.DOWN, DIR.LEFT, DIR.RIGHT];

  function isWall(x, y) { return grid[y][x] === "#"; }
  function pacOK(x, y) { var t = grid[y][x]; return t !== "#" && t !== "-" && t !== "G"; }
  function ghostOK(x, y) { return grid[y][x] !== "#"; }
  function tileAt(t, dir) {
    if (!dir) return { x: t.x, y: t.y };
    var nx = t.x + dir.x, ny = t.y + dir.y;
    if (ny === TUNNEL) {
      if (nx < 0) nx = W - 1;
      else if (nx >= W) nx = 0;
    }
    return { x: nx, y: ny };
  }
  function reverse(d) { return d ? { x: -d.x, y: -d.y } : null; }
  function isReverse(a, b) { return a && b && a.x === -b.x && a.y === -b.y; }

  function makeEnt(x, y) {
    return { tx: x, ty: y, x: x, y: y, dir: null, nextDir: null, progress: 0, speed: 0 };
  }
  function makeGhost(name, x, y) {
    var g = makeEnt(x, y);
    g.name = name;
    g.color = C.ghost[name];
    g.mode = "house";
    g.exitDelay = 0;
    g.elapsed = 0;
    g.corner = {
      blinky: { x: W - 2, y: 1 }, pinky: { x: 1, y: 1 },
      inky: { x: W - 2, y: H - 2 }, clyde: { x: 1, y: H - 2 }
    }[name];
    return g;
  }

  function pacSpeed() { return Math.min(9.5, 6.5 + (level - 1) * 0.45); }
  function ghostSpeed() { return Math.min(8.6, 6.0 + (level - 1) * 0.4); }
  function frightSpeed() { return 3.2; }
  function eatenSpeed() { return 14; }
  function frightTime() { return Math.max(2.5, 7.5 - (level - 1) * 0.5); }

  // ------------------------------------------------------------------ dots / fruit
  function resetDots() {
    dotsLeft = 0; totalDots = 0;
    for (var y = 0; y < H; y++) for (var x = 0; x < W; x++) {
      if (grid[y][x] === "." || grid[y][x] === "o") { dotsLeft++; totalDots++; }
    }
    var third = Math.floor(totalDots / 3);
    fruitTriggers = [third, third * 2];
    fruit = { active: false, timer: 0, eaten: false };
  }

  function resetPositions() {
    pacman = makeEnt(startTile.x, startTile.y);
    ghosts = [
      makeGhost("blinky", 10, 10),
      makeGhost("pinky", 9, 11),
      makeGhost("inky", 11, 11),
      makeGhost("clyde", 10, 12)
    ];
    ghosts[0].mode = "exiting"; ghosts[0].exitDelay = 0;
    ghosts[1].exitDelay = 1.5;
    ghosts[2].exitDelay = 3.5;
    ghosts[3].exitDelay = 6;
    for (var i = 0; i < ghosts.length; i++) { ghosts[i].dir = DIR.UP; ghosts[i].elapsed = 0; }
    frightened = 0; ghostChain = 0;
    modeTimer = 7; modeIsScatter = true;
  }

  // ------------------------------------------------------------------ flow
  function startGame() {
    score = 0; lives = 3; level = 1;
    resetDots();
    resetPositions();
    state = "playing";
    startBtn.style.display = "none";
    controlsEl.style.display = "grid";
    setStatus("Go — eat the dots, dodge the ghosts. 🟡");
    updateHUD();
  }

  function startLevel() {
    resetDots();
    resetPositions();
    state = "playing";
    setStatus("Level " + level + " — a touch quicker now.");
    updateHUD();
  }

  function die() {
    if (state !== "playing") return;
    state = "dying";
    deathTimer = 1.4;
    setStatus("Caught — no worries, again when you're ready.");
  }

  function levelClear() {
    if (state !== "playing") return;
    state = "levelclear";
    levelclearTimer = 2.0;
    setStatus("Maze cleared — lovely! On to the next.");
  }

  function gameOver() {
    state = "gameover";
    startBtn.textContent = "Play again";
    startBtn.style.display = "";
    controlsEl.style.display = "none";
    setStatus("That's the run — " + score + " points. Play again whenever you like.");
  }

  function setStatus(msg) { statusEl.textContent = msg; }
  function addScore(n) { score += n; updateHUD(); }

  function updateHUD() {
    scoreEl.textContent = score;
    levelEl.textContent = level;
    livesEl.textContent = lives > 0 ? "🟡 " + lives : "—";
  }

  function togglePause() {
    if (state === "playing") { state = "paused"; setStatus("⏸ paused — press p or esc to resume"); }
    else if (state === "paused") { state = "playing"; setStatus(""); }
  }

  // ------------------------------------------------------------------ eating
  function eatTile(x, y) {
    var t = grid[y][x];
    if (t === ".") {
      grid[y][x] = " ";
      dotsLeft--; addScore(10);
      maybeSpawnFruit();
      if (dotsLeft === 0) levelClear();
    } else if (t === "o") {
      grid[y][x] = " ";
      dotsLeft--; addScore(50);
      frightened = frightTime();
      ghostChain = 0;
      for (var i = 0; i < ghosts.length; i++) {
        var g = ghosts[i];
        if (g.mode === "chase" || g.mode === "scatter") { g.mode = "frightened"; reverseGhost(g); }
      }
      if (dotsLeft === 0) levelClear();
    }
  }

  function maybeSpawnFruit() {
    var eaten = totalDots - dotsLeft;
    if (fruitTriggers.length && eaten >= fruitTriggers[0]) {
      fruitTriggers.shift();
      fruit = { active: true, timer: 9, eaten: false };
    }
  }

  function reverseGhost(g) {
    g.dir = reverse(g.dir);
    g.progress = 0;
    g.x = g.tx; g.y = g.ty;
  }

  // ------------------------------------------------------------------ ghost AI
  function ghostTarget(g) {
    if (g.mode === "exiting") {
      return (g.tx === doorTile.x && g.ty === doorTile.y) ? aboveDoor : doorTile;
    }
    if (g.mode === "eaten") return doorTile;
    if (g.mode === "scatter") return g.corner;
    if (g.mode === "chase") {
      var d = pacman.dir || DIR.LEFT;
      if (g.name === "blinky") return { x: pacman.tx, y: pacman.ty };
      if (g.name === "pinky") return { x: pacman.tx + d.x * 4, y: pacman.ty + d.y * 4 };
      if (g.name === "inky") {
        var pivot = { x: pacman.tx + d.x * 2, y: pacman.ty + d.y * 2 };
        var b = ghosts[0];
        return { x: pivot.x * 2 - b.tx, y: pivot.y * 2 - b.ty };
      }
      if (g.name === "clyde") {
        var dist = Math.abs(g.tx - pacman.tx) + Math.abs(g.ty - pacman.ty);
        return dist > 8 ? { x: pacman.tx, y: pacman.ty } : g.corner;
      }
    }
    return g.corner;
  }

  function ghostDecide(g) {
    var target = ghostTarget(g);
    var allowReverse = (g.mode === "exiting" || g.mode === "eaten" || g.mode === "house");
    var frightenedMove = (g.mode === "frightened");
    var options = [];
    for (var i = 0; i < DIRS.length; i++) {
      var d = DIRS[i];
      var nt = tileAt({ x: g.tx, y: g.ty }, d);
      if (!ghostOK(nt.x, nt.y)) continue;
      if (isReverse(d, g.dir) && !allowReverse) continue;
      if (frightenedMove) options.push(d);
      else {
        var dx = nt.x - target.x, dy = nt.y - target.y;
        options.push({ d: d, dist: dx * dx + dy * dy });
      }
    }
    if (!options.length) {
      var rd = reverse(g.dir);
      if (rd && ghostOK(tileAt({ x: g.tx, y: g.ty }, rd).x, tileAt({ x: g.tx, y: g.ty }, rd).y)) g.dir = rd;
      return;
    }
    if (frightenedMove) g.dir = options[Math.floor(Math.random() * options.length)];
    else {
      options.sort(function (a, b) { return a.dist - b.dist; });
      g.dir = options[0].d;
    }
  }

  // ------------------------------------------------------------------ movement
  function moveEntity(e, dt, speed, canEnter, onArrive) {
    e.progress += speed * dt;
    while (e.progress >= 1 && e.dir) {
      e.progress -= 1;
      var nt = tileAt(e, e.dir);
      if (!canEnter(nt.x, nt.y)) {
        e.progress = 0; e.dir = null; e.x = e.tx; e.y = e.ty;
        if (onArrive) onArrive();
        return;
      }
      e.tx = nt.x; e.ty = nt.y;
      if (onArrive) onArrive();
      if (!e.dir) break;
    }
    e.x = e.tx + (e.dir ? e.dir.x : 0) * e.progress;
    e.y = e.ty + (e.dir ? e.dir.y : 0) * e.progress;
  }

  function pacmanDecide() {
    if (pacman.nextDir) {
      var nt = tileAt(pacman, pacman.nextDir);
      if (pacOK(nt.x, nt.y)) { pacman.dir = pacman.nextDir; pacman.nextDir = null; return; }
    }
    var ct = tileAt(pacman, pacman.dir);
    if (!pacOK(ct.x, ct.y)) pacman.dir = null;
  }

  function stepPacman(dt) {
    pacman.speed = pacSpeed();
    if (!pacman.dir) {
      if (pacman.nextDir) {
        var t = tileAt(pacman, pacman.nextDir);
        if (pacOK(t.x, t.y)) { pacman.dir = pacman.nextDir; pacman.nextDir = null; }
      }
      if (!pacman.dir) return;
    }
    moveEntity(pacman, dt, pacman.speed, pacOK, function () {
      eatTile(pacman.tx, pacman.ty);
      pacmanDecide();
    });
  }

  function stepGhosts(dt) {
    for (var i = 0; i < ghosts.length; i++) {
      var g = ghosts[i];
      g.elapsed += dt;
      if (g.mode === "house") {
        if (g.elapsed >= g.exitDelay) { g.mode = "exiting"; }
        else {
          var nt = tileAt(g, g.dir);
          if (!(ghostOK(nt.x, nt.y) && nt.y >= 10 && nt.y <= 12)) g.dir = reverse(g.dir);
          moveEntity(g, dt, 3.0, ghostOK, null);
          continue;
        }
      }
      if (g.mode === "frightened") g.speed = frightSpeed();
      else if (g.mode === "eaten") g.speed = eatenSpeed();
      else g.speed = ghostSpeed();
      if (!g.dir) g.dir = DIR.UP;
      moveEntity(g, dt, g.speed, ghostOK, function () {
        if (g.mode === "exiting" && g.tx === aboveDoor.x && g.ty === aboveDoor.y) {
          g.mode = modeIsScatter ? "scatter" : "chase";
        }
        if (g.mode === "eaten" && g.tx === doorTile.x && g.ty === doorTile.y) {
          g.mode = "exiting";
          g.tx = 10; g.ty = 11; g.x = 10; g.y = 11; g.progress = 0; g.dir = DIR.UP;
        }
        ghostDecide(g);
      });
    }
  }

  function collide() {
    for (var i = 0; i < ghosts.length; i++) {
      var g = ghosts[i];
      if (g.mode === "house" || g.mode === "eaten") continue;
      var dy = Math.abs(g.y - pacman.y);
      var dx = Math.abs(g.x - pacman.x);
      if (g.ty === TUNNEL && pacman.ty === TUNNEL) dx = Math.min(dx, W - dx);
      if (dx < 0.6 && dy < 0.6) {
        if (g.mode === "frightened") eatGhost(g);
        else die();
        return;
      }
    }
  }

  function eatGhost(g) {
    ghostChain++;
    var points = 200 * Math.pow(2, ghostChain - 1);
    addScore(points);
    g.mode = "eaten";
    setStatus("👻 " + points + "!");
  }

  // ------------------------------------------------------------------ loop
  function frame(now) {
    if (!last) last = now;
    var dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    nowMs = now;

    if (state === "playing") {
      stepPacman(dt);
      stepGhosts(dt);

      modeTimer -= dt;
      if (modeTimer <= 0) {
        modeIsScatter = !modeIsScatter;
        modeTimer = modeIsScatter ? 7 : 20;
        for (var i = 0; i < ghosts.length; i++) {
          var g = ghosts[i];
          if (g.mode === "chase" || g.mode === "scatter") {
            g.mode = modeIsScatter ? "scatter" : "chase";
            reverseGhost(g);
          }
        }
      }

      if (frightened > 0) {
        frightened -= dt;
        if (frightened <= 0) {
          frightened = 0;
          for (var j = 0; j < ghosts.length; j++) {
            var gg = ghosts[j];
            if (gg.mode === "frightened") gg.mode = modeIsScatter ? "scatter" : "chase";
          }
          ghostChain = 0;
        }
      }

      if (fruit.active && !fruit.eaten) {
        fruit.timer -= dt;
        if (fruit.timer <= 0) fruit.active = false;
        else if (pacman.tx === fruitTile.x && pacman.ty === fruitTile.y) {
          addScore(100); fruit.eaten = true; fruit.active = false;
          setStatus("🍒 cherry — +100");
        }
      }

      collide();
    } else if (state === "dying") {
      deathTimer -= dt;
      if (deathTimer <= 0) {
        lives--;
        updateHUD();
        if (lives <= 0) gameOver();
        else { resetPositions(); state = "playing"; setStatus(""); }
      }
    } else if (state === "levelclear") {
      levelclearTimer -= dt;
      if (levelclearTimer <= 0) { level++; startLevel(); }
    }

    draw();
    requestAnimationFrame(frame);
  }

  // ------------------------------------------------------------------ rendering
  var cell = 16;

  function resize() {
    var avail = root.clientWidth - 4;
    if (!avail || avail < 1) avail = Math.min(400, window.innerWidth - 24);
    cell = Math.floor(avail / W);
    if (cell < 7) cell = 7;
    if (cell > 20) cell = 20;
    var dpr = window.devicePixelRatio || 1;
    var w = cell * W, h = cell * H;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function roundedRect(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }

  function draw() {
    ctx.clearRect(0, 0, cell * W, cell * H);

    // walls + dots
    var pulse = reducedMotion ? 1 : (0.9 + 0.15 * Math.sin(nowMs / 250));
    for (var y = 0; y < H; y++) {
      for (var x = 0; x < W; x++) {
        var t = grid[y][x];
        var px = x * cell, py = y * cell;
        if (t === "#") {
          ctx.fillStyle = C.wall;
          roundedRect(px + 0.5, py + 0.5, cell - 1, cell - 1, cell * 0.28);
          ctx.fill();
          ctx.fillStyle = "rgba(255,255,255,0.07)";
          roundedRect(px + 1.5, py + 1.5, cell - 3, Math.max(1, cell * 0.28), cell * 0.2);
          ctx.fill();
        } else if (t === ".") {
          ctx.fillStyle = C.dot;
          ctx.beginPath();
          ctx.arc(px + cell / 2, py + cell / 2, cell * 0.13, 0, Math.PI * 2);
          ctx.fill();
        } else if (t === "o") {
          ctx.fillStyle = C.power;
          ctx.beginPath();
          ctx.arc(px + cell / 2, py + cell / 2, cell * 0.3 * pulse, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }

    drawFruit();
    for (var i = 0; i < ghosts.length; i++) drawGhost(ghosts[i]);
    drawPacman();
  }

  function drawFruit() {
    if (!fruit.active || fruit.eaten) return;
    var cx = fruitTile.x * cell + cell / 2, cy = fruitTile.y * cell + cell / 2;
    var r = cell * 0.28;
    ctx.strokeStyle = "#7fb98a";
    ctx.lineWidth = Math.max(1, cell * 0.08);
    ctx.beginPath();
    ctx.moveTo(cx, cy - r * 0.9);
    ctx.quadraticCurveTo(cx + r * 0.5, cy - r * 1.5, cx + r * 0.2, cy - r * 1.7);
    ctx.stroke();
    ctx.fillStyle = C.fruit;
    ctx.beginPath();
    ctx.arc(cx - r * 0.45, cy, r * 0.6, 0, Math.PI * 2);
    ctx.arc(cx + r * 0.45, cy, r * 0.6, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "rgba(255,255,255,0.35)";
    ctx.beginPath();
    ctx.arc(cx - r * 0.55, cy - r * 0.2, r * 0.16, 0, Math.PI * 2);
    ctx.fill();
  }

  function drawGhost(g) {
    var xs = [g.x];
    if (g.ty === TUNNEL) xs.push(g.x < W / 2 ? g.x + W : g.x - W);
    for (var k = 0; k < xs.length; k++) drawGhostAt(g, xs[k], g.y);
  }

  function drawGhostAt(g, x, y) {
    var cx = x * cell + cell / 2, cy = y * cell + cell / 2;
    var r = cell * 0.44;
    if (g.mode === "eaten") { drawGhostEyes(g, cx, cy, r); return; }
    var bodyColor;
    if (g.mode === "frightened") {
      var flash = frightened < 2.5 && Math.floor(nowMs / 200) % 2 === 0;
      bodyColor = flash ? C.frightFlash : C.fright;
    } else bodyColor = g.color;

    ctx.fillStyle = bodyColor;
    ctx.beginPath();
    ctx.arc(cx, cy - r * 0.25, r, Math.PI, 0);
    ctx.lineTo(cx + r, cy + r * 0.85);
    var teeth = 3, seg = (2 * r) / teeth;
    for (var i = 0; i < teeth; i++) {
      ctx.lineTo(cx + r - (i + 0.5) * seg, cy + r * 0.55);
      ctx.lineTo(cx + r - (i + 1) * seg, cy + r * 0.85);
    }
    ctx.closePath();
    ctx.fill();

    if (g.mode === "frightened") drawFrightFace(cx, cy, r);
    else drawGhostEyes(g, cx, cy, r);
  }

  function drawGhostEyes(g, cx, cy, r) {
    var d = g.dir || DIR.UP;
    var ex = d.x * r * 0.16, ey = d.y * r * 0.16;
    var eyeR = r * 0.26, off = r * 0.3, y = cy - r * 0.16;
    for (var s = -1; s <= 1; s += 2) {
      var exx = cx + s * off;
      ctx.fillStyle = C.eye;
      ctx.beginPath();
      ctx.ellipse(exx, y, eyeR, eyeR * 1.15, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = C.pupil;
      ctx.beginPath();
      ctx.arc(exx + ex, y + ey * 0.6, eyeR * 0.5, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  function drawFrightFace(cx, cy, r) {
    ctx.fillStyle = "#f0e6d2";
    var eyeR = r * 0.14, off = r * 0.3, y = cy - r * 0.1;
    ctx.beginPath();
    ctx.arc(cx - off, y, eyeR, 0, Math.PI * 2);
    ctx.arc(cx + off, y, eyeR, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "#f0e6d2";
    ctx.lineWidth = Math.max(1, r * 0.08);
    ctx.beginPath();
    var mx = cx - r * 0.45, my = cy + r * 0.35;
    ctx.moveTo(mx, my);
    for (var i = 0; i < 4; i++) {
      ctx.lineTo(mx + r * 0.22, my - r * 0.18);
      ctx.lineTo(mx + r * 0.45, my);
      mx += r * 0.45;
    }
    ctx.stroke();
  }

  function drawPacman() {
    var xs = [pacman.x];
    if (pacman.ty === TUNNEL) xs.push(pacman.x < W / 2 ? pacman.x + W : pacman.x - W);
    for (var k = 0; k < xs.length; k++) drawPacmanAt(xs[k], pacman.y);
  }

  function drawPacmanAt(x, y) {
    var cx = x * cell + cell / 2, cy = y * cell + cell / 2;
    var r = cell * 0.42;
    var d = pacman.dir || DIR.LEFT;
    var base = Math.atan2(d.y, d.x);
    var mouth;
    if (state === "dying") {
      var p = 1 - deathTimer / 1.4;
      if (p < 0.5) mouth = (p / 0.5) * Math.PI * 2;
      else { mouth = Math.PI * 2; r = cell * 0.42 * (1 - (p - 0.5) / 0.5); }
    } else {
      mouth = reducedMotion ? Math.PI * 0.35 : (0.2 + 0.5 * Math.abs(Math.sin(nowMs / 140))) * Math.PI;
    }
    ctx.fillStyle = C.pac;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, r, base + mouth / 2, base - mouth / 2 + Math.PI * 2);
    ctx.closePath();
    ctx.fill();
  }

  // ------------------------------------------------------------------ input
  function setDir(d) {
    if (state === "ready" || state === "gameover") startGame();
    pacman.nextDir = d;
  }

  function keydown(ev) {
    var k = ev.key;
    var d = null;
    if (k === "ArrowLeft" || k === "a" || k === "A") d = DIR.LEFT;
    else if (k === "ArrowRight" || k === "d" || k === "D") d = DIR.RIGHT;
    else if (k === "ArrowUp" || k === "w" || k === "W") d = DIR.UP;
    else if (k === "ArrowDown" || k === "s" || k === "S") d = DIR.DOWN;
    if (d) { ev.preventDefault(); setDir(d); return; }
    if (k === "p" || k === "P" || k === "Escape") { ev.preventDefault(); togglePause(); }
    else if (k === " " || k === "Enter") {
      ev.preventDefault();
      if (state === "ready" || state === "gameover") startGame();
      else if (state === "paused") togglePause();
    }
  }

  function bindTouch(el) {
    var action = el.getAttribute("data-dm");
    var dmap = { up: DIR.UP, down: DIR.DOWN, left: DIR.LEFT, right: DIR.RIGHT };
    var fire = function (e) {
      if (e.preventDefault) e.preventDefault();
      setDir(dmap[action]);
    };
    if (window.PointerEvent) el.addEventListener("pointerdown", fire, false);
    else {
      el.addEventListener("mousedown", fire, false);
      el.addEventListener("touchstart", fire, { passive: false });
    }
  }

  // ------------------------------------------------------------------ init
  startBtn.addEventListener("click", startGame, false);
  document.addEventListener("keydown", keydown, false);
  window.addEventListener("resize", resize, false);
  var touchBtns = controlsEl.querySelectorAll("[data-dm]");
  for (var i = 0; i < touchBtns.length; i++) bindTouch(touchBtns[i]);

  resetDots();
  resetPositions();
  resize();
  draw();
  requestAnimationFrame(frame);
})();
