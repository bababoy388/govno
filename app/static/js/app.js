document.addEventListener("DOMContentLoaded", () => {
  const toast = document.getElementById("toast");
  let toastTimer;
  window.showToast = (message) => {
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("show"), 2800);
  };
  document.querySelectorAll("[data-modal-open]").forEach(btn => btn.addEventListener("click", () => {
    const modal = document.getElementById(btn.dataset.modalOpen);
    if (modal) { modal.classList.add("open"); modal.setAttribute("aria-hidden", "false"); setTimeout(() => modal.querySelector("input")?.focus(), 100); }
  }));
  document.querySelectorAll("[data-modal-close]").forEach(btn => btn.addEventListener("click", () => closeModal(btn.closest(".modal-backdrop"))));
  document.querySelectorAll(".modal-backdrop").forEach(backdrop => backdrop.addEventListener("click", e => { if (e.target === backdrop) closeModal(backdrop); }));
  document.addEventListener("keydown", e => { if (e.key === "Escape") document.querySelectorAll(".modal-backdrop.open").forEach(closeModal); });
  function closeModal(modal) { if (modal) { modal.classList.remove("open"); modal.setAttribute("aria-hidden", "true"); } }
  const search = document.getElementById("doc-search");
  if (search) search.addEventListener("input", () => {
    const q = search.value.toLocaleLowerCase("ru");
    let shown = 0;
    document.querySelectorAll(".document-card").forEach(card => { const visible = card.dataset.title.includes(q); card.hidden = !visible; if (visible) shown++; });
    const empty = document.getElementById("no-search-results");
    if (empty) empty.hidden = shown > 0;
  });
});
