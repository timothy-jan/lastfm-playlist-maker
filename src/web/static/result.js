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
    const subtitle = document.getElementById("result-subtitle");
    const matched = document.getElementById("result-matched");
    const total = document.getElementById("result-total");
    const notMatched = document.getElementById("result-not-matched");
    const openLink = document.getElementById("result-open-link");
    const notFound = document.getElementById("result-not-found");

    if (subtitle) subtitle.textContent = data.playlist_name || "";
    if (matched) matched.textContent = Number(data.matched || 0).toLocaleString();
    if (total) total.textContent = Number(data.total || 0).toLocaleString();

    const notFoundTracks = Array.isArray(data.not_found) ? data.not_found : [];
    if (notMatched) notMatched.textContent = notFoundTracks.length.toLocaleString();
    if (openLink && data.url) openLink.href = data.url;

    if (!notFound) return;

    if (!notFoundTracks.length) {
      notFound.hidden = true;
      return;
    }

    const summary = notFound.querySelector("summary");
    const list = notFound.querySelector(".track-list");
    if (summary) {
      summary.textContent = `${notFoundTracks.length.toLocaleString()} track(s) couldn't be matched`;
    }
    if (list) {
      list.innerHTML = notFoundTracks
        .map(
          (track) =>
            `<li><span class="track-title">${escapeHtml(track.title)}</span>` +
            `<span class="track-artist">${escapeHtml(track.artist)}</span></li>`
        )
        .join("");
    }
    notFound.hidden = false;
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
