const statusLabels = {
  idea: "Idea",
  design: "Design",
  ready: "Ready",
  posted: "Posted",
};

const statusOrder = ["idea", "design", "ready", "posted"];
const ACTOR_NAME = "dashboard-ui";

const state = {
  kanban: null,
  calendar: null,
  analytics: null,
  selectedTask: null,
  selectedTaskId: null,
  activeTab: "content",
  toastTimer: null,
  draggingTaskId: null,
  visibleFields: {
    type: true,
    airDate: true,
    assignee: true,
    missing: true,
  },
};

const dom = {
  refreshBtn: document.getElementById("refreshBtn"),
  runRemindersBtn: document.getElementById("runRemindersBtn"),
  seedDemoBtn: document.getElementById("seedDemoBtn"),
  createTaskBtn: document.getElementById("createTaskBtn"),
  upcomingMetric: document.getElementById("upcomingMetric"),
  inProgressMetric: document.getElementById("inProgressMetric"),
  completedMetric: document.getElementById("completedMetric"),
  upcomingNote: document.getElementById("upcomingNote"),
  inProgressNote: document.getElementById("inProgressNote"),
  completedNote: document.getElementById("completedNote"),
  heroBadges: document.getElementById("heroBadges"),
  timelineAxis: document.getElementById("timelineAxis"),
  timelineLanes: document.getElementById("timelineLanes"),
  kanbanMeta: document.getElementById("kanbanMeta"),
  kanbanColumns: document.getElementById("kanbanColumns"),
  messageList: document.getElementById("messageList"),
  todayTaskList: document.getElementById("todayTaskList"),
  todayCount: document.getElementById("todayCount"),
  detailPanel: document.getElementById("detailPanel"),
  detailTitle: document.getElementById("detailTitle"),
  detailMeta: document.getElementById("detailMeta"),
  detailTabs: document.getElementById("detailTabs"),
  statusSelect: document.getElementById("statusSelect"),
  closeDetailBtn: document.getElementById("closeDetailBtn"),
  deleteTaskBtn: document.getElementById("deleteTaskBtn"),
  contentForm: document.getElementById("contentForm"),
  contentTitle: document.getElementById("contentTitle"),
  contentCaption: document.getElementById("contentCaption"),
  contentHashtags: document.getElementById("contentHashtags"),
  contentMentions: document.getElementById("contentMentions"),
  contentAssignee: document.getElementById("contentAssignee"),
  contentCampaign: document.getElementById("contentCampaign"),
  contentAirDate: document.getElementById("contentAirDate"),
  mediaForm: document.getElementById("mediaForm"),
  mediaProductUrl: document.getElementById("mediaProductUrl"),
  mediaUrls: document.getElementById("mediaUrls"),
  mediaList: document.getElementById("mediaList"),
  checklistForm: document.getElementById("checklistForm"),
  checklistInput: document.getElementById("checklistInput"),
  commentForm: document.getElementById("commentForm"),
  commentInput: document.getElementById("commentInput"),
  commentList: document.getElementById("commentList"),
  activityList: document.getElementById("activityList"),
  taskModalBackdrop: document.getElementById("taskModalBackdrop"),
  closeCreateModalBtn: document.getElementById("closeCreateModalBtn"),
  createTaskForm: document.getElementById("createTaskForm"),
  newTitle: document.getElementById("newTitle"),
  newType: document.getElementById("newType"),
  newStatus: document.getElementById("newStatus"),
  newAirDate: document.getElementById("newAirDate"),
  newAssignee: document.getElementById("newAssignee"),
  newCampaign: document.getElementById("newCampaign"),
  newCaption: document.getElementById("newCaption"),
  newHashtags: document.getElementById("newHashtags"),
  newMentions: document.getElementById("newMentions"),
  newProductUrl: document.getElementById("newProductUrl"),
  newMediaUrls: document.getElementById("newMediaUrls"),
  toast: document.getElementById("toast"),
  showTypeField: document.getElementById("showTypeField"),
  showAirDateField: document.getElementById("showAirDateField"),
  showAssigneeField: document.getElementById("showAssigneeField"),
  showMissingField: document.getElementById("showMissingField"),
};

