const STATUS = {
  queued: "У черзі",
  running: "Виконується",
  done: "Готово",
  failed: "Помилка",
  cancelled: "Скасовано",
};
const FIELDS = { username: "логін", password: "пароль", n: "кількість невідомих", seed: "seed" };
const SHOWN_VALUES = 50;

let token = localStorage.getItem("token");
let limits = null;
let pollTimer = null;
let opened = null;

const $ = (id) => document.getElementById(id);

function esc(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

function formatTime(iso) {
  return iso ? new Date(iso).toLocaleString("uk-UA", { dateStyle: "short", timeStyle: "medium" }) : "—";
}

function isActive(task) {
  return task.status === "queued" || task.status === "running";
}

function errorText(data) {
  if (!data) return "";
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) {
    const names = data.detail.map((e) => FIELDS[e.loc.at(-1)] || e.loc.at(-1));
    return "Некоректне значення: " + [...new Set(names)].join(", ");
  }
  return "";
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(path, { ...options, headers });
  const data = await response.json().catch(() => null);
  if (response.status === 401 && token) {
    logout();
    throw new Error("Сесія завершилась, увійдіть знову");
  }
  if (!response.ok) throw new Error(errorText(data) || `Помилка сервера (${response.status})`);
  return data;
}

function showAuth() {
  $("auth-view").hidden = false;
  $("app-view").hidden = true;
  $("userbox").hidden = true;
}

async function showApp() {
  $("auth-view").hidden = true;
  $("app-view").hidden = false;
  $("userbox").hidden = false;
  $("username").textContent = localStorage.getItem("username") || "";
  limits = await api("/api/limits");
  $("limits").textContent =
    `Обмеження: до ${limits.max_n} невідомих (вручну — до ${limits.max_n_manual}), ` +
    `до ${limits.time_limit_seconds} с обчислення, до ${limits.max_active_tasks} задач одночасно, ` +
    `історія — до ${limits.max_history} останніх задач.`;
  $("task-form").n.max = limits.max_n;
  refresh();
  clearInterval(pollTimer);
  pollTimer = setInterval(refresh, 1500);
}

function logout() {
  token = null;
  localStorage.removeItem("token");
  localStorage.removeItem("username");
  clearInterval(pollTimer);
  opened = null;
  $("details").hidden = true;
  showAuth();
}

function taskRow(t) {
  const note = t.error || t.stage;
  const buttons = [
    isActive(t) ? `<button type="button" class="danger" data-cancel="${t.id}">Скасувати</button>` : "",
    `<button type="button" class="secondary" data-open="${t.id}">Деталі</button>`,
  ].join(" ");
  return `<tr class="${t.status}">
    <td>${t.id}</td>
    <td>${t.n}</td>
    <td>${STATUS[t.status]}</td>
    <td><div class="bar"><div style="width:${t.progress}%"></div></div>
        <small>${t.progress.toFixed(0)}% · ${esc(note)}</small></td>
    <td>${esc(t.server || "—")}</td>
    <td>${formatTime(t.created_at)}</td>
    <td class="actions">${buttons}</td>
  </tr>`;
}

async function refresh() {
  if (!token) return;
  try {
    const tasks = await api("/api/tasks");
    $("tasks").innerHTML = tasks.length
      ? tasks.map(taskRow).join("")
      : `<tr><td colspan="7" class="hint">Задач ще немає</td></tr>`;
    if (opened) {
      const current = tasks.find((t) => t.id === opened.id);
      if (!current) closeDetails();
      else if (isActive(current) || current.status !== opened.status) showDetails(current.id);
    }
  } catch (err) {
    $("task-error").textContent = err.message;
  }
}

function duration(t) {
  if (!t.started_at || !t.finished_at) return null;
  return ((new Date(t.finished_at) - new Date(t.started_at)) / 1000).toFixed(2);
}

