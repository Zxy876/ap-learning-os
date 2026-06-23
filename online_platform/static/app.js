const app = document.querySelector("#app");
const subtitle = document.querySelector("#subtitle");

function routeName() {
  const path = window.location.pathname.replace("/", "");
  return path || "workspace";
}

function setActive(route) {
  document.querySelectorAll("nav a").forEach((a) => {
    a.classList.toggle("active", a.dataset.route === route);
  });
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
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

function statusPill(status) {
  const cls = status === "completed" ? "pill good" : status === "failed" || status === "not_completed" ? "pill bad" : "pill";
  return el("span", { class: cls, text: status || "planned" });
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
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
  const addEvidence = el("button", { text: "Add Evidence" });
  addEvidence.addEventListener("click", async () => {
    await api(`/api/tasks/${task.id}/evidence`, {
      method: "POST",
      body: JSON.stringify({ artifact_type: "note", text_note: note.value }),
    });
    renderTaskDetail(await api(`/api/tasks/${task.id}`), detail);
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
    ...task.evidence.map((item) => el("div", { class: "material" }, [el("strong", { text: item.artifact_type }), el("p", { text: item.text_note || item.storage_key })])),
    note,
    el("div", { class: "actions" }, [addEvidence, requestReview]),
  );
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
    ...task.evidence.map((item) => el("div", { class: "material" }, [el("strong", { text: item.artifact_type }), el("p", { text: item.text_note || item.storage_key })])),
    el("h3", { text: "Decision" }),
    el("label", { text: "Final state" }, [state]),
    el("label", { text: "Failure type" }, [failure]),
    message,
    el("div", { class: "actions" }, [decide]),
  );
}

async function renderAuthor() {
  setActive("author");
  subtitle.textContent = "Author sandbox summary";
  const data = await api("/api/author/compiles");
  const list = el("section", { class: "list" });
  if (!data.compiles.length) {
    list.append(el("section", { class: "empty" }, [el("h2", { text: "No compiles" }), el("p", { text: "Import a compile snapshot first." })]));
  }
  data.compiles.forEach((compile) => {
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
    ]));
  });
  app.replaceChildren(list);
}

async function boot() {
  try {
    const route = routeName();
    if (route === "review") await renderReview();
    else if (route === "author") await renderAuthor();
    else await renderWorkspace();
  } catch (error) {
    renderError(error);
  }
}

boot();
