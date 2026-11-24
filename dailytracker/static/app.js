(() => {
  "use strict";

  const dialog = document.getElementById("entry-dialog");
  const $ = (id) => document.getElementById(id);

  function ensureOption(select, value) {
    if (!value) return;
    if (![...select.options].some((o) => o.value === value)) {
      select.add(new Option(value, value), select.options.length ? 1 : 0);
    }
  }

  // ---- Day dialog: one block per project
  const tplData = document.getElementById("templates-data");
  const templates = tplData ? JSON.parse(tplData.textContent || "[]") : [];
  const itemsBox = $("items");
  const itemTpl = document.getElementById("item-tpl");
  let blockSeq = 0;

  function fillBlock(block, item) {
    const q = (sel) => block.querySelector(sel);
    if ("project" in item) q(".js-project").value = item.project || "";
    if ("details" in item) q(".js-details").value = item.details || "";
    if ("assignee" in item) q(".js-assignee").value = item.assignee || "";
    if (item.category) { ensureOption(q(".js-category"), item.category); q(".js-category").value = item.category; }
    if ("status" in item) { ensureOption(q(".js-status"), item.status); q(".js-status").value = item.status || ""; }
  }

  function renumber() {
    const blocks = [...itemsBox.querySelectorAll(".item-block")];
    blocks.forEach((b, i) => {
      b.querySelector(".item-title").textContent = blocks.length > 1 ? `Project ${i + 1}` : "Project";
      b.querySelector(".js-remove").hidden = blocks.length === 1;
    });
  }

  function addBlock(item, focus) {
    const frag = itemTpl.content.cloneNode(true);
    const block = frag.querySelector(".item-block");
    const n = ++blockSeq;
    // Give every field a unique id and tie its label to it.
    block.querySelectorAll("label").forEach((label) => {
      const field = label.nextElementSibling;
      if (field) { field.id = `b${n}-${field.name}`; label.htmlFor = field.id; }
    });
    block.querySelector(".js-category").value = "Core Dev - Coding";
    block.querySelector(".js-status").value = "In Progress";
    if (item) fillBlock(block, item);

    block.querySelector(".js-tpl").addEventListener("change", (e) => {
      const t = templates[Number(e.target.value)];
      if (t) fillBlock(block, { project: t.project, category: t.task, details: t.details, assignee: t.assignee, status: t.status });
      e.target.value = "";
    });
    block.querySelector(".js-remove").addEventListener("click", () => { block.remove(); renumber(); });
    block.querySelector(".js-save-tpl").addEventListener("click", () => {
      const project = block.querySelector(".js-project").value;
      const cat = block.querySelector(".js-category").value;
      const name = (prompt("Name this template:", project ? `${project} – ${cat}` : "") || "").trim();
      if (!name) return;
      $("t-name").value = name;
      $("t-project").value = project;
      $("t-category").value = cat;
      $("t-details").value = block.querySelector(".js-details").value;
      $("t-assignee").value = block.querySelector(".js-assignee").value;
      $("t-status").value = block.querySelector(".js-status").value;
      $("template-form").submit();
    });
    itemsBox.appendChild(frag);
    renumber();
    if (focus) block.querySelector(".js-project").focus();
    return block;
  }

  function openEntry(cell, override) {
    const d = cell.dataset;
    $("f-title").textContent = d.label;
    $("f-date").value = d.date;
    $("c-date").value = d.date;
    let items = [];
    try { items = JSON.parse(d.items || "[]"); } catch (_) { items = []; }
    $("f-clear").hidden = items.length === 0;
    if (override && override.length) items = override;
    itemsBox.innerHTML = "";
    (items.length ? items : [null]).forEach((item) => addBlock(item, false));
    dialog.showModal();
    itemsBox.querySelector(".js-project").focus();
  }

  if (dialog) {
    document.querySelectorAll("button.day[data-date]").forEach((cell) =>
      cell.addEventListener("click", () => openEntry(cell))
    );
    $("add-item").addEventListener("click", () => {
      const block = addBlock(null, true);
      block.scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
    dialog.querySelectorAll(".js-close").forEach((btn) =>
      btn.addEventListener("click", () => dialog.close())
    );
    dialog.addEventListener("click", (e) => {
      if (e.target === dialog) dialog.close(); // click on backdrop
    });
    $("f-clear").addEventListener("click", (e) => {
      if (!confirm("Clear everything logged for this day, for all projects?")) e.preventDefault();
    });
    // Ctrl/Cmd+Enter saves from anywhere in the form.
    $("entry-form").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) $("entry-form").requestSubmit();
    });

    // Quick-add link: open a day with fields pre-filled (still needs Save)
    const pre = document.getElementById("prefill-data");
    if (pre) {
      const p = JSON.parse(pre.textContent || "{}");
      const cell = document.querySelector(`button.day[data-date="${p.day}"]`);
      if (cell) {
        openEntry(cell, p.items);
        $("f-title").textContent = `${cell.dataset.label} · review and save`;
        history.replaceState(null, "", `?month=${p.day.slice(0, 7)}`); // so a refresh doesn't re-open it
      }
    }
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

  // ---- Import: file picker / drop zone and select-all
  const fileInput = document.getElementById("file");
  if (fileInput) {
    const zone = fileInput.closest(".dropzone");
    const show = () => { $("dz-file").textContent = fileInput.files[0] ? fileInput.files[0].name : ""; };
    fileInput.addEventListener("change", show);
    ["dragenter", "dragover"].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add("is-over"); }));
    ["dragleave", "drop"].forEach((ev) => zone.addEventListener(ev, () => zone.classList.remove("is-over")));
    zone.addEventListener("drop", (e) => {
      e.preventDefault();
      if (e.dataTransfer.files.length) { fileInput.files = e.dataTransfer.files; show(); }
    });
  }
  const toggleAll = document.getElementById("toggle-all");
  if (toggleAll) {
    const boxes = [...document.querySelectorAll(".month-check")];
    const sync = () => { toggleAll.checked = boxes.every((b) => b.checked); };
    toggleAll.addEventListener("change", () => boxes.forEach((b) => (b.checked = toggleAll.checked)));
    boxes.forEach((b) => b.addEventListener("change", sync));
    sync();
  }

  // ---- Import: upload with a real progress bar, then "comparing" while the server analyses.
  const setBar = (fill, bar, pct) => {
    fill.style.width = `${pct}%`;
    bar.setAttribute("aria-valuenow", String(Math.round(pct)));
  };
  const uploadForm = document.getElementById("upload-form");
  if (uploadForm && window.XMLHttpRequest && window.FormData) {
    uploadForm.addEventListener("submit", (e) => {
      if (!$("file").files.length) return; // let the browser show "required"
      e.preventDefault();
      const box = $("upload-progress"), fill = $("up-fill"), bar = $("up-bar");
      box.hidden = false;
      $("up-submit").disabled = true;
      const xhr = new XMLHttpRequest();
      xhr.open("POST", uploadForm.action);
      xhr.upload.addEventListener("progress", (ev) => {
        if (!ev.lengthComputable) return;
        const pct = (ev.loaded / ev.total) * 100;
        setBar(fill, bar, pct);
        $("up-pct").textContent = `${Math.round(pct)}%`;
        if (pct >= 100) {
          $("up-label").textContent = "Reading the file and comparing it with your sheet…";
          $("up-pct").textContent = "";
          fill.classList.add("is-running");
        }
      });
      xhr.addEventListener("load", () => { window.location.href = xhr.responseURL || uploadForm.action; });
      xhr.addEventListener("error", () => {
        $("up-label").textContent = "Upload failed. Check your connection and try again.";
        fill.classList.remove("is-running");
        $("up-submit").disabled = false;
      });
      xhr.send(new FormData(uploadForm));
    });
  }
  const runBtn = document.getElementById("run-import");
  if (runBtn) runBtn.form.addEventListener("submit", () => { runBtn.disabled = true; runBtn.textContent = "Starting import…"; });

  // ---- Import job: poll status and move the bar
  const job = document.getElementById("import-progress");
  if (job) {
    const fill = $("imp-fill"), bar = $("imp-bar");
    setBar(fill, bar, Number(fill.dataset.percent || 0));
    const apply = (s) => {
      setBar(fill, bar, s.percent);
      $("imp-pct").textContent = `${s.percent}%`;
      $("imp-count").textContent = `${s.done} of ${s.total} month${s.total === 1 ? "" : "s"}`;
      $("imp-written").textContent = s.written;
      $("imp-elapsed").textContent = `${s.elapsed}s`;
      $("imp-now").textContent = s.status === "running" ? (s.current ? `Writing ${s.current}…` : "Starting…") : "";
      if (s.status === "done") {
        fill.classList.remove("is-running");
        $("imp-title").textContent = "Import finished";
        $("imp-summary").textContent = `Imported ${s.written} day${s.written === 1 ? "" : "s"} into ${s.touched} month${s.touched === 1 ? "" : "s"}.`;
        $("imp-done").hidden = false;
      } else if (s.status === "error") {
        fill.classList.remove("is-running");
        fill.classList.add("is-error");
        $("imp-title").textContent = "Import stopped";
        $("imp-error-msg").textContent = s.error;
        $("imp-error").hidden = false;
      }
      return s.status === "running";
    };
    const poll = () =>
      fetch(job.dataset.statusUrl, { headers: { Accept: "application/json" }, credentials: "same-origin" })
        .then((r) => r.json())
        .then((s) => { if (apply(s)) setTimeout(poll, 800); })
        .catch(() => setTimeout(poll, 2000));
    if (!$("imp-done").hidden || !$("imp-error").hidden) fill.classList.remove("is-running");
    else poll();
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
