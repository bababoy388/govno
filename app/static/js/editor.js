document.addEventListener("DOMContentLoaded", () => {
  const docId = Number(document.querySelector('meta[name="editor-doc-id"]')?.content);
  const content = document.getElementById("document-content");
  const title = document.getElementById("doc-title");
  const status = document.getElementById("save-status");
  const connection = document.getElementById("connection-label");
  const wordCount = document.getElementById("word-count");
  const sidebarTitle = document.getElementById("sidebar-doc-title");
  if (!docId || !content || !title) return;
  let saveTimer, socket, lastLocal = "", remoteUpdate = false, reconnectTimer;
  const api = `/api/documents/${docId}`;
  function countWords() { const n = content.value.trim() ? content.value.trim().split(/\s+/u).length : 0; wordCount.textContent = n; }
  function setStatus(text, state="saved") { status.innerHTML = `<i></i> ${text}`; status.className = `save-status ${state}`; }
  function connectSocket() {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    socket = new WebSocket(`${protocol}//${location.host}/ws/documents/${docId}`);
    socket.onopen = () => { connection.textContent = "Синхронизация активна"; connection.classList.add("connected"); };
    socket.onclose = () => { connection.textContent = "Переподключение…"; connection.classList.remove("connected"); clearTimeout(reconnectTimer); reconnectTimer = setTimeout(connectSocket, 1800); };
    socket.onerror = () => socket.close();
    socket.onmessage = event => {
      const msg = JSON.parse(event.data);
      if (msg.type !== "content") return;
      remoteUpdate = true;
      const start = content.selectionStart, end = content.selectionEnd;
      if (msg.content !== content.value) { content.value = msg.content; countWords(); }
      if (msg.title && msg.title !== title.value) { title.value = msg.title; sidebarTitle.textContent = msg.title; document.title = `${msg.title} — CollabSpace`; }
      try { content.setSelectionRange(Math.min(start, content.value.length), Math.min(end, content.value.length)); } catch (_) {}
      setStatus(`Обновлено: ${msg.by || "участник"}`, "saved");
      remoteUpdate = false;
    };
  }
  connectSocket();
  function scheduleSave() {
    countWords();
    setStatus("Сохранение…", "saving");
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 500);
  }
  async function save() {
    if (remoteUpdate) return;
    const current = content.value;
    const currentTitle = title.value.trim() || "Новый документ";
    try {
      const res = await fetch(`${api}/save`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({content:current,title:currentTitle})});
      if (!res.ok) throw new Error("save failed");
      lastLocal = current;
      sidebarTitle.textContent = currentTitle;
      document.title = `${currentTitle} — CollabSpace`;
      setStatus("Сохранено", "saved");
    } catch (e) { setStatus("Нет соединения", "error"); }
  }
  content.addEventListener("input", scheduleSave);
  title.addEventListener("input", () => { sidebarTitle.textContent = title.value; scheduleSave(); });
  countWords();
  const shareModal = document.getElementById("share-modal");
  document.getElementById("share-open")?.addEventListener("click", () => { shareModal?.classList.add("open"); shareModal?.setAttribute("aria-hidden","false"); document.getElementById("share-url-text").textContent = location.href; });
  document.getElementById("copy-link")?.addEventListener("click", copyLink);
  document.getElementById("copy-link-modal")?.addEventListener("click", copyLink);
  async function copyLink() { try { await navigator.clipboard.writeText(location.href); window.showToast?.("Ссылка скопирована"); } catch (_) { window.showToast?.("Скопируйте адрес из строки браузера"); } }
  const params = new URLSearchParams(location.search);
  if (params.get("share") === "ok") window.showToast?.("Участник приглашён");
  if (params.get("share") === "notfound") window.showToast?.("Пользователь с таким именем не найден");
  window.addEventListener("beforeunload", () => { if (socket) socket.close(); });
});
