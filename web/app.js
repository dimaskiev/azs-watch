const KEY = "azs-watch-settings";
const LABELS = {
  a95: "Бензин звичайний · А-95",
  a95plus: "Бензин фірмовий · А-95+",
  a92: "Бензин А-92",
  diesel: "Дизель звичайний",
  dieselplus: "Дизель фірмовий",
  lpg: "Газ",
};

const $ = (id) => document.getElementById(id);

const POLL_MS = 30 * 1000;

const EDIT_KEYS = ["a92", "a95", "a95plus", "diesel", "dieselplus", "lpg"];
const EDIT_LABELS = {
  a92: "А-92",
  a95: "А-95",
  a95plus: "А-95+",
  diesel: "ДП Євро",
  dieselplus: "ДП+",
  lpg: "Газ",
};

const state = {
  data: null,
  settings: loadSettings(),
  busy: false,
  tab: "calc",
  editor: null,
};

function loadSettings() {
  try {
    const raw = {
      fuel: "petrol",
      tier: "regular",
      region: "Україна",
      liters: 40,
      sort: "fill",
      ...JSON.parse(localStorage.getItem(KEY) || "{}"),
    };
    if (raw.grade === "a95plus") raw.tier = "premium";
    else if (raw.grade === "a92") raw.tier = "a92";
    else if (raw.grade === "a95") raw.tier = "regular";
    if (!["regular", "premium", "a92"].includes(raw.tier)) raw.tier = "regular";
    return raw;
  } catch {
    return { fuel: "petrol", tier: "regular", region: "Україна", liters: 40, sort: "fill" };
  }
}

function saveSettings() {
  localStorage.setItem(KEY, JSON.stringify(state.settings));
}

function hosted() {
  const host = (location.hostname || "").toLowerCase();
  if (host.endsWith(".vercel.app") || host.endsWith(".vercel.dev")) return true;
  return !!(state.data && state.data.hosted);
}

function applyHostedChrome() {
  if (!hosted()) return;
  document.body.classList.add("hosted");
  const tabs = document.querySelector(".tabs");
  if (tabs) tabs.classList.add("hidden");
  if ($("view-discounts")) $("view-discounts").classList.add("hidden");
  if ($("view-calc")) $("view-calc").classList.remove("hidden");
  state.tab = "calc";
}

function money(n) {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toFixed(2).replace(".", ",");
}

function fuelKey() {
  const fuel = state.settings.fuel;
  const tier = state.settings.tier;
  if (fuel === "lpg") return "lpg";
  if (fuel === "diesel") return tier === "premium" ? "dieselplus" : "diesel";
  if (tier === "premium") return "a95plus";
  if (tier === "a92") return "a92";
  return "a95";
}

function dieselPlusCopied() {
  const region = state.settings.region;
  const priced = (state.data && state.data.partners || []).filter((p) => {
    const pack = (p.regions || {})[region];
    return pack && pack.retail && pack.retail.diesel != null && pack.retail.dieselplus != null;
  });
  return priced.length > 0 && priced.every((p) => p.regions[region].retail.dieselplus === p.regions[region].retail.diesel);
}

function tierHint() {
  const fuel = state.settings.fuel;
  if (fuel === "lpg") return "автогаз";
  if (fuel === "diesel") {
    if (state.settings.tier === "premium") {
      return dieselPlusCopied()
        ? "ДП+ · окремої актуальної ціни немає, рахуємо як ДП Євро"
        : "фірмовий ДП · Pulls / Mustang / EVOX · якщо немає в Мінфіні — з сайту мережі";
    }
    return "звичайний ДП Євро";
  }
  if (state.settings.tier === "premium") return "А-95+ фірмовий · Pulls / Mustang / EVOX. Окремого А-98 у прайсі немає.";
  if (state.settings.tier === "a92") return "бензин А-92";
  return "А-95 Євро · не 98";
}

function regionBundle(partner) {
  const wanted = state.settings.region;
  const pack = partner.regions[wanted];
  const key = fuelKey();
  const inRegion = !!(pack && pack.retail[key] != null);
  return {
    pack: inRegion ? pack : null,
    inRegion,
    missing: !inRegion,
  };
}

