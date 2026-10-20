// Applies the chosen colour theme before the page is painted, so a dark choice does not flash white first.
// "System" is the absence of a choice: nothing is set and the stylesheet follows the operating system.
// A separate file (not inline) because the app's content security policy allows scripts only from itself.
try {
  var v = localStorage.getItem("rekamind.theme");
  if (v === "light" || v === "dark") document.documentElement.setAttribute("data-theme", v);
} catch (e) { /* storage blocked: follow the system */ }
