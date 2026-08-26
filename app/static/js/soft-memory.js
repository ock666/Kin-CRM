/* Memory — a gentle matching-pairs game for the Kin regulation toolkit.
 * No timer, no move counter, no pressure.
 */
(function () {
  "use strict";

  var root = document.getElementById("game-root");
  if (!root) return;

  var EMOJIS = ["🌱", "🌙", "⭐", "🌸", "🍃", "🕊️", "🫧", "☁️"];
  var deck, first = null, lock = false, matched = 0;

  root.innerHTML =
    '<div class="card" style="text-align:center;">' +
      '<div class="flex-between" style="max-width:320px;margin:0 auto .5rem;">' +
        '<span class="text-sm text-muted">pairs found <span id="mem-count">0</span> / ' + EMOJIS.length + '</span>' +
        '<button id="mem-new" class="btn btn-sm" type="button">New game</button>' +
      '</div>' +
      '<div id="mem-grid" class="mem-grid"></div>' +
      '<p id="mem-status" class="text-sm text-muted mt-1" aria-live="polite"></p>' +
    '</div>';

  var gridEl = document.getElementById("mem-grid");
  var countEl = document.getElementById("mem-count");
  var statusEl = document.getElementById("mem-status");

  function shuffle(arr) {
    for (var i = arr.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var t = arr[i]; arr[i] = arr[j]; arr[j] = t;
    }
    return arr;
  }

  function render() {
    gridEl.innerHTML = "";
    deck.forEach(function (emoji, i) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "mem-card";
      b.setAttribute("data-i", i);
      b.setAttribute("aria-label", "card " + (i + 1));
      b.addEventListener("click", function () { flip(i); });
      gridEl.appendChild(b);
    });
  }

  function flip(i) {
    var card = gridEl.children[i];
    if (!card || lock) return;
    if (card.classList.contains("matched") || card.classList.contains("flipped")) return;

    card.classList.add("flipped");
    card.textContent = deck[i];

    if (first === null) {
      first = i;
      return;
    }

    if (deck[first] === deck[i]) {
      card.classList.add("matched");
      gridEl.children[first].classList.add("matched");
      first = null;
      matched++;
      countEl.textContent = matched;
      if (matched === EMOJIS.length) statusEl.textContent = "All matched — lovely. New game whenever you like.";
    } else {
      lock = true;
      var a = first;
      setTimeout(function () {
        gridEl.children[a].classList.remove("flipped");
        gridEl.children[a].textContent = "";
        card.classList.remove("flipped");
        card.textContent = "";
        first = null;
        lock = false;
      }, 700);
    }
  }

  function newGame() {
    deck = shuffle(EMOJIS.concat(EMOJIS));
    first = null;
    lock = false;
    matched = 0;
    countEl.textContent = "0";
    statusEl.textContent = "";
    render();
  }

  document.getElementById("mem-new").addEventListener("click", newGame, false);
  newGame();
})();
