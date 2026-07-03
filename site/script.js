/* Margin — site interactions */
(function () {
  "use strict";
  var docEl = document.documentElement;
  docEl.classList.add("js");

  // ---- sticky header ----
  var nav = document.getElementById("nav");
  function onScroll() { if (nav) nav.classList.toggle("scrolled", window.scrollY > 16); }
  window.addEventListener("scroll", onScroll, { passive: true }); onScroll();

  // ---- mobile drawer ----
  var burger = document.getElementById("burger");
  var drawer = document.getElementById("drawer");
  if (burger && drawer) {
    function setOpen(o) {
      burger.setAttribute("aria-expanded", String(o));
      drawer.classList.toggle("open", o);
      document.body.style.overflow = o ? "hidden" : "";
    }
    burger.addEventListener("click", function () { setOpen(burger.getAttribute("aria-expanded") !== "true"); });
    drawer.querySelectorAll("a").forEach(function (a) { a.addEventListener("click", function () { setOpen(false); }); });
  }

  // ---- scroll reveals (staggered) ----
  var reveals = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e, i) {
        if (e.isIntersecting) {
          e.target.style.transitionDelay = Math.min(i * 70, 300) + "ms";
          e.target.classList.add("in"); io.unobserve(e.target);
        }
      });
    }, { threshold: 0.14, rootMargin: "0px 0px -8% 0px" });
    reveals.forEach(function (el) { io.observe(el); });
  } else { reveals.forEach(function (el) { el.classList.add("in"); }); }

  // ---- animated counters ----
  var counters = document.querySelectorAll("[data-count]");
  if (counters.length && "IntersectionObserver" in window) {
    var cio = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        var el = e.target, target = parseInt(el.getAttribute("data-count"), 10) || 0;
        var pre = el.getAttribute("data-prefix") || "", suf = el.getAttribute("data-suffix") || "";
        var start = null, dur = 1500;
        function tick(ts) {
          if (!start) start = ts;
          var p = Math.min((ts - start) / dur, 1), eased = 1 - Math.pow(1 - p, 3);
          el.textContent = pre + Math.round(target * eased).toLocaleString("en-AU") + suf;
          if (p < 1) requestAnimationFrame(tick);
        }
        requestAnimationFrame(tick); cio.unobserve(el);
      });
    }, { threshold: 0.5 });
    counters.forEach(function (el) { cio.observe(el); });
  }

  // ---- testimonial carousel ----
  var figs = Array.prototype.slice.call(document.querySelectorAll(".quote"));
  var dotsWrap = document.getElementById("quoteDots");
  if (figs.length && dotsWrap) {
    var idx = 0, timer;
    figs.forEach(function (_, i) {
      var b = document.createElement("button");
      b.addEventListener("click", function () { go(i); restart(); });
      dotsWrap.appendChild(b);
    });
    var dots = Array.prototype.slice.call(dotsWrap.children);
    function go(n) {
      idx = (n + figs.length) % figs.length;
      figs.forEach(function (f, i) { f.classList.toggle("is-active", i === idx); });
      dots.forEach(function (d, i) { d.classList.toggle("active", i === idx); });
    }
    function restart() { clearInterval(timer); timer = setInterval(function () { go(idx + 1); }, 5000); }
    go(0); restart();
  }

  // ---- year ----
  var y = document.getElementById("year"); if (y) y.textContent = new Date().getFullYear();
})();
