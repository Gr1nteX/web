const STATUS = { queued: "У черзі", running: "Виконується" };

const $ = (id) => document.getElementById(id);
const token = localStorage.getItem("token");

function esc(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

function formatTime(iso) {
  return iso ? new Date(iso).toLocaleString("uk-UA", { dateStyle: "short", timeStyle: "medium" }) : "—";
}

function formatWait(seconds) {
  const total = Math.ceil(seconds);
  return total < 60 ? `${total} с` : `${Math.floor(total / 60)} хв ${total % 60} с`;
}

function stat(label, value) {
  return `<div class="stat"><span>${label}</span><strong>${value}</strong></div>`;
}

function serverRow(s) {
  return `<tr>
    <td>${esc(s.name)}</td>
    <td>${s.auto ? '<span class="badge">автоматичний</span>' : "базовий"}</td>
    <td><div class="bar"><div style="width:${(s.busy / s.slots) * 100}%"></div></div>
        <small>${s.busy} / ${s.slots}</small></td>
    <td>${s.cpu === null ? "—" : `${s.cpu.toFixed(0)}%`}</td>
    <td>${s.memory_mb === null ? "—" : `${s.memory_mb.toFixed(0)} МБ`}</td>
    <td>${formatTime(s.started_at)}</td>
    <td>${formatTime(s.last_seen)}</td>
  </tr>`;
}

function taskNote(t) {
  if (t.status !== "queued" || !t.queue_position) return t.stage;
  if (t.wait_seconds === null) return `Позиція ${t.queue_position}, немає доступних серверів`;
  return `Позиція ${t.queue_position}, очікування ≈ ${formatWait(t.wait_seconds)}`;
}

function taskRow(t) {
  return `<tr class="${t.status}">
    <td>${t.id}</td>
    <td>${esc(t.user)}</td>
    <td>${t.n}</td>
    <td>${STATUS[t.status]}</td>
    <td>${esc(t.server || "—")}</td>
    <td><div class="bar"><div style="width:${t.progress}%"></div></div>
        <small>${t.progress.toFixed(0)}% · ${esc(taskNote(t))}</small></td>
    <td>${formatTime(t.created_at)}</td>
  </tr>`;
}

function render(data) {
  const slots = data.servers.reduce((sum, s) => sum + s.slots, 0);
  const busy = data.servers.reduce((sum, s) => sum + s.busy, 0);
  const counts = data.counts;
  $("stats").innerHTML = [
    stat("Сервери", `${data.servers.length} / ${data.max_servers}`),
    stat("Зайнято слотів", `${busy} / ${slots}`),
    stat("У черзі", counts.queued || 0),
    stat("Виконується", counts.running || 0),
    stat("Виконано", counts.done || 0),
    stat("Помилки", counts.failed || 0),
    stat("Скасовано", counts.cancelled || 0),
    stat("Користувачів", data.users),
  ].join("");
  $("servers").innerHTML = data.servers.length
    ? data.servers.map(serverRow).join("")
    : `<tr><td colspan="7" class="hint">Немає активних серверів</td></tr>`;
  $("tasks").innerHTML = data.tasks.length
    ? data.tasks.map(taskRow).join("")
    : `<tr><td colspan="7" class="hint">Активних задач немає</td></tr>`;
}

async function refresh() {
  try {
    const response = await fetch("/api/admin/overview", { headers: { Authorization: `Bearer ${token}` } });
    const server = response.headers.get("X-Server");
    if (server) $("served-by").textContent = `Відповів сервер: ${server}`;
    if (response.status === 401) return location.replace("/");
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `Помилка сервера (${response.status})`);
    $("error").textContent = "";
    render(data);
  } catch (err) {
    $("error").textContent = err.message;
  }
}

if (!token) {
  location.replace("/");
} else {
  refresh();
  setInterval(refresh, 2000);
}
