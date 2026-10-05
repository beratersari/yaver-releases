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
  if (!button) return;
  button.addEventListener("click", function () {
    var next = current() === "dark" ? "light" : "dark";
    try {
      localStorage.setItem(key, next);
    } catch (err) {
      /* private mode still switches for this tab */
    }
    apply(next);
  });
})();
