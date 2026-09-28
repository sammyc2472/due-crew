// The landing pages' two small jobs, in a file so their CSP needs no
// inline script: a phone emails itself the link (index only), and Copy code.
(function () {
  var form = document.getElementById("mailme");
  if (form) form.addEventListener("submit", function (e) {
    e.preventDefault();
    var to = document.getElementById("mailto"), said = document.getElementById("mailsaid");
    if (!to.value.trim()) return;
    said.textContent = "Sending…";
    fetch("/api/links/email", { method: "POST", credentials: "same-origin",
      headers: { "content-type": "application/json", "x-due-crew": "1" },
      body: JSON.stringify({ email: to.value, path: "/" }) }).then(function (r) {
      said.textContent = r.ok ? "Sent. Open it on your computer." : r.status === 429 ? "That's a few already. Try again later." : "That doesn't look like an email address.";
      if (r.ok) to.value = "";
    }, function () { said.textContent = "That didn't send. Try again."; });
  });
  var copy = document.getElementById("copy");
  if (copy) copy.addEventListener("click", function () {
    var b = this;
    navigator.clipboard.writeText("2035408484").then(function () {
      b.textContent = "Copied";
      setTimeout(function () { b.textContent = "Copy code"; }, 1600);
    }, function () {
      // no clipboard here (an old browser, or it said no): the code is selected to copy by hand
      var r = document.createRange();
      r.selectNodeContents(document.getElementById("code"));
      var sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
    });
  });
})();
