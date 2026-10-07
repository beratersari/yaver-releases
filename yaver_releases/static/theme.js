(function () {
  var key = "yaver.theme";
  var root = document.documentElement;
  var button = document.getElementById("theme");
  var paint = document.querySelector('meta[name="theme-color"]');

  function current() {
    return root.getAttribute("data-theme") === "light" ? "light" : "dark";
  }

  function apply(theme) {
    var dark = theme !== "light";
    root.setAttribute("data-theme", dark ? "dark" : "light");
    root.style.colorScheme = dark ? "dark" : "light";
    if (paint) paint.setAttribute("content", dark ? "#07090d" : "#f3f6f4");
    if (!button) return;
    button.setAttribute("aria-checked", dark ? "true" : "false");
    button.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
    button.title = dark ? "Light theme" : "Dark theme";
  }

  apply(current());
  if (button) button.addEventListener("click", function () {
    var next = current() === "dark" ? "light" : "dark";
    try {
      localStorage.setItem(key, next);
    } catch (err) {
      /* private mode still switches for this tab */
    }
    apply(next);
  });
})();

(function () {
  function openHashedFold() {
    var raw = (location.hash || "").replace(/^#/, "");
    if (!raw) return;
    var id = raw;
    try {
      id = decodeURIComponent(raw);
    } catch (err) {
      id = raw;
    }
    var el = document.getElementById(id);
    if (!el) return;
    var fold = el.tagName === "DETAILS" ? el : el.closest && el.closest("details");
    if (!fold) return;
    fold.open = true;
    var summary = fold.querySelector("summary");
    if (summary && summary.focus) summary.focus({ preventScroll: true });
    var reduce = false;
    try {
      reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch (err) {
      reduce = false;
    }
    if (fold.scrollIntoView) {
      fold.scrollIntoView({ block: "start", behavior: reduce ? "auto" : "smooth" });
    }
  }

  openHashedFold();
  window.addEventListener("hashchange", openHashedFold);
})();
