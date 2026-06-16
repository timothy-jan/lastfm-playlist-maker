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
      message: "Resolving Spotify links from Last.fm and building your playlist…",
      detail: "Large playlists can take a few minutes. Please keep this tab open.",
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

  window.showLoading = showLoading;
  window.hideLoading = hideLoading;
  window.createPlaylist = createPlaylist;

  async function createPlaylist(url, formData) {
    showLoading("create");
    try {
      const response = await fetch(url, {
        method: "POST",
        body: formData,
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      const data = await response.json();
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
      alert("Something went wrong while creating the playlist.");
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
