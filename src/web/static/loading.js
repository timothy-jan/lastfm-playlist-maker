(function () {
  const screen = document.getElementById("loading-screen");
  const title = document.getElementById("loading-title");
  const message = document.getElementById("loading-message");
  const detail = document.getElementById("loading-detail");

  const MESSAGES = {
    preview: {
      title: "Fetching tracks",
      message: "Pulling your Last.fm stats…",
      detail: "",
    },
    create: {
      title: "Generating playlist",
      message: "Resolving Spotify links and building your playlist…",
      detail: "Large playlists are processed in batches. Please keep this tab open.",
    },
  };

  function hideLoading() {
    if (!screen) return;
    screen.hidden = true;
    document.body.classList.remove("is-loading");
  }

  function showLoading(mode) {
    if (!screen) return;
    const copy = MESSAGES[mode] || MESSAGES.create;
    title.textContent = copy.title;
    message.textContent = copy.message;
    detail.textContent = copy.detail;
    screen.hidden = false;
    document.body.classList.add("is-loading");
  }

  function updateProgress(processed, total, matched) {
    if (!detail || !total) return;
    const pct = Math.min(100, Math.round((processed / total) * 100));
    const matchedText =
      typeof matched === "number" ? ` · ${matched.toLocaleString()} matched` : "";
    detail.textContent = `Processed ${processed.toLocaleString()} of ${total.toLocaleString()} tracks (${pct}%)${matchedText}…`;
  }

  window.showLoading = showLoading;
  window.hideLoading = hideLoading;
  window.createPlaylist = createPlaylist;

  async function postJson(url, body) {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
      },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!data.success) {
      throw new Error(data.error || "Request failed.");
    }
    return data;
  }

  async function processChunkWithRetry(body, attempts = 2) {
    let lastError;
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      try {
        return await postJson("/create/chunk", body);
      } catch (error) {
        lastError = error;
        if (attempt + 1 < attempts) {
          await new Promise((resolve) => setTimeout(resolve, 1000 * (attempt + 1)));
        }
      }
    }
    throw lastError;
  }

  async function processChunks(start) {
    const {
      tracks,
      chunk_size: chunkSize,
      playlist_id: playlistId,
      playlist_url: playlistUrl,
      playlist_name: playlistName,
      total,
    } = start;
    const size = chunkSize || 120;
    let matched = 0;
    const notFound = [];

    for (let offset = 0; offset < tracks.length; offset += size) {
      updateProgress(offset, total, matched);
      const slice = tracks.slice(offset, offset + size);
      const data = await processChunkWithRetry({
        playlist_id: playlistId,
        tracks: slice,
        offset,
      });

      matched += data.matched || 0;
      if (Array.isArray(data.not_found)) {
        notFound.push(...data.not_found);
      }

      updateProgress(data.processed || offset + slice.length, total, matched);
    }

    const finish = await postJson("/create/finish", {
      playlist_id: playlistId,
      playlist_url: playlistUrl,
      playlist_name: playlistName,
      matched,
      total,
      not_found: notFound,
    });

    if (finish.result) {
      sessionStorage.setItem("playlistResult", JSON.stringify(finish.result));
    }

    window.location.href = finish.redirect;
  }

  async function createPlaylist(url, formData) {
    showLoading("create");
    try {
      const response = await fetch(url, {
        method: "POST",
        body: formData,
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      const data = await response.json();

      if (data.success && data.chunked) {
        await processChunks(data);
        return;
      }

      hideLoading();

      if (data.success && data.redirect) {
        window.location.href = data.redirect;
        return;
      }

      const errorMessage = data.error || "Could not create the playlist.";
      alert(errorMessage);
      window.location.href = "/";
    } catch (error) {
      hideLoading();
      alert(error.message || "Something went wrong while creating the playlist.");
      window.location.href = "/";
    }
  }

  document.addEventListener("DOMContentLoaded", hideLoading);
  document.addEventListener("pageshow", (event) => {
    if (event.persisted) hideLoading();
  });

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;

    const submitter = event.submitter;
    const isPreview =
      submitter?.getAttribute("formaction")?.includes("preview") ||
      submitter?.id === "preview-btn";

    if (form.id === "playlist-form") {
      if (isPreview) {
        showLoading("preview");
        return;
      }

      event.preventDefault();
      createPlaylist(form.action, new FormData(form));
      return;
    }

    if (form.id === "resume-form") {
      event.preventDefault();
      createPlaylist(form.action, new FormData(form));
    }
  });
})();
