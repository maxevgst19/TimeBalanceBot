(() => {
  "use strict";

  // ---------------------------------------------------------------- утилиты
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const pad = (n) => String(n).padStart(2, "0");
  const toMin = (s) => {
    const [h, m] = s.split(":").map(Number);
    return h * 60 + m;
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
  const fmtDur = (m) => {
    m = Math.max(0, Math.round(m));
    const h = Math.floor(m / 60);
    const r = m % 60;
    if (h && r) return `${h} ч ${r} мин`;
    if (h) return `${h} ч`;
    return `${r} мин`;
  };
  const fmtDurShort = (m) => {
    const h = Math.floor(m / 60);
    const r = m % 60;
    if (h && r) return `${h} ч ${r} мин`;
    if (h) return `${h} ч`;
    return `${r} мин`;
  };
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

  // ---------------------------------------------------------------- данные
  const STORE_KEY = "timebalance.frontend.v2";
  const DAY_START = 7 * 60;

  function initialState() {
    return {
      settings: { dayEnd: "21:00", breakAfterSchool: 30, notifications: true },
      events: [],
      tasks: [],
      moved: {},
      splits: {}
    };
  }

  function load() {
    try {
      const raw = localStorage.getItem(STORE_KEY);
      if (!raw) return null;
      const data = JSON.parse(raw);
      if (!data || !data.settings || !Array.isArray(data.events) || !Array.isArray(data.tasks)) return null;
      return data;
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
  let screen = "today";
  let selectedDate = todayISO();
  let sheetType = "task";
  let activeTaskId = null;
  let toastTimer = null;

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

  function planFor(dateStr) {
    const d = parseISO(dateStr);
    const dow = d.getDay() === 0 ? 7 : d.getDay();
    const dayEnd = Math.min(toMin(state.settings.dayEnd), 24 * 60);
    const movedOn = state.moved[dateStr] || {};
    const eventsToday = state.events.filter(
      (e) => Array.isArray(e.weekdays) && e.weekdays.includes(dow) && !movedOn[e.id]
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
      let need = Object.prototype.hasOwnProperty.call(state.splits, t.id)
        ? state.splits[t.id]
        : t.estimated;
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
        const cap = w.to - w.from;
        if (cap < 15) continue;
        // Если окно короче на считаные минуты, лучше взять следующее,
        // чем оставить на шкале огрызок меньше 15 минут.
        if (need > cap && need - cap < 15) continue;
        const use = Math.min(cap, need);
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
      const need = Object.prototype.hasOwnProperty.call(state.splits, splitTask.id)
        ? state.splits[splitTask.id]
        : splitTask.estimated;
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
      const dow = parseISO(plan.dateStr).getDay() === 0 ? 7 : parseISO(plan.dateStr).getDay();
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

  function applyAlternative(alt) {
    if (alt.id === "split") {
      const plan = planFor(selectedDate);
      const task = splitCandidate(plan);
      if (task) {
        const need = Object.prototype.hasOwnProperty.call(state.splits, task.id)
          ? state.splits[task.id]
          : task.estimated;
        const keep = Math.max(20, Math.min(30, Math.round(need / 2 / 5) * 5));
        state.splits[task.id] = keep;
        save();
        showToast("План обновлён: часть задания перенесена на завтра");
      }
    } else if (alt.id === "move") {
      const plan = planFor(selectedDate);
      const dow = parseISO(selectedDate).getDay() === 0 ? 7 : parseISO(selectedDate).getDay();
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

  function toggleTaskDone(taskId) {
    const task = state.tasks.find((t) => t.id === taskId);
    if (!task) return;
    task.done = !task.done;
    save();
    showToast(task.done ? "Отмечено выполненным" : "Дело возвращено в план");
    render();
  }

  // ---------------------------------------------------------------- отрисовка
  function render() {
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
  }

  function setScreen(next) {
    screen = next;
    $$("#screen-today, #screen-week, #screen-planb, #screen-profile").forEach((sec) => {
      sec.hidden = sec.id !== `screen-${next}`;
    });
    render();
    appRoot().scrollTop = 0;
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
      if (isTask) {
        activeTaskId = upcoming.sourceId;
        showToast(`Начали: ${upcoming.title} · ${fmtDur(duration)}`);
        renderTimeline(plan, isToday);
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
      <p class="conflict-text">${dueText.charAt(0).toUpperCase() + dueText.slice(1)}: в плане не помещается ${fmtDur(plan.shortage)}. Это не про «соберись», а про время.</p>
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

    for (const b of plan.blocks) {
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
      parts.push(`
        <div class="blk ${kindClass}${compact ? " blk--compact" : ""}${tiny ? " blk--tiny" : ""}${b.sourceId && b.sourceId === activeTaskId ? " is-active" : ""}"
             style="top:${top}px;height:${h}px" role="listitem"
             aria-label="${escapeAttr(label)} ${escapeAttr(b.title)}, ${toHM(b.from)}–${toHM(b.to)}, ${fmtDur(dur)}">
          <span class="blk-title">${escapeHTML(b.title)}</span>
          ${compact ? "" : `<span class="blk-meta">${toHM(b.from)}–${toHM(b.to)} · ${fmtDur(dur)}</span>`}
        </div>`);
    }

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
  }

  function renderSummary(plan) {
    const nextDue = plan.tasks
      .filter((t) => !t.done)
      .sort((a, b) => a.due.localeCompare(b.due))[0];
    const dueText = nextDue
      ? (nextDue.due === todayISO() ? "сегодня" : shortDate(nextDue.due))
      : "нет";

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
      </div>`;
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
        <button class="week-row" type="button" data-date="${date}">
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
    const alts = alternativesFor(plan);
    const body = $("#planbBody");

    if (!plan.shortage) {
      body.innerHTML = `
        <div class="card fact">
          <p class="fact-title">Всё помещается</p>
          <p class="fact-text">На этот день конфликтов нет — План Б не нужен.</p>
        </div>
        <button class="btn btn-primary btn-block" type="button" id="planbDone">Вернуться к дню</button>`;
      $("#planbDone").addEventListener("click", () => setScreen("today"));
      return;
    }

    const task = [...plan.unplaced].sort((a, b) => b.need - a.need)[0].task;
    const maxBar = Math.max(plan.shortage, 1);

    const cards = alts.map((alt) => `
      <article class="card alt" data-alt="${alt.id}">
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
  }

  // ---------------------------------------------------------------- лист добавления
  function openSheet(type) {
    sheetType = type || "task";
    $("#taskDue").value = selectedDate;
    $("#eventDate").value = selectedDate;
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
    $("#taskDue").value = selectedDate;
    $("#eventDate").value = selectedDate;
    $("#taskEst").value = "45";
    $("#priorityChips").querySelectorAll(".chip").forEach((c) => {
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
    }

    if (!ok) {
      const firstError = $('.input[aria-invalid="true"]');
      if (firstError) firstError.focus();
    }
    return ok;
  }

  function submitDeal(event) {
    event.preventDefault();
    if (!validateForm()) return;

    if (sheetType === "task") {
      state.tasks.push({
        id: `t${Date.now()}`,
        title: $("#taskTitle").value.trim(),
        due: $("#taskDue").value,
        estimated: Number($("#taskEst").value),
        splittable: $("#taskSplit").checked,
        priority: ($("#priorityChips .chip[aria-pressed='true']") || {}).dataset?.priority || "normal",
        done: false
      });
      showToast("Задание добавлено в план");
    } else {
      const date = $("#eventDate").value || selectedDate;
      const dow = parseISO(date).getDay() === 0 ? 7 : parseISO(date).getDay();
      state.events.push({
        id: `e${Date.now()}`,
        title: $("#eventTitle").value.trim(),
        category: $("#eventCategory").value,
        weekdays: [dow],
        start: $("#eventStart").value,
        end: $("#eventEnd").value,
        travelBefore: Number($("#eventTravel").value) || 0,
        travelAfter: Number($("#eventTravel").value) || 0,
        movable: $("#eventMovable").checked
      });
      showToast("Занятие добавлено в расписание");
    }

    save();
    closeSheet();
    render();
  }

  // ---------------------------------------------------------------- вспомогательное
  function escapeHTML(value) {
    return String(value).replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[ch]));
  }
  const escapeAttr = escapeHTML;

  function showToast(message) {
    const el = $("#toast");
    el.textContent = message;
    el.classList.add("is-visible");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => el.classList.remove("is-visible"), 3200);
  }

  // ---------------------------------------------------------------- события
  $$(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => setScreen(btn.dataset.screen));
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

  $("#addForm").addEventListener("submit", submitDeal);

  $("#saveSettings").addEventListener("click", () => {
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
    state.settings.dayEnd = dayEnd;
    state.settings.breakAfterSchool = Math.round(brk);
    state.settings.notifications = $("#setNotify").checked;
    save();
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
    },
  };

  $("#resetData").addEventListener("click", () => resetCard.open());

  $("#resetCancel").addEventListener("click", () => resetCard.close());

  $("#resetConfirmYes").addEventListener("click", () => {
    state = initialState();
    selectedDate = todayISO();
    activeTaskId = null;
    save();
    resetCard.close();
    render();
    showToast("Данные сброшены");
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
  $("#taskDue").value = selectedDate;
  $("#eventDate").value = selectedDate;
  setSheetType("task");
  render();
  window.__tbReady = true;
})();
