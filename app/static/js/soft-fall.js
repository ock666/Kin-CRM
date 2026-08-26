/* Soft Fall — a gentle falling-blocks puzzle for the Kin regulation toolkit.
 *
 * No score, no levels, no speed-up: just clear lines at a steady pace.
 * Adapted from jakesgordon/javascript-tetris (MIT License, (c) 2011 Jake Gordon).
 */
(function () {
  "use strict";

  var canvas = document.getElementById("sf-canvas");
  var ucanvas = document.getElementById("sf-upcoming");
  var startBtn = document.getElementById("sf-start");
  var statusEl = document.getElementById("sf-status");
  var linesEl = document.getElementById("sf-lines");
  var controls = document.getElementById("sf-controls");
  if (!canvas || !ucanvas || !startBtn) return;

  var ctx = canvas.getContext("2d");
  var uctx = ucanvas.getContext("2d");

  var NX = 10, NY = 20, NU = 5;
  var STEP = 0.8; // seconds before a piece drops one row (constant on purpose)
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    STEP = 1.1;
  }

  var DIR = { UP: 0, RIGHT: 1, DOWN: 2, LEFT: 3, MIN: 0, MAX: 3 };

  var PIECES = {
    I: { size: 4, blocks: [0x0F00, 0x2222, 0x00F0, 0x4444], color: "#8fb3a4" },
    J: { size: 3, blocks: [0x44C0, 0x8E00, 0x6440, 0x0E20], color: "#8aa3c0" },
    L: { size: 3, blocks: [0x4460, 0x0E80, 0xC440, 0x2E00], color: "#d9a95c" },
    O: { size: 2, blocks: [0xCC00, 0xCC00, 0xCC00, 0xCC00], color: "#e6c56b" },
    S: { size: 3, blocks: [0x06C0, 0x8C40, 0x6C00, 0x4620], color: "#a5bd8f" },
    T: { size: 3, blocks: [0x0E40, 0x4C40, 0x4E00, 0x4640], color: "#a99ec9" },
    Z: { size: 3, blocks: [0x0C60, 0x4C80, 0xC600, 0x2640], color: "#d98f7c" }
  };

  var dx, dy, blocks, actions, playing, paused, dt, current, next, lines;

  // ---------------------------------------------------------------------------
  // helpers
  // ---------------------------------------------------------------------------
  function eachblock(type, x, y, dir, fn) {
    var bit, row = 0, col = 0, bits = type.blocks[dir];
    for (bit = 0x8000; bit > 0; bit = bit >> 1) {
      if (bits & bit) fn(x + col, y + row);
      if (++col === 4) { col = 0; ++row; }
    }
  }

  function occupied(type, x, y, dir) {
    var result = false;
    eachblock(type, x, y, dir, function (x, y) {
      if ((x < 0) || (x >= NX) || (y < 0) || (y >= NY) || getBlock(x, y)) result = true;
    });
    return result;
  }

  function unoccupied(type, x, y, dir) { return !occupied(type, x, y, dir); }

  function getBlock(x, y) { return (blocks && blocks[x] ? blocks[x][y] : null); }
  function setBlock(x, y, type) { blocks[x] = blocks[x] || []; blocks[x][y] = type; invalidate(); }
  function clearBlocks() { blocks = []; invalidate(); }
  function clearActions() { actions = []; }

  // 7-bag randomizer: a shuffled bag of each piece, no repeats until all used.
  var bag = [];
  function randomPiece() {
    if (!bag.length) {
      bag = ["I", "I", "I", "I", "J", "J", "J", "J", "L", "L", "L", "L",
             "O", "O", "O", "O", "S", "S", "S", "S", "T", "T", "T", "T",
             "Z", "Z", "Z", "Z"];
    }
    var key = bag.splice(Math.floor(Math.random() * bag.length), 1)[0];
    var type = PIECES[key];
    return { type: type, dir: DIR.UP, x: Math.round(Math.random() * (NX - type.size)), y: 0 };
  }

  function setCurrentPiece(p) { current = p || randomPiece(); invalidate(); }
  function setNextPiece(p) { next = p || randomPiece(); invalidateNext(); }

  // ---------------------------------------------------------------------------
  // game flow
  // ---------------------------------------------------------------------------
  function start() {
    reset();
    playing = true;
    paused = false;
    startBtn.style.display = "none";
    if (controls) controls.style.display = "flex";
    setStatus("");
  }

  function end() {
    playing = false;
    paused = false;
    startBtn.textContent = "Play again";
    startBtn.style.display = "";
    setStatus("Full board — nice going. That's enough for now, whenever you like.");
  }

  function togglePause() {
    if (!playing) return;
    paused = !paused;
    setStatus(paused ? "⏸ paused — press Esc to resume" : "");
  }

  function setStatus(msg) { if (statusEl) statusEl.textContent = msg; }

  function reset() {
    dt = 0;
    clearActions();
    clearBlocks();
    lines = 0;
    invalidateLines();
    setCurrentPiece(randomPiece());
    setNextPiece(randomPiece());
  }

  // ---------------------------------------------------------------------------
  // moves
  // ---------------------------------------------------------------------------
  function move(dir) {
    var x = current.x, y = current.y;
    switch (dir) {
      case DIR.RIGHT: x = x + 1; break;
      case DIR.LEFT: x = x - 1; break;
      case DIR.DOWN: y = y + 1; break;
    }
    if (unoccupied(current.type, x, y, current.dir)) {
      current.x = x; current.y = y; invalidate();
      return true;
    }
    return false;
  }

  function rotate() {
    var newdir = (current.dir === DIR.MAX ? DIR.MIN : current.dir + 1);
    if (unoccupied(current.type, current.x, current.y, newdir)) {
      current.dir = newdir;
      invalidate();
    }
  }

  function handle(action) {
    if (action === DIR.LEFT) move(DIR.LEFT);
    else if (action === DIR.RIGHT) move(DIR.RIGHT);
    else if (action === DIR.UP) rotate();
    else if (action === DIR.DOWN) softDrop();
  }

  function softDrop() {
    dt = 0;
    drop();
  }

  function hardDrop() {
    while (move(DIR.DOWN)) { /* keep falling */ }
    lock();
  }

  function drop() {
    if (!move(DIR.DOWN)) lock();
  }

  function lock() {
    eachblock(current.type, current.x, current.y, current.dir, function (x, y) {
      setBlock(x, y, current.type);
    });
    removeLines();
    setCurrentPiece(next);
    setNextPiece(randomPiece());
    clearActions();
    if (occupied(current.type, current.x, current.y, current.dir)) end();
  }

  function removeLines() {
    var x, y, complete, n = 0;
    for (y = NY; y > 0; --y) {
      complete = true;
      for (x = 0; x < NX; ++x) {
        if (!getBlock(x, y)) complete = false;
      }
      if (complete) {
        removeLine(y);
        y = y + 1; // recheck the same line
        n++;
      }
    }
    if (n > 0) {
      lines = lines + n;
      invalidateLines();
    }
  }

  function removeLine(n) {
    var x, y;
    for (y = n; y >= 0; --y) {
      for (x = 0; x < NX; ++x) {
        setBlock(x, y, (y === 0) ? null : getBlock(x, y - 1));
      }
    }
  }

  // ---------------------------------------------------------------------------
  // game loop
  // ---------------------------------------------------------------------------
  function run() {
    addEvents();
    resize();
    reset();
    last = 0;
    requestAnimationFrame(frame);
  }

  var last = 0;
  function frame(now) {
    if (!last) last = now;
    var idt = Math.min(1, (now - last) / 1000.0); // clamp for background-tab hibernation
    last = now;
    update(idt);
    draw();
    requestAnimationFrame(frame);
  }

  function update(idt) {
    if (!playing || paused) return;
    handle(actions.shift());
    dt = dt + idt;
    if (dt > STEP) {
      dt = dt - STEP;
      drop();
    }
  }

  // ---------------------------------------------------------------------------
  // input
  // ---------------------------------------------------------------------------
  function addEvents() {
    document.addEventListener("keydown", keydown, false);
    window.addEventListener("resize", resize, false);
    if (controls) {
      var btns = controls.querySelectorAll("[data-sf]");
      for (var i = 0; i < btns.length; i++) bindTouch(btns[i]);
    }
  }

  function bindTouch(el) {
    var action = el.getAttribute("data-sf");
    var fire = function (e) {
      if (e.preventDefault) e.preventDefault();
      if (playing && !paused) {
        if (action === "left") actions.push(DIR.LEFT);
        else if (action === "right") actions.push(DIR.RIGHT);
        else if (action === "rotate") actions.push(DIR.UP);
        else if (action === "down") softDrop();
        else if (action === "drop") hardDrop();
      }
    };
    if (window.PointerEvent) {
      el.addEventListener("pointerdown", fire, false);
    } else {
      el.addEventListener("mousedown", fire, false);
      el.addEventListener("touchstart", fire, { passive: false });
    }
  }

  function keydown(ev) {
    if (ev.keyCode === 27) { togglePause(); ev.preventDefault(); return; }
    if (!playing || paused) return;
    var handled = true;
    switch (ev.keyCode) {
      case 37: actions.push(DIR.LEFT); break;   // left
      case 39: actions.push(DIR.RIGHT); break;  // right
      case 38: actions.push(DIR.UP); break;     // up = rotate
      case 40: softDrop(); break;               // down
      case 32: hardDrop(); break;               // space
      default: handled = false;
    }
    if (handled && ev.preventDefault) ev.preventDefault();
  }

  // ---------------------------------------------------------------------------
  // rendering
  // ---------------------------------------------------------------------------
  var invalid = { court: true, next: true, lines: true };

  function invalidate() { invalid.court = true; }
  function invalidateNext() { invalid.next = true; }
  function invalidateLines() { invalid.lines = true; }

  function resize() {
    canvas.width = canvas.clientWidth;
    canvas.height = canvas.clientHeight;
    ucanvas.width = ucanvas.clientWidth;
    ucanvas.height = ucanvas.clientHeight;
    dx = canvas.width / NX;
    dy = canvas.height / NY;
    invalidate();
    invalidateNext();
  }

  function draw() {
    drawCourt();
    drawNext();
    drawLines();
  }

  function drawCourt() {
    if (!invalid.court) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (playing) drawPiece(ctx, current.type, current.x, current.y, current.dir);
    var x, y, block;
    for (y = 0; y < NY; y++) {
      for (x = 0; x < NX; x++) {
        block = getBlock(x, y);
        if (block) drawBlock(ctx, x, y, block.color);
      }
    }
    invalid.court = false;
  }

  function drawNext() {
    if (!invalid.next) return;
    var padding = (NU - next.type.size) / 2;
    uctx.clearRect(0, 0, ucanvas.width, ucanvas.height);
    drawPiece(uctx, next.type, padding, padding, next.dir);
    invalid.next = false;
  }

  function drawLines() {
    if (!invalid.lines) return;
    if (linesEl) linesEl.textContent = lines;
    invalid.lines = false;
  }

  function drawPiece(ctx2, type, x, y, dir) {
    eachblock(type, x, y, dir, function (x, y) {
      drawBlock(ctx2, x, y, type.color);
    });
  }

  function drawBlock(ctx2, x, y, color) {
    var px = x * dx, py = y * dy;
    ctx2.fillStyle = color;
    ctx2.fillRect(px + 1, py + 1, dx - 2, dy - 2);
    ctx2.fillStyle = "rgba(255,255,255,0.22)";
    ctx2.fillRect(px + 1, py + 1, dx - 2, Math.max(2, dy * 0.16));
  }

  // ---------------------------------------------------------------------------
  startBtn.addEventListener("click", start, false);
  run();
})();
