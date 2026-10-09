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
    var name = dark ? "dark" : "light";
    var scheme = dark ? "only dark" : "only light";
    root.setAttribute("data-theme", name);
    /* setProperty keeps the "only" keyword. The colorScheme property drops it,
       and Edge then repaints the page with its own night or light colors. */
    root.style.setProperty("color-scheme", scheme);
    if (document.body) {
      document.body.setAttribute("data-theme", name);
      document.body.style.setProperty("color-scheme", scheme);
    }
    var declared = document.querySelector('meta[name="color-scheme"]');
    if (declared) declared.setAttribute("content", scheme);
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

(function () {
  function fallbackCopy(field) {
    field.focus();
    field.select();
    try {
      return document.execCommand("copy");
    } catch (err) {
      return false;
    }
  }

  function show(button, ok) {
    var previous = button.getAttribute("data-label") || button.textContent;
    button.setAttribute("data-label", previous);
    button.textContent = ok ? "Copied" : "Select and copy";
    window.setTimeout(function () {
      button.textContent = previous;
    }, 1600);
  }

  var buttons = document.querySelectorAll("[data-copy-target]");
  for (var i = 0; i < buttons.length; i++) {
    buttons[i].addEventListener("click", function () {
      var button = this;
      var field = document.getElementById(button.getAttribute("data-copy-target"));
      if (!field) return;
      var text = field.value;
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(function () {
          show(button, true);
        }, function () {
          show(button, fallbackCopy(field));
        });
        return;
      }
      show(button, fallbackCopy(field));
    });
  }
})();
