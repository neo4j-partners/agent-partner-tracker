(() => {
  "use strict";

  const catalogue = document.querySelector("[data-catalogue]");
  if (!catalogue) return;

  const table = catalogue.querySelector("table");
  const tableScroll = catalogue.querySelector(".table-scroll");
  const body = table.querySelector("tbody");
  const rows = Array.from(body.rows);
  const total = rows.length;
  const controls = Array.from(catalogue.querySelectorAll("[data-filter]"));
  const count = catalogue.querySelector("[data-result-count]");
  const clearButtons = Array.from(catalogue.querySelectorAll("[data-clear-filters]"));
  const chips = catalogue.querySelector("[data-active-filters]");
  const emptyState = catalogue.querySelector("[data-empty-state]");
  const collator = new Intl.Collator(undefined, {
    numeric: true,
    sensitivity: "base",
  });
  let sortKey = "";
  let sortDirection = "ascending";

  function restoreFilters() {
    const params = new URLSearchParams(window.location.search);
    controls.forEach((control) => {
      const candidate = params.get(control.name) || "";
      const valid = Array.from(control.options).some(
        (option) => option.value === candidate,
      );
      control.value = valid ? candidate : "";
    });
  }

  function renderChips() {
    if (!chips) return;
    chips.innerHTML = "";
    controls.forEach((control) => {
      if (!control.value) return;
      const label = control.dataset.label || control.name;
      const optionText = control.options[control.selectedIndex].textContent;
      const chip = document.createElement("span");
      chip.className = "filter-chip";
      const text = document.createElement("span");
      text.textContent = `${label}: ${optionText}`;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.setAttribute("aria-label", `Remove ${label.toLowerCase()} filter`);
      remove.textContent = "×";
      remove.addEventListener("click", () => {
        control.value = "";
        filterRows({ updateHistory: true });
      });
      chip.append(text, remove);
      chips.append(chip);
    });
  }

  function filterRows({ updateHistory = false } = {}) {
    let visible = 0;
    rows.forEach((row) => {
      const matches = controls.every(
        (control) => !control.value || row.dataset[control.name] === control.value,
      );
      row.hidden = !matches;
      if (matches) visible += 1;
    });
    count.textContent = visible === total
      ? `${total} ${total === 1 ? "record" : "records"}`
      : `${visible} of ${total} ${total === 1 ? "record" : "records"}`;
    if (tableScroll) tableScroll.hidden = visible === 0;
    if (emptyState) emptyState.hidden = visible !== 0;
    renderChips();

    if (updateHistory) {
      const params = new URLSearchParams();
      controls.forEach((control) => {
        if (control.value) params.set(control.name, control.value);
      });
      const query = params.toString();
      const url = `${window.location.pathname}${query ? `?${query}` : ""}`;
      window.history.pushState({}, "", url);
    }
  }

  function cellValue(row, key) {
    const cell = row.querySelector(`[data-column="${key}"]`);
    return cell ? cell.dataset.sortValue || cell.textContent.trim() : "";
  }

  function sortRows(button) {
    const key = button.dataset.sortKey;
    sortDirection = sortKey === key && sortDirection === "ascending"
      ? "descending"
      : "ascending";
    sortKey = key;

    table.querySelectorAll("th[aria-sort]").forEach((header) => {
      header.setAttribute("aria-sort", "none");
    });
    button.closest("th").setAttribute("aria-sort", sortDirection);

    rows.sort((left, right) => {
      const comparison = collator.compare(cellValue(left, key), cellValue(right, key));
      return sortDirection === "ascending" ? comparison : -comparison;
    });
    rows.forEach((row) => body.append(row));
  }

  controls.forEach((control) => {
    control.addEventListener("change", () => filterRows({ updateHistory: true }));
  });
  clearButtons.forEach((button) => {
    button.addEventListener("click", () => {
      controls.forEach((control) => {
        control.value = "";
      });
      filterRows({ updateHistory: true });
      controls[0].focus();
    });
  });
  table.querySelectorAll("[data-sort-key]").forEach((button) => {
    button.addEventListener("click", () => sortRows(button));
  });
  window.addEventListener("popstate", () => {
    restoreFilters();
    filterRows();
  });

  restoreFilters();
  filterRows();
})();