async function showDetails(id) {
  const t = await api(`/api/tasks/${id}`);
  opened = { id: t.id, status: t.status };
  const kind = t.mode === "random" ? `випадкова система, seed = ${t.seed}` : "введена вручну";
  let html = `<h2>Задача #${t.id}</h2>
    <p>Кількість невідомих: ${t.n} (${kind})</p>
    <p>Статус: ${STATUS[t.status]}${t.stage !== STATUS[t.status] ? ` — ${esc(t.stage)}` : ""} (${t.progress.toFixed(0)}%)</p>
    <p>Сервер: ${esc(t.server || "—")}</p>`;
  const seconds = duration(t);
  if (seconds && t.status === "done") html += `<p>Час обчислення: ${seconds} с</p>`;
  if (t.error) html += `<p class="error">${esc(t.error)}</p>`;
  if (t.result) {
    const values = t.result.x.slice(0, SHOWN_VALUES).map((v, i) => `x${i + 1} = ${v.toPrecision(10)}`);
    if (t.result.x.length > SHOWN_VALUES) values.push(`… ще ${t.result.x.length - SHOWN_VALUES} значень`);
    html += `<p>Нев'язка ‖Ax − b‖ = ${t.result.residual.toExponential(3)}</p><pre>${values.join("\n")}</pre>`;
  }
  html += `<button type="button" class="secondary" id="close-details">Закрити</button>`;
  $("details").innerHTML = html;
  $("details").hidden = false;
}

function closeDetails() {
  opened = null;
  $("details").hidden = true;
}

function parseManual(text) {
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  const a = [];
  const b = [];
  lines.forEach((line, i) => {
    const numbers = line
      .replace(/,/g, ".")
      .replace("|", " ")
      .split(/[\s;]+/)
      .filter(Boolean)
      .map(Number);
    if (numbers.length < 2 || numbers.some((v) => !Number.isFinite(v))) {
      throw new Error(`Рядок ${i + 1}: некоректні числа`);
    }
    b.push(numbers.pop());
    a.push(numbers);
  });
  const n = a.length;
  if (n < 2 || n > limits.max_n_manual) {
    throw new Error(`При ручному введенні кількість рівнянь має бути від 2 до ${limits.max_n_manual}`);
  }
  if (a.some((row) => row.length !== n)) {
    throw new Error(`Кожен рядок має містити ${n} коефіцієнтів і вільний член`);
  }
  return { mode: "manual", a, b };
}

function buildTask(form) {
  if (form.mode.value === "manual") return parseManual(form.matrix.value);
  const n = Number(form.n.value);
  if (!Number.isInteger(n) || n < 2 || n > limits.max_n) {
    throw new Error(`Кількість невідомих має бути цілим числом від 2 до ${limits.max_n}`);
  }
  const task = { mode: "random", n };
  if (form.seed.value !== "") task.seed = Number(form.seed.value);
  return task;
}

$("auth-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const action = e.submitter?.value === "register" ? "register" : "login";
  $("auth-error").textContent = "";
  try {
    const data = await api(`/api/auth/${action}`, {
      method: "POST",
      body: JSON.stringify({ username: form.username.value.trim(), password: form.password.value }),
    });
    token = data.access_token;
    localStorage.setItem("token", token);
    localStorage.setItem("username", data.username);
    form.reset();
    showApp();
  } catch (err) {
    $("auth-error").textContent = err.message;
  }
});

$("task-form").addEventListener("change", (e) => {
  if (e.target.name !== "mode") return;
  const manual = e.target.value === "manual";
  $("manual-fields").hidden = !manual;
  $("random-fields").hidden = manual;
});

$("task-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("task-error").textContent = "";
  try {
    await api("/api/tasks", { method: "POST", body: JSON.stringify(buildTask(e.target)) });
    refresh();
  } catch (err) {
    $("task-error").textContent = err.message;
  }
});

$("tasks").addEventListener("click", async (e) => {
  const button = e.target.closest("button");
  if (!button) return;
  try {
    if (button.dataset.cancel) {
      await api(`/api/tasks/${button.dataset.cancel}/cancel`, { method: "POST" });
      refresh();
    } else if (button.dataset.open) {
      await showDetails(Number(button.dataset.open));
    }
  } catch (err) {
    $("task-error").textContent = err.message;
  }
});

$("details").addEventListener("click", (e) => {
  if (e.target.id === "close-details") closeDetails();
});

$("logout").addEventListener("click", logout);

if (token) {
  api("/api/auth/me").then(showApp).catch(showAuth);
} else {
  showAuth();
}
