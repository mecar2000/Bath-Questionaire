/* ============================================================
   H2GV · HyLab — shared form interactions
   Header/footer are rendered by Flask/Jinja2 in base.html.
   This file handles only client-side form behaviour.
   ============================================================ */
(function () {
  "use strict";

  function wireInteractions() {
    /* radio / checkbox selected state + Other reveal */
    document.addEventListener("change", function (e) {
      const input = e.target;
      if (input.type === "radio") {
        document
          .querySelectorAll(`input[name="${input.name}"]`)
          .forEach((r) => r.closest(".option-item")?.classList.remove("selected"));
        input.closest(".option-item")?.classList.add("selected");
        const otherInput = document.querySelector(
          `.option-other-input[data-for="${input.name}"]`
        );
        if (otherInput)
          otherInput.classList.toggle("visible", input.value === "Other");
      }
      if (input.type === "checkbox" && input.closest(".option-item")) {
        input.closest(".option-item").classList.toggle("selected", input.checked);
      }
    });

    /* scale buttons */
    document.addEventListener("click", function (e) {
      const btn = e.target.closest(".scale-btn");
      if (!btn || btn.disabled) return;
      const group = btn.closest(".scale-wrap");
      group.querySelectorAll(".scale-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const hidden = group.querySelector('input[type="hidden"]');
      if (hidden) hidden.value = btn.dataset.value;
    });

    /* legend toggle */
    document.addEventListener("click", function (e) {
      const t = e.target.closest(".legend-toggle");
      if (!t) return;
      t.classList.toggle("open");
      const box = t.nextElementSibling;
      if (box) box.classList.toggle("open");
    });

    /* N/A checkbox disables its scale row */
    document.addEventListener("change", function (e) {
      if (!e.target.matches(".na-wrap input[type=checkbox]")) return;
      const wrap = e.target.closest(".scale-wrap");
      const btns = wrap.querySelectorAll(".scale-btn");
      const hidden = wrap.querySelector('input[type="hidden"]');
      if (e.target.checked) {
        btns.forEach((b) => { b.classList.remove("active"); b.disabled = true; });
        if (hidden) hidden.value = "";
      } else {
        btns.forEach((b) => (b.disabled = false));
      }
    });
  }

  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", wireInteractions);
  else wireInteractions();
})();
