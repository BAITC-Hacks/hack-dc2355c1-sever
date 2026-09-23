(() => {
  const editor = document.getElementById("catalog-editor");
  const select = document.getElementById("catalog-scenario");
  const form = document.getElementById("catalog-form");
  const fields = document.getElementById("catalog-fields");
  const loadButton = document.getElementById("catalog-load");
  const saveButton = document.getElementById("catalog-save");
  const resetButton = document.getElementById("catalog-reset");
  const status = document.getElementById("catalog-status");
  const inputs = Object.fromEntries(["name", "description", "ru", "kk"].map(key => [key, document.getElementById("catalog-" + key)]));
  let catalog = [], original = null, busy = false, dirty = false, message = "";
  const copy = value => JSON.parse(JSON.stringify(value));
  function say(key) { message = key; status.textContent = tr(key); }
  function controls() {
    fields.disabled = busy || !original;
    select.disabled = busy || !catalog.length;
    loadButton.disabled = busy;
    saveButton.disabled = busy || !dirty;
    resetButton.disabled = busy || !dirty;
  }
  function fill(scenario) {
    original = scenario ? copy(scenario) : null;
    inputs.name.value = scenario?.name || "";
    inputs.description.value = scenario?.description || "";
    inputs.ru.value = scenario?.responses?.ru?.opening || "";
    inputs.kk.value = scenario?.responses?.kk?.opening || "";
    dirty = false;
    controls();
  }
  function populate(id) {
    select.replaceChildren();
    catalog.forEach(s => select.add(new Option(s.scenario_id + " · " + s.name, s.scenario_id)));
    select.value = catalog.some(s => s.scenario_id === id) ? id : (catalog[0]?.scenario_id || "");
    fill(catalog.find(s => s.scenario_id === select.value));
  }
  async function fetchCatalog() {
    const response = await fetch("/api/scenarios", { cache: "no-store" });
    if (!response.ok) throw new Error("load");
    const result = await response.json();
    if (!Array.isArray(result) || result.some(s => !s || typeof s.scenario_id !== "string")) throw new Error("format");
    if (new Set(result.map(s => s.scenario_id)).size !== result.length) throw new Error("duplicate");
    return result;
  }
  function discardAllowed() { return !dirty || window.confirm(tr("Отменить несохранённые правки?")); }
  async function load() {
    if (busy || !discardAllowed()) return;
    busy = true; controls(); say("Загрузка…");
    try {
      const id = select.value;
      catalog = await fetchCatalog();
      populate(id);
      say(catalog.length ? "Каталог загружен." : "Каталог пуст.");
    } catch { say("Не удалось загрузить каталог. Правки сохранены в форме."); }
    finally { busy = false; controls(); }
  }
  select.onchange = () => {
    if (!discardAllowed()) { select.value = original?.scenario_id || ""; return; }
    fill(catalog.find(s => s.scenario_id === select.value)); say("");
  };
  form.oninput = () => {
    dirty = !!original && (inputs.name.value !== original.name || inputs.description.value !== original.description ||
      inputs.ru.value !== (original.responses?.ru?.opening || "") || inputs.kk.value !== (original.responses?.kk?.opening || ""));
    controls(); say(dirty ? "Есть несохранённые правки." : "");
  };
  form.onsubmit = async event => {
    event.preventDefault();
    if (busy || !dirty || !original || !form.reportValidity()) return;
    if (!inputs.name.value.trim() || !inputs.description.value.trim()) { say("Название и описание не могут быть пустыми."); return; }
    const edited = copy(original);
    edited.name = inputs.name.value.trim(); edited.description = inputs.description.value.trim();
    edited.responses ||= {};
    for (const lang of ["ru", "kk"]) {
      const value = inputs[lang].value;
      if (value !== (original.responses?.[lang]?.opening || "")) {
        edited.responses[lang] ||= {};
        edited.responses[lang].opening = value;
      }
    }
    busy = true; controls(); say("Сохраняю…");
    try {
      // API принимает весь каталог: берём свежую версию, чтобы сохранить другие сценарии.
      const latest = await fetchCatalog();
      const index = latest.findIndex(s => s.scenario_id === original.scenario_id);
      if (index < 0 || JSON.stringify(latest[index]) !== JSON.stringify(original)) {
        say("Сценарий уже изменён. Скопируйте свои правки и загрузите каталог заново."); return;
      }
      latest[index] = edited;
      const response = await fetch("/api/scenarios", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(latest) });
      if (!response.ok) throw new Error("save");
      catalog = latest; populate(edited.scenario_id); say("Сценарий сохранён.");
    } catch { say("Не удалось сохранить. Правки остались в форме."); }
    finally { busy = false; controls(); }
  };
  resetButton.onclick = () => { fill(original); say(""); };
  loadButton.onclick = load;
  editor.addEventListener("toggle", () => { if (editor.open && !catalog.length && !busy) load(); });
  window.addEventListener("uilanguagechange", () => say(message));
  window.addEventListener("beforeunload", event => { if (dirty) { event.preventDefault(); event.returnValue = ""; } });
})();
