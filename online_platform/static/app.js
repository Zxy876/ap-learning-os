const app = document.querySelector("#app");
const subtitle = document.querySelector("#subtitle");

function basePath() {
  const path = window.location.pathname;
  if (path === "/aplos" || path.startsWith("/aplos/")) return "/aplos";
  return "";
}

function routeName() {
  const base = basePath();
  const raw = base ? window.location.pathname.slice(base.length) || "/" : window.location.pathname;
  const path = raw.replace("/", "");
  return path || "workspace";
}

function setActive(route) {
  document.querySelectorAll("nav a").forEach((a) => {
    a.classList.toggle("active", a.dataset.route === route);
  });
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  const response = await fetch(`${basePath()}${path}`, {
    headers,
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || response.statusText);
  }
  return data;
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "html") node.innerHTML = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) {
    if (child === null || child === undefined) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function renderError(error) {
  app.prepend(el("div", { class: "error", text: error.message || String(error) }));
}

function renderRouteError(route, error) {
  app.replaceChildren(
    el("div", { class: "error", text: error.message || String(error) }),
  );
}

function statusPill(status) {
  const cls = ["completed", "active"].includes(status)
    ? "pill good"
    : ["failed", "not_completed", "archived"].includes(status)
      ? "pill bad"
      : status === "sandbox"
        ? "pill warn"
        : "pill";
  return el("span", { class: cls, text: status || "planned" });
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

async function renderWorkspace() {
  setActive("workspace");
  subtitle.textContent = "Executor workspace";
  const dateInput = el("input", { type: "date", value: new URLSearchParams(location.search).get("date") || todayIso() });
  const list = el("section", { class: "list" });
  const detail = el("aside", { class: "detail" }, [el("p", { text: "Select a task." })]);
  const load = async () => {
    list.replaceChildren();
    detail.replaceChildren(el("p", { text: "Select a task." }));
    const data = await api(`/api/workspace/today?date=${dateInput.value}`);
    if (!data.tasks.length) {
      list.append(el("section", { class: "empty" }, [el("h2", { text: "No tasks" }), el("p", { text: "No task instances for this date." })]));
      return;
    }
  data.tasks.forEach((task) => list.append(taskCard(task, detail)));
  };
  const button = el("button", { class: "primary", text: "Load" });
  button.addEventListener("click", () => load().catch(renderError));
  app.replaceChildren(
    el("div", { class: "toolbar" }, [el("label", { text: "Date" }, [dateInput]), button]),
    el("div", { class: "grid" }, [list, detail]),
  );
  await load();
}

function taskCard(task, detail) {
  const card = el("article", { class: "record" });
  card.append(
    el("h3", { text: task.title }),
    el("div", { class: "meta" }, [
      statusPill(task.status),
      el("span", { class: "pill", text: task.course }),
      el("span", { class: "pill", text: `${task.target_minutes} min` }),
      el("span", { class: "pill", text: `${task.evidence_count} evidence` }),
    ]),
    el("p", { text: task.observable_goal }),
  );
  const open = el("button", { text: "Open" });
  open.addEventListener("click", async () => {
    document.querySelectorAll(".record.selected").forEach((item) => item.classList.remove("selected"));
    card.classList.add("selected");
    const full = await api(`/api/tasks/${task.id}`);
    renderTaskDetail(full, detail);
  });
  card.append(el("div", { class: "actions" }, [open]));
  return card;
}

function renderTaskDetail(task, detail) {
  const materials = el("div", { class: "materials" });
  task.materials.forEach((material) => {
    const url = material.browser_url || material.external_url;
    const link = url ? el("a", { href: url, target: "_blank", rel: "noreferrer", text: url }) : el("span", { text: material.local_target || "unpublished" });
    materials.append(el("div", { class: "material" }, [
      el("strong", { text: `${material.role} · ${material.label}` }),
      el("div", {}, [link]),
      material.page_start ? el("p", { text: `pages ${material.page_start}-${material.page_end}` }) : null,
    ]));
  });
  const note = el("textarea", { placeholder: "Evidence note, screenshot description, or external file link." });
  const evidenceFile = el("input", { type: "file", accept: "image/*,application/pdf,.txt,.md" });
  const uploadStatus = el("div", { class: "muted" });
  const addEvidence = el("button", { text: "Add Evidence" });
  addEvidence.addEventListener("click", async () => {
    try {
      uploadStatus.textContent = "Saving note...";
      await api(`/api/tasks/${task.id}/evidence`, {
        method: "POST",
        body: JSON.stringify({ artifact_type: "note", text_note: note.value }),
      });
      renderTaskDetail(await api(`/api/tasks/${task.id}`), detail);
    } catch (error) {
      uploadStatus.replaceChildren(el("div", { class: "error", text: error.message || String(error) }));
    }
  });
  const uploadEvidence = el("button", { text: "Upload Evidence File" });
  uploadEvidence.addEventListener("click", async () => {
    try {
      const file = evidenceFile.files && evidenceFile.files[0];
      if (!file) throw new Error("Choose a file first.");
      uploadStatus.textContent = `Uploading ${file.name}...`;
      const dataUrl = await fileToDataUrl(file);
      await api(`/api/tasks/${task.id}/evidence-upload`, {
        method: "POST",
        body: JSON.stringify({
          artifact_type: file.type && file.type.startsWith("image/") ? "screenshot" : "file",
          filename: file.name,
          content_type: file.type,
          data_base64: dataUrl,
          text_note: note.value,
        }),
      });
      uploadStatus.textContent = "Uploaded.";
      renderTaskDetail(await api(`/api/tasks/${task.id}`), detail);
    } catch (error) {
      uploadStatus.replaceChildren(el("div", { class: "error", text: error.message || String(error) }));
    }
  });
  const requestReview = el("button", { class: "primary", text: "Request Review" });
  requestReview.addEventListener("click", async () => {
    await api(`/api/tasks/${task.id}/review-requests`, { method: "POST" });
    renderTaskDetail(await api(`/api/tasks/${task.id}`), detail);
  });
  detail.replaceChildren(
    el("h2", { text: task.title }),
    el("div", { class: "meta" }, [statusPill(task.status), el("span", { class: "pill", text: `${task.target_minutes} min` })]),
    el("h3", { text: "Materials" }),
    materials,
    el("h3", { text: "Evidence" }),
    ...task.evidence.map((item) => evidenceBlock(item)),
    note,
    evidenceFile,
    el("div", { class: "actions" }, [addEvidence, uploadEvidence, requestReview]),
    uploadStatus,
  );
}

function evidenceBlock(item) {
  const metadata = item.metadata || {};
  const href = item.storage_key ? `${basePath()}/files/${item.storage_key}` : "";
  const isImage = item.artifact_type === "screenshot" || (metadata.content_type || "").startsWith("image/");
  const title = metadata.filename || item.storage_key || item.artifact_type;
  return el("div", { class: "material" }, [
    el("strong", { text: item.artifact_type }),
    item.text_note ? el("p", { text: item.text_note }) : null,
    href ? el("a", { href, target: "_blank", rel: "noreferrer", text: title }) : null,
    href && isImage ? el("a", { href, target: "_blank", rel: "noreferrer" }, [
      el("img", { class: "evidence-image", src: href, alt: title }),
    ]) : null,
    !item.text_note && !href ? el("p", { class: "muted", text: "Empty note evidence." }) : null,
  ]);
}

function materialPreviewLine(material) {
  const url = material.browser_url || material.external_url;
  const target = url || material.local_target || material.label || "unpublished";
  const pageText = material.page_start ? ` · pages ${material.page_start}-${material.page_end || material.page_start}` : "";
  const state = material.missing
    ? "missing"
    : material.browser_openable || url
      ? "openable"
      : "indexed";
  return el("li", {}, [
    el("strong", { text: `${material.role}: ` }),
    url
      ? el("a", { href: url, target: "_blank", rel: "noreferrer", text: target })
      : el("span", { text: target }),
    el("span", { class: material.missing ? "inline-bad" : "muted", text: `${pageText} · ${state}` }),
  ]);
}

function authorTaskPreviewCard(task) {
  const materials = task.materials && task.materials.length
    ? el("ul", { class: "compact-list" }, task.materials.map(materialPreviewLine))
    : el("p", { class: "muted", text: "No material is attached to this task." });
  return el("article", { class: "preview-task" }, [
    el("h4", { text: task.title }),
    el("div", { class: "meta" }, [
      statusPill(task.status),
      el("span", { class: "pill", text: task.course }),
      el("span", { class: "pill", text: `${task.target_minutes} min` }),
    ]),
    el("p", { text: task.observable_goal }),
    materials,
  ]);
}

function authorWorkspacePreview(compile) {
  const dateInput = el("input", { type: "date", value: compile.start_date || todayIso() });
  const preview = el("div", { class: "preview-box" }, [
    el("p", { class: "muted", text: "Choose a date to see exactly what the executor workspace would show for this sandbox." }),
  ]);
  const load = el("button", { text: "Preview B Workspace" });
  const loadPreview = async () => {
    preview.replaceChildren(el("p", { class: "muted", text: "Loading preview..." }));
    const data = await api(`/api/author/compiles/${compile.id}/preview?date=${dateInput.value}`);
    if (!data.tasks.length) {
      preview.replaceChildren(el("p", { class: "muted", text: "No executor tasks generated for this date." }));
      return;
    }
    preview.replaceChildren(...data.tasks.map(authorTaskPreviewCard));
  };
  load.addEventListener("click", () => loadPreview().catch((error) => {
    preview.replaceChildren(el("div", { class: "error", text: error.message || String(error) }));
  }));
  return el("details", { class: "sandbox-preview" }, [
    el("summary", { text: "B Workspace Preview" }),
    el("div", { class: "toolbar" }, [
      el("label", { text: "Preview Date" }, [dateInput]),
      load,
    ]),
    preview,
  ]);
}

async function renderReview() {
  setActive("review");
  subtitle.textContent = "Supervisor review queue";
  const list = el("section", { class: "list" });
  const detail = el("aside", { class: "detail" }, [el("p", { text: "Select a review request." })]);
  const load = async () => {
    list.replaceChildren();
    const data = await api("/api/review/queue");
    if (!data.review_requests.length) {
      list.append(el("section", { class: "empty" }, [el("h2", { text: "Queue clear" }), el("p", { text: "No open review requests." })]));
      return;
    }
    data.review_requests.forEach((request) => list.append(reviewCard(request, detail, load)));
  };
  app.replaceChildren(el("div", { class: "grid" }, [list, detail]));
  await load();
}

function reviewCard(request, detail, reload) {
  const card = el("article", { class: "record" }, [
    el("h3", { text: request.title }),
    el("div", { class: "meta" }, [
      statusPill(request.task_status),
      el("span", { class: "pill", text: request.course }),
      el("span", { class: "pill", text: `${request.evidence_count} evidence` }),
    ]),
  ]);
  const inspect = el("button", { text: "Inspect" });
  inspect.addEventListener("click", async () => {
    const task = await api(`/api/tasks/${request.task_instance_id}`);
    renderReviewDetail(request, task, detail, reload);
  });
  card.append(el("div", { class: "actions" }, [inspect]));
  return card;
}

function renderReviewDetail(request, task, detail, reload) {
  const state = el("select", {}, ["completed", "partial", "not_completed", "failed", "blocked"].map((value) => el("option", { value, text: value })));
  const failure = el("select", {}, ["", "insufficient_evidence", "wrong_resource", "insufficient_time", "incomplete_work", "low_quality_work", "misunderstood_task", "access_blocked", "technical_blocked", "external_blocked", "other"].map((value) => el("option", { value, text: value || "none" })));
  const message = el("textarea", { placeholder: "Reviewer message." });
  const decide = el("button", { class: "primary", text: "Submit Decision" });
  decide.addEventListener("click", async () => {
    await api(`/api/review/requests/${request.review_request_id}/decision`, {
      method: "POST",
      body: JSON.stringify({ final_state: state.value, failure_type: failure.value, message: message.value }),
    });
    await reload();
    detail.replaceChildren(el("p", { text: "Decision saved." }));
  });
  detail.replaceChildren(
    el("h2", { text: task.title }),
    el("div", { class: "meta" }, [statusPill(task.status), el("span", { class: "pill", text: task.source_lineage.sheet }), el("span", { class: "pill", text: `row ${task.source_lineage.row_number}` })]),
    el("h3", { text: "Evidence" }),
    ...(task.evidence.length ? task.evidence.map((item) => evidenceBlock(item)) : [el("p", { class: "muted", text: "No evidence uploaded yet." })]),
    el("h3", { text: "Decision" }),
    el("label", { text: "Final state" }, [state]),
    el("label", { text: "Failure type" }, [failure]),
    message,
    el("div", { class: "actions" }, [decide]),
  );
}

async function renderAuthor() {
  setActive("author");
  subtitle.textContent = "Author sandbox: compile plans, preview executor tasks, then publish";
  const compileStart = el("input", { type: "date", value: todayIso() });
  const compileDays = el("input", { type: "number", min: "1", max: "370", value: "30" });
  const planFiles = el("input", { type: "file", accept: ".xlsx,.xlsm", multiple: "multiple" });
  const resourceZipFile = el("input", { type: "file", accept: ".zip" });
  const compileResult = el("pre", { class: "result", text: "" });
  const compileButton = el("button", { class: "primary", text: "Compile + Import From Excel Plans" });
  compileButton.addEventListener("click", async () => {
    try {
      const selectedPlans = Array.from(planFiles.files || []);
      const zipFile = resourceZipFile.files && resourceZipFile.files[0];
      if (!selectedPlans.length) throw new Error("Choose at least one plan Excel file.");
      const toPayload = async (file) => ({
        filename: file.name,
        content_type: file.type,
        data_base64: await fileToDataUrl(file),
      });
      compileResult.textContent = "Uploading and compiling on server...";
      const result = await api("/api/author/compile-from-plans", {
        method: "POST",
        body: JSON.stringify({
          organization_id: "org_hosted_ap_learning_os",
          organization_name: "Hosted AP Learning OS",
          start_date: compileStart.value,
          days: Number(compileDays.value || 30),
          plan_files: await Promise.all(selectedPlans.map(toPayload)),
          resource_zip_file: zipFile ? await toPayload(zipFile) : null,
          publish_materials: true,
          base_url: `${window.location.origin}${basePath()}`,
        }),
      });
      compileResult.textContent = `${JSON.stringify(result, null, 2)}\n\nSandbox created. Publish it only after preview looks right.`;
      await renderAuthor();
    } catch (error) {
      compileResult.textContent = `Error: ${error.message || String(error)}`;
    }
  });
  const tools = el("section", { class: "record" }, [
    el("h2", { text: "Compile From Excel Plans" }),
    el("p", { class: "muted", text: "Upload one or more plan spreadsheets and one optional resource ZIP. The result stays in sandbox until you publish it." }),
    el("div", { class: "toolbar" }, [
      el("label", { text: "Start Date" }, [compileStart]),
      el("label", { text: "Days" }, [compileDays]),
      el("label", { text: "Plan Excel(s)" }, [planFiles]),
      el("label", { text: "Resource ZIP optional" }, [resourceZipFile]),
    ]),
    el("div", { class: "actions" }, [compileButton]),
    compileResult,
  ]);
  const data = await api("/api/author/compiles");
  const list = el("section", { class: "list" });
  if (!data.compiles.length) {
    list.append(el("section", { class: "empty" }, [el("h2", { text: "No sandboxes" }), el("p", { text: "Upload one plan Excel and an optional resource ZIP to compile a sandbox." })]));
  }
  data.compiles.forEach((compile) => {
    const publish = el("button", { class: compile.status === "active" ? "" : "primary", text: compile.status === "active" ? "Already Active" : "Publish to Workspace" });
    publish.disabled = compile.status === "active";
    publish.addEventListener("click", async () => {
      publish.textContent = "Publishing...";
      await api(`/api/author/compiles/${compile.id}/publish`, { method: "POST", body: JSON.stringify({}) });
      await renderAuthor();
    });
    const meaning = compile.status === "sandbox"
      ? "Sandbox only: visible here for checking, not used by the executor workspace."
      : compile.status === "active"
        ? "Active: executor workspace uses this compile for matching courses."
        : "Archived: kept for history, not used by the executor workspace.";
    list.append(el("article", { class: "record" }, [
      el("h3", { text: compile.compile_id }),
      el("div", { class: "meta" }, [
        statusPill(compile.status),
        el("span", { class: "pill", text: `${compile.plan_steps} steps` }),
        el("span", { class: "pill", text: `${compile.task_instances} tasks` }),
        el("span", { class: compile.missing_materials ? "pill bad" : "pill good", text: `${compile.missing_materials} missing` }),
        el("span", { class: "pill", text: `${compile.published_materials}/${compile.material_records} materials published` }),
      ]),
      el("p", { text: `Start ${compile.start_date}, ${compile.days} days, courses ${compile.courses.join(", ")}` }),
      el("p", { class: "muted", text: meaning }),
      el("div", { class: "actions" }, [publish]),
      authorWorkspacePreview(compile),
    ]));
  });
  app.replaceChildren(tools, list);
}

async function boot() {
  const route = routeName();
  try {
    if (route === "review") await renderReview();
    else if (route === "author") await renderAuthor();
    else await renderWorkspace();
  } catch (error) {
    renderRouteError(route, error);
  }
}

boot();