function rows() {
  const key = fuelKey();
  const liters = Number(state.settings.liters) || 0;
  return state.data.partners
    .map((p) => {
      const { pack, inRegion, missing } = regionBundle(p);
      const retail = pack?.retail[key] ?? null;
      const discount = pack?.discount[key] ?? null;
      const real = pack?.real[key] ?? null;
      const source = (pack?.sources && pack.sources[key]) || "";
      const fill = real != null ? round2(real * liters) : null;
      const saved = discount != null ? round2(discount * liters) : null;
      return { ...p, retail, discount, real, fill, saved, source, inRegion, missing };
    })
    .filter((p) => p.inRegion);
}

function round2(n) {
  return Math.round(n * 100) / 100;
}

function sortedRows() {
  return rows().sort((a, b) => {
    const ar = a.real == null ? 1e9 : a.real;
    const br = b.real == null ? 1e9 : b.real;
    if (ar !== br) return ar - br;
    const af = a.fill == null ? 1e9 : a.fill;
    const bf = b.fill == null ? 1e9 : b.fill;
    if (af !== bf) return af - bf;
    return a.name.localeCompare(b.name, "uk");
  });
}

function renderKpis(list) {
  const priced = list.filter((x) => x.real != null).slice().sort((a, b) => a.real - b.real);
  const best = priced[0];
  const liters = Number(state.settings.liters) || 0;
  const saveSum = best && best.discount != null ? best.discount * liters : null;
  $("kpis").innerHTML = [
    kpi("ОПТИМУМ", best ? money(best.real) : "—", best ? `${best.name} · грн/л` : "немає в області"),
    kpi("ЗАПРАВКА", best && best.fill != null ? money(best.fill) : "—", `${liters} л на найдешевшій`),
    kpi("ЕКОНОМІЯ", saveSum != null ? `−${money(saveSum)}` : "—", `${liters} л зі знижкою`),
    kpi("МЕРЕЖ В ОБЛАСТІ", String(list.length), "партнери Плюсів з цим пальним"),
  ].join("");
}

function kpi(k, v, t) {
  return `<article class="kpi"><div class="k">${k}</div><div class="v">${v}</div><div class="t">${t}</div></article>`;
}

function isPhone() {
  return window.matchMedia("(max-width: 720px)").matches;
}

function brandLine(item) {
  const b = item.branded || {};
  const fuel = state.settings.fuel;
  const tier = state.settings.tier;
  let line = "";
  if (fuel === "lpg") line = "";
  else if (fuel === "diesel") {
    line = tier === "premium" ? (b.diesel ? `зараз ДП+ ${b.diesel}` : "зараз ДП+") : "зараз ДП Євро";
  } else if (tier === "premium") line = b.petrol ? `зараз А-95+ ${b.petrol}` : "зараз А-95+";
  else if (tier === "a92") line = "зараз А-92";
  else line = "зараз А-95 Євро";
  if (line && item.source) line += ` · ${item.source}`;
  return line;
}

function netCell(item, extra) {
  const brand = brandLine(item);
  return `<div class="net"><span class="dot" style="background:${item.accent || "#8fa35a"}"></span><div><div>${item.name}${extra || ""}</div>${brand ? `<small class="net-brand">${brand}</small>` : ""}</div></div>`;
}

