(() => {
  "use strict";
  const form = document.getElementById("catalog-filters");
  if (!form) return;
  let records = [];
  const fields = ["query", "runtime-version", "robot", "controller", "os"];
  const elements = Object.fromEntries(fields.map(id => [id, document.getElementById(id)]));
  const cards = [...document.querySelectorAll("[data-skill]")];
  const count = document.getElementById("result-count");
  const hint = document.getElementById("filter-hint");
  const empty = document.getElementById("empty-state");
  function filter() {
    if (!records.length) return;
    const text = elements.query.value.trim().toLowerCase();
    const constraints = {runtime_version: elements["runtime-version"].value.trim(), robot: elements.robot.value, controller: elements.controller.value, os: elements.os.value};
    const visible = new Set();
    for (const r of records) {
      const searchable = [r.id, r.name, r.summary, ...r.capabilities, ...r.aliases].join(" ").toLowerCase();
      if (text && !text.split(/\s+/).every(word => searchable.includes(word))) continue;
      // Compatibility is a tuple. Never combine runtime/robot/controller from
      // separate tuples, and never treat unknown metadata as an exact match.
      if (!r.compatibility.some(tuple => Object.entries(constraints).every(([key, value]) => !value || (tuple[key] !== "unknown" && tuple[key] === value)))) continue;
      visible.add(r.id);
    }
    cards.forEach(card => { card.hidden = !visible.has(card.dataset.skill); });
    count.textContent = visible.size + (visible.size === 1 ? " recipe" : " recipes");
    empty.hidden = visible.size > 0;
    const missing = Object.entries(constraints).filter(([, value]) => !value).map(([key]) => key.replaceAll("_", " "));
    hint.textContent = missing.length ? "Unknown environment fields: " + missing.join(", ") + ". Inspect all requirements; runtime execution is unverified." : "Exact documented environment match only. Runtime execution remains unverified; observation, Python and architecture must also match.";
  }
  form.addEventListener("submit", event => event.preventDefault());
  Object.values(elements).forEach(element => element.addEventListener("input", filter));
  document.getElementById("clear-filters").addEventListener("click", () => { form.reset(); filter(); elements.query.focus(); });
  const script = document.currentScript || [...document.scripts].find(s => s.src.endsWith("/assets/catalog.js"));
  const catalogUrl = new URL("../catalog/v1/index.json", script.src);
  fetch(catalogUrl).then(response => { if (!response.ok) throw new Error("Catalog request failed"); return response.json(); }).then(data => { records = data.records; filter(); }).catch(() => { hint.textContent = "Search is unavailable. The static recipe pages below remain readable; retry on a working connection."; });
})();
