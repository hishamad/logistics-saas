// Applies the saved (or the computer's) theme before the page paints, so there is no flash.
(function () {
  var theme = null;
  try {
    theme = localStorage.getItem("theme");
  } catch (e) {}
  if (theme !== "night" && theme !== "day") {
    theme = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "day" : "night";
  }
  document.documentElement.setAttribute("data-theme", theme);
})();
