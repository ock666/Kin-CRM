/* 2048 — a gentle sliding-tile puzzle for the Kin regulation toolkit.
 * No timer, no pressure. Original concept by Gabriele Cirulli (MIT, github.com/gabrielecirulli/2048).
 */
(function () {
  "use strict";

  var root = document.getElementById("game-root");
  if (!root) return;

  var SIZE = 4;
  var grid = [];
  var score = 0;
  var cells = [];
  var done = false;

  root.innerHTML =
    '<div class="card" style="text-align:center;">' +
      '<div class="flex-between" style="max-width:320px;margin:0 auto .5rem;">' +
        '<span class="text-sm text-muted">score</span>' +
        '<span class="text-sm" id="g2048-score">0</span>' +
        '<button id="g2048-new" class="btn btn-sm" type="button">New game</button>' +
      '</div>' +
      '<div id="g2048-grid" class="g2048-grid"></div>' +
      '<p id="g2048-status" class="text-sm text-muted mt-1" aria-live="polite"></p>' +
      '<p class="help-text mt-1 mb-0">Swipe, or use the arrow keys / WASD.</p>' +
    '</div>';

  var gridEl = document.getElementById("g2048-grid");
  var scoreEl = document.getElementById("g2048-score");
  var statusEl = document.getElementById("g2048-status");

  for (var r = 0; r < SIZE; r++) {
    for (var c = 0; c < SIZE; c++) {
      var cell = document.createElement("div");
      cell.className = "g2048-cell";
      gridEl.appendChild(cell);
      cells.push(cell);
    }
  }

  function emptyCells() {
    var out = [];
    for (var r = 0; r < SIZE; r++) {
      for (var c = 0; c < SIZE; c++) {
        if (!grid[r][c]) out.push([r, c]);
      }
    }
    return out;
  }

  function spawn() {
    var empties = emptyCells();
    if (!empties.length) return;
    var p = empties[Math.floor(Math.random() * empties.length)];
    grid[p[0]][p[1]] = Math.random() < 0.9 ? 2 : 4;
  }

  function slideLine(line) {
    var vals = line.filter(function (v) { return v; });
    var merged = [];
    for (var i = 0; i < vals.length; i++) {
      if (i + 1 < vals.length && vals[i] === vals[i + 1]) {
        merged.push(vals[i] * 2);
        score += vals[i] * 2;
        i++;
      } else {
        merged.push(vals[i]);
      }
    }
    while (merged.length < SIZE) merged.push(0);
    return merged;
  }

  function rows() {
    var out = [];
    for (var r = 0; r < SIZE; r++) out.push(grid[r].slice());
    return out;
  }

  function columns() {
    var out = [];
    for (var c = 0; c < SIZE; c++) {
      var col = [];
      for (var r = 0; r < SIZE; r++) col.push(grid[r][c]);
      out.push(col);
    }
    return out;
  }

  function setRows(rowsArr) {
    for (var r = 0; r < SIZE; r++) grid[r] = rowsArr[r].slice();
  }

  function setColumns(colsArr) {
    for (var c = 0; c < SIZE; c++) {
      for (var r = 0; r < SIZE; r++) grid[r][c] = colsArr[c][r];
    }
  }

  function reverseLines(lines) {
    return lines.map(function (l) { return l.slice().reverse(); });
  }

  function move(dir) {
    // dir: 0 up, 1 right, 2 down, 3 left
    var changed = false;
    var before = JSON.stringify(grid);
    var lines;
    if (dir === 0) { lines = columns(); lines = lines.map(slideLine); setColumns(lines); }
    else if (dir === 1) { lines = rows(); lines = reverseLines(lines).map(slideLine).map(function (l) { return l.slice().reverse(); }); setRows(lines); }
    else if (dir === 2) { lines = columns(); lines = reverseLines(lines).map(slideLine).map(function (l) { return l.slice().reverse(); }); setColumns(lines); }
    else { lines = rows(); lines = lines.map(slideLine); setRows(lines); }
    changed = before !== JSON.stringify(grid);
    if (changed) {
      spawn();
      render();
      if (!canMove()) { done = true; statusEl.textContent = "No more moves — that was a good run. New game whenever you like."; }
    }
    return changed;
  }

  function canMove() {
    for (var r = 0; r < SIZE; r++) {
      for (var c = 0; c < SIZE; c++) {
        if (!grid[r][c]) return true;
        if (c + 1 < SIZE && grid[r][c] === grid[r][c + 1]) return true;
        if (r + 1 < SIZE && grid[r][c] === grid[r + 1][c]) return true;
      }
    }
    return false;
  }

  function render() {
    scoreEl.textContent = score;
    var idx = 0;
    for (var r = 0; r < SIZE; r++) {
      for (var c = 0; c < SIZE; c++) {
        var v = grid[r][c];
        var cell = cells[idx++];
        cell.textContent = v || "";
        cell.setAttribute("data-v", v || "0");
      }
    }
  }

  function newGame() {
    grid = [];
    for (var r = 0; r < SIZE; r++) grid.push([0, 0, 0, 0]);
    score = 0;
    done = false;
    statusEl.textContent = "";
    spawn();
    spawn();
    render();
  }

  // input
  function keydown(e) {
    if (done) return;
    var handled = true;
    if (e.keyCode === 37 || e.keyCode === 65) move(3);          // left / A
    else if (e.keyCode === 39 || e.keyCode === 68) move(1);      // right / D
    else if (e.keyCode === 38 || e.keyCode === 87) move(0);      // up / W
    else if (e.keyCode === 40 || e.keyCode === 83) move(2);      // down / S
    else handled = false;
    if (handled) e.preventDefault();
  }

  var touchStart = null;
  function touchstart(e) { touchStart = e.touches[0]; }
  function touchend(e) {
    if (done) return;
    if (!touchStart) return;
    var dx = e.changedTouches[0].clientX - touchStart.clientX;
    var dy = e.changedTouches[0].clientY - touchStart.clientY;
    touchStart = null;
    if (Math.max(Math.abs(dx), Math.abs(dy)) < 24) return;
    if (Math.abs(dx) > Math.abs(dy)) move(dx > 0 ? 1 : 3);
    else move(dy > 0 ? 2 : 0);
  }

  document.addEventListener("keydown", keydown, false);
  gridEl.addEventListener("touchstart", touchstart, { passive: true });
  gridEl.addEventListener("touchend", touchend, false);
  document.getElementById("g2048-new").addEventListener("click", newGame, false);

  newGame();
})();
