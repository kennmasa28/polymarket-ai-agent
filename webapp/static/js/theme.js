// Apply the saved theme before first paint (no flash); classic script on purpose.
(function () {
  var t = null;
  try { t = localStorage.getItem("pa-theme"); } catch (e) {}
  document.documentElement.setAttribute("data-theme", t || "auto");
})();