function renderGrid(list) {
  const liters = Number(state.settings.liters) || 0;
  const label = LABELS[fuelKey()];
  const region = state.settings.region;
  $("table-title").textContent = "ВАРТІСТЬ ЗАПРАВКИ ПО МЕРЕЖАХ";
  const sameDiesel = fuelKey() === "dieselplus" && list.some((p) => {
    const pack = (p.regions || {})[region];
    return pack && pack.retail && pack.retail.diesel != null && pack.retail.dieselplus === pack.retail.diesel;
  });
  const fromSites = list.filter((p) => p.source).map((p) => p.name);
  $("table-sub").textContent = fromSites.length
    ? `${label} · ${region} · ${liters} л · ${fromSites.join(", ")} — актуальна ціна з сайту мережі`
    : sameDiesel
      ? `${label} · ${region} · ${liters} л · окремої актуальної ціни ДП+ немає — цифра як у ДП Євро`
      : `${label} · ${region} · ${liters} л · від найдешевшої до найдорожчої`;

  if (!list.length) {
    $("grid").innerHTML = `<p class="empty">У вибраній області немає партнерів Армія+ з ціною на ${label}.</p>`;
    return;
  }

  const head = `
    <thead><tr>
      <th>#</th>
      <th>Мережа</th>
      <th class="num">Стеля, грн/л</th>
      <th class="num">Знижка</th>
      <th class="num">З Армія+, грн/л</th>
      <th class="num">Заправка ${liters} л</th>
      <th class="num">Економія</th>
      <th>Умови</th>
    </tr></thead>`;

  const cheapest = list.reduce((m, p) => (p.fill != null && (m == null || p.fill < m) ? p.fill : m), null);
  if (isPhone()) {
    $("grid").innerHTML = `<div class="cards">${list
      .map((p, i) => {
        const best = p.fill != null && p.fill === cheapest;
        return `<article class="m-card ${best ? "best" : ""}">
          <div class="m-head">
            <span class="m-rank">${String(i + 1).padStart(2, "0")}</span>
            <h3><span class="dot" style="background:${p.accent || "#8fa35a"}"></span>${p.name}${best ? " · оптимум" : ""}</h3>
            ${brandLine(p) ? `<p class="net-brand">${brandLine(p)}</p>` : ""}
          </div>
          <div class="m-prices">
            <div><span>Стеля</span><b>${money(p.retail)}</b></div>
            <div><span>Знижка</span><b>${p.discount != null ? "−" + money(p.discount) : "—"}</b></div>
            <div class="hi"><span>З Армія+</span><b>${p.real != null ? money(p.real) : "—"}</b></div>
          </div>
          <p class="m-fill">${liters} л = <b>${p.fill != null ? money(p.fill) : "—"}</b> грн</p>
          <p class="m-save">економія ${p.saved != null ? money(p.saved) : "—"} грн</p>
          <p class="m-note">${[p.limit, ...(p.extras || [])].filter(Boolean).join(" · ")}</p>
        </article>`;
      })
      .join("")}</div>`;
    return;
  }

  const body = list
    .map((p, i) => {
      const best = p.fill != null && p.fill === cheapest;
      return `<tr class="${best ? "best" : ""}">
        <td>${String(i + 1).padStart(2, "0")}</td>
        <td>${netCell(p, best ? " · оптимум" : "")}</td>
        <td class="num">${money(p.retail)}</td>
        <td class="num">${p.discount != null ? "−" + money(p.discount) : "—"}</td>
        <td class="num real">${p.real != null ? money(p.real) : "—"}</td>
        <td class="num fill">${p.fill != null ? money(p.fill) : "—"}</td>
        <td class="num">${p.saved != null ? "−" + money(p.saved) : "—"}</td>
        <td class="note">${[p.limit, ...(p.extras || [])].filter(Boolean).join(" · ")}</td>
      </tr>`;
    })
    .join("");

  $("grid").innerHTML = `<table class="sheet">${head}<tbody>${body}</tbody></table>`;
}

