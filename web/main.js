/* ============================================================
   ABYSM — the descent engine
   Maps scroll position to depth, then drives the ocean color,
   the dive-computer readout, and the sunlight fade — using the
   exact color ramp and zone boundaries from the game.
   ============================================================ */

(function () {
  "use strict";

  var MAX_DEPTH = 10935; // Challenger Deep, metres

  // GameConfig.depthColorStops — [metres, [r,g,b]]
  var STOPS = [
    [0,     [104, 198, 196]],
    [60,    [64, 162, 182]],
    [200,   [34, 104, 150]],
    [700,   [20, 60, 116]],
    [1500,  [13, 38, 84]],
    [4000,  [8, 22, 54]],
    [6500,  [5, 12, 32]],
    [10935, [2, 5, 14]]
  ];

  // GameConfig.zones — first boundary at or below the depth wins
  var ZONES = [
    [0,    "Sunlight Zone"],
    [200,  "Twilight Zone"],
    [1000, "Midnight Zone"],
    [4000, "The Abyss"],
    [6000, "Hadal Zone"]
  ];

  function clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }

  // Linear-interpolate the depth ramp, exactly like depthColor() in-game.
  function depthColor(m) {
    if (m <= STOPS[0][0]) return STOPS[0][1];
    if (m >= STOPS[STOPS.length - 1][0]) return STOPS[STOPS.length - 1][1];
    for (var i = 1; i < STOPS.length; i++) {
      if (m <= STOPS[i][0]) {
        var a = STOPS[i - 1], b = STOPS[i];
        var t = (m - a[0]) / (b[0] - a[0]);
        return [
          Math.round(a[1][0] + (b[1][0] - a[1][0]) * t),
          Math.round(a[1][1] + (b[1][1] - a[1][1]) * t),
          Math.round(a[1][2] + (b[1][2] - a[1][2]) * t)
        ];
      }
    }
    return STOPS[STOPS.length - 1][1];
  }
  function rgb(c) { return "rgb(" + c[0] + "," + c[1] + "," + c[2] + ")"; }

  function zoneName(m) {
    var name = ZONES[0][1];
    for (var i = 0; i < ZONES.length; i++) { if (m >= ZONES[i][0]) name = ZONES[i][1]; }
    return name.toUpperCase();
  }

  var ocean = document.getElementById("ocean");
  var rays = document.getElementById("rays");
  var dcNum = document.getElementById("dcNum");
  var dcZone = document.getElementById("dcZone");
  var dcFill = document.getElementById("dcFill");
  var shareApp = document.getElementById("shareApp");
  var shareStatus = document.getElementById("shareStatus");

  var lastZone = "";
  function fmt(n) { return n.toLocaleString("en-US"); }

  function render() {
    var doc = document.documentElement;
    var scrollable = doc.scrollHeight - window.innerHeight;
    var scrollY = window.scrollY || window.pageYOffset;
    var topFrac = scrollable > 0 ? clamp(scrollY / scrollable, 0, 1) : 0;
    var botFrac = scrollable > 0 ? clamp((scrollY + window.innerHeight) / doc.scrollHeight, 0, 1) : 1;

    // Ocean: the visible band spans the depth at the top and bottom of the viewport.
    ocean.style.background = "linear-gradient(180deg, " +
      rgb(depthColor(topFrac * MAX_DEPTH)) + ", " +
      rgb(depthColor(botFrac * MAX_DEPTH)) + ")";

    // Sunlight only reaches the top ~120 m of screen — fade the rays out fast.
    rays.style.setProperty("--rays-opacity", String(clamp(1 - topFrac * 6, 0, 1)));

    // Dive computer reads the depth you've descended past (top of viewport),
    // so it starts at 0 M at the surface and hits 10,935 M at the floor.
    var meters = Math.round(topFrac * MAX_DEPTH);
    dcNum.textContent = fmt(meters);
    dcFill.style.height = (topFrac * 100) + "%";
    var z = zoneName(meters);
    if (z !== lastZone) { dcZone.textContent = z; lastZone = z; }
  }

  // rAF-throttle scroll/resize.
  var ticking = false;
  function onScroll() {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(function () { render(); ticking = false; });
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll);

  // Share the same canonical App Store URL used by the game.
  if (shareApp) {
    shareApp.addEventListener("click", async function () {
      var appStoreURL = "https://apps.apple.com/app/id6783505799";
      try {
        if (navigator.share) {
          await navigator.share({ title: "ABYSM", text: "A dive to the bottom of the sea.", url: appStoreURL });
          if (shareStatus) shareStatus.textContent = "Shared";
        } else if (navigator.clipboard) {
          await navigator.clipboard.writeText(appStoreURL);
          if (shareStatus) shareStatus.textContent = "App Store link copied";
        } else {
          window.location.href = appStoreURL;
        }
      } catch (error) {
        if (error && error.name !== "AbortError") window.location.href = appStoreURL;
      }
    });
  }

  // Reveal-on-scroll (skipped when the user prefers reduced motion).
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var reveals = document.querySelectorAll(".reveal");
  if (reduce || !("IntersectionObserver" in window)) {
    reveals.forEach(function (el) { el.classList.add("in"); });
  } else {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
      });
    }, { rootMargin: "0px 0px -12% 0px", threshold: 0.12 });
    reveals.forEach(function (el) { io.observe(el); });
  }

  render();
})();
