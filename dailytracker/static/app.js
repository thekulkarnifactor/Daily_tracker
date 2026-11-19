(() => {
  "use strict";

  const dialog = document.getElementById("entry-dialog");
  const $ = (id) => document.getElementById(id);

  function ensureOption(select, value) {
    if (!value) return;
    if (![...select.options].some((o) => o.value === value)) {
      select.add(new Option(value, value), 0);
    }
  }

  function openEntry(cell) {
    const d = cell.dataset;
    $("f-title").textContent = d.label;
    $("f-date").value = d.date;
    $("c-date").value = d.date;
    $("f-project").value = d.project || "";
    $("f-details").value = d.details || "";
    $("f-assignee").value = d.assignee || "";

    const cat = $("f-category");
    ensureOption(cat, d.task);
    cat.value = d.task || "Core Dev - Coding";

    const status = $("f-status");
    ensureOption(status, d.status);
    status.value = d.status || "In Progress";

    $("f-clear").hidden = !(d.project || d.task || d.details);
    dialog.showModal();
    $("f-project").focus();
  }

  if (dialog) {
    document.querySelectorAll("button.day[data-date]").forEach((cell) =>
      cell.addEventListener("click", () => openEntry(cell))
    );
    dialog.querySelectorAll(".js-close").forEach((btn) =>
      btn.addEventListener("click", () => dialog.close())
    );
    dialog.addEventListener("click", (e) => {
      if (e.target === dialog) dialog.close(); // click on backdrop
    });
    $("f-clear").addEventListener("click", (e) => {
      if (!confirm("Clear everything logged for this day?")) e.preventDefault();
    });
    // Ctrl/Cmd+Enter saves from anywhere in the form.
    $("entry-form").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) $("entry-form").requestSubmit();
    });
  }

  // Auto-submit the month picker.
  document.querySelectorAll("form.js-autosubmit select").forEach((sel) =>
    sel.addEventListener("change", () => sel.form.submit())
  );

  // Keyboard month navigation: ← / →
  document.addEventListener("keydown", (e) => {
    if (dialog && dialog.open) return;
    if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return;
    const link = e.key === "ArrowLeft" ? '[aria-label="Previous month"]'
      : e.key === "ArrowRight" ? '[aria-label="Next month"]' : null;
    if (link) document.querySelector(link)?.click();
  });

  // Fade out toasts.
  document.querySelectorAll(".toast").forEach((t) => {
    setTimeout(() => t.classList.add("hide"), 3500);
    setTimeout(() => t.remove(), 4000);
  });

  // Bring the edited / current day into view.
  const target = location.hash ? document.querySelector(location.hash) : document.querySelector(".is-today");
  if (target && window.innerWidth < 760) target.scrollIntoView({ block: "center" });
})();