function fmtWhen(iso) {
  if (!iso) return "—";
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return iso.replace("T", " ").slice(0, 19);
  return dt.toLocaleString("uk-UA", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function fmtRemain(ms) {
  if (ms <= 0) return "зараз";
  const total = Math.ceil(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h} год ${String(m).padStart(2, "0")} хв`;
  if (m > 0) return `${m} хв ${String(s).padStart(2, "0")} с`;
  return `${s} с`;
}

function renderMeta() {
  const d = state.data;
  const live = d.live && !d.from_cache;
  $("link-pill").textContent = live ? "LINK LIVE" : d.from_cache ? "LINK CACHE" : "LINK DOWN";
  $("link-pill").className = "pill" + (live ? "" : " hot");
  $("src-pill").textContent = hosted()
    ? (d.alt_notes && d.alt_notes.length)
      ? "SRC МІНФІН+МЕРЕЖІ"
      : d.source_date
        ? `SRC ${d.source_date}`
        : "SRC —"
    : d.customized
      ? "ЗНИЖКИ РУЧНІ"
      : (d.alt_notes && d.alt_notes.length)
        ? "SRC МІНФІН+МЕРЕЖІ"
        : d.source_date
          ? `SRC ${d.source_date}`
          : "SRC —";
  $("src-pill").className = "pill" + (!hosted() && d.customized ? "" : " dim");
  $("stamp").textContent = [
    d.caption || "ціни мереж АЗК",
    d.error ? `помилка: ${d.error}` : "",
  ]
    .filter(Boolean)
    .join("  ·  ");
  $("disclaimer").textContent = d.disclaimer || "";
  updateSyncClock();
}

function updateSyncClock() {
  const d = state.data;
  if (!d) return;
  $("sync-last").textContent = `останнє оновлення: ${fmtWhen(d.fetched_at)}`;
  const next = d.next_refresh_at ? new Date(d.next_refresh_at).getTime() : 0;
  const left = next ? next - Date.now() : 0;
  const hours = Math.round((d.refresh_every_sec || 3600) / 3600);
  $("sync-next").textContent = next
    ? `авто кожні ${hours} год · через ${fmtRemain(left)}`
    : `авто кожні ${hours} год`;
}

function fillRegions() {
  const sel = $("region");
  const current = state.settings.region;
  sel.innerHTML = (state.data.regions || ["Україна"])
    .map((r) => `<option value="${r}">${r}</option>`)
    .join("");
  sel.value = state.data.regions.includes(current) ? current : "Україна";
  state.settings.region = sel.value;
}

function applyControls() {
  document.querySelectorAll(".fuel").forEach((btn) => {
    btn.classList.toggle("on", btn.dataset.fuel === state.settings.fuel);
  });
  const showTier = state.settings.fuel !== "lpg";
  $("tier-wrap").style.display = showTier ? "" : "none";
  $("tier-hint").style.display = showTier ? "" : "none";
  const petrol = state.settings.fuel === "petrol";
  $("tier-wrap").classList.toggle("diesel", !petrol);
  $("tier-a92").style.display = petrol ? "" : "none";
  if (!petrol && state.settings.tier === "a92") {
    state.settings.tier = "regular";
  }
  if (petrol) {
    $("tier-regular-code").textContent = "А-95";
    $("tier-regular-name").textContent = "Євро";
    $("tier-premium-code").textContent = "А-95+";
    $("tier-premium-name").textContent = "фірмовий";
    const petrolCode = state.settings.tier === "a92" ? "А-92" : state.settings.tier === "premium" ? "А-95+" : "А-95";
    $("fuel-petrol-code").textContent = petrolCode;
  } else {
    $("tier-regular-code").textContent = "ДП";
    $("tier-regular-name").textContent = "Євро";
    $("tier-premium-code").textContent = "ДП+";
    $("tier-premium-name").textContent = "фірмовий";
    $("fuel-petrol-code").textContent = "А-95";
  }
  document.querySelectorAll(".tier").forEach((btn) => {
    btn.classList.toggle("on", btn.dataset.tier === state.settings.tier);
  });
  $("tier-hint").textContent = tierHint();
  $("liters").value = state.settings.liters;
}

function showTab(tab) {
  if (hosted()) tab = "calc";
  state.tab = tab;
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.classList.toggle("on", btn.dataset.tab === tab);
  });
  $("view-calc").classList.toggle("hidden", tab !== "calc");
  $("view-discounts").classList.toggle("hidden", tab !== "discounts");
  if (tab === "discounts") loadEditor();
  applyHostedChrome();
}

function renderEditor() {
  const editor = state.editor;
  if (!editor) return;
  const keys = editor.keys || Object.keys(EDIT_LABELS);
  const head = `<thead><tr><th>Мережа</th>${keys.map((k) => `<th class="num">${EDIT_LABELS[k] || k}</th>`).join("")}<th>Каталог</th></tr></thead>`;
  const body = (editor.rows || [])
    .map((row) => {
      const cells = keys
        .map((k) => {
          const cur = row.current[k];
          const cat = row.catalog[k];
          const dirty = String(cur ?? "") !== String(cat ?? "");
          return `<td class="num"><input class="cut${dirty ? " dirty" : ""}" data-id="${row.id}" data-key="${k}" type="number" min="0" step="0.1" placeholder="—" value="${cur == null ? "" : cur}" /></td>`;
        })
        .join("");
      const catText = keys
        .map((k) => `${EDIT_LABELS[k]} ${row.catalog[k] == null ? "—" : row.catalog[k]}`)
        .join(" · ");
      return `<tr>
        <td>${netCell(row)}</td>
        ${cells}
        <td class="note">${catText}</td>
      </tr>`;
    })
    .join("");
  $("edit-grid").innerHTML = `<table class="sheet">${head}<tbody>${body}</tbody></table>`;
  $("edit-status").textContent = editor.customized
    ? "є ручні правки з Армія+"
    : "зараз стоять цифри з публічних анонсів";
}

function collectOverrides() {
  const overrides = {};
  $("edit-grid").querySelectorAll("input.cut").forEach((input) => {
    const id = input.dataset.id;
    const key = input.dataset.key;
    if (!overrides[id]) overrides[id] = {};
    overrides[id][key] = input.value === "" ? null : Number(input.value);
  });
  return overrides;
}

async function loadEditor() {
  if (hosted()) return;
  const res = await fetch("/api/discounts", { cache: "no-store" });
  if (!res.ok) throw new Error("HTTP " + res.status);
  state.editor = await res.json();
  renderEditor();
}

async function saveEditor() {
  $("save-discounts").disabled = true;
  $("edit-status").textContent = "зберігаю…";
  try {
    const overrides = collectOverrides();
    const res = await fetch("/api/discounts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ overrides }),
    });
    const payload = await res.json();
    state.editor = payload.editor;
    if (payload.state) {
      state.data = payload.state;
      fillRegions();
      paint();
    }
    renderEditor();
    $("edit-status").textContent = "збережено · розрахунок оновлено";
  } catch (err) {
    $("edit-status").textContent = "не вдалося зберегти: " + err.message;
  } finally {
    $("save-discounts").disabled = false;
  }
}

async function resetEditor() {
  $("reset-discounts").disabled = true;
  try {
    const res = await fetch("/api/discounts/reset", { method: "POST" });
    const payload = await res.json();
    state.editor = payload.editor;
    if (payload.state) {
      state.data = payload.state;
      fillRegions();
      paint();
    }
    renderEditor();
    $("edit-status").textContent = "повернуто каталог публічних анонсів";
  } finally {
    $("reset-discounts").disabled = false;
  }
}

function paint() {
  if (!state.data) return;
  applyControls();
  const list = sortedRows();
  renderMeta();
  renderKpis(list);
  renderGrid(list);
}

async function load(path) {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error("HTTP " + res.status);
  state.data = await res.json();
  applyHostedChrome();
  fillRegions();
  paint();
}

async function manualRefresh() {
  if (state.busy) return;
  state.busy = true;
  $("refresh").disabled = true;
  $("refresh").textContent = "СИНХРОНІЗАЦІЯ…";
  try {
    await load("/api/refresh");
  } catch (err) {
    $("stamp").textContent = "оновлення не вдалося: " + err.message;
  } finally {
    state.busy = false;
    $("refresh").disabled = false;
    $("refresh").textContent = "ОНОВИТИ ЗАРАЗ";
  }
}

function bind() {
  document.querySelectorAll(".fuel").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.settings.fuel = btn.dataset.fuel;
      saveSettings();
      paint();
    });
  });
  $("region").addEventListener("change", () => {
    state.settings.region = $("region").value;
    saveSettings();
    paint();
  });
  document.querySelectorAll(".tier").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.settings.tier = btn.dataset.tier;
      saveSettings();
      paint();
    });
  });
  $("liters").addEventListener("input", () => {
    state.settings.liters = Math.max(1, Number($("liters").value) || 40);
    saveSettings();
    paint();
  });
  $("refresh").addEventListener("click", () => {
    manualRefresh();
  });
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => showTab(btn.dataset.tab));
  });
  $("save-discounts").addEventListener("click", () => saveEditor());
  $("reset-discounts").addEventListener("click", () => resetEditor());
  window.matchMedia("(max-width: 720px)").addEventListener("change", () => {
    if (state.data) paint();
    if (state.tab === "discounts" && state.editor) renderEditor();
  });
}

bind();
applyHostedChrome();
applyControls();
load("/api/state").catch((err) => {
  $("stamp").textContent = "канал недоступний: " + err.message;
});

setInterval(() => {
  if (state.busy || state.tab === "discounts") return;
  load("/api/state").catch(() => {});
}, hosted() ? 5 * 60 * 1000 : POLL_MS);

let dueFetchAt = 0;
setInterval(() => {
  if (!state.data) return;
  updateSyncClock();
  const next = state.data.next_refresh_at ? new Date(state.data.next_refresh_at).getTime() : 0;
  if (next && Date.now() >= next && !state.busy && Date.now() - dueFetchAt > 15000) {
    dueFetchAt = Date.now();
    load("/api/state").catch(() => {});
  }
}, 1000);