function escapeHtml(input) {
  return String(input)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function parseSpaceList(raw) {
  return String(raw || "")
    .split(/\s+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function parseLineList(raw) {
  return String(raw || "")
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

function onlyDateKey(dateStr) {
  if (!dateStr) return "";
  const date = new Date(dateStr);
  if (Number.isNaN(date.valueOf())) return "";
  return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`;
}

function fmtDate(dateStr, withTime = true) {
  if (!dateStr) return "No air date";
  const date = new Date(dateStr);
  if (Number.isNaN(date.valueOf())) return "Invalid date";
  const options = withTime
    ? { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }
    : { month: "short", day: "numeric" };
  return new Intl.DateTimeFormat("en-US", options).format(date);
}

function inputDatetimeValue(dateStr) {
  if (!dateStr) return "";
  const date = new Date(dateStr);
  if (Number.isNaN(date.valueOf())) return "";
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  return `${year}-${month}-${day}T${hour}:${minute}`;
}

function initials(name) {
  if (!name) return "NA";
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() || "")
    .join("") || "NA";
}

function flattenKanban(kanban) {
  return statusOrder.flatMap((status) => kanban?.[status] || []);
}

function showToast(message, isError = false) {
  if (!dom.toast) return;
  dom.toast.hidden = false;
  dom.toast.textContent = message;
  dom.toast.classList.toggle("error", isError);
  if (state.toastTimer) {
    clearTimeout(state.toastTimer);
  }
  state.toastTimer = window.setTimeout(() => {
    dom.toast.hidden = true;
    dom.toast.classList.remove("error");
  }, 2400);
}

async function requestJson(url, options = {}) {
  const init = { ...options };
  if (init.body && typeof init.body !== "string") {
    init.body = JSON.stringify(init.body);
    init.headers = {
      ...(init.headers || {}),
      "Content-Type": "application/json",
    };
  }
  const response = await fetch(url, init);
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const detail = data?.detail ? `: ${data.detail}` : "";
    throw new Error(`${response.status}${detail}`);
  }
  return data;
}

async function loadDashboard() {
  try {
    const [kanban, calendar, analytics] = await Promise.all([
      requestJson("/dashboard/kanban"),
      requestJson("/dashboard/calendar"),
      requestJson("/analytics/basic"),
    ]);
    state.kanban = kanban;
    state.calendar = calendar;
    state.analytics = analytics;

    const allTasks = flattenKanban(kanban);
    renderHeroBadges(analytics, allTasks);
    renderMetrics(kanban, analytics);
    renderTimeline(calendar);
    renderKanban(kanban);
    renderMessages(allTasks);
    renderToday(calendar);
  } catch (error) {
    showToast(`Failed to load dashboard (${error.message})`, true);
  }
}

function renderHeroBadges(analytics, allTasks) {
  const badges = [
    `This week: ${analytics.total_this_week ?? 0}`,
    `Overdue: ${analytics.overdue_count ?? 0}`,
    `Campaigns: ${analytics.campaign_count ?? 0}`,
    `Assignees: ${new Set(allTasks.map((task) => task.assignee).filter(Boolean)).size}`,
  ];

  dom.heroBadges.innerHTML = badges
    .map((badge, index) => {
      const extraClass = index === 1 ? "overdue-pill" : "";
      return `<span class="pill ${extraClass}" data-animate style="animation-delay:${index * 50}ms">${escapeHtml(badge)}</span>`;
    })
    .join("");
}

function renderMetrics(kanban, analytics) {
  const tasks = flattenKanban(kanban);
  const now = new Date();
  const upcoming = tasks.filter((task) => task.status !== "posted" && task.air_date && new Date(task.air_date) >= now).length;
  const inProgress = tasks.filter((task) => task.status === "design" || task.status === "ready").length;
  const completed = tasks.filter((task) => task.status === "posted").length;

  dom.upcomingMetric.textContent = String(upcoming);
  dom.inProgressMetric.textContent = String(inProgress);
  dom.completedMetric.textContent = String(completed);

  dom.upcomingNote.classList.add("overdue-alert");
  dom.upcomingNote.textContent = `${analytics.overdue_count ?? 0} overdue in queue`;
  dom.inProgressNote.textContent = `${analytics.total_this_week ?? 0} planned this week`;
  dom.completedNote.textContent = `${analytics.campaign_count ?? 0} campaigns active`;
}

function renderKanban(kanban) {
  const total = flattenKanban(kanban).length;
  dom.kanbanMeta.textContent = `${total} tasks`;
  const visible = state.visibleFields;

  dom.kanbanColumns.innerHTML = statusOrder
    .map((status) => {
      const items = kanban?.[status] || [];
      const cards = items
        .map((item) => {
          const missing = Number(item.missing_count || 0);
          const metaBadges = [];
          if (visible.type) {
            metaBadges.push(
              `<span class="card-badge type-${escapeHtml(item.type)}">${escapeHtml(item.type.toUpperCase())}</span>`,
            );
          }
          if (visible.airDate) {
            metaBadges.push(`<span class="card-badge">${escapeHtml(fmtDate(item.air_date, false))}</span>`);
          }
          if (visible.assignee) {
            metaBadges.push(`<span class="card-badge">${escapeHtml(item.assignee || "Unassigned")}</span>`);
          }
          if (visible.missing) {
            metaBadges.push(`<span class="card-badge">${missing > 0 ? `Missing ${missing}` : "Complete"}</span>`);
          }

          return `
            <li class="kanban-card type-${escapeHtml(item.type)}" draggable="true" data-task-id="${escapeHtml(item.id)}" data-status="${escapeHtml(item.status)}">
              <strong>${escapeHtml(item.title)}</strong>
              <div class="badges">${metaBadges.join("")}</div>
            </li>
          `;
        })
        .join("");

      return `
        <section class="kanban-col" data-status="${escapeHtml(status)}" data-animate>
          <header>
            <strong>${escapeHtml(statusLabels[status])}</strong>
            <span class="pill">${items.length}</span>
          </header>
          <ul class="drop-zone">${cards || '<li class="kanban-card">No tasks yet</li>'}</ul>
        </section>
      `;
    })
    .join("");

  dom.kanbanColumns.querySelectorAll(".kanban-card[data-task-id]").forEach((card) => {
    card.addEventListener("click", () => {
      const taskId = card.getAttribute("data-task-id");
      if (taskId) {
        openTask(taskId);
      }
    });
  });
}

function renderTimeline(calendarTasks) {
  const items = (calendarTasks || []).filter((item) => item.air_date);
  dom.timelineAxis.innerHTML = "";
  dom.timelineLanes.innerHTML = "";

  if (items.length === 0) {
    dom.timelineAxis.innerHTML = '<span style="grid-column:1 / -1">No schedule yet</span>';
    dom.timelineLanes.innerHTML = '<p style="padding:16px">Set air_date to render roadmap bars.</p>';
    return;
  }

  const dates = items.map((item) => new Date(item.air_date));
  const now = new Date();
  const minDate = new Date(Math.min(...dates.map((date) => date.valueOf()), now.valueOf()));
  minDate.setHours(0, 0, 0, 0);

  const totalDays = 14;
  for (let i = 0; i < totalDays; i += 1) {
    const day = new Date(minDate);
    day.setDate(minDate.getDate() + i);
    const label = new Intl.DateTimeFormat("en-US", {
      weekday: "short",
      month: "short",
      day: "numeric",
    }).format(day);
    const node = document.createElement("span");
    node.textContent = label;
    dom.timelineAxis.append(node);
  }

  const laneEnd = [Number.NEGATIVE_INFINITY, Number.NEGATIVE_INFINITY, Number.NEGATIVE_INFINITY, Number.NEGATIVE_INFINITY];
  const sorted = [...items].sort((a, b) => new Date(a.air_date).valueOf() - new Date(b.air_date).valueOf());

  sorted.forEach((task) => {
    const date = new Date(task.air_date);
    const dayIndex = Math.floor((date.valueOf() - minDate.valueOf()) / (24 * 3600 * 1000));
    if (dayIndex < 0 || dayIndex > totalDays - 1) return;

    const duration = task.status === "ready" ? 2 : 1;
    const end = dayIndex + duration;
    let lane = laneEnd.findIndex((value) => dayIndex > value);
    if (lane === -1) lane = 0;
    laneEnd[lane] = end;

    const card = document.createElement("button");
    card.type = "button";
    card.className = `timeline-item ${task.status}`;
    card.dataset.taskId = task.id;
    card.style.top = `${10 + lane * 58}px`;
    card.style.left = `${(dayIndex / totalDays) * 100}%`;
    card.style.width = `${Math.max((duration / totalDays) * 100, 8)}%`;
    card.innerHTML = `<h4>${escapeHtml(task.title)}</h4><p>${escapeHtml(task.assignee || "Unassigned")}</p>`;
    card.addEventListener("click", () => openTask(task.id));
    dom.timelineLanes.append(card);
  });
}

function renderMessages(tasks) {
  const sorted = [...tasks].sort((a, b) => new Date(b.air_date || 0).valueOf() - new Date(a.air_date || 0).valueOf());
  const rows = sorted.slice(0, 6).map((task) => {
    const text = task.missing_count > 0
      ? `${task.missing_count} field(s) missing before auto package.`
      : task.status === "posted"
      ? "Marked posted by team."
      : "Waiting next status update.";
    return `
      <li class="message">
        <span class="avatar">${escapeHtml(initials(task.assignee || task.campaign || "SO"))}</span>
        <div>
          <h4>${escapeHtml(task.assignee || "Content Team")}</h4>
          <p>${escapeHtml(task.title)}</p>
          <p>${escapeHtml(text)}</p>
        </div>
      </li>
    `;
  });

  dom.messageList.innerHTML = rows.join("") || '<li class="message"><div><h4>No updates</h4><p>Create tasks to see activity.</p></div></li>';
}

function renderToday(calendarTasks) {
  const todayKey = onlyDateKey(new Date().toISOString());
  const todayItems = (calendarTasks || []).filter((task) => onlyDateKey(task.air_date) === todayKey);
  dom.todayCount.textContent = String(todayItems.length);

  dom.todayTaskList.innerHTML = todayItems
    .map((task) => {
      const nextStatus = task.status === "posted" ? "ready" : "posted";
      const nextLabel = task.status === "posted" ? "Mark Ready" : "Mark Posted";
      return `
        <li class="today-item">
          <span class="avatar">${escapeHtml(initials(task.assignee || "NA"))}</span>
          <div>
            <h4>${escapeHtml(task.title)}</h4>
            <p>${escapeHtml(fmtDate(task.air_date, true))} · ${escapeHtml(statusLabels[task.status] || task.status)}</p>
          </div>
          <button class="tiny-btn quick-status" data-task-id="${escapeHtml(task.id)}" data-status="${escapeHtml(nextStatus)}" type="button">${escapeHtml(nextLabel)}</button>
        </li>
      `;
    })
    .join("") || '<li class="today-item"><div><h4>No tasks today</h4><p>Air-date tasks for today will show here.</p></div></li>';
}

function setActiveTab(tabName) {
  state.activeTab = tabName;
  document.querySelectorAll(".tab-btn").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === tabName);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.panel === tabName);
  });
}

function setDetailOpen(open) {
  if (!dom.detailPanel) return;
  dom.detailPanel.classList.toggle("open", open);
  dom.detailPanel.hidden = !open;
}

function setTaskModalOpen(open) {
  if (!dom.taskModalBackdrop) return;
  dom.taskModalBackdrop.classList.toggle("open", open);
  dom.taskModalBackdrop.setAttribute("aria-hidden", open ? "false" : "true");
  if (open) {
    dom.newTitle.focus();
  }
}

function renderStatusSelect(task) {
  if (!dom.statusSelect) return;
  dom.statusSelect.innerHTML = statusOrder
    .map((status) => {
      const selected = task.status === status ? "selected" : "";
      return `<option value="${escapeHtml(status)}" ${selected}>${escapeHtml(statusLabels[status])}</option>`;
    })
    .join("");
  dom.statusSelect.className = `status-${task.status}`;
}

function renderAssigneeOptions(selectedValue) {
  const names = new Set();
  flattenKanban(state.kanban).forEach((task) => {
    if (task.assignee) names.add(task.assignee);
  });
  if (selectedValue) names.add(selectedValue);

  const options = ['<option value="">Unchanged</option>'];
  [...names]
    .sort((a, b) => a.localeCompare(b))
    .forEach((name) => {
      const selected = name === selectedValue ? "selected" : "";
      options.push(`<option value="${escapeHtml(name)}" ${selected}>${escapeHtml(name)}</option>`);
    });
  dom.contentAssignee.innerHTML = options.join("");
}

function renderDetail(task) {
  setDetailOpen(true);
  dom.detailTitle.textContent = task.title || "Task detail";
  const summary = flattenKanban(state.kanban).find((row) => row.id === task.id);
  const assigneeName = summary?.assignee || "";

  const missing = task.validate?.missing_fields || [];
  const missingText = missing.length > 0 ? `Missing: ${missing.join(", ")}` : "Ready for full package.";
  dom.detailMeta.textContent = `${task.type?.toUpperCase() || "TASK"} · ${fmtDate(task.air_date)} · ${missingText}`;

  renderStatusSelect(task);

  dom.contentTitle.value = task.title || "";
  dom.contentCaption.value = task.caption || "";
  dom.contentHashtags.value = (task.hashtags || []).join(" ");
  dom.contentMentions.value = (task.mentions || []).join(" ");
  dom.mediaProductUrl.value = task.product_url || "";
  dom.contentAirDate.value = inputDatetimeValue(task.air_date);
  renderAssigneeOptions(assigneeName);
  dom.contentCampaign.value = "";

  dom.mediaList.innerHTML = (task.assets || [])
    .map((asset) => `<article class="list-item"><strong>${escapeHtml(asset.kind.toUpperCase())}</strong><p class="meta">${escapeHtml(asset.url)}</p></article>`)
    .join("") || '<article class="list-item"><p class="meta">No media attached.</p></article>';

  dom.checklistInput.value = (task.checklist_items || [])
    .sort((a, b) => a.position - b.position)
    .map((item) => `${item.is_done ? "[x]" : "[ ]"} ${item.title}`)
    .join("\n");

  dom.commentList.innerHTML = (task.comments || [])
    .slice()
    .sort((a, b) => new Date(a.created_at).valueOf() - new Date(b.created_at).valueOf())
    .map((comment) => {
      return `<article class="list-item"><strong>${escapeHtml(comment.user_id || "User")}</strong><p>${escapeHtml(comment.content)}</p><p class="meta">${escapeHtml(fmtDate(comment.created_at))}</p></article>`;
    })
    .join("") || '<article class="list-item"><p class="meta">No comments yet.</p></article>';

  dom.activityList.innerHTML = (task.activity_logs || [])
    .slice()
    .sort((a, b) => new Date(b.created_at).valueOf() - new Date(a.created_at).valueOf())
    .map((log) => {
      const text = `${log.action}${log.field_name ? ` (${log.field_name})` : ""}`;
      const value = [log.old_value ? `from: ${log.old_value}` : "", log.new_value ? `to: ${log.new_value}` : ""]
        .filter(Boolean)
        .join(" · ");
      return `<article class="list-item"><strong>${escapeHtml(text)}</strong><p>${escapeHtml(value || "-")}</p><p class="meta">${escapeHtml(fmtDate(log.created_at))}</p></article>`;
    })
    .join("") || '<article class="list-item"><p class="meta">No activity yet.</p></article>';

  setActiveTab(state.activeTab);
}

async function openTask(taskId, push = true) {
  try {
    const task = await requestJson(`/tasks/${taskId}`);
    state.selectedTask = task;
    state.selectedTaskId = task.id;
    renderDetail(task);
    if (push) {
      window.history.pushState({}, "", `/dashboard/tasks/${task.id}`);
    }
  } catch (error) {
    showToast(`Failed to open task (${error.message})`, true);
  }
}

async function refreshAndReopen(taskId) {
  await loadDashboard();
  if (taskId) {
    await openTask(taskId, false);
  }
}

async function updateTaskStatus(taskId, status) {
  try {
    await requestJson(`/tasks/${taskId}?actor_name=${encodeURIComponent(ACTOR_NAME)}`, {
      method: "PATCH",
      body: { status },
    });
    showToast(`Task moved to ${statusLabels[status]}`);
    await refreshAndReopen(state.selectedTaskId === taskId ? taskId : null);
  } catch (error) {
    showToast(`Status update failed (${error.message})`, true);
  }
}

function parseChecklistLines(text) {
  const lines = parseLineList(text);
  return lines.map((line, index) => {
    const match = line.match(/^\[(x|X| )\]\s*(.+)$/);
    if (match) {
      return {
        title: match[2].trim(),
        is_done: match[1].toLowerCase() === "x",
        position: index,
      };
    }
    return {
      title: line,
      is_done: false,
      position: index,
    };
  });
}

async function handlePathOnLoad() {
  const match = window.location.pathname.match(/^\/dashboard\/tasks\/([^/]+)$/);
  if (match) {
    await openTask(match[1], false);
  } else {
    setDetailOpen(false);
  }
}

async function seedDemoData() {
  const now = new Date();
  const plusDays = (days, hour) => {
    const date = new Date(now);
    date.setDate(date.getDate() + days);
    date.setHours(hour, 0, 0, 0);
    return inputDatetimeValue(date);
  };

  const demoTasks = [
    {
      title: "Demo Story Launch",
      type: "story",
      status: "idea",
      air_date: plusDays(1, 19),
      assignee_name: "Linh",
      campaign_name: "SpringBrand",
      hashtags: ["#spring", "#brand"],
      media_urls: ["https://cdn.example.com/demo-story.jpg"],
    },
    {
      title: "Demo Reel Product",
      type: "reel",
      status: "design",
      air_date: plusDays(2, 19),
      assignee_name: "An",
      campaign_name: "ProductDrop",
      caption: "Product tease and CTA",
      media_urls: ["https://cdn.example.com/demo-reel.mp4"],
    },
    {
      title: "Demo Post Recap",
      type: "post",
      status: "ready",
      air_date: plusDays(0, 19),
      assignee_name: "Ram",
      campaign_name: "WeeklyRecap",
      caption: "Recap highlights",
      media_urls: ["https://cdn.example.com/demo-post.jpg"],
    },
  ];

  try {
    for (const payload of demoTasks) {
      await requestJson("/tasks", { method: "POST", body: payload });
    }
    showToast("Demo tasks created");
    await loadDashboard();
  } catch (error) {
    showToast(`Seed failed (${error.message})`, true);
  }
}

function bindGlobalEvents() {
  const syncVisibleFields = () => {
    state.visibleFields.type = Boolean(dom.showTypeField?.checked);
    state.visibleFields.airDate = Boolean(dom.showAirDateField?.checked);
    state.visibleFields.assignee = Boolean(dom.showAssigneeField?.checked);
    state.visibleFields.missing = Boolean(dom.showMissingField?.checked);
    if (state.kanban) {
      renderKanban(state.kanban);
    }
  };

  [dom.showTypeField, dom.showAirDateField, dom.showAssigneeField, dom.showMissingField].forEach((input) => {
    input?.addEventListener("change", syncVisibleFields);
  });
  syncVisibleFields();

  dom.refreshBtn?.addEventListener("click", async () => {
    await loadDashboard();
    if (state.selectedTaskId) {
      await openTask(state.selectedTaskId, false);
    }
  });

  dom.runRemindersBtn?.addEventListener("click", async () => {
    try {
      const result = await requestJson("/reminders/run", {
        method: "POST",
        body: { limit: 200 },
      });
      showToast(`Reminders processed: ${result.processed}`);
    } catch (error) {
      showToast(`Reminder run failed (${error.message})`, true);
    }
  });

  dom.seedDemoBtn?.addEventListener("click", seedDemoData);

  dom.createTaskBtn?.addEventListener("click", () => setTaskModalOpen(true));
  dom.closeCreateModalBtn?.addEventListener("click", () => setTaskModalOpen(false));
  dom.taskModalBackdrop?.addEventListener("click", (event) => {
    if (event.target === dom.taskModalBackdrop) {
      setTaskModalOpen(false);
    }
  });
  dom.closeDetailBtn?.addEventListener("click", () => {
    setDetailOpen(false);
    state.selectedTaskId = null;
    state.selectedTask = null;
    window.history.pushState({}, "", "/dashboard");
  });

  dom.createTaskForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {
      title: dom.newTitle.value.trim(),
      type: dom.newType.value,
      status: dom.newStatus.value,
      air_date: dom.newAirDate.value || null,
      assignee_name: dom.newAssignee.value.trim() || null,
      campaign_name: dom.newCampaign.value.trim() || null,
      caption: dom.newCaption.value.trim() || null,
      hashtags: parseSpaceList(dom.newHashtags.value),
      mentions: parseSpaceList(dom.newMentions.value),
      product_url: dom.newProductUrl.value.trim() || null,
      media_urls: parseLineList(dom.newMediaUrls.value),
    };

    try {
      const created = await requestJson("/tasks", { method: "POST", body: payload });
      showToast("Task created");
      dom.createTaskForm.reset();
      setTaskModalOpen(false);
      await loadDashboard();
      await openTask(created.id);
    } catch (error) {
      showToast(`Create failed (${error.message})`, true);
    }
  });

  dom.kanbanColumns?.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const card = target.closest(".kanban-card[data-task-id]");
    if (card instanceof HTMLElement) {
      const taskId = card.dataset.taskId;
      if (taskId) await openTask(taskId);
    }
  });

  dom.kanbanColumns?.addEventListener("dragstart", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const card = target.closest(".kanban-card[data-task-id]");
    if (!(card instanceof HTMLElement)) return;
    state.draggingTaskId = card.dataset.taskId || null;
    card.style.opacity = "0.5";
  });

  dom.kanbanColumns?.addEventListener("dragend", (event) => {
    const target = event.target;
    if (target instanceof HTMLElement) {
      const card = target.closest(".kanban-card[data-task-id]");
      if (card instanceof HTMLElement) {
        card.style.opacity = "1";
      }
    }
    state.draggingTaskId = null;
    document.querySelectorAll(".kanban-col.drag-over").forEach((col) => col.classList.remove("drag-over"));
  });

  dom.kanbanColumns?.addEventListener("dragover", (event) => {
    event.preventDefault();
    const target = event.target;
    if (!(target instanceof Element)) return;
    const col = target.closest(".kanban-col");
    if (!(col instanceof HTMLElement)) return;
    col.classList.add("drag-over");
  });

  dom.kanbanColumns?.addEventListener("dragleave", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const col = target.closest(".kanban-col");
    if (col instanceof HTMLElement) {
      col.classList.remove("drag-over");
    }
  });

  dom.kanbanColumns?.addEventListener("drop", async (event) => {
    event.preventDefault();
    const target = event.target;
    if (!(target instanceof Element)) return;
    const col = target.closest(".kanban-col");
    if (!(col instanceof HTMLElement)) return;
    col.classList.remove("drag-over");

    const nextStatus = col.dataset.status;
    if (!state.draggingTaskId || !nextStatus) return;
    await updateTaskStatus(state.draggingTaskId, nextStatus);
  });

  dom.todayTaskList?.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const button = target.closest(".quick-status");
    if (!(button instanceof HTMLElement)) return;
    const taskId = button.dataset.taskId;
    const nextStatus = button.dataset.status;
    if (!taskId || !nextStatus) return;
    await updateTaskStatus(taskId, nextStatus);
  });

  dom.timelineLanes?.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const item = target.closest(".timeline-item");
    if (!(item instanceof HTMLElement)) return;
    const id = item.dataset.taskId;
    if (id) openTask(id);
  });

  dom.detailTabs?.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const button = target.closest(".tab-btn");
    if (!(button instanceof HTMLElement)) return;
    const tab = button.dataset.tab;
    if (tab) setActiveTab(tab);
  });

  dom.statusSelect?.addEventListener("change", async () => {
    const nextStatus = dom.statusSelect?.value;
    if (!state.selectedTaskId || !nextStatus) return;
    await updateTaskStatus(state.selectedTaskId, nextStatus);
  });

  dom.contentForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.selectedTaskId) return;
    const payload = {
      title: dom.contentTitle.value.trim(),
      caption: dom.contentCaption.value,
      hashtags: parseSpaceList(dom.contentHashtags.value),
      mentions: parseSpaceList(dom.contentMentions.value),
    };

    const assigneeName = dom.contentAssignee.value.trim();
    const campaignName = dom.contentCampaign.value.trim();
    const airDate = dom.contentAirDate.value;
    if (assigneeName) payload.assignee_name = assigneeName;
    if (campaignName) payload.campaign_name = campaignName;
    if (airDate) payload.air_date = airDate;

    try {
      await requestJson(`/tasks/${state.selectedTaskId}?actor_name=${encodeURIComponent(ACTOR_NAME)}`, {
        method: "PATCH",
        body: payload,
      });
      showToast("Content saved");
      await refreshAndReopen(state.selectedTaskId);
    } catch (error) {
      showToast(`Save failed (${error.message})`, true);
    }
  });

  dom.mediaForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.selectedTaskId) return;
    const mediaUrls = parseLineList(dom.mediaUrls.value);
    const productUrl = dom.mediaProductUrl.value.trim();
    if (mediaUrls.length === 0 && !productUrl) {
      showToast("Add media URL or product URL first", true);
      return;
    }

    try {
      if (productUrl) {
        await requestJson(`/tasks/${state.selectedTaskId}?actor_name=${encodeURIComponent(ACTOR_NAME)}`, {
          method: "PATCH",
          body: { product_url: productUrl || null },
        });
      }
      if (mediaUrls.length > 0) {
        await requestJson(`/tasks/${state.selectedTaskId}/assets?actor_name=${encodeURIComponent(ACTOR_NAME)}`, {
          method: "POST",
          body: { media_urls: mediaUrls },
        });
      }
      dom.mediaUrls.value = "";
      showToast("Media/Product updated");
      await refreshAndReopen(state.selectedTaskId);
      setActiveTab("media");
    } catch (error) {
      showToast(`Attach failed (${error.message})`, true);
    }
  });

  dom.checklistForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.selectedTaskId) return;
    const items = parseChecklistLines(dom.checklistInput.value);
    try {
      await requestJson(`/tasks/${state.selectedTaskId}/checklist?actor_name=${encodeURIComponent(ACTOR_NAME)}`, {
        method: "PUT",
        body: { items },
      });
      showToast("Checklist saved");
      await refreshAndReopen(state.selectedTaskId);
      setActiveTab("checklist");
    } catch (error) {
      showToast(`Checklist failed (${error.message})`, true);
    }
  });

  dom.commentForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.selectedTaskId) return;
    const content = dom.commentInput.value.trim();
    if (!content) return;
    try {
      await requestJson(`/tasks/${state.selectedTaskId}/comments`, {
        method: "POST",
        body: { content, user_name: ACTOR_NAME },
      });
      dom.commentInput.value = "";
      showToast("Comment added");
      await refreshAndReopen(state.selectedTaskId);
      setActiveTab("comments");
    } catch (error) {
      showToast(`Comment failed (${error.message})`, true);
    }
  });

  dom.deleteTaskBtn?.addEventListener("click", async () => {
    if (!state.selectedTaskId) return;
    const ok = window.confirm("Delete this task? This action cannot be undone.");
    if (!ok) return;

    try {
      await requestJson(`/tasks/${state.selectedTaskId}?actor_name=${encodeURIComponent(ACTOR_NAME)}`, {
        method: "DELETE",
      });
      showToast("Task deleted");
      state.selectedTaskId = null;
      state.selectedTask = null;
      setDetailOpen(false);
      window.history.pushState({}, "", "/dashboard");
      await loadDashboard();
    } catch (error) {
      showToast(`Delete failed (${error.message})`, true);
    }
  });

  window.addEventListener("popstate", () => {
    handlePathOnLoad();
  });
}

async function init() {
  setTaskModalOpen(false);
  bindGlobalEvents();
  await loadDashboard();
  await handlePathOnLoad();
}

init();
