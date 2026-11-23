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

  // ---- Entry templates in the day dialog
  const tplData = document.getElementById("templates-data");
  const templates = tplData ? JSON.parse(tplData.textContent || "[]") : [];
  const tplSelect = $("f-template");
  if (tplSelect) {
    tplSelect.addEventListener("change", () => {
      const t = templates[Number(tplSelect.value)];
      if (!t) return;
      $("f-project").value = t.project || "";
      $("f-details").value = t.details || "";
      $("f-assignee").value = t.assignee || "";
      const cat = $("f-category");
      ensureOption(cat, t.task);
      cat.value = t.task || cat.value;
      const status = $("f-status");
      ensureOption(status, t.status);
      status.value = t.status || "";
    });
  }
  const saveTpl = $("f-save-template");
  if (saveTpl) {
    saveTpl.addEventListener("click", () => {
      const suggestion = $("f-project").value ? `${$("f-project").value} – ${$("f-category").value}` : "";
      const name = (prompt("Name this template:", suggestion) || "").trim();
      if (!name) return;
      $("t-name").value = name;
      $("t-project").value = $("f-project").value;
      $("t-category").value = $("f-category").value;
      $("t-details").value = $("f-details").value;
      $("t-assignee").value = $("f-assignee").value;
      $("t-status").value = $("f-status").value;
      $("template-form").submit();
    });
  }

  // Confirm before destructive form submits.
  document.querySelectorAll("form.js-confirm").forEach((form) =>
    form.addEventListener("submit", (e) => {
      if (!confirm(form.dataset.confirm || "Are you sure?")) e.preventDefault();
    })
  );

  // ---- Month template live preview
  const preview = document.getElementById("preview");
  const monthForm = document.getElementById("month-form");
  if (preview && monthForm) {
    const val = (name) => monthForm.elements[name] && monthForm.elements[name].value;
    const render = () => {
      const font = val("font") || "Calibri";
      const size = Number(val("font_size")) || 11;
      const border = val("border");
      preview.style.fontFamily = `${font}, Calibri, Arial, sans-serif`;
      preview.style.fontSize = `${Math.round(size * 1.15)}px`;
      preview.querySelectorAll("th").forEach((th, i) => {
        th.style.background = val("header_bg");
        th.style.color = val("header_fg");
        th.style.borderColor = border;
        th.textContent = val(`header_${i}`) || "";
        th.style.width = `${(Number(val(`width_${i}`)) || 10) * 7}px`;
      });
      preview.querySelectorAll("tr[data-wd]").forEach((tr) => {
        const wd = tr.dataset.wd;
        tr.querySelectorAll("td").forEach((td) => {
          td.style.background = val(`bg_${wd}`);
          td.style.color = val(`fg_${wd}`);
          td.style.borderColor = border;
        });
      });
      const spacers = monthForm.elements["spacer_rows"].checked;
      preview.querySelectorAll(".spacer-row").forEach((tr) => (tr.hidden = !spacers));
      preview.querySelectorAll(".js-weekend-label").forEach((el) => (el.textContent = val("weekend_label")));
    };
    monthForm.addEventListener("input", render);
    monthForm.addEventListener("change", render);
    render();
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
