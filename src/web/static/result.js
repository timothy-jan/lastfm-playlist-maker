(function () {
  const STORAGE_KEY = "playlistResult";

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderResult(data) {
    const heading = document.getElementById("result-heading");
    const note = document.getElementById("result-note");
    const subtitle = document.getElementById("result-subtitle");
    const matchedEl = document.getElementById("result-matched");
    const totalEl = document.getElementById("result-total");
    const notMatchedEl = document.getElementById("result-not-matched");
    const openLink = document.getElementById("result-open-link");
    const notFound = document.getElementById("result-not-found");

    const matched = Number(data.matched || 0);
    const total = Number(data.total || 0);
    const notFoundTracks = Array.isArray(data.not_found) ? data.not_found : [];
    const unmatchedCount =
      notFoundTracks.length > 0 ? notFoundTracks.length : Math.max(0, total - matched);

    if (subtitle) subtitle.textContent = data.playlist_name || "";
    if (matchedEl) matchedEl.textContent = matched.toLocaleString();
    if (totalEl) totalEl.textContent = total.toLocaleString();
    if (notMatchedEl) notMatchedEl.textContent = unmatchedCount.toLocaleString();

    if (heading) {
      heading.textContent = matched > 0 ? "Playlist created" : "No tracks matched";
    }
    if (note) {
      note.hidden = matched > 0;
    }
    if (openLink) {
      if (matched > 0 && data.url) {
        openLink.href = data.url;
        openLink.hidden = false;
      } else {
        openLink.hidden = true;
      }
    }

    if (!notFound) return;

    if (!unmatchedCount) {
      notFound.hidden = true;
      return;
    }

    const summary = document.getElementById("result-not-found-summary");
    const list = notFound.querySelector(".track-list");
    if (summary) {
      summary.textContent = `${unmatchedCount.toLocaleString()} track(s) couldn't be matched`;
    }
    if (list && notFoundTracks.length) {
      list.innerHTML = notFoundTracks
        .map(
          (track) =>
            `<li><span class="track-title">${escapeHtml(track.title)}</span>` +
            `<span class="track-artist">${escapeHtml(track.artist)}</span></li>`
        )
        .join("");
    }
    notFound.hidden = false;
    if (matched === 0) {
      notFound.open = true;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const root = document.getElementById("result-page");
    if (!root || root.dataset.clientResult !== "true") return;

    let data;
    try {
      data = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "null");
    } catch {
      data = null;
    }

    sessionStorage.removeItem(STORAGE_KEY);

    if (!data) {
      window.location.replace("/");
      return;
    }

    renderResult(data);
    document.body.classList.remove("is-loading");
    const screen = document.getElementById("loading-screen");
    if (screen) screen.hidden = true;
  });
})();
