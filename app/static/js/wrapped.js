/* Kin Wrapped helpers:
   - Deck: JS-driven cross-fade between full-viewport sections (works in every browser),
     progress dots (active section) + a scroll cue that hides at the bottom.
   - Clickable month bars: clicking a month reveals what happened that month, inline.
   - Share-link reveal/copy.
   - Exporting the card as a PNG (flattens the deck into one continuous image).
   Dependency-free - the PNG capture serializes the card's DOM (with computed styles inlined)
   into an SVG foreignObject and rasterizes it to a canvas, so it works offline with no CDN.
   Same-origin images (served through Kin's own proxy) render fine without tainting the canvas.
   All motion honours prefers-reduced-motion. */
(function () {
  'use strict';

  var cardEl = document.getElementById('wrapped-card');
  var sections = Array.prototype.slice.call(document.querySelectorAll('#wrapped-card .wrapped-section'));
  var reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var imgBase = cardEl ? (cardEl.getAttribute('data-img-base') || '') : '';

  // --- Deck: cross-fade + progress dots + scroll cue -------------------------
  function scrollToSection(i) {
    if (!sections[i]) return;
    sections[i].scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'start' });
  }

  function setActive(index) {
    var dots = document.querySelectorAll('.wrapped-dots button');
    for (var i = 0; i < dots.length; i++) {
      dots[i].classList.toggle('is-active', i === index);
    }
  }

  var dotsWrap = null;
  var cue = null;
  if (sections.length > 0) {
    dotsWrap = document.createElement('div');
    dotsWrap.className = 'wrapped-dots';
    dotsWrap.setAttribute('role', 'tablist');
    sections.forEach(function (s, i) {
      var b = document.createElement('button');
      b.type = 'button';
      b.setAttribute('aria-label', 'Go to section ' + (i + 1));
      b.setAttribute('role', 'tab');
      b.addEventListener('click', function () { scrollToSection(i); });
      dotsWrap.appendChild(b);
    });
    document.body.appendChild(dotsWrap);

    cue = document.createElement('button');
    cue.className = 'wrapped-scroll-cue';
    cue.type = 'button';
    cue.setAttribute('aria-label', 'More content below');
    cue.textContent = '↓';
    cue.addEventListener('click', function () {
      scrollToSection((setActive.current || 0) + 1);
    });
    document.body.appendChild(cue);
  }

  function updateDeck() {
    if (!sections.length) return;
    var center = window.scrollY + window.innerHeight / 2;
    var best = 0, bestDist = Infinity;
    for (var i = 0; i < sections.length; i++) {
      var r = sections[i].getBoundingClientRect();
      var sCenter = r.top + r.height / 2 + window.scrollY;
      var d = Math.abs(sCenter - center);
      if (d < bestDist) { bestDist = d; best = i; }
    }
    setActive(best);
    setActive.current = best;
    if (cue) {
      var nearBottom = (window.innerHeight + window.scrollY) >= (document.documentElement.scrollHeight - 180);
      cue.classList.toggle('is-hidden', nearBottom || best >= sections.length - 1);
    }
  }

  // Cross-fade: a section is opaque while centred and fades as its centre leaves the middle of
  // the viewport, so the outgoing fades as the next fades in. The last section stays visible.
  function updateFade() {
    if (!sections.length || reducedMotion) return;
    var vh = window.innerHeight;
    var last = sections.length - 1;
    for (var i = 0; i < sections.length; i++) {
      var rect = sections[i].getBoundingClientRect();
      var pos = (rect.top + rect.height / 2) / vh; // 0=top edge, 0.5=centre, 1=bottom edge
      var opacity = 1 - Math.abs(pos - 0.5) * 2.2;
      opacity = Math.max(0, Math.min(1, opacity));
      if (i === last && pos <= 0.5) opacity = 1;
      sections[i].style.opacity = opacity.toFixed(3);
      sections[i].style.transform = 'translateY(' + ((pos - 0.5) * vh * 0.06).toFixed(1) + 'px)';
    }
  }

  var rafPending = false;
  function onScroll() {
    if (rafPending) return;
    rafPending = true;
    requestAnimationFrame(function () {
      rafPending = false;
      updateDeck();
      updateFade();
    });
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', onScroll, { passive: true });
  onScroll();

  // --- Share link reveal + copy ---------------------------------------------
  var shareBtn = document.getElementById('wrapped-share-btn');
  var shareBox = document.getElementById('wrapped-share-box');
  if (shareBtn && shareBox) {
    shareBtn.addEventListener('click', function () {
      shareBox.style.display = (shareBox.style.display === 'none' || !shareBox.style.display) ? '' : 'none';
    });
  }
  var copyBtn = document.getElementById('wrapped-copy-btn');
  var urlInput = document.getElementById('wrapped-share-url');
  if (copyBtn && urlInput) {
    copyBtn.addEventListener('click', function () {
      var done = function () {
        copyBtn.textContent = 'Copied ✓';
        setTimeout(function () { copyBtn.textContent = 'Copy'; }, 1600);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(urlInput.value).then(done, function () {
          urlInput.select();
          document.execCommand('copy');
          done();
        });
      } else {
        urlInput.select();
        document.execCommand('copy');
        done();
      }
    });
  }

  // --- Clickable months: peek at what happened, inline in the section --------
  var monthDataEl = document.getElementById('wrapped-months-data');
  var panel = document.getElementById('wrapped-month-panel');
  if (monthDataEl && panel) {
    var months = [];
    try { months = JSON.parse(monthDataEl.textContent); } catch (e) { months = []; }
    var labels = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    var activeMonth = null;
    var panelTitle = document.getElementById('wrapped-month-title');
    var panelMoments = document.getElementById('wrapped-month-moments');
    var panelClose = document.getElementById('wrapped-month-close');
    var carouselHint = document.getElementById('wrapped-carousel-hint');

    function updateCarouselHint() {
      if (!carouselHint) return;
      var overflow = panelMoments && panelMoments.scrollWidth > panelMoments.clientWidth + 4;
      carouselHint.hidden = !overflow;
    }

    function esc(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
    function eventLabel(et) {
      return ({ hangout: 'Hangout', call: 'Call', message: 'Message', gift: 'Gift',
                milestone: 'Milestone', instagram: 'Shared', note: 'Moment', other: 'Moment' }[et] || 'Moment');
    }
    function buildMoment(m) {
      var el = document.createElement('div');
      el.className = 'wrapped-month-moment';
      var img = '';
      if (m.asset_id) { img = '<img src="' + imgBase + '/asset/' + esc(m.asset_id) + '/thumbnail" alt="" loading="lazy">'; }
      else if (m.url) { img = '<img src="' + esc(m.url) + '" alt="" loading="lazy">'; }
      var meta = (m.date_display || '') + ' · ' + eventLabel(m.event_type);
      if (m.people && m.people.length) { meta += ' · ' + esc(m.people.join(', ')); }
      var text = m.summary || m.body_preview || '';
      el.innerHTML = img +
        '<div class="wrapped-month-moment-body">' +
        '<div class="wrapped-month-moment-meta">' + meta + '</div>' +
        (m.title ? '<h4>' + esc(m.title) + '</h4>' : '') +
        (text ? '<p>' + esc(text) + '</p>' : '') +
        '</div>';
      return el;
    }

    function refreshCols() {
      var cols = document.querySelectorAll('.wrapped-chart-col');
      for (var i = 0; i < cols.length; i++) { cols[i].classList.toggle('is-active', i === activeMonth); }
    }

    function fillPanel(i) {
      var md = months[i];
      panelTitle.textContent = labels[i] + ' — ' + md.count + ' moment' + (md.count === 1 ? '' : 's');
      panelMoments.innerHTML = '';
      if (!md.moments || !md.moments.length) {
        var none = document.createElement('p');
        none.className = 'wrapped-month-none';
        none.textContent = "Nothing much logged this month — and that's okay.";
        panelMoments.appendChild(none);
      } else {
        md.moments.forEach(function (m) { panelMoments.appendChild(buildMoment(m)); });
      }
      refreshCols();
      updateCarouselHint();
    }

    // Fade out the current month's pane, swap in the new month's content, fade it back in.
    function openMonth(i) {
      var md = months[i];
      if (!md) return;
      if (activeMonth === i) { closeMonth(); return; }
      activeMonth = i;
      if (panel.hidden) {
        panel.hidden = false;
        fillPanel(i);
        requestAnimationFrame(function () { panel.classList.add('is-open'); });
      } else {
        panel.classList.remove('is-open');
        setTimeout(function () {
          fillPanel(i);
          requestAnimationFrame(function () { panel.classList.add('is-open'); });
        }, 300);
      }
      onScroll();
    }
    function closeMonth() {
      if (panel.hidden) return;
      activeMonth = null;
      panel.classList.remove('is-open');
      setTimeout(function () { panel.hidden = true; }, 300);
      refreshCols();
      onScroll();
    }
    if (panelClose) { panelClose.addEventListener('click', closeMonth); }

    var cols = document.querySelectorAll('.wrapped-chart-col');
    for (var i = 0; i < cols.length; i++) {
      (function (idx) {
        cols[idx].addEventListener('click', function () { if (months[idx] && months[idx].count) openMonth(idx); });
        cols[idx].addEventListener('keydown', function (e) {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (months[idx] && months[idx].count) openMonth(idx); }
        });
      })(i);
    }
  }

  // --- "Little things" photo stage: cross-fade + gentle float + mouse push --
  var factsStage = document.getElementById('wrapped-facts-stage');
  if (factsStage && !reducedMotion) {
    var stagePhotos = Array.prototype.slice.call(factsStage.querySelectorAll('.wrapped-photo'));
    if (stagePhotos.length > 1) {
      var shownIdx = 0;
      setInterval(function () {
        var next = (shownIdx + 1) % stagePhotos.length;
        stagePhotos[shownIdx].classList.remove('is-shown');
        stagePhotos[next].classList.add('is-shown');
        shownIdx = next;
      }, 2600);
    }
    // Moving the mouse near a photo gently pushes it out of the way.
    var pushRadius = 160;
    var pushForce = 46;
    function movePhotos(e) {
      var r = factsStage.getBoundingClientRect();
      var cx = e.clientX - r.left;
      var cy = e.clientY - r.top;
      for (var i = 0; i < stagePhotos.length; i++) {
        var pr = stagePhotos[i].getBoundingClientRect();
        var pxc = pr.left - r.left + pr.width / 2;
        var pyc = pr.top - r.top + pr.height / 2;
        var dx = pxc - cx, dy = pyc - cy;
        var dist = Math.sqrt(dx * dx + dy * dy);
        var push = Math.max(0, 1 - dist / pushRadius);
        var force = push * pushForce;
        var nx = dist > 0 ? (dx / dist) * force : 0;
        var ny = dist > 0 ? (dy / dist) * force : 0;
        stagePhotos[i].style.transform = 'translate(calc(-50% + ' + nx.toFixed(1) + 'px), calc(-50% + ' + ny.toFixed(1) + 'px))';
      }
    }
    function releasePhotos() {
      for (var i = 0; i < stagePhotos.length; i++) {
        stagePhotos[i].style.transform = '';
      }
    }
    factsStage.addEventListener('mousemove', movePhotos);
    factsStage.addEventListener('mouseleave', releasePhotos);
  }

  // --- Reveal-on-scroll (per-person cards) ----------------------------------
  var reveals = document.querySelectorAll('.wrapped-reveal');
  if (reveals.length) {
    if ('IntersectionObserver' in window) {
      var rIo = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-in');
            rIo.unobserve(entry.target);
          }
        });
      }, { threshold: 0.12 });
      reveals.forEach(function (el) { rIo.observe(el); });
    } else {
      reveals.forEach(function (el) { el.classList.add('is-in'); });
    }
  }

  // --- Save as image ---------------------------------------------------------
  var saveButtons = [];
  [document.getElementById('wrapped-save'), document.getElementById('wrapped-save-2')]
    .forEach(function (b) { if (b) saveButtons.push(b); });
  if (!cardEl || !saveButtons.length) return;

  var STYLE_PROPS = [
    'display', 'flex', 'flex-direction', 'flex-wrap', 'justify-content', 'align-items',
    'gap', 'padding', 'margin', 'width', 'min-width', 'max-width', 'height', 'min-height',
    'font-size', 'font-family', 'font-weight', 'font-style', 'line-height', 'letter-spacing',
    'text-transform', 'text-align', 'color', 'background-color', 'background-image',
    'background-clip', '-webkit-background-clip', 'border', 'border-radius', 'border-left',
    'border-bottom', 'box-shadow', 'object-fit', 'overflow', 'text-overflow', 'text-decoration'
  ];

  function inlineStyles(root) {
    var els = root.querySelectorAll('*');
    for (var i = 0; i < els.length; i++) {
      var cs = window.getComputedStyle(els[i]);
      var styleStr = '';
      for (var j = 0; j < STYLE_PROPS.length; j++) {
        var val = cs.getPropertyValue(STYLE_PROPS[j]);
        if (val) styleStr += STYLE_PROPS[j] + ': ' + val + ';';
      }
      // Preserve custom properties (--px, --float-x, ...) that were set inline, otherwise
      // inlining would wipe them and layout like the photo collage would collapse.
      var inline = els[i].style;
      for (var k = 0; k < inline.length; k++) {
        var prop = inline[k];
        if (prop.indexOf('--') === 0) {
          var cv = inline.getPropertyValue(prop);
          if (cv) styleStr += prop + ': ' + cv + ';';
        }
      }
      els[i].setAttribute('style', styleStr);
    }
    var imgs = root.querySelectorAll('img');
    return new Promise(function (resolve) {
      var remaining = imgs.length;
      if (!remaining) { resolve(); return; }
      function done() { if (--remaining <= 0) resolve(); }
      imgs.forEach(function (img) {
        if (img.complete && img.naturalWidth > 0) { done(); return; }
        img.onload = done;
        img.onerror = done;
      });
    });
  }

  // Flatten the full-viewport deck into a single flowing column for the image.
  function flattenDeck(root) {
    var els = root.querySelectorAll('.wrapped-section');
    for (var i = 0; i < els.length; i++) {
      els[i].style.minHeight = 'auto';
      els[i].style.height = 'auto';
      els[i].style.opacity = '1';
      els[i].style.transform = 'none';
      els[i].style.animation = 'none';
    }
    var panel = root.querySelector('#wrapped-month-panel');
    if (panel) { panel.setAttribute('hidden', ''); }

    // Static, full-opacity state for the photo collage (no fade/float/push in the image).
    var stagePhotos = root.querySelectorAll('.wrapped-photo');
    for (var s = 0; s < stagePhotos.length; s++) {
      stagePhotos[s].classList.add('is-shown');
      stagePhotos[s].style.opacity = '1';
      stagePhotos[s].style.transform = 'translate(-50%, -50%)';
    }
    var floats = root.querySelectorAll('.wrapped-photo-float');
    for (var f = 0; f < floats.length; f++) {
      floats[f].style.animation = 'none';
    }
  }

  function setBusy(busy) {
    saveButtons.forEach(function (b) { b.disabled = busy; });
  }

  saveButtons.forEach(function (btn) {
    btn.addEventListener('click', async function () {
      if (btn.disabled) return;
      try {
        setBusy(true);
        var width = cardEl.offsetWidth || 680;

        // Off-screen holder so the flattened clone can be measured.
        var holder = document.createElement('div');
        holder.style.cssText = 'position:fixed;left:-99999px;top:0;width:' + width + 'px;';
        var clone = cardEl.cloneNode(true);
        clone.querySelectorAll('.wrapped-reveal').forEach(function (el) { el.classList.remove('wrapped-reveal'); });
        holder.appendChild(clone);
        document.body.appendChild(holder);

        await inlineStyles(clone);
        flattenDeck(clone);
        var height = clone.offsetHeight;

        var svg =
          '<svg xmlns="http://www.w3.org/2000/svg" width="' + width + '" height="' + (height + 40) + '">' +
          '<foreignObject width="100%" height="100%">' +
          '<div xmlns="http://www.w3.org/1999/xhtml" style="width:' + width + 'px;">' + clone.outerHTML + '</div>' +
          '</foreignObject></svg>';
        document.body.removeChild(holder);

        var blob = new Blob([svg], { type: 'image/svg+xml;charset=utf-8' });
        var url = URL.createObjectURL(blob);
        var img = new Image();
        img.onload = function () {
          var scale = 2;
          var canvas = document.createElement('canvas');
          canvas.width = width * scale;
          canvas.height = (height + 40) * scale;
          var ctx = canvas.getContext('2d');
          ctx.scale(scale, scale);
          ctx.fillStyle = '#221e1a';
          ctx.fillRect(0, 0, width, height + 40);
          ctx.drawImage(img, 0, 0, width, height + 40);
          URL.revokeObjectURL(url);
          var a = document.createElement('a');
          a.download = 'kin-wrapped.png';
          a.href = canvas.toDataURL('image/png');
          a.click();
          setBusy(false);
        };
        img.onerror = function () {
          URL.revokeObjectURL(url);
          setBusy(false);
          alert("Couldn't create the image in this browser — try a screenshot instead.");
        };
        img.src = url;
      } catch (e) {
        setBusy(false);
        alert("Couldn't create the image — try a screenshot instead.");
      }
    });
  });
})();
