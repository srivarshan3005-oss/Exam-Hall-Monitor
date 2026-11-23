(function () {
  var b = document.getElementById("print-btn");
  if (b) b.addEventListener("click", function () { window.print(); });
  if (/[?&]print=1/.test(location.search)) { window.addEventListener("load", function () { setTimeout(function () { window.print(); }, 300); }); }
})();
