(() => {
  "use strict";

  // ---------------------------------------------------------------- утилиты
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const pad = (n) => String(n).padStart(2, "0");
  const toMin = (s) => {
    const [h, m] = String(s).split(":").map(Number);
    return (h || 0) * 60 + (m || 0);
  };
  const toHM = (m) => `${pad(Math.floor(m / 60) % 24)}:${pad(Math.round(m) % 60)}`;
  const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const parseISO = (s) => new Date(s + "T00:00:00");
  const addDays = (d, n) => {
    const x = new Date(d);
    x.setDate(x.getDate() + n);
    return x;
  };
  const todayISO = () => iso(new Date());
  const nowMin = () => {
    const d = new Date();
    return d.getHours() * 60 + d.getMinutes();
  };
  const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
  const uid = (p) => p + Date.now().toString(36) + Math.random().toString(36).slice(2, 5);
  const dowOf = (dateStr) => {
    const d = parseISO(dateStr).getDay();
    return d === 0 ? 7 : d;
  };
  const hasOwn = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);
  const fmtDur = (m) => {
    m = Math.max(0, Math.round(m));
    const h = Math.floor(m / 60);
    const r = m % 60;
    if (h && r) return `${h} ч ${r} мин`;
    if (h) return `${h} ч`;
    return `${r} мин`;
  };
  const fmtDurShort = fmtDur;
  const WEEKDAYS = ["воскресенье", "понедельник", "вторник", "среда", "четверг", "пятница", "суббота"];
  const WEEKDAYS_SHORT = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];
  const MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
    "августа", "сентября", "октября", "ноября", "декабря"];

  const dateLabel = (s) => {
    const d = parseISO(s);
    return `${cap(WEEKDAYS[d.getDay()])}, ${d.getDate()} ${MONTHS[d.getMonth()]}`;
  };
  const shortDate = (s) => {
    const d = parseISO(s);
    return `${d.getDate()} ${MONTHS[d.getMonth()]}`;
  };
  const categoryLabel = { school: "Школа", extra: "Кружки", personal: "Личное" };

  // Дни недели в порядке пн..вс (в state храним 1..7, где 7 — воскресенье)
  const WEEK_ORDER = [1, 2, 3, 4, 5, 6, 7];
  const WEEK_SHORT_BY_NUM = { 1: "пн", 2: "вт", 3: "ср", 4: "чт", 5: "пт", 6: "сб", 7: "вс" };

  const weekdaysLabel = (days) => {
    if (!Array.isArray(days) || !days.length) return "без повторов";
    const sorted = days.slice().sort((a, b) => a - b);
    if (sorted.length === 7) return "каждый день";
    if (sorted.join(",") === "1,2,3,4,5") return "по будням";
    return sorted.map((d) => WEEK_SHORT_BY_NUM[d] || "?").join(", ");
  };

  // ---------------------------------------------------------------- шаблоны
  const TASK_TEMPLATES = [
    { label: "Домашка", title: "Домашнее задание", estimated: 60 },
    { label: "Чтение", title: "Чтение", estimated: 30 },
    { label: "Проект", title: "Проект", estimated: 90 },
    { label: "Повторение", title: "Повторить тему", estimated: 25 }
  ];

  const EVENT_TEMPLATES = [
    { label: "Школа", title: "Школа", category: "school", start: "08:30", end: "14:00", weekdays: [1, 2, 3, 4, 5] },
    { label: "Секция", title: "Секция", category: "extra", start: "17:00", end: "18:30", weekdays: [] },
    { label: "Репетитор", title: "Репетитор", category: "extra", start: "16:00", end: "17:00", weekdays: [] }
  ];

  // ---------------------------------------------------------------- данные
  const STORE_KEY = "timebalance.frontend.v2";
  const DAY_START = 7 * 60;

  function initialState() {
    return {
      settings: { dayEnd: "21:00", breakAfterSchool: 30, notifications: true, theme: "auto", layout: "mobile" },
      events: [],
      tasks: [],
      moved: {},
      splits: {},
      meta: { onboarded: false }
    };
  }

  function normalizeTask(t) {
    return {
      id: t.id || uid("t"),
      title: String(t.title || "Задание").slice(0, 120),
      due: t.due || todayISO(),
      estimated: Number(t.estimated) || 30,
      splittable: t.splittable !== false,
      priority: t.priority === "high" ? "high" : "normal",
      done: Boolean(t.done),
      startedAt: typeof t.startedAt === "number" ? t.startedAt : null,
      spent: Number(t.spent) || 0
    };
  }

  function normalizeEvent(e) {
    const days = Array.isArray(e.weekdays) && e.weekdays.length
      ? e.weekdays.filter((d) => d >= 1 && d <= 7)
      : [1];
    return {
      id: e.id || uid("e"),
      onlyDate: e.onlyDate || null,
      title: String(e.title || "Занятие").slice(0, 120),
      category: e.category || "extra",
      weekdays: days.length ? days : [1],
      start: e.start || "16:00",
      end: e.end || "17:00",
      travelBefore: Number(e.travelBefore) || 0,
      travelAfter: Number(e.travelAfter) || 0,
      movable: Boolean(e.movable)
    };
  }

  function normalize(data) {
    const base = initialState();
    if (!data || typeof data !== "object") return base;
    return {
      settings: Object.assign(base.settings, data.settings || {}),
      events: Array.isArray(data.events) ? data.events.map(normalizeEvent) : [],
      tasks: Array.isArray(data.tasks) ? data.tasks.map(normalizeTask) : [],
      moved: data.moved && typeof data.moved === "object" ? data.moved : {},
      splits: data.splits && typeof data.splits === "object" ? data.splits : {},
      meta: Object.assign(base.meta, data.meta || {})
    };
  }

  function load() {
    try {
      const raw = localStorage.getItem(STORE_KEY);
      if (!raw) return null;
      return normalize(JSON.parse(raw));
    } catch (err) {
      return null;
    }
  }

  function save() {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(state));
    } catch (err) {
      /* хранилище недоступно — работаем в памяти */
    }
  }

  let state = load() || initialState();
  let apiToken = null;
  let remoteMode = false;
  let serverPlan = null;
  let serverAlternatives = [];
  let cityList = null;
  let cityEvents = [];
  let cityReminders = [];
  let cityLoading = false;
  let cityError = "";
  let chosenCity = localStorage.getItem("timebalance.city.v1") || "";
  const apiBase = "/api/v1";

  async function api(path, method = "GET", body) {
    const response = await fetch(apiBase + path, {
      method,
      headers: {
        Authorization: `Bearer ${apiToken}`,
        ...(body === undefined ? {} : { "Content-Type": "application/json" })
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) })
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.message || `Ошибка сервера (${response.status})`);
    }
    return response.status === 204 ? null : response.json();
  }

  function eventPayload(event, dateStr) {
    return {
      title: event.title, category: event.category,
      starts_at: `${dateStr}T${event.start}:00`,
      ends_at: `${dateStr}T${event.end}:00`,
      travel_before_min: event.travelBefore || 0,
      travel_after_min: event.travelAfter || 0,
      movable: Boolean(event.movable),
      recurrence: event.weekdays?.length ? { weekdays: event.weekdays } : null
    };
  }

  function localDateTime(value) {
    return value.slice(0, 16);
  }

  async function reloadRemote() {
    const previousTasks = new Map(state.tasks.map((task) => [task.id, task]));
    const theme = state.settings.theme || "auto";
    const layout = state.settings.layout || "mobile";
    const meta = state.meta || { onboarded: false };
    const from = iso(addDays(new Date(), -7));
    const to = iso(addDays(new Date(), 23));
    const [user, events, tasks] = await Promise.all([
      api("/me"),
      api(`/events?from=${from}&to=${to}`),
      api("/tasks")
    ]);
    const unique = new Map();
    for (const event of events) if (!unique.has(event.id)) unique.set(event.id, event);
    state = {
      settings: {
        dayEnd: user.settings.day_end,
        breakAfterSchool: user.settings.break_after_school_min,
        notifications: user.settings.notifications_enabled,
        theme, layout
      },
      events: [...unique.values()].map((event) => ({
        id: event.id, title: event.title, category: event.category,
        weekdays: event.recurrence?.weekdays || [],
        onlyDate: event.recurrence ? null : event.starts_at.slice(0, 10),
        seriesDate: (event.series_starts_at || event.starts_at).slice(0, 10),
        start: localDateTime(event.starts_at).slice(11),
        end: localDateTime(event.ends_at).slice(11),
        travelBefore: event.travel_before_min,
        travelAfter: event.travel_after_min,
        movable: event.movable
      })),
      tasks: tasks.map((task) => ({
        id: task.id, title: task.title, due: task.due_at.slice(0, 10),
        estimated: task.estimated_min, splittable: task.splittable,
        priority: task.priority, done: task.status === "done",
        startedAt: task.started_at_ms || previousTasks.get(task.id)?.startedAt || null,
        spent: task.spent_min ?? previousTasks.get(task.id)?.spent ?? 0
      })),
      moved: {}, splits: {}, meta
    };
    serverPlan = null;
    await refreshServerPlan();
    render();
  }

  function minuteOf(value) {
    return toMin(localDateTime(value).slice(11));
  }

  async function refreshServerPlan() {
    if (!apiToken) return;
    const dateStr = selectedDate;
    const raw = await api(`/plan?from=${dateStr}&to=${dateStr}`);
    const conflicts = raw.conflicts.filter((item) => item.shortage_min > 0);
    const conflict = conflicts.sort((a, b) => b.shortage_min - a.shortage_min)[0] || null;
    const blocks = raw.blocks.map((block) => ({
      kind: block.kind, category: block.category, title: block.title,
      sourceId: block.source_id, from: minuteOf(block.starts_at),
      to: minuteOf(block.ends_at)
    }));
    const busy = blocks.filter((block) => block.kind !== "free");
    const dayEnd = toMin(state.settings.dayEnd);
    const free = gaps(mergeIntervals(busy), DAY_START, dayEnd);
    serverPlan = {
      dateStr, dayEnd, blocks: busy, free,
      unplaced: (conflict?.affected_task_ids || []).map((id) => ({
        task: state.tasks.find((task) => task.id === id), need: conflict.shortage_min
      })).filter((item) => item.task),
      shortage: conflict?.shortage_min || 0,
      plannedMin: raw.planned_min, freeMin: raw.free_min,
      tasks: state.tasks.filter((task) => !task.done && task.due <= dateStr),
      schoolEnd: DAY_START, conflict, revision: raw.revision
    };
    serverAlternatives = [];
    if (screen === "planb" && conflict) {
      const options = await api("/plan/alternatives", "POST", {
        conflict_id: conflict.id, plan_revision: raw.revision
      });
      serverAlternatives = options.map((item) => ({
        id: item.id, title: item.title, changes: item.changes,
        remaining: item.remaining_shortage_min,
        action: item.title === "Оставить как есть" ? "keep" : "apply"
      }));
    }
  }

  async function connectMax() {
    const initData = window.WebApp?.initData || window.MAX?.WebApp?.initData;
    if (!initData) return;
    try {
      const response = await fetch(apiBase + "/auth/max", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ init_data: initData })
      });
      if (!response.ok) throw new Error("Не удалось подтвердить вход через MAX");
      apiToken = (await response.json()).access_token;
      remoteMode = true;
      await reloadRemote();
      if (screen === "city") await loadCityReminders();
      showToast("Данные синхронизированы");
    } catch (error) {
      remoteMode = false;
      apiToken = null;
      showToast(error.message);
    }
  }
  let screen = "today";
  let selectedDate = todayISO();
  let sheetType = "task";
  let editingId = null;
  let activeTaskId = null;
  let toastTimer = null;
  let themeFadeTimer = null;
  let selectedWeekdays = [];
  let calcDays = [];
  let onboardStep = 0;

  // ---------------------------------------------------------------- тема
  const DARK_QUERY = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

  function applyTheme() {
    const theme = state.settings.theme || "auto";
    const root = document.documentElement;
    root.dataset.theme = theme;
    const isDark = theme === "dark" || (theme === "auto" && DARK_QUERY && DARK_QUERY.matches);
    root.classList.toggle("is-dark", Boolean(isDark));
    const meta = $('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", isDark ? "#24221f" : "#f5f0e7");
    root.classList.add("is-theme-fading");
    window.clearTimeout(themeFadeTimer);
    themeFadeTimer = window.setTimeout(() => root.classList.remove("is-theme-fading"), 500);
  }

  function applyLayout() {
    const layout = state.settings.layout === "desktop" ? "desktop" : "mobile";
    const root = document.documentElement;
    root.dataset.layout = layout;
    $$("#layoutChips .chip").forEach((chip) => {
      chip.setAttribute("aria-pressed", String(chip.dataset.layout === layout));
    });
  }

  if (DARK_QUERY && DARK_QUERY.addEventListener) {
    DARK_QUERY.addEventListener("change", () => {
      if ((state.settings.theme || "auto") === "auto") applyTheme();
    });
  }

  // ---------------------------------------------------------------- шкала
  function gaps(occupied, start, end) {
    const out = [];
    let cursor = start;
    for (const part of occupied) {
      if (part.from > cursor) out.push({ from: cursor, to: Math.min(part.from, end) });
      cursor = Math.max(cursor, part.to);
      if (cursor >= end) break;
    }
    if (cursor < end) out.push({ from: cursor, to: end });
    return out.filter((g) => g.to - g.from > 0);
  }

  function mergeIntervals(list) {
    const sorted = list
      .filter((b) => b.to > b.from)
      .slice()
      .sort((a, b) => a.from - b.from);
    const out = [];
    for (const item of sorted) {
      const last = out[out.length - 1];
      if (last && item.from <= last.to) {
        last.to = Math.max(last.to, item.to);
      } else {
        out.push({ from: item.from, to: item.to });
      }
    }
    return out;
  }

  // Остаток работы: оценка минус уже потраченное время (план против факта).
  function remainingFor(task) {
    if (hasOwn(state.splits, task.id)) return state.splits[task.id];
    return Math.max(0, task.estimated - (task.spent || 0));
  }

  function planFor(dateStr) {
    if (remoteMode && serverPlan?.dateStr === dateStr) return serverPlan;
    const d = parseISO(dateStr);
    const dow = d.getDay() === 0 ? 7 : d.getDay();
    const dayEnd = Math.min(toMin(state.settings.dayEnd), 24 * 60);
    const movedOn = state.moved[dateStr] || {};
    const eventsToday = state.events.filter(
      (e) => (e.onlyDate === dateStr || (!e.onlyDate && Array.isArray(e.weekdays) && e.weekdays.includes(dow))) && !movedOn[e.id]
    );

    const fixed = [];
    for (const e of eventsToday) {
      const s = toMin(e.start);
      const en = toMin(e.end);
      fixed.push({ kind: "event", category: e.category, title: e.title, from: s, to: en, sourceId: e.id });
      if (e.travelBefore > 0) fixed.push({ kind: "travel", title: "Дорога", from: s - e.travelBefore, to: s });
      if (e.travelAfter > 0) fixed.push({ kind: "travel", title: "Дорога", from: en, to: en + e.travelAfter });
    }

    const school = eventsToday.find((e) => e.category === "school");
    if (school && state.settings.breakAfterSchool > 0) {
      const s = toMin(school.end);
      fixed.push({
        kind: "break", title: "Отдых после школы",
        from: s, to: s + state.settings.breakAfterSchool
      });
    }

    for (const b of fixed) {
      b.from = Math.max(b.from, DAY_START);
      b.to = Math.min(b.to, dayEnd);
    }

    const occupied = mergeIntervals(fixed);
    const taskStart = school ? Math.max(DAY_START, toMin(school.end)) : DAY_START;
    const windows = gaps(occupied, DAY_START, dayEnd)
      .filter((w) => w.to > taskStart)
      .map((w) => ({ from: Math.max(w.from, taskStart), to: w.to }));

    const tasks = state.tasks
      .filter((t) => !t.done && t.due <= dateStr)
      .sort((a, b) =>
        (b.priority === "high") - (a.priority === "high") ||
        a.due.localeCompare(b.due) ||
        a.estimated - b.estimated
      );

    const work = windows.map((w) => ({ from: w.from, to: w.to }));
    const placed = [];
    const unplaced = [];

    for (const t of tasks) {
      let need = remainingFor(t);
      if (need <= 0) continue;

      if (!t.splittable) {
        const idx = work.findIndex((w) => w.to - w.from >= need);
        if (idx >= 0) {
          const w = work[idx];
          placed.push({ kind: "task", title: t.title, from: w.from, to: w.from + need, sourceId: t.id, category: "task" });
          w.from += need;
        } else {
          unplaced.push({ task: t, need });
        }
        continue;
      }

      for (const w of work) {
        if (need <= 0) break;
        const capw = w.to - w.from;
        if (capw < 15) continue;
        // Если окно короче на считаные минуты, лучше взять следующее,
        // чем оставить на шкале огрызок меньше 15 минут.
        if (need > capw && need - capw < 15) continue;
        const use = Math.min(capw, need);
        placed.push({ kind: "task", title: t.title, from: w.from, to: w.from + use, sourceId: t.id, category: "task" });
        w.from += use;
        need -= use;
      }
      if (need > 0) unplaced.push({ task: t, need });
    }

    const blocks = fixed.concat(placed).sort((a, b) => a.from - b.from);
    const after = mergeIntervals(blocks);
    const free = gaps(after, DAY_START, dayEnd);

    const plannedMin = blocks.reduce((sum, b) => sum + (b.to - b.from), 0);
    const freeMin = free.reduce((sum, g) => sum + (g.to - g.from), 0);
    const shortage = unplaced.reduce((sum, u) => sum + u.need, 0);

    return {
      dateStr, dayEnd, blocks, free, unplaced, shortage, plannedMin, freeMin, tasks,
      schoolEnd: school ? toMin(school.end) : DAY_START
    };
  }

  // ---------------------------------------------------------------- действия
  function splitCandidate(plan) {
    const worst = [...plan.unplaced].sort((a, b) => b.need - a.need).find((u) => u.task.splittable);
    if (worst) return worst.task;
    return plan.tasks.find((t) => t.splittable) || null;
  }

  function alternativesFor(plan) {
    const alts = [];
    const splitTask = splitCandidate(plan);
    if (splitTask) {
      const need = remainingFor(splitTask);
      const keep = Math.max(20, Math.min(30, Math.round(need / 2 / 5) * 5));
      const freed = Math.min(plan.shortage, need - keep);
      alts.push({
        id: "split",
        title: `Разделить «${splitTask.title}» на две части`,
        changes: [
          `Оставить ${fmtDur(keep)} на сегодня`,
          `Остальное (${fmtDur(need - keep)}) — на завтра`,
          plan.shortage - freed > 0 ? "Часть работы всё равно не поместится" : "Все дела успевают к сроку"
        ],
        freed,
        remaining: Math.max(0, plan.shortage - freed),
        action: "apply"
      });
    }

    const movable = state.events.find((e) => {
      const dow = dowOf(plan.dateStr);
      return e.movable && e.weekdays.includes(dow) && !(state.moved[plan.dateStr] || {})[e.id];
    });
    if (movable) {
      const freed = (toMin(movable.end) - toMin(movable.start)) + (movable.travelBefore || 0) + (movable.travelAfter || 0);
      alts.push({
        id: "move",
        title: `Перенести «${movable.title}» на другой день`,
        changes: [`Освободится ${fmtDur(freed)} вместе с дорогой`, "Занятие останется в расписании недели"],
        freed,
        remaining: Math.max(0, plan.shortage - freed),
        action: "apply"
      });
    }

    alts.push({
      id: "keep",
      title: "Оставить как есть",
      changes: [
        "Ничего не меняем",
        `Под риском просрочки ${fmtDur(plan.shortage)}`
      ],
      freed: 0,
      remaining: plan.shortage,
      action: "keep"
    });

    return alts;
  }

  async function applyAlternative(alt) {
    if (remoteMode) {
      if (alt.action === "keep") { setScreen("today"); return; }
      try {
        await api(`/plan/alternatives/${encodeURIComponent(alt.id)}/apply`, "POST", {
          plan_revision: serverPlan.revision
        });
        await reloadRemote();
        setScreen("today");
        showToast("План Б применён");
      } catch (error) { showToast(error.message); }
      return;
    }
    if (alt.id === "split") {
      const plan = planFor(selectedDate);
      const task = splitCandidate(plan);
      if (task) {
        const need = remainingFor(task);
        const keep = Math.max(20, Math.min(30, Math.round(need / 2 / 5) * 5));
        state.splits[task.id] = keep;
        save();
        showToast("План обновлён: часть задания перенесена на завтра");
      }
    } else if (alt.id === "move") {
      const dow = dowOf(selectedDate);
      const event = state.events.find((e) => e.movable && e.weekdays.includes(dow));
      if (event) {
        state.moved[selectedDate] = state.moved[selectedDate] || {};
        state.moved[selectedDate][event.id] = true;
        save();
        showToast(`«${event.title}» перенесено: день разгружен`);
      }
    } else {
      showToast("Оставляем план — риск просрочки остаётся");
    }
    setScreen("today");
  }

  // --- отметки выполнения и таймер «план против факта»
  async function toggleTaskDone(taskId) {
    const task = state.tasks.find((t) => t.id === taskId);
    if (!task) return;
    if (remoteMode) {
      try {
        const extra = !task.done && task.startedAt
          ? { spent_min: task.spent + elapsedMinutes(task), started_at_ms: 0 } : {};
        await api(`/tasks/${encodeURIComponent(taskId)}`, "PATCH",
          { status: task.done ? "todo" : "done", ...extra });
      }
      catch (error) { showToast(error.message); return; }
    }
    task.done = !task.done;
    if (task.done && task.startedAt) {
      commitTimer(task);
    }
    save();
    if (remoteMode) await refreshServerPlan().catch((error) => showToast(error.message));
    showToast(task.done ? "Отмечено выполненным" : "Дело возвращено в план");
    render();
  }

  function commitTimer(task) {
    if (!task.startedAt) return 0;
    const mins = elapsedMinutes(task);
    task.spent = (task.spent || 0) + mins;
    task.startedAt = null;
    return mins;
  }

  function elapsedMinutes(task) {
    return Math.max(1, Math.round((Date.now() - task.startedAt) / 60000));
  }

  async function startTask(taskId) {
    const task = state.tasks.find((t) => t.id === taskId);
    if (!task) return;
    const running = state.tasks.find((t) => t.startedAt && t.id !== task.id);
    const startedAt = Date.now();
    if (remoteMode) {
      try {
        if (running) await api(`/tasks/${encodeURIComponent(running.id)}`, "PATCH", {
          spent_min: running.spent + elapsedMinutes(running), started_at_ms: 0,
          status: "todo"
        });
        await api(`/tasks/${encodeURIComponent(task.id)}`, "PATCH", {
          started_at_ms: startedAt, status: "in_progress"
        });
      } catch (error) { showToast(error.message); return; }
    }
    if (running) commitTimer(running);
    task.startedAt = startedAt;
    activeTaskId = task.id;
    save();
    showToast(`Засекли время: ${task.title}`);
    render();
  }

  async function stopTask(taskId) {
    const task = state.tasks.find((t) => t.id === taskId);
    if (!task || !task.startedAt) return;
    if (remoteMode) {
      try { await api(`/tasks/${encodeURIComponent(taskId)}`, "PATCH", {
        spent_min: task.spent + elapsedMinutes(task), started_at_ms: 0,
        status: "todo"
      }); } catch (error) { showToast(error.message); return; }
    }
    const mins = commitTimer(task);
    save();
    if (remoteMode) await refreshServerPlan().catch((error) => showToast(error.message));
    showToast(`Записано ${fmtDur(mins)}`);
    render();
  }

  async function finishTask(taskId) {
    const task = state.tasks.find((t) => t.id === taskId);
    if (!task) return;
    if (remoteMode) {
      try { await api(`/tasks/${encodeURIComponent(taskId)}`, "PATCH", {
        status: "done", started_at_ms: 0,
        spent_min: task.spent + (task.startedAt ? elapsedMinutes(task) : 0)
      }); }
      catch (error) { showToast(error.message); return; }
    }
    if (task.startedAt) commitTimer(task);
    task.done = true;
    save();
    if (remoteMode) await refreshServerPlan().catch((error) => showToast(error.message));
    showToast("Готово. Время записано в факт");
    render();
  }

  function elapsedLabel(startedAt) {
    const secs = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    const s = secs % 60;
    return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
  }

  function tickTimers() {
    $$("[data-timer]").forEach((el) => {
      const task = state.tasks.find((t) => t.id === el.dataset.timer);
      if (task && task.startedAt) el.textContent = elapsedLabel(task.startedAt);
    });
  }

  // --- удаление с возможностью отмены
  async function deleteTask(id) {
    const idx = state.tasks.findIndex((t) => t.id === id);
    if (idx < 0) return;
    const removed = state.tasks[idx];
    if (remoteMode) {
      try { await api(`/tasks/${encodeURIComponent(id)}`, "DELETE"); }
      catch (error) { showToast(error.message); return; }
    }
    const splitBefore = state.splits[id];
    state.tasks.splice(idx, 1);
    delete state.splits[id];
    save();
    if (remoteMode) await refreshServerPlan().catch((error) => showToast(error.message));
    render();
    showToast(`Удалено: ${removed.title}`, {
      label: "Отменить",
      onAction: async () => {
        if (remoteMode) {
          try {
            const restored = await api("/tasks", "POST", {
              title: removed.title, due_at: `${removed.due}T23:59:00`,
              estimated_min: removed.estimated, splittable: removed.splittable,
              priority: removed.priority
            });
            if (removed.done || removed.spent || removed.startedAt) {
              await api(`/tasks/${encodeURIComponent(restored.id)}`, "PATCH", {
                status: removed.done ? "done" : removed.startedAt ? "in_progress" : "todo",
                spent_min: removed.spent || 0,
                started_at_ms: removed.startedAt || 0
              });
            }
            await reloadRemote();
            showToast("Восстановлено");
          } catch (error) { showToast(error.message); }
          return;
        }
        state.tasks.splice(idx, 0, removed);
        if (splitBefore !== undefined) state.splits[id] = splitBefore;
        save();
        render();
        showToast("Восстановлено");
      }
    });
  }

  async function deleteEvent(id) {
    const idx = state.events.findIndex((e) => e.id === id);
    if (idx < 0) return;
    const removed = state.events[idx];
    if (remoteMode) {
      try { await api(`/events/${encodeURIComponent(id)}`, "DELETE"); }
      catch (error) { showToast(error.message); return; }
    }
    state.events.splice(idx, 1);
    save();
    if (remoteMode) await refreshServerPlan().catch((error) => showToast(error.message));
    render();
    showToast(`Удалено: ${removed.title}`, {
      label: "Отменить",
      onAction: async () => {
        if (remoteMode) {
          try {
            await api("/events", "POST", eventPayload(removed, removed.seriesDate || removed.onlyDate || selectedDate));
            await reloadRemote();
            showToast("Восстановлено");
          } catch (error) { showToast(error.message); }
          return;
        }
        state.events.splice(idx, 0, removed);
        save();
        render();
        showToast("Восстановлено");
      }
    });
  }

  // ---------------------------------------------------------------- отрисовка
  function render() {
    applyTheme();
    applyLayout();
    document.body.dataset.screen = screen;
    $$("[data-screen]").forEach((btn) => {
      if (btn.dataset.screen === screen) btn.setAttribute("aria-current", "page");
      else btn.removeAttribute("aria-current");
    });
    $("#fab").hidden = screen === "planb" || screen === "profile";
    renderToday();
    if (screen === "week") renderWeek();
    if (screen === "planb") renderPlanB();
    if (screen === "profile") renderProfile();
    if (screen === "city") renderCity();
  }

  function setScreen(next) {
    screen = next;
    $$("#screen-today, #screen-week, #screen-city, #screen-planb, #screen-profile").forEach((sec) => {
      const active = sec.id === `screen-${next}`;
      sec.hidden = !active;
      if (active) {
        sec.classList.remove("screen-enter");
        // перезапуск анимации перехода
        void sec.offsetWidth;
        sec.classList.add("screen-enter");
      }
    });
    render();
    if (remoteMode && (next === "today" || next === "planb")) {
      refreshServerPlan().then(render).catch((error) => showToast(error.message));
    }
    if (next === "city") loadCitiesAndEvents();
    appRoot().scrollTop = 0;
  }

  async function loadCitiesAndEvents() {
    if (!cityList) {
      try {
        const response = await fetch(`${apiBase}/city-events/cities`);
        if (!response.ok) throw new Error("Не удалось загрузить города");
        cityList = await response.json();
        cityError = "";
      } catch (error) { cityError = error.message; renderCity(); return; }
    }
    renderCity();
    if (chosenCity) await loadCityEvents();
  }

  async function loadCityEvents() {
    cityLoading = true;
    cityError = "";
    renderCity();
    try {
      const response = await fetch(`${apiBase}/city-events?city=${encodeURIComponent(chosenCity)}`);
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.message || "Не удалось загрузить афишу");
      }
      cityEvents = await response.json();
      if (remoteMode) await loadCityReminders();
    } catch (error) { cityError = error.message; cityEvents = []; }
    finally { cityLoading = false; renderCity(); }
  }

  async function loadCityReminders() {
    if (!remoteMode) return;
    try { cityReminders = await api("/city-events/reminders"); }
    catch (error) { showToast(error.message); }
    if (screen === "city") renderCity();
  }

  function cityDate(value) {
    return new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
  }

  function renderCity() {
    const select = $("#citySelect");
    if (cityList) {
      $("#citySuggestions").innerHTML = cityList.map((item) =>
        `<option value="${escapeHTML(item.name)}"></option>`).join("");
      if (document.activeElement !== select) select.value = chosenCity;
    }
    const box = $("#cityEvents");
    if (cityError) {
      box.innerHTML = `<div class="card city-empty"><p>${escapeHTML(cityError)}</p><button class="btn btn-outline" id="cityRetry" type="button">Повторить</button></div>`;
      $("#cityRetry").addEventListener("click", loadCitiesAndEvents);
      return;
    }
    if (!chosenCity) { box.innerHTML = `<div class="card city-empty">Выбери город — покажем ближайшие события.</div>`; return; }
    if (cityLoading) { box.innerHTML = `<div class="card city-empty">Ищем мероприятия…</div>`; return; }
    if (!cityEvents.length) { box.innerHTML = `<div class="card city-empty">На ближайшие недели событий пока не нашлось.</div>`; return; }
    box.innerHTML = cityEvents.map((item) => {
      const options = item.dates.map((date) => `<option value="${escapeHTML(date)}">${cityDate(date)}</option>`).join("");
      const reminded = cityReminders.find((saved) => String(saved.source_id) === String(item.id));
      const details = item.url.startsWith("https://spontanno.space/")
        ? `<a class="city-link" href="${escapeHTML(item.url)}" target="_blank" rel="noopener noreferrer">Подробнее ↗</a>` : "";
      return `<article class="card city-card">
        <span class="city-stamp">АФИША / ${escapeHTML(chosenCity.toUpperCase())}</span>
        <h2>${escapeHTML(item.title)}</h2>
        <p class="city-meta">${escapeHTML(item.place || "Место уточняется")}${item.price ? ` · ${escapeHTML(item.price)}` : ""}</p>
        <label for="cityDate-${item.id}">Дата события</label>
        <select class="input" id="cityDate-${item.id}" data-city-date="${item.id}">${options}</select>
        <div class="city-actions">${details}<button class="btn ${reminded ? "btn-outline" : "btn-primary"}" type="button" ${reminded ? `data-unremind="${escapeHTML(reminded.id)}"` : `data-remind="${item.id}"`} ${!remoteMode || !item.url ? "disabled" : ""}>${reminded ? "Убрать напоминание" : "Напомнить"}</button></div>
      </article>`;
    }).join("") + `<p class="hint city-note">Источник: <a href="https://spontanno.space/" target="_blank" rel="noopener noreferrer">СПОНТАННО</a>. Напоминания в чате доступны при открытии через MAX.</p>`;
  }

  function appRoot() {
    return $(".app");
  }

  function renderToday() {
    const isToday = selectedDate === todayISO();
    const plan = planFor(selectedDate);

    $("#todayKicker").textContent = isToday ? "Сегодня" : "День";
    $("#todayDate").textContent = dateLabel(selectedDate);
    const totalTasks = plan.tasks.length;
    $("#todayGreeting").textContent = totalTasks
      ? `${totalTasks} ${plural(totalTasks, "дело", "дела", "дел")} в работе. Смотрим, что реально успеть.`
      : "Пока нет дел — можно добавить первое.";

    renderNow(plan, isToday);
    renderConflict(plan);
    renderTimeline(plan, isToday);
    renderTaskList();
    renderEventList();
    renderSummary(plan);
  }

  function plural(n, one, few, many) {
    const mod10 = n % 10;
    const mod100 = n % 100;
    if (mod10 === 1 && mod100 !== 11) return one;
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few;
    return many;
  }

  function renderNow(plan, isToday) {
    const card = $("#nowCard");
    const running = state.tasks.find((t) => t.startedAt);

    // Идёт засечённое время — карточка показывает таймер.
    if (running) {
      card.innerHTML = `
        <p class="now-label">Идёт работа</p>
        <h2 class="now-title">${escapeHTML(running.title)}</h2>
        <p class="now-note">Время записывается в факт. Можно поставить паузу.</p>
        <div class="now-foot">
          <span class="now-time"><span data-timer="${escapeAttr(running.id)}">${elapsedLabel(running.startedAt)}</span><small>идёт сейчас</small></span>
          <span class="now-actions">
            <button class="btn btn-outline" type="button" data-stop="${escapeAttr(running.id)}">Пауза</button>
            <button class="btn btn-primary" type="button" data-finish="${escapeAttr(running.id)}">Готово</button>
          </span>
        </div>`;
      const stopBtn = $("[data-stop]", card);
      if (stopBtn) stopBtn.addEventListener("click", () => stopTask(running.id));
      const finBtn = $("[data-finish]", card);
      if (finBtn) finBtn.addEventListener("click", () => finishTask(running.id));
      return;
    }

    const ref = isToday ? nowMin() : DAY_START;
    const upcoming = plan.blocks
      .filter((b) => (b.kind === "task" || b.kind === "event") && b.to > ref)
      .sort((a, b) => a.from - b.from)[0];

    if (!plan.tasks.length && !plan.blocks.length) {
      card.innerHTML = `
        <p class="now-label">Свободный день</p>
        <h2 class="now-title">Пока нет дел на сегодня</h2>
        <p class="now-note">Добавь занятие или задание — шкала соберётся сама.</p>
        <div class="now-foot">
          <span class="now-time">${fmtDur(plan.freeMin)}<small>свободно</small></span>
          <button class="btn btn-primary" type="button" data-open-add>Добавить дело</button>
        </div>`;
      bindOpenAdd(card);
      return;
    }

    if (!upcoming) {
      card.innerHTML = `
        <p class="now-label">Сейчас</p>
        <h2 class="now-title">Время отдыха</h2>
        <p class="now-note">На сегодня дел не осталось. Отдых — тоже часть плана.</p>
        <div class="now-foot">
          <span class="now-time">${plan.shortage ? "Есть риск" : "Всё помещается"}<small>${plan.shortage ? `не хватает ${fmtDur(plan.shortage)}` : "план сходится"}</small></span>
          <button class="btn btn-soft" type="button" data-open-add>Добавить</button>
        </div>`;
      bindOpenAdd(card);
      return;
    }

    const isTask = upcoming.kind === "task";
    const duration = upcoming.to - upcoming.from;
    card.innerHTML = `
      <p class="now-label">${isToday ? "Сейчас" : "Первый шаг"}</p>
      <h2 class="now-title">${escapeHTML(upcoming.title)}</h2>
      <p class="now-note">${isTask
        ? `${fmtDur(duration)} спокойной работы, без спешки.`
        : `${categoryLabel[upcoming.category] || "Занятие"} по расписанию.`}</p>
      <div class="now-foot">
        <span class="now-time">${toHM(upcoming.from)}–${toHM(upcoming.to)}<small>${isTask ? `${fmtDur(duration)}` : "занятие"}</small></span>
        <button class="btn ${isTask ? "btn-primary" : "btn-outline"}" type="button" data-now-action="${isTask ? "start" : "view"}">
          ${isTask ? "Начать" : "Посмотреть"}
        </button>
      </div>`;

    const btn = $("[data-now-action]", card);
    btn.addEventListener("click", () => {
      if (isTask && upcoming.sourceId) {
        startTask(upcoming.sourceId);
      } else {
        showToast(`${upcoming.title} · ${toHM(upcoming.from)}–${toHM(upcoming.to)}`);
      }
    });
  }

  function bindOpenAdd(root) {
    $$("[data-open-add]", root).forEach((btn) => {
      btn.addEventListener("click", () => openSheet(sheetType));
    });
  }

  function renderConflict(plan) {
    const card = $("#conflictCard");
    if (!plan.shortage) {
      card.hidden = true;
      card.innerHTML = "";
      return;
    }
    card.hidden = false;
    const firstDue = [...plan.unplaced].sort((a, b) => b.need - a.need)[0]?.task;
    const dueText = firstDue ? `до срока «${escapeHTML(firstDue.title)}»` : "до ближайшего срока";
    card.innerHTML = `
      <h2 class="conflict-title">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M12 8v5M12 16.5v.5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
          <path d="M10.3 4.2 2.9 17a2 2 0 0 0 1.7 3h14.8a2 2 0 0 0 1.7-3L13.7 4.2a2 2 0 0 0-3.4 0Z" stroke="currentColor" stroke-width="1.8"/>
        </svg>
        Не хватает ${fmtDur(plan.shortage)}
      </h2>
      <p class="conflict-text">${remoteMode && plan.conflict ? escapeHTML(plan.conflict.explanation) : `${dueText.charAt(0).toUpperCase() + dueText.slice(1)}: в плане не помещается ${fmtDur(plan.shortage)}. Это не про «соберись», а про время.`}</p>
      <button class="btn btn-danger" type="button" id="openPlanB">Собрать План Б</button>`;
    $("#openPlanB").addEventListener("click", () => setScreen("planb"));
  }

  const PX_PER_MIN = 1.0;

  function renderTimeline(plan, isToday) {
    const timeline = $("#timeline");
    $("#timelineRange").textContent = `${toHM(DAY_START)}–${toHM(plan.dayEnd)}`;

    if (!plan.blocks.length) {
      timeline.style.height = "auto";
      timeline.style.marginLeft = "0";
      timeline.innerHTML = `
        <div class="empty">
          <p>Пока нет дел на сегодня. Добавь первое — шкала соберётся сама.</p>
          <button class="btn btn-primary" type="button" data-open-add>Добавить первое дело</button>
        </div>`;
      bindOpenAdd(timeline);
      return;
    }

    timeline.style.marginLeft = "";
    timeline.style.height = `${(plan.dayEnd - DAY_START) * PX_PER_MIN}px`;

    const parts = [];

    const firstHour = Math.ceil(DAY_START / 60) * 60;
    for (let m = firstHour; m <= plan.dayEnd; m += 60) {
      const top = (m - DAY_START) * PX_PER_MIN;
      parts.push(`<div class="hour" style="top:${top}px"><span class="hour-label">${toHM(m)}</span></div>`);
    }

    plan.blocks.forEach((b, index) => {
      const dur = b.to - b.from;
      const top = (b.from - DAY_START) * PX_PER_MIN;
      const h = Math.max(8, dur * PX_PER_MIN - 4);
      const kindClass = b.kind === "task" ? "blk--task"
        : b.kind === "travel" ? "blk--travel"
        : b.kind === "break" ? "blk--rest"
        : `blk--${b.category || "personal"}`;
      const label = b.kind === "task" ? "Задание"
        : b.kind === "travel" ? "Дорога"
        : b.kind === "break" ? "Отдых"
        : categoryLabel[b.category] || "Занятие";
      const compact = h < 38;
      const tiny = h < 18;
      const editable = (b.kind === "task" || b.kind === "event") && b.sourceId;
      const isRunning = b.kind === "task" && b.sourceId && state.tasks.some((t) => t.id === b.sourceId && t.startedAt);
      parts.push(`
        <div class="blk ${kindClass}${compact ? " blk--compact" : ""}${tiny ? " blk--tiny" : ""}${b.sourceId && b.sourceId === activeTaskId ? " is-active" : ""}${isRunning ? " is-running" : ""}"
             style="top:${top}px;height:${h}px;animation-delay:${Math.min(index * 18, 260)}ms" role="listitem"
             ${editable ? `data-edit-id="${escapeAttr(b.sourceId)}" data-edit-kind="${b.kind}" tabindex="0"` : ""}
             aria-label="${escapeAttr(label)} ${escapeAttr(b.title)}, ${toHM(b.from)}–${toHM(b.to)}, ${fmtDur(dur)}">
          <span class="blk-title">${escapeHTML(b.title)}</span>
          ${compact ? "" : `<span class="blk-meta">${toHM(b.from)}–${toHM(b.to)} · ${fmtDur(dur)}</span>`}
        </div>`);
    });

    for (const g of plan.free) {
      const dur = g.to - g.from;
      if (dur < 30) continue;
      const top = (g.from - DAY_START) * PX_PER_MIN;
      const h = Math.max(24, dur * PX_PER_MIN - 4);
      parts.push(`
        <div class="blk blk--free" style="top:${top}px;height:${h}px" role="listitem"
             aria-label="Свободно ${fmtDur(dur)}">
          <span class="blk-title">Свободно · ${fmtDur(dur)}</span>
        </div>`);
    }

    if (isToday) {
      const n = nowMin();
      if (n >= DAY_START && n <= plan.dayEnd) {
        const top = (n - DAY_START) * PX_PER_MIN;
        parts.push(`<div class="now-line" style="top:${top}px" aria-hidden="true"></div>`);
      }
    }

    timeline.innerHTML = parts.join("");

    // Нажатие на блок открывает правку этого дела
    $$("[data-edit-id]", timeline).forEach((blk) => {
      const open = () => openSheet(blk.dataset.editKind === "task" ? "task" : "event", blk.dataset.editId);
      blk.addEventListener("click", open);
      blk.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          open();
        }
      });
    });
  }

  // --- список дел с редактированием и удалением
  function renderTaskList() {
    const list = $("#taskList");
    const tasks = state.tasks.slice().sort((a, b) => {
      if (a.done !== b.done) return a.done ? 1 : -1;
      return a.due.localeCompare(b.due) || a.title.localeCompare(b.title);
    });
    $("#taskCount").textContent = tasks.length ? `${tasks.length}` : "";

    if (!tasks.length) {
      list.innerHTML = `
        <div class="card empty">
          <p>Дел пока нет. Добавь первое — оно появится на шкале.</p>
          <button class="btn btn-primary" type="button" data-add-task>Добавить задание</button>
        </div>`;
      $("[data-add-task]", list).addEventListener("click", () => openSheet("task"));
      return;
    }

    list.innerHTML = tasks.map((t, index) => {
      const left = remainingFor(t);
      const running = Boolean(t.startedAt);
      const meta = [
        t.due === todayISO() ? "срок сегодня" : `до ${shortDate(t.due)}`,
        fmtDur(t.estimated),
        t.spent ? `факт ${fmtDur(t.spent)}` : "",
        !t.done && left !== t.estimated ? `осталось ${fmtDur(left)}` : ""
      ].filter(Boolean).join(" · ");

      return `
        <div class="row-item${t.done ? " is-done" : ""}${running ? " is-running" : ""}"
             style="animation-delay:${Math.min(index * 24, 240)}ms">
          <button class="check" type="button" data-done="${escapeAttr(t.id)}"
                  aria-pressed="${t.done ? "true" : "false"}"
                  aria-label="${t.done ? "Вернуть в план" : "Отметить выполненным"}">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M5 12.5 10 17.5 19 7" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </button>
          <div class="row-main">
            <p class="row-title">${escapeHTML(t.title)}</p>
            <p class="row-meta">${escapeHTML(meta)}</p>
          </div>
          <div class="row-actions">
            ${t.done ? "" : (running
              ? `<button class="row-btn row-btn--stop" type="button" data-stop="${escapeAttr(t.id)}" aria-label="Пауза">❚❚</button>`
              : `<button class="row-btn row-btn--play" type="button" data-start="${escapeAttr(t.id)}" aria-label="Засечь время">▶</button>`)}
            <button class="row-btn" type="button" data-edit="${escapeAttr(t.id)}" aria-label="Изменить">✎</button>
            <button class="row-btn row-btn--danger" type="button" data-del="${escapeAttr(t.id)}" aria-label="Удалить">✕</button>
          </div>
        </div>`;
    }).join("");

    $$("[data-done]", list).forEach((b) => b.addEventListener("click", () => toggleTaskDone(b.dataset.done)));
    $$("[data-start]", list).forEach((b) => b.addEventListener("click", () => startTask(b.dataset.start)));
    $$("[data-stop]", list).forEach((b) => b.addEventListener("click", () => stopTask(b.dataset.stop)));
    $$("[data-edit]", list).forEach((b) => b.addEventListener("click", () => openSheet("task", b.dataset.edit)));
    $$("[data-del]", list).forEach((b) => b.addEventListener("click", () => deleteTask(b.dataset.del)));
  }

  // --- список занятий
  function renderEventList() {
    const list = $("#eventList");
    const events = state.events.slice().sort((a, b) => toMin(a.start) - toMin(b.start));
    $("#eventCount").textContent = events.length ? `${events.length}` : "";

    if (!events.length) {
      list.innerHTML = `
        <div class="card empty">
          <p>Занятий пока нет. Школа, кружок или секция — с повторением по дням.</p>
          <button class="btn btn-primary" type="button" data-add-event>Добавить занятие</button>
        </div>`;
      $("[data-add-event]", list).addEventListener("click", () => openSheet("event"));
      return;
    }

    list.innerHTML = events.map((e, index) => `
      <div class="row-item" style="animation-delay:${Math.min(index * 24, 240)}ms">
        <span class="cat-dot cat-dot--${escapeAttr(e.category)}" aria-hidden="true"></span>
        <div class="row-main">
          <p class="row-title">${escapeHTML(e.title)}</p>
          <p class="row-meta">${toHM(toMin(e.start))}–${toHM(toMin(e.end))} · ${escapeHTML(weekdaysLabel(e.weekdays))}${e.travelBefore || e.travelAfter ? ` · дорога ${fmtDur((e.travelBefore || 0) + (e.travelAfter || 0))}` : ""}</p>
        </div>
        <div class="row-actions">
          <button class="row-btn" type="button" data-edit="${escapeAttr(e.id)}" aria-label="Изменить">✎</button>
          <button class="row-btn row-btn--danger" type="button" data-del="${escapeAttr(e.id)}" aria-label="Удалить">✕</button>
        </div>
      </div>`).join("");

    $$("[data-edit]", list).forEach((b) => b.addEventListener("click", () => openSheet("event", b.dataset.edit)));
    $$("[data-del]", list).forEach((b) => b.addEventListener("click", () => deleteEvent(b.dataset.del)));
  }

  function renderSummary(plan) {
    const nextDue = plan.tasks
      .filter((t) => !t.done)
      .sort((a, b) => a.due.localeCompare(b.due))[0];
    const dueText = nextDue
      ? (nextDue.due === todayISO() ? "сегодня" : shortDate(nextDue.due))
      : "нет";

    const doneTasks = state.tasks.filter((t) => t.done);
    const estimateDone = doneTasks.reduce((sum, t) => sum + t.estimated, 0);
    const spentDone = doneTasks.reduce((sum, t) => sum + (t.spent || 0), 0);

    const factCard = doneTasks.length
      ? `<div class="sum-card">
           <dt>Оценка / факт</dt>
           <dd>${fmtDurShort(estimateDone)} / ${fmtDurShort(spentDone)}
             <small>по ${doneTasks.length} ${plural(doneTasks.length, "делу", "делам", "делам")}</small></dd>
         </div>`
      : "";

    $("#summary").innerHTML = `
      <div class="sum-card">
        <dt>Свободно</dt>
        <dd>${fmtDurShort(plan.freeMin)}</dd>
      </div>
      <div class="sum-card">
        <dt>Запланировано</dt>
        <dd>${fmtDurShort(plan.plannedMin)}</dd>
      </div>
      <div class="sum-card">
        <dt>Ближайший срок</dt>
        <dd>${dueText}<small>${nextDue ? escapeHTML(nextDue.title) : "дел нет"}</small></dd>
      </div>
      ${factCard}`;
  }

  function renderWeek() {
    const start = parseISO(todayISO());
    const list = $("#weekList");
    const rows = [];

    if (!state.events.length && !state.tasks.length) {
      list.innerHTML = `
        <div class="card empty">
          <p>Пока нет дел на неделю. Добавь занятие или задание — здесь появится нагрузка по дням.</p>
          <button class="btn btn-primary" type="button" data-open-add>Добавить дело</button>
        </div>`;
      bindOpenAdd(list);
      return;
    }

    for (let i = 0; i < 7; i++) {
      const date = iso(addDays(start, i));
      const plan = planFor(date);
      const total = plan.plannedMin + plan.freeMin || 1;
      const load = Math.round((plan.plannedMin / total) * 100);
      const d = parseISO(date);
      const isToday = date === todayISO();
      rows.push(`
        <button class="week-row" type="button" data-date="${date}" style="animation-delay:${i * 30}ms">
          <span class="week-top">
            <span class="week-day">${cap(WEEKDAYS[d.getDay()])}</span>
            <span class="week-date">${d.getDate()} ${MONTHS[d.getMonth()]}</span>
            ${isToday ? '<span class="today-mark">сегодня</span>' : ""}
            ${plan.shortage
              ? `<span class="badge">не хватает ${fmtDurShort(plan.shortage)}</span>`
              : '<span class="badge badge--ok">всё помещается</span>'}
          </span>
          <span class="week-bar" aria-hidden="true">
            <i class="${plan.shortage ? "is-over" : ""}" style="width:${Math.min(100, load)}%"></i>
          </span>
          <span class="week-meta">
            <span>занято ${fmtDurShort(plan.plannedMin)}</span>
            <span>свободно ${fmtDurShort(plan.freeMin)}</span>
          </span>
        </button>`);
    }

    list.innerHTML = rows.join("");
    $$(".week-row", list).forEach((row) => {
      row.addEventListener("click", () => {
        selectedDate = row.dataset.date;
        setScreen("today");
      });
    });
  }

  function renderPlanB() {
    const plan = planFor(selectedDate);
    const alts = remoteMode ? serverAlternatives : alternativesFor(plan);
    const body = $("#planbBody");

    if (!plan.shortage) {
      body.innerHTML = `
        <div class="card fact fact--ok">
          <p class="fact-title">Всё помещается</p>
          <p class="fact-text">На этот день конфликтов нет — План Б не нужен.</p>
        </div>
        <button class="btn btn-primary btn-block" type="button" id="planbDone">Вернуться к дню</button>`;
      $("#planbDone").addEventListener("click", () => setScreen("today"));
      return;
    }

    const task = [...plan.unplaced].sort((a, b) => b.need - a.need)[0]?.task;
    const maxBar = Math.max(plan.shortage, 1);

    const cards = alts.map((alt, index) => `
      <article class="card alt" data-alt="${alt.id}" style="animation-delay:${index * 50}ms">
        <h3>${escapeHTML(alt.title)}</h3>
        <ul class="alt-changes">
          ${alt.changes.map((c) => `<li>${escapeHTML(c)}</li>`).join("")}
        </ul>
        <div class="cmp">
          <div class="cmp-row">
            <span>Сейчас</span>
            <span class="cmp-bar"><i style="width:${Math.round((plan.shortage / maxBar) * 100)}%"></i></span>
            <span class="cmp-val">${fmtDurShort(plan.shortage)}</span>
          </div>
          <div class="cmp-row">
            <span>После</span>
            <span class="cmp-bar"><i class="after" style="width:${Math.round((alt.remaining / maxBar) * 100)}%"></i></span>
            <span class="cmp-val">${alt.remaining ? fmtDurShort(alt.remaining) : "0 мин"}</span>
          </div>
        </div>
        <p class="risk-line">${alt.remaining
          ? `Останется под риском: <strong>${fmtDur(alt.remaining)}</strong>`
          : "Риск просрочки закрывается полностью"}</p>
        <button class="btn ${alt.action === "keep" ? "btn-outline" : "btn-primary"} btn-block"
                type="button" data-apply="${alt.id}">
          ${alt.action === "keep" ? "Оставить как есть" : "Применить"}
        </button>
      </article>`).join("");

    body.innerHTML = `
      <div class="fact">
        <p class="fact-title">Не хватает ${fmtDur(plan.shortage)}</p>
        <p class="fact-text">${task ? `До срока «${escapeHTML(task.title)}»` : "До ближайшего срока"} не помещается ${fmtDur(plan.shortage)}. Выбери вариант — изменения видно до применения.</p>
      </div>
      ${cards}`;

    $$("[data-apply]", body).forEach((btn) => {
      btn.addEventListener("click", () => {
        const alt = alts.find((a) => a.id === btn.dataset.apply);
        if (alt) applyAlternative(alt);
      });
    });
  }

  function renderProfile() {
    $("#setDayEnd").value = state.settings.dayEnd;
    $("#setBreak").value = String(state.settings.breakAfterSchool);
    $("#setNotify").checked = Boolean(state.settings.notifications);
    const theme = state.settings.theme || "auto";
    $$("#themeChips .chip").forEach((chip) => {
      chip.setAttribute("aria-pressed", String(chip.dataset.theme === theme));
    });
    const layout = state.settings.layout || "mobile";
    $$("#layoutChips .chip").forEach((chip) => {
      chip.setAttribute("aria-pressed", String(chip.dataset.layout === layout));
    });
  }

  // ---------------------------------------------------------------- лист добавления
  function renderTemplates() {
    const taskBox = $("#taskTemplates");
    taskBox.innerHTML = TASK_TEMPLATES.map((t) =>
      `<button class="chip chip--tpl" type="button" data-tpl-task="${escapeAttr(t.label)}">${escapeHTML(t.label)}</button>`
    ).join("");
    $$("[data-tpl-task]", taskBox).forEach((btn) => {
      btn.addEventListener("click", () => {
        const tpl = TASK_TEMPLATES.find((t) => t.label === btn.dataset.tplTask);
        if (!tpl) return;
        $("#taskTitle").value = tpl.title;
        $("#taskEst").value = String(tpl.estimated);
        clearErrors();
        $("#taskTitle").focus();
      });
    });

    const eventBox = $("#eventTemplates");
    eventBox.innerHTML = EVENT_TEMPLATES.map((t) =>
      `<button class="chip chip--tpl" type="button" data-tpl-event="${escapeAttr(t.label)}">${escapeHTML(t.label)}</button>`
    ).join("");
    $$("[data-tpl-event]", eventBox).forEach((btn) => {
      btn.addEventListener("click", () => {
        const tpl = EVENT_TEMPLATES.find((t) => t.label === btn.dataset.tplEvent);
        if (!tpl) return;
        $("#eventTitle").value = tpl.title;
        $("#eventCategory").value = tpl.category;
        $("#eventStart").value = tpl.start;
        $("#eventEnd").value = tpl.end;
        if (tpl.weekdays.length) {
          selectedWeekdays = tpl.weekdays.slice();
          renderWeekdayChips();
        }
        clearErrors();
      });
    });
  }

  function renderWeekdayChips() {
    const box = $("#weekdayChips");
    box.innerHTML = WEEK_ORDER.map((d) =>
      `<button class="day-chip" type="button" data-day="${d}" aria-pressed="${selectedWeekdays.includes(d) ? "true" : "false"}">${WEEK_SHORT_BY_NUM[d]}</button>`
    ).join("");
    $$("[data-day]", box).forEach((chip) => {
      chip.addEventListener("click", () => {
        const d = Number(chip.dataset.day);
        const at = selectedWeekdays.indexOf(d);
        if (at >= 0) selectedWeekdays.splice(at, 1);
        else selectedWeekdays.push(d);
        renderWeekdayChips();
        $("#weekdayErr").textContent = "";
      });
    });
  }

  // ------------------------------------------------- проверка окна «а если добавить?»
  const pluralDays = (n) => {
    const m10 = n % 10;
    const m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return "день";
    if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return "дня";
    return "дней";
  };
  function renderCalcChips() {
    const box = $("#calcChips");
    if (!box) return;
    box.innerHTML = WEEK_ORDER.map((d) =>
      `<button class="day-chip" type="button" data-calc-day="${d}" aria-pressed="${calcDays.includes(d) ? "true" : "false"}">${WEEK_SHORT_BY_NUM[d]}</button>`
    ).join("");
    $$("[data-calc-day]", box).forEach((chip) => {
      chip.addEventListener("click", () => {
        const d = Number(chip.dataset.calcDay);
        const at = calcDays.indexOf(d);
        if (at >= 0) calcDays.splice(at, 1);
        else calcDays.push(d);
        renderCalcChips();
      });
    });
  }

  function runCalculator() {
    const out = $("#calcResult");
    out.hidden = false;
    const from = toMin($("#calcFrom").value || "00:00");
    const to = toMin($("#calcTo").value || "00:00");

    if (!calcDays.length) {
      out.innerHTML = '<p class="hint">Выбери хотя бы один день недели.</p>';
      return;
    }
    if (to <= from) {
      out.innerHTML = '<p class="hint">Время «По» должно быть позже времени «С».</p>';
      return;
    }

    const start = parseISO(todayISO());
    const rows = [];
    let conflicts = 0;
    let daysTotal = 0;

    for (let i = 0; i < 14; i++) {
      const date = iso(addDays(start, i));
      const d = parseISO(date);
      const dow = d.getDay() === 0 ? 7 : d.getDay();
      if (!calcDays.includes(dow)) continue;

      const plan = planFor(date);
      const wFrom = Math.max(from, DAY_START);
      const wTo = Math.min(to, plan.dayEnd);
      if (wTo <= wFrom) continue;

      const hits = plan.blocks
        .filter((b) => b.kind !== "free")
        .filter((b) => Math.max(b.from, wFrom) < Math.min(b.to, wTo))
        .map((b) => ({ block: b, overlap: Math.min(b.to, wTo) - Math.max(b.from, wFrom) }));

      const dueTasks = state.tasks.filter(
        (t) => !t.done && t.due === date && remainingFor(t) > 0 &&
          !hits.some((h) => h.block.sourceId === t.id)
      );
      if (!hits.length && !dueTasks.length) continue;

      const clashMin = hits.reduce((sum, h) => sum + h.overlap, 0);
      const gapMin = Math.max(0, wTo - wFrom - clashMin);
      const freed = Math.min(gapMin, plan.freeMin);
      const freeAfter = Math.max(0, plan.freeMin - freed);
      const note = gapMin <= 0
        ? "Окно занято полностью — новое дело не вписывается: что-то придётся перенести."
        : `Новое займёт ${fmtDurShort(freed)} свободного времени, останется ${fmtDurShort(freeAfter)}.`;

      daysTotal += 1;
      conflicts += hits.length + dueTasks.length;
      if (rows.length >= 6) continue;

      rows.push(`
        <div class="calc-day">
          <p class="calc-day-name">${cap(WEEKDAYS[d.getDay()])}, ${d.getDate()} ${MONTHS[d.getMonth()]}</p>
          <ul class="calc-list">
            ${hits.map((h) => `<li>«${escapeHTML(h.block.title)}» ${toHM(h.block.from)}–${toHM(h.block.to)} — уже занято ${fmtDurShort(h.overlap)}</li>`).join("")}
            ${dueTasks.map((t) => `<li>Срок: «${escapeHTML(t.title)}» — около ${fmtDurShort(remainingFor(t))}</li>`).join("")}
          </ul>
          <p class="calc-note">${note}</p>
        </div>`);
    }

    if (!daysTotal) {
      out.innerHTML = '<p class="calc-ok">Окно свободно — можно добавлять, ничего переносить не придётся.</p>';
      return;
    }

    const overflow = daysTotal - rows.length;
    out.innerHTML = `
      <p class="calc-verdict">Найдено ${daysTotal} ${pluralDays(daysTotal)} с занятым окном — что именно мешает, ниже.</p>
      ${rows.join("")}
      ${overflow > 0 ? `<p class="calc-note">…и ещё на ${overflow} ${pluralDays(overflow)} похожая ситуация.</p>` : ""}`;
  }

  function openSheet(type, id) {
    sheetType = type || "task";
    editingId = id || null;
    selectedWeekdays = [];
    renderTemplates();

    if (editingId) {
      if (sheetType === "task") {
        const task = state.tasks.find((t) => t.id === editingId);
        if (task) {
          $("#taskTitle").value = task.title;
          $("#taskDue").value = task.due;
          $("#taskEst").value = String(task.estimated);
          $("#taskSplit").checked = task.splittable;
          $$("#priorityChips .chip").forEach((c) => {
            c.setAttribute("aria-pressed", String(c.dataset.priority === task.priority));
          });
        }
      } else {
        const ev = state.events.find((e) => e.id === editingId);
        if (ev) {
          $("#eventTitle").value = ev.title;
          $("#eventCategory").value = ev.category;
          $("#eventStart").value = ev.start;
          $("#eventEnd").value = ev.end;
          $("#eventTravel").value = String(ev.travelBefore || 0);
          $("#eventTravelAfter").value = String(ev.travelAfter || 0);
          $("#eventMovable").checked = ev.movable;
          selectedWeekdays = ev.weekdays.slice();
        }
      }
    } else {
      $("#taskDue").value = selectedDate;
      if (sheetType === "event") selectedWeekdays = [dowOf(selectedDate)];
    }

    renderWeekdayChips();
    $("#sheetTitle").textContent = editingId
      ? (sheetType === "task" ? "Изменить задание" : "Изменить занятие")
      : "Новое дело";
    $("#saveDeal").textContent = editingId ? "Сохранить изменения" : "Сохранить";
    $("#deleteDeal").hidden = !editingId;

    $("#sheetBackdrop").hidden = false;
    appRoot().style.overflowY = "hidden";
    setSheetType(sheetType);
    const first = sheetType === "task" ? $("#taskTitle") : $("#eventTitle");
    window.setTimeout(() => first.focus(), 30);
  }

  function closeSheet() {
    $("#sheetBackdrop").hidden = true;
    appRoot().style.overflowY = "";
    $("#addForm").reset();
    editingId = null;
    selectedWeekdays = [];
    $("#taskDue").value = selectedDate;
    $("#taskEst").value = "45";
    $("#eventTravel").value = "0";
    $("#eventTravelAfter").value = "0";
    $("#deleteDeal").hidden = true;
    $("#saveDeal").textContent = "Сохранить";
    $$("#priorityChips .chip").forEach((c) => {
      c.setAttribute("aria-pressed", c.dataset.priority === "normal" ? "true" : "false");
    });
    clearErrors();
  }

  function setSheetType(type) {
    sheetType = type;
    $("#tabTask").setAttribute("aria-pressed", String(type === "task"));
    $("#tabEvent").setAttribute("aria-pressed", String(type === "event"));
    $("#fieldsTask").hidden = type !== "task";
    $("#fieldsEvent").hidden = type !== "event";
    $("#formNote").textContent = type === "task"
      ? "Название, срок и длительность — этого достаточно."
      : "Название, начало и конец — остальное по желанию.";
    clearErrors();
  }

  function clearErrors() {
    $$(".field-error").forEach((el) => (el.textContent = ""));
    $$(".input").forEach((el) => el.removeAttribute("aria-invalid"));
  }

  function setError(id, message) {
    const el = $("#" + id);
    if (el) el.textContent = message;
    const input = el && el.previousElementSibling;
    if (input && input.classList && input.classList.contains("input")) {
      input.setAttribute("aria-invalid", "true");
    }
  }

  function validateForm() {
    clearErrors();
    let ok = true;

    if (sheetType === "task") {
      const title = $("#taskTitle").value.trim();
      const due = $("#taskDue").value;
      const est = Number($("#taskEst").value);

      if (!title) { setError("taskTitleErr", "Впиши название задания"); ok = false; }
      if (!due) { setError("taskDueErr", "Выбери срок"); ok = false; }
      if (!Number.isFinite(est) || est < 5 || est > 480) {
        setError("taskEstErr", "Длительность от 5 до 480 минут");
        ok = false;
      }
    } else {
      const title = $("#eventTitle").value.trim();
      const start = $("#eventStart").value;
      const end = $("#eventEnd").value;

      if (!title) { setError("eventTitleErr", "Впиши название занятия"); ok = false; }
      if (!start || !end || toMin(end) <= toMin(start)) {
        setError("eventTimeErr", "Конец должен быть позже начала");
        ok = false;
      }
      if (!selectedWeekdays.length) {
        setError("weekdayErr", "Отметь хотя бы один день недели");
        ok = false;
      }
    }

    if (!ok) {
      const firstError = $('.input[aria-invalid="true"]');
      if (firstError) firstError.focus();
    }
    return ok;
  }

  async function submitDeal(event) {
    event.preventDefault();
    if (!validateForm()) return;

    if (remoteMode) {
      const button = $("#saveDeal");
      button.disabled = true;
      try {
        if (sheetType === "task") {
          const payload = {
            title: $("#taskTitle").value.trim(),
            due_at: `${$("#taskDue").value}T23:59:00`,
            estimated_min: Number($("#taskEst").value),
            splittable: $("#taskSplit").checked,
            priority: ($("#priorityChips .chip[aria-pressed='true']") || {}).dataset?.priority || "normal"
          };
          await api(editingId ? `/tasks/${encodeURIComponent(editingId)}` : "/tasks",
            editingId ? "PATCH" : "POST", payload);
        } else {
          const existing = state.events.find((item) => item.id === editingId);
          const payload = eventPayload({
            title: $("#eventTitle").value.trim(),
            category: $("#eventCategory").value,
            start: $("#eventStart").value,
            end: $("#eventEnd").value,
            travelBefore: Number($("#eventTravel").value) || 0,
            travelAfter: Number($("#eventTravelAfter").value) || 0,
            movable: $("#eventMovable").checked,
            weekdays: selectedWeekdays.slice().sort((a, b) => a - b)
          }, existing?.seriesDate || existing?.onlyDate || selectedDate);
          await api(editingId ? `/events/${encodeURIComponent(editingId)}` : "/events",
            editingId ? "PATCH" : "POST", payload);
        }
        const wasEditing = Boolean(editingId);
        await reloadRemote();
        closeSheet();
        showToast(wasEditing ? "Изменения сохранены" : "Дело добавлено в план");
      } catch (error) { showToast(error.message); }
      finally { button.disabled = false; }
      return;
    }

    if (sheetType === "task") {
      const priority = ($("#priorityChips .chip[aria-pressed='true']") || {}).dataset?.priority || "normal";
      const data = {
        title: $("#taskTitle").value.trim(),
        due: $("#taskDue").value,
        estimated: Number($("#taskEst").value),
        splittable: $("#taskSplit").checked,
        priority
      };

      if (editingId) {
        const task = state.tasks.find((t) => t.id === editingId);
        if (task) {
          Object.assign(task, data);
          delete state.splits[task.id];
        }
        showToast("Задание изменено");
      } else {
        state.tasks.push(normalizeTask(Object.assign({ id: uid("t") }, data)));
        showToast("Задание добавлено в план");
      }
    } else {
      const data = {
        title: $("#eventTitle").value.trim(),
        category: $("#eventCategory").value,
        weekdays: selectedWeekdays.slice().sort((a, b) => a - b),
        start: $("#eventStart").value,
        end: $("#eventEnd").value,
        travelBefore: Number($("#eventTravel").value) || 0,
        travelAfter: Number($("#eventTravelAfter").value) || 0,
        movable: $("#eventMovable").checked
      };

      if (editingId) {
        const ev = state.events.find((e) => e.id === editingId);
        if (ev) Object.assign(ev, data);
        showToast("Занятие изменено");
      } else {
        state.events.push(normalizeEvent(Object.assign({ id: uid("e") }, data)));
        showToast("Занятие добавлено в расписание");
      }
    }

    save();
    closeSheet();
    render();
  }

  function deleteFromSheet() {
    if (!editingId) return;
    const id = editingId;
    const kind = sheetType;
    closeSheet();
    if (kind === "task") deleteTask(id);
    else deleteEvent(id);
  }

  // ---------------------------------------------------------------- онбординг
  const ONBOARDING_STEPS = [
    {
      art: "clock",
      title: "Это твой реальный день",
      text: "Занятия, дорога, задания и отдых — на одной шкале времени. Видно, что успеваешь, а что нет."
    },
    {
      art: "plan",
      title: "Когда не помещается",
      text: "Приложение покажет точный дефицит в минутах и предложит «План Б» — варианты без чувства вины."
    },
    {
      art: "check",
      title: "План и факт",
      text: "Засекай время на задании. Через несколько дел станет видно, насколько точны твои оценки."
    }
  ];

  const ART = {
    clock: `<svg viewBox="0 0 120 120" fill="none" aria-hidden="true">
      <circle cx="60" cy="60" r="42" stroke="currentColor" stroke-width="3" opacity="0.35"/>
      <path d="M60 34v26l18 12" stroke="currentColor" stroke-width="4" stroke-linecap="round"/>
      <circle cx="60" cy="60" r="4" fill="currentColor"/>
    </svg>`,
    plan: `<svg viewBox="0 0 120 120" fill="none" aria-hidden="true">
      <rect x="24" y="30" width="72" height="14" rx="7" fill="currentColor" opacity="0.7"/>
      <rect x="24" y="54" width="46" height="14" rx="7" fill="currentColor" opacity="0.45"/>
      <rect x="24" y="78" width="60" height="14" rx="7" fill="currentColor" opacity="0.25"/>
    </svg>`,
    check: `<svg viewBox="0 0 120 120" fill="none" aria-hidden="true">
      <circle cx="60" cy="60" r="40" stroke="currentColor" stroke-width="3" opacity="0.35"/>
      <path d="M42 61l12 12 24-26" stroke="currentColor" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>`
  };

  function renderOnboarding() {
    const step = ONBOARDING_STEPS[onboardStep];
    $("#onboardingArt").innerHTML = ART[step.art] || "";
    $("#onboardingStep").textContent = `Шаг ${onboardStep + 1} из ${ONBOARDING_STEPS.length}`;
    $("#onboardingTitle").textContent = step.title;
    $("#onboardingText").textContent = step.text;
    $("#onboardingNext").textContent = onboardStep === ONBOARDING_STEPS.length - 1 ? "Начать" : "Дальше";
    $("#onboardingDots").innerHTML = ONBOARDING_STEPS.map((_, i) =>
      `<span class="${i === onboardStep ? "is-active" : ""}"></span>`
    ).join("");
  }

  function openOnboarding() {
    onboardStep = 0;
    renderOnboarding();
    $("#onboarding").hidden = false;
  }

  function finishOnboarding() {
    $("#onboarding").hidden = true;
    state.meta.onboarded = true;
    save();
    openSheet("task");
  }

  function skipOnboarding() {
    $("#onboarding").hidden = true;
    state.meta.onboarded = true;
    save();
  }

  // ---------------------------------------------------------------- вспомогательное
  function escapeHTML(value) {
    return String(value).replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[ch]));
  }
  const escapeAttr = escapeHTML;

  function showToast(message, action) {
    const el = $("#toast");
    el.innerHTML = "";
    const text = document.createElement("span");
    text.textContent = message;
    el.appendChild(text);

    if (action) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "toast-action";
      btn.textContent = action.label;
      btn.addEventListener("click", () => {
        el.classList.remove("is-visible");
        window.clearTimeout(toastTimer);
        action.onAction();
      });
      el.appendChild(btn);
    }

    el.classList.add("is-visible");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => el.classList.remove("is-visible"), action ? 6000 : 3200);
  }

  // ---------------------------------------------------------------- события
  $$(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => setScreen(btn.dataset.screen));
  });

  $("#cityShow").addEventListener("click", () => {
    chosenCity = $("#citySelect").value.trim();
    if (!chosenCity) { showToast("Введи название города"); return; }
    localStorage.setItem("timebalance.city.v1", chosenCity);
    cityEvents = [];
    cityError = "";
    renderCity();
    loadCityEvents();
  });

  $("#citySelect").addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); $("#cityShow").click(); }
  });

  $("#cityEvents").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-remind], [data-unremind]");
    if (!button) return;
    if (button.dataset.unremind) {
      button.disabled = true;
      try {
        await api(`/city-events/reminders/${encodeURIComponent(button.dataset.unremind)}`, "DELETE");
        await loadCityReminders();
        showToast("Напоминание убрано");
      } catch (error) { button.disabled = false; showToast(error.message); }
      return;
    }
    const item = cityEvents.find((row) => String(row.id) === button.dataset.remind);
    if (!item || !remoteMode) return;
    if (!state.settings.notifications) { showToast("Включи уведомления в профиле"); return; }
    const date = $(`#cityDate-${item.id}`)?.value;
    if (!date) return;
    button.disabled = true;
    try {
      await api("/city-events/reminders", "POST", {
        source_id: item.id, city: chosenCity, starts_at: date,
        title: item.title, url: item.url
      });
      await loadCityReminders();
      showToast("Напомним в день мероприятия через бота MAX");
    } catch (error) { button.disabled = false; showToast(error.message); }
  });

  $("#planbBack").addEventListener("click", () => setScreen("today"));

  $("#fab").addEventListener("click", () => openSheet(sheetType));

  $("#sheetClose").addEventListener("click", closeSheet);
  $("#sheetBackdrop").addEventListener("click", (e) => {
    if (e.target === $("#sheetBackdrop")) closeSheet();
  });

  $("#tabTask").addEventListener("click", () => setSheetType("task"));
  $("#tabEvent").addEventListener("click", () => setSheetType("event"));

  $("#priorityChips").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    $$(".chip", $("#priorityChips")).forEach((c) => {
      c.setAttribute("aria-pressed", String(c === chip));
    });
  });

  $("#themeChips").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    state.settings.theme = chip.dataset.theme;
    save();
    applyTheme();
    renderProfile();
  });

  $("#layoutChips").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    state.settings.layout = chip.dataset.layout;
    save();
    applyLayout();
    renderProfile();
  });

  $("#addForm").addEventListener("submit", submitDeal);
  $("#deleteDeal").addEventListener("click", deleteFromSheet);

  $("#onboardingNext").addEventListener("click", () => {
    if (onboardStep >= ONBOARDING_STEPS.length - 1) {
      finishOnboarding();
      return;
    }
    onboardStep += 1;
    renderOnboarding();
  });

  $("#onboardingSkip").addEventListener("click", skipOnboarding);

  $("#saveSettings").addEventListener("click", async () => {
    const dayEnd = $("#setDayEnd").value || "21:00";
    const brk = Number($("#setBreak").value);
    if (toMin(dayEnd) < 12 * 60) {
      showToast("Учебный день должен заканчиваться не раньше 12:00");
      return;
    }
    if (!Number.isFinite(brk) || brk < 0 || brk > 180) {
      showToast("Перерыв — от 0 до 180 минут");
      return;
    }
    if (remoteMode) {
      try {
        await api("/me", "PATCH", {
          day_end: dayEnd, break_after_school_min: Math.round(brk),
          notifications_enabled: $("#setNotify").checked
        });
      } catch (error) { showToast(error.message); return; }
    }
    state.settings.dayEnd = dayEnd;
    state.settings.breakAfterSchool = Math.round(brk);
    state.settings.notifications = $("#setNotify").checked;
    save();
    if (remoteMode) await refreshServerPlan().catch((error) => showToast(error.message));
    showToast("Настройки сохранены");
    render();
  });

  const resetCard = {
    open() {
      $("#resetData").hidden = true;
      $("#resetConfirm").hidden = false;
      $("#resetConfirmYes").focus();
    },
    close() {
      $("#resetConfirm").hidden = true;
      $("#resetData").hidden = false;
      $("#resetData").focus();
    }
  };

  $("#resetData").addEventListener("click", () => resetCard.open());

  $("#resetCancel").addEventListener("click", () => resetCard.close());

  $("#resetConfirmYes").addEventListener("click", async () => {
    const reconnect = remoteMode;
    if (remoteMode) {
      try { await api("/me/data", "DELETE"); }
      catch (error) { showToast(error.message); return; }
      remoteMode = false;
      apiToken = null;
    }
    const theme = state.settings.theme;
    const layout = state.settings.layout;
    state = initialState();
    state.settings.theme = theme;
    state.settings.layout = layout;
    state.meta.onboarded = true;
    selectedDate = todayISO();
    activeTaskId = null;
    save();
    resetCard.close();
    render();
    showToast("Данные сброшены");
    if (reconnect) connectMax();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("#resetConfirm").hidden) {
      resetCard.close();
      return;
    }
    if (e.key === "Escape" && !$("#sheetBackdrop").hidden) closeSheet();
    if (e.key !== "Tab" || $("#sheetBackdrop").hidden) return;
    const focusable = $$('button, input, select, [tabindex]:not([tabindex="-1"])', $("#sheet"))
      .filter((el) => !el.disabled && el.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  });

  // ---------------------------------------------------------------- старт
  applyTheme();
  applyLayout();
  renderTemplates();
  renderWeekdayChips();
  renderCalcChips();
  $("#calcRun").addEventListener("click", runCalculator);
  $("#taskDue").value = selectedDate;
  setSheetType("task");
  render();

  window.setInterval(tickTimers, 1000);

  if (!state.meta.onboarded) {
    openOnboarding();
  }

  window.__tbReady = true;
  connectMax();
})();
