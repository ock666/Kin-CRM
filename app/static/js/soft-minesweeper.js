/* Minesweeper — a gentle reveal-the-safe-tiles game for the Kin regulation toolkit.
 * No timer, no rush. First click is always safe.
 */
(function () {
  "use strict";

  var root = document.getElementById("game-root");
  if (!root) return;

  var ROWS = 9, COLS = 9, MINES = 10;

  root.innerHTML =
    '<div class="card" style="text-align:center;">' +
      '<div class="flex-between" style="max-width:340px;margin:0 auto .5rem;">' +
        '<span class="text-sm text-muted">flags <span id="ms-flags">0</span> / ' + MINES + '</span>' +
        '<button id="ms-new" class="btn btn-sm" type="button">New game</button>' +
      '</div>' +
      '<div id="ms-grid" class="ms-grid"></div>' +
      '<div class="flex-gap mt-1" style="justify-content:center;">' +
        '<button id="ms-flag" class="btn btn-sm" type="button">🚩 Flag mode</button>' +
      '</div>' +
      '<p id="ms-status" class="text-sm text-muted mt-1" aria-live="polite"></p>' +
      '<p class="help-text mt-1 mb-0">Tap to reveal · toggle Flag mode to mark mines · right-click also flags.</p>' +
    '</div>';

  var gridEl = document.getElementById("ms-grid");
  var flagsEl = document.getElementById("ms-flags");
  var statusEl = document.getElementById("ms-status");
  var flagBtn = document.getElementById("ms-flag");

  var cells, cellEls, started, gameOver, won, flagMode, flags, revealedCount;

  function makeCell() { return { mine: false, revealed: false, flagged: false, adjacent: 0 }; }

  function neighbors(r, c) {
    var out = [];
    for (var dr = -1; dr <= 1; dr++) {
      for (var dc = -1; dc <= 1; dc++) {
        if (dr === 0 && dc === 0) continue;
        var nr = r + dr, nc = c + dc;
        if (nr >= 0 && nr < ROWS && nc >= 0 && nc < COLS) out.push([nr, nc]);
      }
    }
    return out;
  }

  function placeMines(excludeR, excludeC) {
    var forbidden = {};
    forbidden[excludeR + "," + excludeC] = true;
    neighbors(excludeR, excludeC).forEach(function (p) { forbidden[p[0] + "," + p[1]] = true; });
    var placed = 0;
    while (placed < MINES) {
      var r = Math.floor(Math.random() * ROWS), c = Math.floor(Math.random() * COLS);
      if (cells[r][c].mine || forbidden[r + "," + c]) continue;
      cells[r][c].mine = true;
      placed++;
    }
    for (var rr = 0; rr < ROWS; rr++) {
      for (var cc = 0; cc < COLS; cc++) {
        if (cells[rr][cc].mine) continue;
        var n = 0;
        neighbors(rr, cc).forEach(function (p) { if (cells[p[0]][p[1]].mine) n++; });
        cells[rr][cc].adjacent = n;
      }
    }
  }

  function buildGrid() {
    gridEl.innerHTML = "";
    cellEls = [];
    for (var r = 0; r < ROWS; r++) {
      cellEls.push([]);
      for (var c = 0; c < COLS; c++) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "ms-cell";
        b.setAttribute("data-r", r);
        b.setAttribute("data-c", c);
        b.addEventListener("click", onCell);
        b.addEventListener("contextmenu", function (e) {
          e.preventDefault();
          var rr = +this.getAttribute("data-r"), cc = +this.getAttribute("data-c");
          toggleFlag(rr, cc);
        });
        gridEl.appendChild(b);
        cellEls[r].push(b);
      }
    }
  }

  function onCell() {
    var r = +this.getAttribute("data-r"), c = +this.getAttribute("data-c");
    if (flagMode) toggleFlag(r, c);
    else reveal(r, c);
  }

  function toggleFlag(r, c) {
    if (gameOver || won) return;
    var cell = cells[r][c];
    if (cell.revealed) return;
    cell.flagged = !cell.flagged;
    flags += cell.flagged ? 1 : -1;
    render();
  }

  function reveal(r, c) {
    if (gameOver || won) return;
    var cell = cells[r][c];
    if (cell.flagged) return;
    if (!started) { placeMines(r, c); started = true; }
    if (cell.mine) {
      cell.revealed = true;
      gameOver = true;
      revealAllMines();
      statusEl.textContent = "A mine — that's okay, it's random. Take a breath, and try again when you're ready.";
    } else {
      flood(r, c);
      checkWin();
    }
    render();
  }

  function flood(r, c) {
    var q = [[r, c]];
    while (q.length) {
      var p = q.pop();
      var rr = p[0], cc = p[1];
      var cell = cells[rr][cc];
      if (cell.revealed || cell.flagged || cell.mine) continue;
      cell.revealed = true;
      revealedCount++;
      if (cell.adjacent === 0) neighbors(rr, cc).forEach(function (n) { q.push(n); });
    }
  }

  function revealAllMines() {
    for (var r = 0; r < ROWS; r++) {
      for (var c = 0; c < COLS; c++) {
        if (cells[r][c].mine) cells[r][c].revealed = true;
      }
    }
  }

  function checkWin() {
    if (revealedCount === ROWS * COLS - MINES) {
      won = true;
      statusEl.textContent = "Cleared it — nice and steady.";
    }
  }

  function render() {
    flagsEl.textContent = flags;
    for (var r = 0; r < ROWS; r++) {
      for (var c = 0; c < COLS; c++) {
        var cell = cells[r][c];
        var el = cellEls[r][c];
        el.className = "ms-cell";
        if (cell.flagged) { el.classList.add("flag"); el.textContent = "🚩"; }
        else if (cell.revealed) {
          el.classList.add("revealed");
          if (cell.mine) { el.classList.add("mine"); el.textContent = "💣"; }
          else if (cell.adjacent > 0) { el.textContent = cell.adjacent; el.setAttribute("data-n", cell.adjacent); }
          else el.textContent = "";
        } else {
          el.textContent = "";
          el.removeAttribute("data-n");
        }
      }
    }
    flagBtn.textContent = flagMode ? "🚩 Flag mode: on" : "🚩 Flag mode";
    flagBtn.classList.toggle("btn-primary", flagMode);
  }

  function newGame() {
    cells = [];
    for (var r = 0; r < ROWS; r++) { cells.push([]); for (var c = 0; c < COLS; c++) cells[r].push(makeCell()); }
    started = false; gameOver = false; won = false; flagMode = false; flags = 0; revealedCount = 0;
    statusEl.textContent = "";
    buildGrid();
    render();
  }

  flagBtn.addEventListener("click", function () { flagMode = !flagMode; render(); });
  document.getElementById("ms-new").addEventListener("click", newGame, false);

  newGame();
})();
