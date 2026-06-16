(function () {
  const periodSelect = document.getElementById("period");
  const customPanel = document.getElementById("custom-range-panel");
  const dateFrom = document.getElementById("date_from");
  const dateTo = document.getElementById("date_to");
  const summary = document.getElementById("date-range-summary");
  const form = document.getElementById("playlist-form");

  if (!periodSelect || !customPanel || !dateFrom || !dateTo || !summary) {
    return;
  }

  const formatter = new Intl.DateTimeFormat(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });

  function parseInput(value) {
    if (!value) return null;
    const [year, month, day] = value.split("-").map(Number);
    if (!year || !month || !day) return null;
    return new Date(year, month - 1, day);
  }

  function toInputValue(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  function todayLocal() {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), now.getDate());
  }

  function updateSummary() {
    const start = parseInput(dateFrom.value);
    const end = parseInput(dateTo.value);

    if (!start || !end) {
      summary.textContent = "Choose both dates and we'll show you what that means.";
      summary.classList.remove("date-range-summary-error");
      return;
    }

    if (start > end) {
      summary.textContent = "Hmm — the start date comes after the end date. Swap them around?";
      summary.classList.add("date-range-summary-error");
      return;
    }

    if (end > todayLocal()) {
      summary.textContent = "We can't look into the future — pick an end date that's today or earlier.";
      summary.classList.add("date-range-summary-error");
      return;
    }

    summary.classList.remove("date-range-summary-error");

    const sameDay =
      start.getFullYear() === end.getFullYear() &&
      start.getMonth() === end.getMonth() &&
      start.getDate() === end.getDate();

    if (sameDay) {
      summary.textContent = `So that's everything you played on ${formatter.format(start)}.`;
      return;
    }

    summary.textContent = `So that's everything you played from ${formatter.format(start)} through ${formatter.format(end)}.`;
  }

  function applyPreset(days) {
    const end = todayLocal();
    const start = new Date(end);
    start.setDate(start.getDate() - (days - 1));
    dateFrom.value = toInputValue(start);
    dateTo.value = toInputValue(end);
    updateSummary();
  }

  function toggleCustomPanel() {
    const show = periodSelect.value === "custom";
    customPanel.hidden = !show;
    if (show) {
      updateSummary();
    }
  }

  periodSelect.addEventListener("change", toggleCustomPanel);

  dateFrom.addEventListener("change", () => {
    if (dateFrom.value && dateTo.value && dateFrom.value > dateTo.value) {
      dateTo.value = dateFrom.value;
    }
    updateSummary();
  });

  dateTo.addEventListener("change", updateSummary);

  customPanel.querySelectorAll("[data-preset]").forEach((button) => {
    button.addEventListener("click", () => {
      const preset = button.dataset.preset;
      if (preset === "year") {
        const end = todayLocal();
        const start = new Date(end.getFullYear(), 0, 1);
        dateFrom.value = toInputValue(start);
        dateTo.value = toInputValue(end);
        updateSummary();
        return;
      }
      applyPreset(Number(preset));
    });
  });

  if (form) {
    form.addEventListener("submit", (event) => {
      if (periodSelect.value !== "custom") {
        return;
      }
      if (!dateFrom.value || !dateTo.value) {
        event.preventDefault();
        summary.textContent = "Pick both dates before we go digging through your scrobbles.";
        summary.classList.add("date-range-summary-error");
        customPanel.hidden = false;
        dateFrom.focus();
        return;
      }
      const start = parseInput(dateFrom.value);
      const end = parseInput(dateTo.value);
      if (!start || !end || start > end || end > todayLocal()) {
        event.preventDefault();
        updateSummary();
        customPanel.hidden = false;
      }
    });
  }

  toggleCustomPanel();
  updateSummary();
})();
