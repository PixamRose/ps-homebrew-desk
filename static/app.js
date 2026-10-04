const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

const state = {
  host: localStorage.getItem("pshd-host") || "",
  file: null,
  transferFiles: [],
  transferPaths: [],
  transferJob: null,
  transferTimer: null,
  linkTimer: null,
  linkJobId: null,
  finderPath: "/data/homebrew",
  finderParent: "/data",
  finderWritable: true,
  finderSelection: [],
  finderAnchorIdx: -1,
  finderHistory: ["/data/homebrew"],
  finderHistIdx: 0,
  finderClipboard: null,
  finderItems: [],
  finderSearchMode: false,
  finderSearchTimer: null,
  finderDragActive: false,
  finderMarquee: null,
  finderBusy: false,
  finderProgressTimer: null,
  finderProgressFake: 0,
  finderProgressTotal: 0,
  finderProgressDone: 0,
  finderProgressStarted: 0,
  finderProgressUnit: "",
  consoleDetected: false,
  relapse: null,
  henFile: null,
  henFileB64: null,
  henLocalName: "",
  catalogItems: [],
  games: [],
  gamesSelected: null,
  elfs: [],
  elfsSelected: null,
  elfsFilter: "all",
  autoHenSent: false,
  autoHenBusy: false,
  lastElfldrOk: false,
  autoHenTimer: null,
};

$("#host").value = state.host;

// Bootstrap LAN token from ?token=… (PWA / Safari)
(() => {
  try {
    const q = new URLSearchParams(location.search);
    const t = (q.get("token") || "").trim();
    if (t) {
      localStorage.setItem("pshd-token", t);
      q.delete("token");
      const clean = `${location.pathname}${q.toString() ? `?${q}` : ""}${location.hash || ""}`;
      history.replaceState({}, "", clean);
    }
  } catch (_) {
    /* ignore */
  }
})();

function currentTheme() {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

function setThemeIcon(el, name) {
  if (!el) return;
  const use = el.querySelector("use");
  if (use) use.setAttribute("href", `#i-${name}`);
}

function syncThemeLabels() {
  const dark = currentTheme() === "dark";
  const label = $("#theme-label");
  if (label) label.textContent = dark ? "Mode clair" : "Mode sombre";
  const icon = dark ? "sun" : "moon";
  setThemeIcon($("#theme-ic-side"), icon);
  setThemeIcon($("#theme-ic-bar"), icon);
}

function setTheme(theme) {
  const next = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("pshd-theme", next);
  syncThemeLabels();
}

function toggleTheme() {
  setTheme(currentTheme() === "dark" ? "light" : "dark");
}

syncThemeLabels();
$("#theme-toggle")?.addEventListener("click", toggleTheme);
$("#theme-toggle-bar")?.addEventListener("click", toggleTheme);

function host() {
  return ($("#host").value || "").trim() || "";
}

function toast(message) {
  const el = $("#toast");
  el.hidden = false;
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => {
    el.classList.remove("show");
  }, 3200);
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = localStorage.getItem("pshd-token");
  if (token && !headers.has("X-PSHD-Token")) headers.set("X-PSHD-Token", token);
  const res = await fetch(path, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) {
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  return data;
}

function syncTokenField() {
  const input = $("#desk-token-input");
  const status = $("#desk-token-status");
  if (!input) return;
  const saved = localStorage.getItem("pshd-token") || "";
  if (document.activeElement !== input) input.value = saved;
  if (status) {
    status.textContent = saved
      ? "Token enregistré dans ce navigateur (header X-PSHD-Token)."
      : "Aucun token local — nécessaire seulement si DESK_TOKEN est défini sur le hub.";
  }
}

async function refreshDeskInfo() {
  try {
    const data = await api(`/api/desk/info?host=${encodeURIComponent(host())}`);
    const url = data.lan_url || "—";
    if ($("#desk-lan-url")) $("#desk-lan-url").textContent = url;
    const author = data.author || "Pixam";
    if ($("#desk-version-label")) {
      $("#desk-version-label").textContent = `v${data.version || "?"} · ${data.platform || "?"} · by ${author}`;
    }
    if ($("#side-author")) {
      $("#side-author").textContent = `by ${author}`;
    }
    if ($("#side-platform-label")) {
      const plat = data.platform === "mac" ? "Mac" : data.platform === "windows" ? "Windows" : data.platform || "Companion";
      $("#side-platform-label").textContent = data.lan_enabled ? `${plat} · LAN` : plat;
    }
    const bullets = $("#desk-network-bullets");
    if (bullets) {
      const upd = data.update;
      const ex = data.extract || {};
      const fq = ex.ftp_queue || {};
      bullets.innerHTML = [
        `<li>LAN ${data.lan_enabled ? "ouvert" : "local only — lance start-lan.* pour le Wi‑Fi"}</li>`,
        `<li>Bind <code>${escapeHtml(String(data.bind_host))}:${data.port}</code></li>`,
        data.token_required
          ? "<li>Token LAN requis — renseigne-le ci-dessous</li>"
          : "<li>Réseau privé de confiance (pas de token côté hub)</li>",
        ex.has_unar
          ? "<li>Extract : <code>unar</code> OK</li>"
          : `<li>Extract : ${ex.hint ? escapeHtml(ex.hint) : "pas d’unar — brew install unar"}</li>`,
        fq.slots
          ? `<li>File FTP : ${fq.active || 0}/${fq.slots} actifs · ${fq.waiting || 0} en attente</li>`
          : "",
        upd?.version
          ? `<li>Update publiée <strong>v${escapeHtml(String(upd.version))}</strong> · ${formatBytes(upd.bytes || 0)}</li>`
          : "<li>Aucune update publiée pour l’instant</li>",
      ]
        .filter(Boolean)
        .join("");
    }
    const exHint = $("#extract-tools-hint");
    if (exHint) {
      const ex = data.extract || {};
      const names = (ex.tools || []).map((t) => t.name).filter(Boolean);
      exHint.textContent = names.length
        ? `Outils extract : ${names.join(", ")}${ex.hint ? " — " + ex.hint : ""}`
        : ex.hint || "Aucun extracteur CLI détecté — brew install unar";
    }
    syncTokenField();
    const link = $("#download-update-link");
    const preview = $("#update-manifest-preview");
    if (data.update?.version) {
      if (link) {
        link.hidden = false;
        link.href = data.update.url || "/updates/latest.zip";
      }
      if (preview) {
        preview.hidden = false;
        preview.textContent = JSON.stringify(data.update, null, 2);
      }
    } else if (link) {
      link.hidden = true;
    }
    if ($("#iphone-hint")) $("#iphone-hint").textContent = data.iphone_hint || "";
  } catch (err) {
    if ($("#desk-network-bullets")) {
      $("#desk-network-bullets").innerHTML = `<li>${escapeHtml(err.message)}</li>`;
    }
  }
}

function setPills(ports = {}) {
  $$(".pill[data-port]").forEach((el) => {
    const key = el.dataset.port;
    el.classList.remove("on", "off");
    if (!(key in ports)) return;
    el.classList.add(ports[key] ? "on" : "off");
  });
}

function setChip(mode, text) {
  const chip = $("#conn-chip");
  chip.classList.remove("idle", "ok", "bad");
  chip.classList.add(mode);
  chip.textContent = text;
}

function renderList(items) {
  const ul = $("#homebrew-list");
  if (!items.length) {
    ul.innerHTML = `<li><span>Dossier vide ou inaccessible</span></li>`;
    return;
  }
  ul.innerHTML = items
    .map(
      (it) => `<li>
        <span>${escapeHtml(it.name)}</span>
        <span class="meta">${it.type}${it.type === "file" ? ` · ${formatBytes(it.size)}` : ""}</span>
      </li>`
    )
    .join("");
}

function renderDoctor(doc) {
  setPills(doc.ports || {});
  state.consoleDetected = !!doc.ftp_ok;
  const note = $("#status-note");
  if (doc.ftp_ok) {
    setChip("ok", `Connecté · ${doc.host}`);
    note.textContent = `FTP OK · ${doc.homebrew?.length || 0} élément(s) dans /data/homebrew`;
  } else {
    setChip("bad", "Connexion échouée");
    note.textContent = `Impossible de joindre FTP sur ${doc.host}`;
  }

  const warnings = $("#warnings");
    warnings.innerHTML = (doc.warnings || [])
    .map((w) => `<li>${escapeHtml(w)}</li>`)
    .join("") || `<li style="color:var(--chip-ok-ink)">Aucun warning critique</li>`;

  const hints = $("#hints");
  hints.innerHTML = (doc.hen_hints || [])
    .map((h) => `<li>${escapeHtml(h)}</li>`)
    .join("");

  const auto = $("#autoload-preview");
  if (doc.autoload) {
    auto.hidden = false;
    auto.textContent = doc.autoload;
  } else {
    auto.hidden = true;
    auto.textContent = "";
  }

  renderList(doc.homebrew || []);

  if (doc.notify) {
    if (doc.notify.console_toast_likely) {
      toast("Notification envoyée sur la console");
      note.textContent += " · notif console OK";
    } else if (doc.notify.ftp_beacon) {
      toast("Connexion établie — ping écrit sur la console");
      note.textContent += " · ping console écrit (PSHD_CONNECTED.txt)";
    } else {
      toast("Connecté, mais ping console impossible");
    }
  }

  refreshRelapse().catch(() => {});
}

function setRelapsePill(el, on, label) {
  if (!el) return;
  el.classList.remove("on", "off");
  el.classList.add(on ? "on" : "off");
  el.textContent = label;
}

function renderRelapse(rel) {
  state.relapse = rel || null;
  const ftpOk = !!(rel?.console?.ftp_ok);
  const elfOk = !!(rel?.console?.elfldr_ok);
  const consoleOk = !!(rel?.console?.detected ?? state.consoleDetected) || ftpOk || elfOk;
  const ready = !!rel?.ready;
  const running = !!rel?.running;
  const url = rel?.url || "—";

  setRelapsePill(
    $("#relapse-console-pill"),
    consoleOk,
    consoleOk ? `Console · ${rel?.console?.host || host()}` : "Console absente"
  );
  setRelapsePill($("#relapse-elfldr-pill"), elfOk, elfOk ? "ELF 9021 OK" : "ELF 9021 off");
  setRelapsePill($("#relapse-ftp-pill"), ftpOk, ftpOk ? "FTP 1337 OK" : "FTP 1337 off");
  setRelapsePill($("#relapse-ready-pill"), ready, ready ? "Fichiers OK" : "Fichiers manquants");
  setRelapsePill($("#relapse-server-pill"), running, running ? `Serveur :${rel.port}` : "Serveur arrêté");

  $("#relapse-url").textContent = url;
  if (rel?.port) $("#relapse-port").value = String(rel.port);

  const startBtn = $("#relapse-start-btn");
  const setupBtn = $("#relapse-setup-btn");
  const stopBtn = $("#relapse-stop-btn");
  const sendBtn = $("#hen-send-btn");
  if (startBtn) startBtn.disabled = running;
  if (setupBtn) setupBtn.disabled = false;
  if (stopBtn) stopBtn.disabled = !running;
  if (sendBtn) sendBtn.disabled = !(elfOk && (state.henFileB64 || state.henLocalName));

  const note = $("#relapse-note");
  if (!ready) {
    note.textContent = "Télécharge Relapse, puis lance le serveur.";
  } else if (elfOk && !ftpOk) {
    note.textContent = "elfldr up — envoie etaHEN.elf ci-dessous pour avoir le FTP.";
  } else if (running) {
    note.textContent = `En écoute — Guide utilisateur PS5 → ${url}`;
  } else if (ftpOk) {
    note.textContent = `HEN/FTP déjà up · IP Mac ${rel?.pc_ip || "?"}.`;
  } else {
    note.textContent = `Prêt · IP Mac ${rel?.pc_ip || "?"} · lance le serveur puis ouvre l’URL sur la PS5.`;
  }

  renderHenPayloads(rel?.payloads || []);
  syncHenAutoUi(rel?.payloads || []);
  maybeAutoSendHen(rel).catch(() => {});

  const out = $("#relapse-status");
  if (out && rel) {
    out.hidden = false;
    out.textContent = JSON.stringify(
      {
        pc_ip: rel.pc_ip,
        url: rel.url,
        port: rel.port,
        running: rel.running,
        ready: rel.ready,
        directory: rel.directory,
        console: rel.console,
        error: rel.error || null,
      },
      null,
      2
    );
  }
}

function henAutoEnabled() {
  return localStorage.getItem("pshd-auto-hen") === "1";
}

function syncHenAutoUi(items) {
  const box = $("#hen-auto-send");
  const sel = $("#hen-auto-file");
  const note = $("#hen-auto-note");
  if (box) box.checked = henAutoEnabled();
  if (sel) {
    const preferred = localStorage.getItem("pshd-auto-hen-file") || state.henLocalName || "";
    const names = (items || []).map((it) => it.name);
    const opts = ['<option value="">— choisir —</option>'].concat(
      names.map((n) => `<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`)
    );
    const prev = sel.value;
    sel.innerHTML = opts.join("");
    const pick = preferred || prev || names.find((n) => /etahen/i.test(n)) || names[0] || "";
    if (pick) sel.value = pick;
  }
  if (note) {
    if (!henAutoEnabled()) {
      note.textContent = "Off — envoi manuel uniquement.";
    } else if (!(sel && sel.value) && !state.henFileB64) {
      note.textContent = "Auto ON — choisis un ELF dans payloads/ (ou un fichier).";
    } else {
      note.textContent = `Auto ON — enverra ${sel?.value || state.henFile?.name || "ELF"} dès que :9021 apparaît.`;
    }
  }
  ensureAutoHenPolling();
}

function ensureAutoHenPolling() {
  if (henAutoEnabled()) {
    if (!state.autoHenTimer) {
      state.autoHenTimer = setInterval(() => {
        refreshRelapse().catch(() => {});
      }, 4000);
    }
  } else if (state.autoHenTimer) {
    clearInterval(state.autoHenTimer);
    state.autoHenTimer = null;
  }
}

async function maybeAutoSendHen(rel) {
  const elfOk = !!(rel?.console?.elfldr_ok);
  const ftpOk = !!(rel?.console?.ftp_ok);
  if (!elfOk) {
    state.autoHenSent = false;
    state.lastElfldrOk = false;
    return;
  }
  state.lastElfldrOk = true;
  if (!henAutoEnabled()) return;
  if (ftpOk) return;
  if (state.autoHenBusy || state.autoHenSent) return;
  const filename = ($("#hen-auto-file")?.value || localStorage.getItem("pshd-auto-hen-file") || "").trim();
  if (!filename && !state.henFileB64) return;
  state.autoHenBusy = true;
  state.autoHenSent = true;
  try {
    toast("Auto-HEN : envoi vers elfldr…");
    if (filename) await sendHenElf({ filename });
    else await sendHenElf({ data_base64: state.henFileB64, fileLabel: state.henFile?.name || "payload.elf" });
  } catch (_) {
    state.autoHenSent = false;
  } finally {
    state.autoHenBusy = false;
  }
}

function renderHenPayloads(items) {
  const ul = $("#hen-payload-list");
  if (!ul) return;
  if (!items.length) {
    ul.innerHTML = `<li><span>Aucun .elf dans payloads/</span><span class="meta">ajoute etaHEN.elf</span></li>`;
    return;
  }
  ul.innerHTML = items
    .map(
      (it) => `<li>
        <span>${escapeHtml(it.name)}</span>
        <span class="meta">${formatBytes(it.bytes)} ·
          <button type="button" class="btn ghost hen-payload-send" data-name="${escapeHtml(it.name)}">Envoyer</button>
        </span>
      </li>`
    )
    .join("");
  ul.querySelectorAll(".hen-payload-send").forEach((btn) => {
    btn.addEventListener("click", () => {
      localStorage.setItem("pshd-auto-hen-file", btn.dataset.name || "");
      syncHenAutoUi(items);
      sendHenElf({ filename: btn.dataset.name });
    });
  });
}

async function sendHenElf({ filename = "", path = "", data_base64 = "", fileLabel = "" } = {}) {
  const out = $("#hen-send-result");
  if (!out) return;
  out.hidden = false;
  out.textContent = "Envoi vers elfldr :9021…";
  try {
    const body = { host: host(), port: 9021 };
    if (path) body.path = path;
    else if (filename) body.filename = filename;
    else if (data_base64) {
      body.data_base64 = data_base64;
      body.filename = fileLabel || state.henFile?.name || "payload.elf";
    } else {
      throw new Error("Choisis un ELF d’abord");
    }
    const data = await api("/api/elfldr/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    out.textContent = JSON.stringify(data.send, null, 2);
    toast(data.send.ftp_ok ? "HEN up — FTP ouvert" : "ELF envoyé — attends le FTP");
    await refreshRelapse();
  } catch (err) {
    out.textContent = `Erreur: ${err.message}`;
    toast(err.message);
  }
}

async function refreshRelapse() {
  const data = await api(`/api/relapse/status?host=${encodeURIComponent(host())}`);
  renderRelapse(data.relapse);
  return data.relapse;
}

async function setupRelapse() {
  const btn = $("#relapse-setup-btn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Téléchargement…";
  }
  try {
    const data = await api("/api/relapse/setup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ host: host() }),
    });
    renderRelapse({ ...data.relapse, console: state.relapse?.console });
    toast("Relapse téléchargé");
    await refreshRelapse();
  } catch (err) {
    toast(err.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Télécharger Relapse";
    }
  }
}

async function startRelapse() {
  const btn = $("#relapse-start-btn");
  btn.disabled = true;
  btn.textContent = "Démarrage…";
  try {
    const port = Number($("#relapse-port").value) || 8000;
    const data = await api("/api/relapse/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ host: host(), port, require_console: false }),
    });
    renderRelapse(data.relapse);
    toast(`Relapse actif · ${data.relapse.url}`);
  } catch (err) {
    toast(err.message);
    await refreshRelapse().catch(() => {});
  } finally {
    btn.textContent = "Lancer le serveur";
    await refreshRelapse().catch(() => {});
  }
}

async function stopRelapse() {
  try {
    const data = await api("/api/relapse/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    renderRelapse(data.relapse);
    toast("Serveur Relapse arrêté");
  } catch (err) {
    toast(err.message);
  }
}

async function copyRelapseUrl() {
  const url = $("#relapse-url")?.textContent?.trim();
  if (!url || url === "—") {
    toast("Aucune URL disponible");
    return;
  }
  try {
    await navigator.clipboard.writeText(url);
    toast("URL copiée");
  } catch {
    toast(url);
  }
}

state.catalogItems = [];

function renderCatalog(catalog) {
  state.catalogItems = (catalog.items || []).filter((i) => i.enabled !== false && i.url);
  paintCatalog();
}

function paintCatalog() {
  const root = $("#catalog-list");
  const q = ($("#catalog-search")?.value || "").trim().toLowerCase();
  let items = state.catalogItems || [];
  if (q) {
    items = items.filter((item) => {
      const hay = [item.name, item.summary, item.filename, ...(item.tags || []), item.source || ""]
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }
  const count = $("#catalog-count");
  if (count) {
    count.textContent = q
      ? `${items.length} résultat(s) / ${state.catalogItems.length}`
      : `${state.catalogItems.length} payloads de confiance`;
  }
  if (!items.length) {
    root.innerHTML = `<div class="catalog-item">
      <h3>Aucun résultat</h3>
      <p class="summary">${state.catalogItems.length ? "Refine ta recherche." : "Catalogue vide."}</p>
    </div>`;
    return;
  }
  root.innerHTML = items
    .map(
      (item) => `<div class="catalog-item" data-id="${escapeHtml(item.id)}">
        <div class="row-between wrap">
          <h3>${escapeHtml(item.name)}</h3>
          <div class="tags">${(item.tags || []).map((t) => `<span>${escapeHtml(t)}</span>`).join("")}</div>
        </div>
        <p class="summary">${escapeHtml(item.summary || "")}</p>
        <div class="row-between wrap">
          <span class="meta">FW ${escapeHtml(item.firmware || "?")} · ${escapeHtml(item.filename || "")}${
            item.bytes ? ` · ${formatBytes(item.bytes)}` : ""
          }${
            item.source
              ? ` · <a href="${escapeHtml(item.source)}" target="_blank" rel="noreferrer">source</a>`
              : ""
          }</span>
          <button class="btn primary install-btn" data-id="${escapeHtml(item.id)}">Installer</button>
        </div>
      </div>`
    )
    .join("");

  root.querySelectorAll(".install-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const item = (state.catalogItems || []).find((i) => i.id === btn.dataset.id);
      if (!item) return;
      btn.disabled = true;
      btn.textContent = "Installation…";
      try {
        const out = await api("/api/install", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            host: host(),
            url: item.url,
            filename: item.filename,
            sha256: item.sha256 || "",
          }),
        });
        btn.textContent = "OK";
        toast(`Installé → ${out.remote}`);
        await refreshHomebrew();
      } catch (err) {
        btn.textContent = "Erreur";
        toast(err.message);
      } finally {
        setTimeout(() => {
          btn.disabled = false;
          btn.textContent = "Installer";
        }, 1200);
      }
    });
  });
}

async function connect() {
  state.host = host();
  localStorage.setItem("pshd-host", state.host);
  setChip("idle", "Connexion…");
  $("#status-note").textContent = `Scan de ${state.host}…`;
  $("#connect-btn").disabled = true;
  try {
    const data = await api(`/api/doctor?host=${encodeURIComponent(state.host)}&ping=1`);
    renderDoctor(data.doctor);
  } finally {
    $("#connect-btn").disabled = false;
  }
}

async function refreshHomebrew() {
  const data = await api(`/api/homebrew?host=${encodeURIComponent(host())}`);
  renderList(data.items || []);
}

async function refreshCatalog() {
  const data = await api("/api/catalog");
  renderCatalog(data.catalog || { items: [] });
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || "");
      const idx = result.indexOf(",");
      resolve(idx >= 0 ? result.slice(idx + 1) : result);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

async function uploadSelected() {
  if (!state.file) {
    toast("Choisis un fichier d’abord");
    return;
  }
  const out = $("#upload-result");
  out.hidden = false;
  out.textContent = `Upload de ${state.file.name}…`;
  const data_base64 = await fileToBase64(state.file);
  try {
    const res = await api("/api/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        host: host(),
        filename: state.file.name,
        data_base64,
      }),
    });
    out.textContent = `OK → ${res.remote}\n${formatBytes(res.bytes)}\nsha256 ${res.sha256}`;
    toast("Fichier envoyé sur la console");
    await refreshHomebrew();
  } catch (err) {
    out.textContent = `Erreur: ${err.message}`;
    toast(err.message);
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatBytes(n) {
  const num = Number(n) || 0;
  if (num < 1024) return `${num} B`;
  if (num < 1024 ** 2) return `${(num / 1024).toFixed(1)} KiB`;
  if (num < 1024 ** 3) return `${(num / 1024 ** 2).toFixed(1)} MiB`;
  return `${(num / 1024 ** 3).toFixed(2)} GiB`;
}

function formatEta(seconds) {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "";
  const s = Math.max(0, Math.ceil(seconds));
  if (s < 60) return `~${s}s`;
  const m = Math.floor(s / 60);
  const rs = s % 60;
  if (m < 60) return rs ? `~${m}m ${rs}s` : `~${m}m`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return rm ? `~${h}h ${rm}m` : `~${h}h`;
}

/** Estimate remaining seconds from byte progress. */
function etaFromProgress(done, total, startedAt, mbps = 0) {
  done = Number(done) || 0;
  total = Number(total) || 0;
  if (total <= 0 || done <= 0) return null;
  if (done >= total) return 0;
  let bytesPerSec = 0;
  if (mbps > 0) bytesPerSec = (Number(mbps) * 1_000_000) / 8;
  else if (startedAt) {
    const elapsed = Date.now() / 1000 - Number(startedAt);
    if (elapsed > 0.4) bytesPerSec = done / elapsed;
  }
  if (bytesPerSec <= 0) return null;
  return (total - done) / bytesPerSec;
}

function jobEtaSeconds(job) {
  if (!job) return null;
  if (job.eta_seconds != null && Number.isFinite(Number(job.eta_seconds))) {
    return Number(job.eta_seconds);
  }
  const phase = jobPhase(job);
  let done = 0;
  let total = 0;
  if (phase === "download") {
    done = job.download_bytes;
    total = job.download_total;
  } else if (phase === "extract") {
    done = job.extract_bytes;
    total = job.extract_total;
  } else {
    done = job.upload_bytes != null ? job.upload_bytes : job.sent_bytes;
    total = job.upload_total != null ? job.upload_total : job.total_bytes;
  }
  return etaFromProgress(done, total, job.started_at, job.mbps);
}

function formatPctEta(pct, etaSec) {
  const p = `${Math.round(Number(pct) || 0)}%`;
  const e = formatEta(etaSec);
  return e ? `${p} · ${e}` : p;
}

async function refreshGames() {
  const grid = $("#games-grid");
  const count = $("#games-count");
  if (grid) grid.innerHTML = `<div class="note">Scan des jeux sur la console…</div>`;
  if (count) count.textContent = "Scan…";
  try {
    const data = await api(`/api/games?host=${encodeURIComponent(host())}`);
    state.games = data.games || [];
    renderGamesGrid();
  } catch (err) {
    if (grid) grid.innerHTML = `<div class="note">${escapeHtml(err.message)}</div>`;
    if (count) count.textContent = "Erreur";
    toast(err.message);
  }
}

function filteredGames() {
  const q = ($("#games-search")?.value || "").trim().toLowerCase();
  if (!q) return state.games;
  return state.games.filter((g) => {
    const blob = `${g.title_id || ""} ${g.title_name || ""} ${g.path || ""} ${g.source || ""}`.toLowerCase();
    return blob.includes(q);
  });
}

function gameCoverUrl(game) {
  if (!game?.icon_path) return "";
  return `/api/games/icon?host=${encodeURIComponent(host())}&title_id=${encodeURIComponent(
    game.title_id || "GAME"
  )}&icon_path=${encodeURIComponent(game.icon_path)}`;
}

function renderGamesGrid() {
  const grid = $("#games-grid");
  const count = $("#games-count");
  if (!grid) return;
  const games = filteredGames();
  if (count) count.textContent = `${games.length} jeu(x)` + (state.games.length !== games.length ? ` / ${state.games.length}` : "");
  if (!games.length) {
    grid.innerHTML = `<div class="note">Aucun jeu détecté. Connecte la console (FTP) puis Actualiser.</div>`;
    return;
  }
  const selectedPath = state.gamesSelected?.path;
  grid.innerHTML = games
    .map((g) => {
      const cover = gameCoverUrl(g);
      const tidShort = escapeHtml((g.title_id || "GAME").slice(0, 8));
      const coverHtml = cover
        ? `<img class="cover" src="${cover}" alt="" loading="lazy" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'cover placeholder',textContent:'${tidShort}'}))" />`
        : `<div class="cover placeholder">${tidShort}</div>`;
      return `<button type="button" class="game-card ${selectedPath === g.path ? "selected" : ""}" data-path="${escapeHtml(
        g.path
      )}">
        ${coverHtml}
        <div class="tid">${escapeHtml(g.title_id || "—")}</div>
        <div class="gname">${escapeHtml(g.title_name || g.title_id || "Sans nom")}</div>
        <div class="gsrc">${escapeHtml(g.source || g.kind || "")}</div>
      </button>`;
    })
    .join("");
  grid.querySelectorAll(".game-card").forEach((card) => {
    card.addEventListener("click", () => {
      const game = state.games.find((x) => x.path === card.dataset.path);
      if (game) selectGame(game).catch((e) => toast(e.message));
    });
  });
}

async function selectGame(game) {
  state.gamesSelected = game;
  renderGamesGrid();
  const detail = $("#games-detail");
  if (detail) detail.hidden = false;
  $("#games-detail-title").textContent = game.title_name || game.title_id || "Jeu";
  $("#games-detail-tid").textContent = game.title_id || "—";
  $("#games-detail-source").textContent = `${game.source || "—"} · ${game.kind || ""}`;
  $("#games-detail-path").textContent = game.path || "";
  const cover = $("#games-detail-cover");
  const url = gameCoverUrl(game);
  if (cover) {
    if (url) {
      cover.src = url;
      cover.hidden = false;
    } else {
      cover.removeAttribute("src");
      cover.hidden = true;
    }
  }
  const uninstall = $("#games-uninstall-btn");
  if (uninstall) uninstall.disabled = !game.can_uninstall;
  // Load rich info
  try {
    const data = await api(
      `/api/games/info?host=${encodeURIComponent(host())}&path=${encodeURIComponent(game.path)}`
    );
    const info = data.game || game;
    state.gamesSelected = { ...game, ...info };
    const bullets = $("#games-detail-bullets");
    if (bullets) {
      bullets.innerHTML = [
        `<li>TITLEID · <code>${escapeHtml(info.title_id || "—")}</code></li>`,
        info.content_id ? `<li>Content ID · <code>${escapeHtml(info.content_id)}</code></li>` : "",
        `<li>Type · ${escapeHtml(info.kind || "—")}${info.image_type ? ` (${escapeHtml(info.image_type)})` : ""}</li>`,
        `<li>Source · ${escapeHtml(info.source || "—")}</li>`,
        info.size ? `<li>Taille fichier · ${formatBytes(info.size)}</li>` : "",
        typeof info.entries === "number" ? `<li>${info.entries} entrée(s) à la racine</li>` : "",
        `<li>Désinstallable · ${info.can_uninstall ? "oui" : "non"}</li>`,
      ]
        .filter(Boolean)
        .join("");
    }
    const files = $("#games-detail-files");
    if (files) {
      const lines = [];
      if (info.sce_sys?.length) lines.push("sce_sys/", ...info.sce_sys.map((n) => `  ${n}`), "");
      if (info.files_sample?.length) lines.push("racine/", ...info.files_sample.map((n) => `  ${n}`));
      files.textContent = lines.join("\n") || "(pas de listing)";
    }
  } catch (err) {
    toast(err.message);
  }
}

async function uninstallSelectedGame() {
  const game = state.gamesSelected;
  if (!game?.path || !game.title_id) return;
  if (!game.can_uninstall) return toast("Désinstallation bloquée pour ce titre");
  const ok = confirm(
    `Désinstaller « ${game.title_name || game.title_id} » (${game.title_id}) ?\n\n` +
      `Suppression FTP de :\n${game.path}\n\nIrréversible.`
  );
  if (!ok) return;
  const typed = prompt(`Tape le TITLEID pour confirmer :`, game.title_id);
  if ((typed || "").trim().toUpperCase() !== game.title_id.toUpperCase()) {
    return toast("Confirmation annulée");
  }
  try {
    await api("/api/games/uninstall", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        host: host(),
        path: game.path,
        title_id: game.title_id,
        confirm: game.title_id,
      }),
    });
    toast(`Désinstallé · ${game.title_id}`);
    state.gamesSelected = null;
    $("#games-detail").hidden = true;
    await refreshGames();
  } catch (err) {
    toast(err.message);
  }
}

function elfHue(name) {
  let h = 0;
  const s = String(name || "elf");
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h % 360;
}

function elfAvatarStyle(name) {
  const hue = elfHue(name);
  return `background: linear-gradient(145deg, hsl(${hue} 72% 52%), hsl(${(hue + 40) % 360} 65% 38%));`;
}

function elfInitials(name) {
  const clean = String(name || "ELF").replace(/\.elf$/i, "");
  const parts = clean.split(/[-_\s]+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return clean.slice(0, 3).toUpperCase();
}

async function refreshElfs() {
  const grid = $("#elfs-grid");
  const count = $("#elfs-count");
  if (grid) grid.innerHTML = `<div class="note">Scan des .elf…</div>`;
  if (count) count.textContent = "Scan…";
  try {
    const data = await api(`/api/elfs?host=${encodeURIComponent(host())}`);
    state.elfs = data.elfs || [];
    const total = state.elfs.length;
    const updates = state.elfs.filter((e) => e.update_available).length;
    const local = state.elfs.filter((e) => e.location === "local").length;
    if ($("#elfs-stat-total")) $("#elfs-stat-total").textContent = String(total);
    if ($("#elfs-stat-updates")) $("#elfs-stat-updates").textContent = String(updates);
    if ($("#elfs-stat-local")) $("#elfs-stat-local").textContent = String(local);
    renderElfsGrid();
  } catch (err) {
    if (grid) grid.innerHTML = `<div class="note">${escapeHtml(err.message)}</div>`;
    if (count) count.textContent = "Erreur";
    toast(err.message);
  }
}

function filteredElfs() {
  let items = state.elfs || [];
  const filter = state.elfsFilter || "all";
  if (filter === "updates") items = items.filter((e) => e.update_available);
  if (filter === "console") items = items.filter((e) => e.location === "console");
  if (filter === "local") items = items.filter((e) => e.location === "local");
  const q = ($("#elfs-search")?.value || "").trim().toLowerCase();
  if (!q) return items;
  return items.filter((e) => {
    const blob = `${e.name || ""} ${e.filename || ""} ${e.version || ""} ${e.path || ""} ${e.summary || ""} ${e.github || ""} ${(e.tags || []).join(" ")}`.toLowerCase();
    return blob.includes(q);
  });
}

function renderElfsGrid() {
  const grid = $("#elfs-grid");
  const count = $("#elfs-count");
  if (!grid) return;
  const elfs = filteredElfs();
  if (count) {
    count.textContent =
      `${elfs.length} ELF` +
      (elfs.length !== state.elfs.length ? ` / ${state.elfs.length}` : "") +
      (state.elfs.some((e) => e.update_available) ? ` · ${state.elfs.filter((e) => e.update_available).length} MAJ` : "");
  }
  if (!elfs.length) {
    grid.innerHTML = `<div class="note">Aucun .elf. Connecte le FTP ou place des fichiers dans <code>payloads/</code>.</div>`;
    return;
  }
  const selectedPath = state.elfsSelected?.path;
  grid.innerHTML = elfs
    .map((e, i) => {
      const initials = escapeHtml(elfInitials(e.name || e.filename));
      const style = elfAvatarStyle(e.family || e.name || e.filename);
      const hue = elfHue(e.family || e.name || e.filename);
      return `<button type="button" class="elf-card ${selectedPath === e.path ? "selected" : ""} ${
        e.update_available ? "has-update" : ""
      }" data-path="${escapeHtml(e.path)}" style="animation-delay:${Math.min(i, 12) * 0.03}s">
        <span class="elf-glow" style="background:hsl(${hue} 80% 55%)"></span>
        ${e.update_available ? `<span class="elf-badge">MAJ</span>` : ""}
        <div class="elf-avatar" style="${style}">${initials}</div>
        <div class="ename">${escapeHtml(e.name || e.filename || "ELF")}</div>
        <div class="ever">v${escapeHtml(String(e.version || "—").replace(/^v/i, ""))}${
          e.update_available
            ? ` → v${escapeHtml(String(e.latest_version || "").replace(/^v/i, ""))}`
            : ""
        }</div>
        <div class="emeta">${escapeHtml(e.source_label || e.location || "")} · ${formatBytes(e.size || 0)}</div>
      </button>`;
    })
    .join("");
  grid.querySelectorAll(".elf-card").forEach((card) => {
    card.addEventListener("click", () => {
      const elf = state.elfs.find((x) => x.path === card.dataset.path);
      if (elf) selectElf(elf).catch((err) => toast(err.message));
    });
  });
}

async function selectElf(elf) {
  state.elfsSelected = elf;
  renderElfsGrid();
  const detail = $("#elfs-detail");
  if (detail) detail.hidden = false;
  const style = elfAvatarStyle(elf.family || elf.name || elf.filename);
  const avatar = $("#elfs-detail-avatar");
  if (avatar) {
    avatar.style.cssText = style;
    avatar.textContent = elfInitials(elf.name || elf.filename);
  }
  const orb = $("#elfs-detail-orb");
  if (orb) orb.style.background = `hsl(${elfHue(elf.family || elf.name)} 75% 55%)`;
  $("#elfs-detail-title").textContent = elf.name || elf.filename || "ELF";
  $("#elfs-detail-ver").textContent = elf.update_available
    ? `v${String(elf.version || "?").replace(/^v/i, "")} → v${String(elf.latest_version || "").replace(/^v/i, "")}`
    : `v${String(elf.version || "—").replace(/^v/i, "")}`;
  $("#elfs-detail-meta").textContent = `${elf.source_label || "—"} · ${elf.filename || ""}`;
  $("#elfs-detail-path").textContent = elf.path || "";
  const bullets = $("#elfs-detail-bullets");
  if (bullets) {
    bullets.innerHTML = [
      `<li>Fichier · <code>${escapeHtml(elf.filename || "—")}</code></li>`,
      `<li>Famille · <code>${escapeHtml(elf.family || "—")}</code></li>`,
      `<li>Version installée · <code>${escapeHtml(String(elf.version || "—"))}</code></li>`,
      elf.latest_version
        ? `<li>Dernière catalogue · <code>${escapeHtml(String(elf.latest_version))}</code></li>`
        : "",
      elf.firmware ? `<li>Firmware · ${escapeHtml(elf.firmware)}</li>` : "",
      elf.size ? `<li>Taille · ${formatBytes(elf.size)}</li>` : "",
      elf.summary ? `<li>${escapeHtml(elf.summary)}</li>` : "",
      `<li>MAJ dispo · ${elf.update_available ? "oui" : "non"}</li>`,
    ]
      .filter(Boolean)
      .join("");
  }
  const upd = $("#elfs-update-btn");
  if (upd) {
    upd.hidden = !elf.update_available;
    upd.disabled = !elf.update_available;
    upd.textContent = elf.update_available
      ? `Mettre à jour · v${String(elf.latest_version || "").replace(/^v/i, "")}`
      : "À jour";
  }
  const gh = $("#elfs-github-btn");
  if (gh) {
    if (elf.github) {
      gh.hidden = false;
      gh.href = elf.github;
    } else {
      gh.hidden = true;
      gh.removeAttribute("href");
    }
  }
  const uninstall = $("#elfs-uninstall-btn");
  if (uninstall) uninstall.disabled = !elf.can_uninstall;
  // Refresh rich info
  try {
    const data = await api(
      `/api/elfs/info?host=${encodeURIComponent(host())}&path=${encodeURIComponent(elf.path)}`
    );
    if (data.elf) {
      state.elfsSelected = { ...elf, ...data.elf };
    }
  } catch (_) {
    /* ignore */
  }
}

async function updateSelectedElf() {
  const elf = state.elfsSelected;
  if (!elf?.update_available || !elf.update_url) return toast("Pas de MAJ catalogue");
  const btn = $("#elfs-update-btn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Mise à jour…";
  }
  try {
    const out = await api("/api/elfs/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        host: host(),
        path: elf.path,
        update_url: elf.update_url,
        update_filename: elf.update_filename,
        update_sha256: elf.update_sha256,
        remove_old: true,
      }),
    });
    toast(`Mis à jour → ${out.remote || out.filename}`);
    await refreshElfs();
    const next = state.elfs.find((e) => e.filename === out.filename || e.path === out.remote);
    if (next) await selectElf(next);
  } catch (err) {
    toast(err.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Mettre à jour";
    }
  }
}

async function uninstallSelectedElf() {
  const elf = state.elfsSelected;
  if (!elf?.path || !elf.filename) return;
  if (!elf.can_uninstall) return toast("Désinstallation bloquée");
  const ok = confirm(
    `Désinstaller « ${elf.name || elf.filename} » ?\n\nSuppression de :\n${elf.path}\n\nIrréversible.`
  );
  if (!ok) return;
  const typed = prompt(`Tape le nom du fichier pour confirmer :`, elf.filename);
  if ((typed || "").trim().toLowerCase() !== elf.filename.toLowerCase()) {
    return toast("Confirmation annulée");
  }
  try {
    await api("/api/elfs/uninstall", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        host: host(),
        path: elf.path,
        filename: elf.filename,
        confirm: elf.filename,
      }),
    });
    toast(`Désinstallé · ${elf.filename}`);
    state.elfsSelected = null;
    $("#elfs-detail").hidden = true;
    await refreshElfs();
  } catch (err) {
    toast(err.message);
  }
}

async function sendSelectedElf() {
  const elf = state.elfsSelected;
  if (!elf) return;
  const body = { host: host() };
  if (elf.location === "local" || String(elf.path || "").startsWith("local:")) {
    body.filename = elf.filename;
    if (elf.local_path) body.path = elf.local_path;
  } else {
    body.remote_path = elf.path;
    body.filename = elf.filename;
  }
  try {
    toast("Envoi vers elfldr…");
    const data = await api("/api/elfldr/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    toast(`Envoyé · ${data.send?.filename || data.filename || elf.filename}`);
  } catch (err) {
    toast(err.message);
  }
}

$$(".nav-item").forEach((tab) => {
  tab.addEventListener("click", () => {
    $$(".nav-item").forEach((t) => t.classList.remove("active"));
    $$(".panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    $(`#panel-${tab.dataset.tab}`).classList.add("active");
    if (tab.dataset.tab === "files") {
      navigateFinder(state.finderPath, { history: false }).catch((e) => toast(e.message));
    }
    if (tab.dataset.tab === "games") {
      refreshGames().catch((e) => toast(e.message));
    }
    if (tab.dataset.tab === "elfs") {
      refreshElfs().catch((e) => toast(e.message));
    }
    if (tab.dataset.tab === "relapse") {
      refreshRelapse().catch((e) => toast(e.message));
    }
  });
});

$("#games-refresh-btn")?.addEventListener("click", () => refreshGames().catch((e) => toast(e.message)));
$("#games-search")?.addEventListener("input", () => renderGamesGrid());
$("#games-detail-close")?.addEventListener("click", () => {
  state.gamesSelected = null;
  $("#games-detail").hidden = true;
  renderGamesGrid();
});
$("#games-uninstall-btn")?.addEventListener("click", () => uninstallSelectedGame());
$("#games-open-folder-btn")?.addEventListener("click", () => {
  const game = state.gamesSelected;
  if (!game?.path) return;
  const path = game.kind === "image" ? game.path.replace(/\/[^/]+$/, "") || "/" : game.path;
  $$(".nav-item").forEach((t) => t.classList.toggle("active", t.dataset.tab === "files"));
  $$(".panel").forEach((p) => p.classList.remove("active"));
  $("#panel-files")?.classList.add("active");
  navigateFinder(path).catch((e) => toast(e.message));
});
$$(".games-tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".games-tab").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const tab = btn.dataset.gtab;
    $("#games-tab-info").hidden = tab !== "info";
    $("#games-tab-files").hidden = tab !== "files";
  });
});

$("#elfs-refresh-btn")?.addEventListener("click", () => refreshElfs().catch((e) => toast(e.message)));
$("#elfs-search")?.addEventListener("input", () => renderElfsGrid());
$$("#elfs-filters .elf-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    state.elfsFilter = chip.dataset.filter || "all";
    $$("#elfs-filters .elf-chip").forEach((c) => c.classList.toggle("active", c === chip));
    renderElfsGrid();
  });
});
$("#elfs-detail-close")?.addEventListener("click", () => {
  state.elfsSelected = null;
  $("#elfs-detail").hidden = true;
  renderElfsGrid();
});
$("#elfs-update-btn")?.addEventListener("click", () => updateSelectedElf());
$("#elfs-uninstall-btn")?.addEventListener("click", () => uninstallSelectedElf());
$("#elfs-send-btn")?.addEventListener("click", () => sendSelectedElf());
$("#elfs-open-folder-btn")?.addEventListener("click", () => {
  const elf = state.elfsSelected;
  if (!elf?.path) return;
  if (String(elf.path).startsWith("local:")) {
    toast(`Local · payloads/${elf.filename}`);
    return;
  }
  const path = elf.path.replace(/\/[^/]+$/, "") || "/";
  $$(".nav-item").forEach((t) => t.classList.toggle("active", t.dataset.tab === "files"));
  $$(".panel").forEach((p) => p.classList.remove("active"));
  $("#panel-files")?.classList.add("active");
  navigateFinder(path).catch((e) => toast(e.message));
});

$("#relapse-setup-btn")?.addEventListener("click", () => setupRelapse());
$("#relapse-start-btn")?.addEventListener("click", () => startRelapse());
$("#relapse-stop-btn")?.addEventListener("click", () => stopRelapse());
$("#relapse-refresh-btn")?.addEventListener("click", () =>
  refreshRelapse().catch((e) => toast(e.message))
);
$("#relapse-copy-btn")?.addEventListener("click", () => copyRelapseUrl());
$("#hen-pick-btn")?.addEventListener("click", () => $("#hen-elf-input")?.click());
$("#hen-elf-input")?.addEventListener("change", async (e) => {
  const file = e.target.files?.[0] || null;
  state.henFile = file;
  state.henLocalName = "";
  state.henFileB64 = file ? await fileToBase64(file) : null;
  const sendBtn = $("#hen-send-btn");
  if (sendBtn) sendBtn.disabled = !file;
  if (file) toast(`Prêt: ${file.name}`);
});
$("#hen-send-btn")?.addEventListener("click", () => {
  if (state.henFileB64) {
    sendHenElf({ data_base64: state.henFileB64, fileLabel: state.henFile?.name || "etaHEN.elf" });
  } else if (state.henLocalName) {
    sendHenElf({ filename: state.henLocalName });
  } else {
    toast("Choisis un ELF d’abord");
  }
});
$("#hen-refresh-payloads-btn")?.addEventListener("click", () =>
  refreshRelapse().catch((e) => toast(e.message))
);

$("#connect-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await connect();
  } catch (err) {
    setChip("bad", "Erreur");
    $("#status-note").textContent = err.message;
    toast(err.message);
  }
});

$("#refresh-homebrew").addEventListener("click", () => refreshHomebrew().catch((e) => toast(e.message)));
$("#refresh-catalog").addEventListener("click", () => refreshCatalog().catch((e) => toast(e.message)));
$("#catalog-search")?.addEventListener("input", () => paintCatalog());
$("#upload-btn").addEventListener("click", () => uploadSelected());
$("#file-input").addEventListener("change", (e) => {
  state.file = e.target.files?.[0] || null;
});

const dz = $("#dropzone");
if (dz) {
  ["dragenter", "dragover"].forEach((evt) => {
    dz.addEventListener(evt, (e) => {
      e.preventDefault();
      dz.classList.add("drag");
    });
  });
  ["dragleave", "drop"].forEach((evt) => {
    dz.addEventListener(evt, (e) => {
      e.preventDefault();
      dz.classList.remove("drag");
    });
  });
  dz.addEventListener("drop", (e) => {
    const file = e.dataTransfer?.files?.[0];
    if (!file) return;
    state.file = file;
    try {
      if ($("#file-input")) $("#file-input").files = e.dataTransfer.files;
    } catch (_) {
      /* ignore */
    }
  });
}

$$(".log-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const view = $("#log-view");
    view.textContent = "Chargement…";
    try {
      const data = await api(`/api/logs?host=${encodeURIComponent(host())}&name=${btn.dataset.log}`);
      view.textContent = `// ${data.path}\n\n${data.content || "(vide)"}`;
    } catch (err) {
      view.textContent = err.message;
    }
  });
});

function workers() {
  const n = Number($("#transfer-workers")?.value || 3);
  return Math.max(1, Math.min(6, n || 3));
}

function updateTransferSelection() {
  const el = $("#transfer-selection");
  const list = $("#xfer-file-list");
  const startBtn = $("#start-transfer-btn");
  const clearBtn = $("#xfer-clear-btn");
  const nItems = state.transferPaths.length || state.transferFiles.length;
  const bytes = state.transferFiles.reduce((s, f) => s + (f.size || 0), 0);
  if ($("#xfer-stat-items")) $("#xfer-stat-items").textContent = String(nItems);
  if ($("#xfer-stat-size")) {
    $("#xfer-stat-size").textContent = state.transferPaths.length ? "—" : bytes ? formatBytes(bytes) : "0";
  }
  if (startBtn) startBtn.disabled = !nItems;
  if (clearBtn) clearBtn.disabled = !nItems;

  if (state.transferPaths.length) {
    if (el) el.textContent = `${state.transferPaths.length} chemin(s) Mac · transfert direct`;
    if (list) {
      list.hidden = false;
      list.innerHTML = state.transferPaths
        .slice(0, 40)
        .map((p) => `<li><span class="xname">${escapeHtml(String(p).split(/[/\\]/).pop() || p)}</span><span class="xmeta">${escapeHtml(p)}</span></li>`)
        .join("");
      if (state.transferPaths.length > 40) {
        list.innerHTML += `<li class="xmore">+${state.transferPaths.length - 40} autres…</li>`;
      }
    }
    return;
  }
  if (state.transferFiles.length) {
    if (el) el.textContent = `${state.transferFiles.length} fichier(s) · ${formatBytes(bytes)} → ${xferDestRoot()}`;
    if (list) {
      list.hidden = false;
      list.innerHTML = state.transferFiles
        .slice(0, 40)
        .map((f) => {
          const rel = f.webkitRelativePath || f.name;
          return `<li><span class="xname">${escapeHtml(f.name)}</span><span class="xmeta">${escapeHtml(rel)} · ${formatBytes(f.size || 0)}</span></li>`;
        })
        .join("");
      if (state.transferFiles.length > 40) {
        list.innerHTML += `<li class="xmore">+${state.transferFiles.length - 40} autres…</li>`;
      }
    }
    return;
  }
  if (el) el.textContent = "Rien à envoyer — glisse ou choisis des fichiers.";
  if (list) {
    list.hidden = true;
    list.innerHTML = "";
  }
}

function xferDestRoot() {
  const preset = $("#xfer-dest-preset")?.value || "/data/homebrew";
  if (preset === "__custom__") {
    return ($("#xfer-dest-custom")?.value || "").trim() || "/data/homebrew";
  }
  return preset;
}

function jobPhase(job) {
  if (!job) return "idle";
  if (job.phase) return job.phase;
  const cur = String(job.current || "").toLowerCase();
  if (job.status === "cancelled" || job.status === "cancelling") return "cancelled";
  if (job.status === "error") return "error";
  if (job.status === "done" || job.status === "done_with_errors") return "done";
  if (cur.startsWith("download")) return "download";
  if (cur.startsWith("extract")) return "extract";
  if (cur.startsWith("upload") || job.kind === "transfer") return "upload";
  return "queued";
}

function phaseLabel(phase) {
  return (
    {
      queued: "En file",
      download: "Téléchargement",
      extract: "Extraction",
      upload: "Upload FTP",
      done: "Terminé",
      error: "Erreur",
      cancelled: "Annulé",
      idle: "—",
    }[phase] || phase
  );
}

function setFillPhase(el, phase, { width = null, indeterminate = false } = {}) {
  if (!el) return;
  el.classList.remove(
    "phase-download",
    "phase-extract",
    "phase-upload",
    "phase-done",
    "phase-error",
    "phase-cancelled",
    "phase-idle",
    "indeterminate",
    "cancelled"
  );
  const map = {
    download: "phase-download",
    extract: "phase-extract",
    upload: "phase-upload",
    done: "phase-done",
    error: "phase-error",
    cancelled: "phase-cancelled",
    idle: "phase-idle",
    queued: "phase-idle",
  };
  el.classList.add(map[phase] || "phase-idle");
  if (indeterminate) {
    el.classList.add("indeterminate");
  } else if (width != null) {
    el.style.width = `${Math.max(0, Math.min(100, width))}%`;
  }
}

function updateGlobalXfer(job) {
  const root = $("#global-xfer");
  if (!root) return;
  if (!job || ["done", "done_with_errors", "error", "cancelled"].includes(job.status)) {
    // Keep visible briefly on terminal states when just finished from active poll
    if (!job || !state._xferKeepGlobal) {
      root.hidden = true;
      return;
    }
  }
  root.hidden = false;
  const phase = jobPhase(job);
  const phaseEl = $("#global-xfer-phase");
  if (phaseEl) {
    phaseEl.textContent = phaseLabel(phase);
    phaseEl.dataset.phase = phase;
  }
  if ($("#global-xfer-label")) $("#global-xfer-label").textContent = job.current || job.remote_path || "—";
  const dlPct = job.kind === "url" ? Number(job.download_percent || 0) : 100;
  const upPct = Number(job.upload_percent != null ? job.upload_percent : job.percent || 0);
  setFillPhase($("#global-dl-fill"), job.kind === "url" ? "download" : "done", {
    width: job.kind === "url" ? (phase === "download" ? dlPct : Math.max(dlPct, 100)) : 100,
  });
  const stageLabel = $("#global-stage-label");
  if (stageLabel) {
    stageLabel.textContent = phase === "extract" ? "Extract" : phase === "upload" || phase === "done" ? "Upload" : "Suite";
  }
  const eta = jobEtaSeconds(job);
  if (phase === "extract") {
    const exPct = Number(job.extract_percent || 0);
    if (exPct > 0) {
      setFillPhase($("#global-stage-fill"), "extract", { width: Math.max(3, Math.min(99, exPct)) });
      if ($("#global-xfer-pct")) $("#global-xfer-pct").textContent = formatPctEta(exPct, eta);
    } else {
      setFillPhase($("#global-stage-fill"), "extract", { indeterminate: true });
      if ($("#global-xfer-pct")) $("#global-xfer-pct").textContent = "…";
    }
  } else if (phase === "upload" || phase === "done") {
    setFillPhase($("#global-stage-fill"), phase === "done" ? "done" : "upload", {
      width: phase === "done" ? 100 : upPct,
    });
    if ($("#global-xfer-pct")) {
      $("#global-xfer-pct").textContent =
        phase === "done" ? "100%" : formatPctEta(upPct, eta);
    }
  } else if (phase === "error" || phase === "cancelled") {
    setFillPhase($("#global-stage-fill"), phase, { width: Math.max(upPct, 8) });
    if ($("#global-xfer-pct")) $("#global-xfer-pct").textContent = phaseLabel(phase);
  } else {
    setFillPhase($("#global-stage-fill"), "idle", { width: 0 });
    if ($("#global-xfer-pct")) $("#global-xfer-pct").textContent = formatPctEta(dlPct, eta);
  }
}

function renderJob(job) {
  if ($("#transfer-progress-wrap")) $("#transfer-progress-wrap").hidden = false;
  const phase = jobPhase(job);
  const pct = Number(job.upload_percent != null ? job.upload_percent : job.percent || 0);
  const eta = jobEtaSeconds(job);
  setFillPhase($("#transfer-fill"), phase === "done" ? "done" : phase === "error" ? "error" : "upload", {
    width: phase === "done" ? 100 : pct,
  });
  if ($("#transfer-stage-pct")) {
    $("#transfer-stage-pct").textContent = phase === "done" ? "100%" : formatPctEta(pct, eta);
  }
  const note = $("#transfer-phase-note");
  if (note) {
    note.dataset.phase = phase;
    const etaBit = formatEta(eta);
    note.textContent = `${phaseLabel(phase)} · ${job.current || "—"}${etaBit ? ` · reste ${etaBit}` : ""}`;
  }
  $("#transfer-status").textContent =
    `status=${job.status}\n` +
    `phase=${phase}\n` +
    `files=${job.done_files}/${job.total_files}\n` +
    `bytes=${formatBytes(job.upload_bytes || job.sent_bytes)} / ${formatBytes(job.upload_total || job.total_bytes)}\n` +
    `speed=${job.mbps} Mbps\n` +
    `eta=${formatEta(eta) || "—"}\n` +
    `workers=${job.workers}\n` +
    `current=${job.current || "-"}\n` +
    (job.errors?.length ? `errors:\n- ${job.errors.join("\n- ")}` : "errors=0");
  state._xferKeepGlobal = !["done", "done_with_errors", "error", "cancelled"].includes(job.status);
  updateGlobalXfer(job);
  if (!state._xferKeepGlobal) {
    setTimeout(() => {
      state._xferKeepGlobal = false;
      updateGlobalXfer(null);
    }, 3500);
  }
}

async function pollJob(id) {
  clearInterval(state.transferTimer);
  state.transferJobId = id;
  state.transferTimer = setInterval(async () => {
    try {
      const data = await api(`/api/transfer/job?id=${encodeURIComponent(id)}`);
      state.transferJob = data.job;
      renderJob(data.job);
      if (["done", "done_with_errors", "error", "cancelled"].includes(data.job.status)) {
        clearInterval(state.transferTimer);
        state.transferJobId = null;
        if (data.job.status === "done") toast("Transfert terminé");
        else if (data.job.status === "cancelled") toast("Transfert annulé");
        else toast("Transfert terminé avec erreurs");
        refreshHomebrew().catch(() => {});
        if ($("#xfer-cancel-btn")) $("#xfer-cancel-btn").hidden = true;
      } else if ($("#xfer-cancel-btn")) {
        $("#xfer-cancel-btn").hidden = false;
      }
    } catch (err) {
      clearInterval(state.transferTimer);
      state.transferJobId = null;
      toast(err.message);
    }
  }, 400);
}

async function startLocalTransfer(paths, destRoot = "/data/homebrew") {
  const data = await api("/api/transfer/local", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      host: host(),
      paths,
      workers: workers(),
      dest_root: destRoot || "/data/homebrew",
    }),
  });
  renderJob(data.job);
  pollJob(data.job.id);
  return data.job;
}

function readAllDirectoryEntries(reader) {
  return new Promise((resolve, reject) => {
    const acc = [];
    const readBatch = () => {
      reader.readEntries(
        (batch) => {
          if (!batch.length) return resolve(acc);
          acc.push(...batch);
          readBatch();
        },
        reject
      );
    };
    readBatch();
  });
}

async function filesFromEntry(entry, prefix = "") {
  if (!entry || entry.name === ".DS_Store" || entry.name.startsWith("._")) return [];
  if (entry.isFile) {
    const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
    const rel = prefix ? `${prefix}/${file.name}` : file.name;
    try {
      Object.defineProperty(file, "webkitRelativePath", { configurable: true, value: rel });
    } catch (_) {
      /* ignore */
    }
    return [file];
  }
  if (!entry.isDirectory) return [];
  const nextPrefix = prefix ? `${prefix}/${entry.name}` : entry.name;
  const children = await readAllDirectoryEntries(entry.createReader());
  const out = [];
  for (const child of children) {
    out.push(...(await filesFromEntry(child, nextPrefix)));
  }
  return out;
}

async function collectDataTransferFiles(dt) {
  if (!dt) return [];
  const files = [];
  const items = dt.items ? [...dt.items] : [];
  if (items.length && typeof items[0].webkitGetAsEntry === "function") {
    for (const item of items) {
      if (item.kind !== "file") continue;
      const entry = item.webkitGetAsEntry();
      if (entry) files.push(...(await filesFromEntry(entry, "")));
      else {
        const f = item.getAsFile?.();
        if (f) files.push(f);
      }
    }
  } else if (dt.files?.length) {
    files.push(...dt.files);
  }
  const seen = new Set();
  return files.filter((f) => {
    const key = `${f.webkitRelativePath || f.name}|${f.size}|${f.lastModified || 0}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function rawUploadWithProgress(file, headers, onBytes) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/transfer/raw");
    Object.entries(headers).forEach(([k, v]) => xhr.setRequestHeader(k, v));
    xhr.upload.onprogress = (ev) => {
      if (!ev.lengthComputable) return;
      onBytes?.(ev.loaded, ev.total || file.size || 0);
    };
    xhr.onload = () => {
      let data = {};
      try {
        data = JSON.parse(xhr.responseText || "{}");
      } catch (_) {
        data = {};
      }
      if (xhr.status >= 200 && xhr.status < 300 && data.ok !== false) resolve(data);
      else reject(new Error(data.error || data.detail || `HTTP ${xhr.status}`));
    };
    xhr.onerror = () => reject(new Error("Réseau upload"));
    xhr.send(file);
  });
}

async function waitTransferJob(jobId, onSnap) {
  for (;;) {
    const data = await api(`/api/transfer/job?id=${encodeURIComponent(jobId)}`);
    const job = data.job;
    onSnap?.(job);
    if (["done", "done_with_errors", "error", "cancelled"].includes(job.status)) return job;
    await new Promise((r) => setTimeout(r, 400));
  }
}

async function startBrowserTransfer(
  files,
  destRoot = "/data/homebrew",
  { silent = false, onFileDone = null, onProgress = null } = {}
) {
  if (!files?.length) throw new Error("Aucun fichier");
  const dest = (destRoot || "/data/homebrew").replace(/\/$/, "") || "/data/homebrew";
  if ($("#transfer-progress-wrap")) $("#transfer-progress-wrap").hidden = false;
  let done = 0;
  let sent = 0;
  const total = files.reduce((s, f) => s + (f.size || 0), 0);
  const concurrency = Math.min(workers(), 2);
  const queue = [...files];
  const errors = [];
  const t0 = Date.now() / 1000;

  const emit = (extra = {}) => {
    const uploadBytes = Math.min(total, sent + (extra.inFlight || 0));
    const elapsed = Math.max(0.001, Date.now() / 1000 - t0);
    const mbps =
      extra.mbps != null ? Number(extra.mbps) : (uploadBytes * 8) / elapsed / 1_000_000;
    const startedAt = extra.started_at || t0;
    const snap = {
      status: "running",
      phase: "upload",
      kind: "transfer",
      done_files: done,
      total_files: files.length,
      sent_bytes: uploadBytes,
      total_bytes: total,
      upload_bytes: uploadBytes,
      upload_total: total,
      upload_percent: total ? (uploadBytes / total) * 100 : 0,
      percent: total ? (uploadBytes / total) * 100 : 0,
      mbps: Math.round(mbps * 100) / 100,
      started_at: startedAt,
      eta_seconds:
        extra.eta_seconds != null
          ? Number(extra.eta_seconds)
          : etaFromProgress(uploadBytes, total, startedAt, mbps),
      workers: concurrency,
      current: extra.current || dest,
      errors: [...errors],
    };
    if (!silent) renderJob(snap);
    onProgress?.(snap);
    return snap;
  };

  async function one(file) {
    const rel = (file.webkitRelativePath || file.name || "file.bin").replace(/^\/+/, "");
    const headers = {
      "Content-Type": "application/octet-stream",
      "X-PSHD-Host": host(),
      "X-PSHD-Relative-Path": rel,
      "X-PSHD-Dest-Root": dest,
      "Content-Length": String(file.size),
    };
    const token = localStorage.getItem("pshd-token");
    if (token) headers["X-PSHD-Token"] = token;

    let spoolLoaded = 0;
    const data = await rawUploadWithProgress(file, headers, (loaded) => {
      spoolLoaded = loaded;
      // Spool Mac→Desk is usually fast; keep bar alive then switch to FTP job %.
      emit({ inFlight: spoolLoaded * 0.15, current: `prépare ${rel}` });
    });

    if (data.job?.id) {
      await waitTransferJob(data.job.id, (job) => {
        const jobBytes = Number(job.upload_bytes || 0);
        emit({
          inFlight: jobBytes,
          current: job.current || `${rel} → FTP`,
          eta_seconds: job.eta_seconds,
          mbps: job.mbps,
          started_at: job.started_at || t0,
        });
      });
    }

    done += 1;
    sent += file.size || 0;
    const snap = emit({ inFlight: 0, current: `${rel} → ${dest}` });
    onFileDone?.(done, files.length, snap);
  }

  const runners = Array.from({ length: concurrency }, async () => {
    while (queue.length) {
      const file = queue.shift();
      if (!file) break;
      try {
        await one(file);
      } catch (err) {
        errors.push(`${file.name}: ${err.message || err}`);
        done += 1;
        emit({ inFlight: 0, current: file.name });
      }
    }
  });
  await Promise.all(runners);
  const finalSnap = {
    status: errors.length ? (done > errors.length ? "done_with_errors" : "error") : "done",
    phase: errors.length && done <= errors.length ? "error" : "done",
    kind: "transfer",
    done_files: done,
    total_files: files.length,
    sent_bytes: sent,
    total_bytes: total,
    upload_bytes: sent,
    upload_total: total,
    upload_percent: 100,
    percent: 100,
    mbps: 0,
    started_at: t0,
    eta_seconds: 0,
    workers: concurrency,
    current: dest,
    errors,
  };
  if (!silent) {
    renderJob(finalSnap);
    toast(errors.length ? `Terminé avec ${errors.length} erreur(s)` : `Upload → ${dest}`);
    refreshHomebrew().catch(() => {});
  }
  onProgress?.(finalSnap);
  return finalSnap;
}

async function uploadExternalDropToFinder(dt, destDir) {
  if (!state.finderWritable) throw new Error("Dossier en lecture seule");
  const files = await collectDataTransferFiles(dt);
  if (!files.length) throw new Error("Aucun fichier déposé (dossiers : réessaie ou utilise Transfert)");
  const dest = destDir || state.finderPath || "/data/homebrew";
  const byteTotal = files.reduce((s, f) => s + (f.size || 0), 0);
  state.finderProgressUnit = "bytes";
  await withFinderProgress(
    `Upload → ${dest}`,
    async (p) => {
      p.update?.(0, byteTotal);
      await startBrowserTransfer(files, dest, {
        silent: true,
        onProgress: (snap) => {
          p.update?.(snap.upload_bytes || 0, snap.upload_total || byteTotal, snap.current);
        },
      });
    },
    { total: byteTotal }
  );
  toast(`${files.length} fichier(s) → ${dest}`);
  await loadFinder(state.finderPath);
}

$("#pick-folder-btn")?.addEventListener("click", async () => {
  if (window.pywebview?.api?.pick_folder) {
    try {
      const paths = await window.pywebview.api.pick_folder();
      if (paths?.length) {
        state.transferPaths = paths;
        state.transferFiles = [];
        updateTransferSelection();
      }
      return;
    } catch (err) {
      toast(err.message || String(err));
    }
  }
  $("#folder-input")?.click();
});

$("#pick-pkg-btn")?.addEventListener("click", async () => {
  if (window.pywebview?.api?.pick_files) {
    try {
      const paths = await window.pywebview.api.pick_files();
      if (paths?.length) {
        state.transferPaths = paths;
        state.transferFiles = [];
        updateTransferSelection();
      }
      return;
    } catch (err) {
      toast(err.message || String(err));
    }
  }
  $("#multi-input")?.click();
});

$("#folder-input")?.addEventListener("change", (e) => {
  state.transferFiles = [...(e.target.files || [])];
  state.transferPaths = [];
  updateTransferSelection();
});

$("#multi-input")?.addEventListener("change", (e) => {
  state.transferFiles = [...(e.target.files || [])];
  state.transferPaths = [];
  updateTransferSelection();
});

$("#start-transfer-btn")?.addEventListener("click", async () => {
  try {
    const dest = xferDestRoot();
    if (!dest.startsWith("/")) return toast("Destination invalide");
    if (state.transferPaths.length) {
      await startLocalTransfer(state.transferPaths, dest);
      return;
    }
    if (state.transferFiles.length) {
      await startBrowserTransfer(state.transferFiles, dest);
      return;
    }
    toast("Sélectionne un dossier ou des fichiers d’abord");
  } catch (err) {
    toast(err.message);
  }
});

$("#xfer-clear-btn")?.addEventListener("click", () => {
  state.transferFiles = [];
  state.transferPaths = [];
  if ($("#multi-input")) $("#multi-input").value = "";
  if ($("#folder-input")) $("#folder-input").value = "";
  updateTransferSelection();
});

$("#xfer-cancel-btn")?.addEventListener("click", async () => {
  const id = state.transferJobId || state.transferJob?.id;
  if (!id) return toast("Aucun transfert en cours");
  try {
    const data = await api("/api/transfer/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    if (data.job) renderJob(data.job);
    toast("Annulation demandée…");
  } catch (err) {
    toast(err.message);
  }
});

$("#xfer-dest-preset")?.addEventListener("change", () => {
  const wrap = $("#xfer-dest-custom-wrap");
  if (wrap) wrap.hidden = $("#xfer-dest-preset").value !== "__custom__";
  updateTransferSelection();
});
$("#xfer-dest-custom")?.addEventListener("input", () => updateTransferSelection());

{
  const xdz = $("#xfer-dropzone");
  if (xdz) {
    ["dragenter", "dragover"].forEach((evt) => {
      xdz.addEventListener(evt, (e) => {
        e.preventDefault();
        e.stopPropagation();
        xdz.classList.add("drag");
        if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
      });
    });
    ["dragleave", "drop"].forEach((evt) => {
      xdz.addEventListener(evt, (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (evt === "dragleave" && e.relatedTarget && xdz.contains(e.relatedTarget)) return;
        xdz.classList.remove("drag");
      });
    });
    xdz.addEventListener("drop", async (e) => {
      try {
        const files = await collectDataTransferFiles(e.dataTransfer);
        if (!files.length) return toast("Rien à déposer");
        state.transferFiles = files;
        state.transferPaths = [];
        updateTransferSelection();
        toast(`${files.length} fichier(s) prêts`);
      } catch (err) {
        toast(err.message);
      }
    });
  }
}

function linkDestRoot() {
  const preset = $("#link-dest-preset")?.value || "/data/homebrew";
  if (preset === "__custom__") {
    return ($("#link-dest-custom")?.value || "").trim() || "/data/homebrew";
  }
  return preset;
}

function updateLinkDestHint() {
  const dest = linkDestRoot().replace(/\/$/, "") || "/data/homebrew";
  const hint = $("#link-dest-hint");
  const customWrap = $("#link-dest-custom-wrap");
  const preset = $("#link-dest-preset")?.value;
  if (customWrap) customWrap.hidden = preset !== "__custom__";
  if (!hint) return;
  if (dest === "/data/homebrew") {
    hint.innerHTML = `Fichiers → <code>${dest}</code> · PKG/FPKG → <code>/data/homebrew/pkgs</code>`;
  } else {
    hint.innerHTML = `Tout sera envoyé dans <code>${escapeHtml(dest)}</code>`;
  }
}

function persistLinkDest() {
  const preset = $("#link-dest-preset")?.value || "/data/homebrew";
  localStorage.setItem("pshd-link-dest-preset", preset);
  if (preset === "__custom__") {
    localStorage.setItem("pshd-link-dest-custom", ($("#link-dest-custom")?.value || "").trim());
  }
}

function restoreLinkDest() {
  const preset = localStorage.getItem("pshd-link-dest-preset") || "/data/homebrew";
  const custom = localStorage.getItem("pshd-link-dest-custom") || "";
  const sel = $("#link-dest-preset");
  if (sel) {
    const known = [...sel.options].some((o) => o.value === preset);
    sel.value = known ? preset : "__custom__";
    if (!known && preset !== "__custom__") {
      if ($("#link-dest-custom")) $("#link-dest-custom").value = preset;
    }
  }
  if ($("#link-dest-custom") && custom) $("#link-dest-custom").value = custom;
  updateLinkDestHint();
}

function setLinkBusy(busy) {
  const start = $("#link-start-btn");
  const cancel = $("#link-cancel-btn");
  if (start) start.disabled = !!busy;
  if (cancel) cancel.hidden = !busy;
}

function renderLinkJob(job) {
  $("#link-progress-wrap").hidden = false;
  const phase = jobPhase(job);
  const dlPct = Number(job.download_percent || 0);
  const upPct = Number(job.upload_percent || 0);
  const dlDone = phase !== "download" && phase !== "queued";
  const eta = jobEtaSeconds(job);

  setFillPhase($("#link-dl-fill"), "download", { width: dlDone ? Math.max(dlPct, 100) : dlPct });
  if ($("#link-dl-pct")) {
    $("#link-dl-pct").textContent = dlDone
      ? "100%"
      : formatPctEta(dlPct, phase === "download" ? eta : null);
  }

  const stageLabel = $("#link-stage-label");
  const stagePct = $("#link-stage-pct");
  if (phase === "extract") {
    const exPct = Number(job.extract_percent || 0);
    if (stageLabel) stageLabel.textContent = "Extraction (Mac)";
    if (stagePct) {
      stagePct.textContent = exPct > 0 ? formatPctEta(exPct, eta) : "…";
    }
    // Real progress when available; soft pulse if still at 0
    if (exPct > 0) {
      setFillPhase($("#link-stage-fill"), "extract", { width: Math.max(3, Math.min(99, exPct)) });
    } else {
      setFillPhase($("#link-stage-fill"), "extract", { indeterminate: true });
    }
  } else if (phase === "upload") {
    if (stageLabel) stageLabel.textContent = "Upload FTP";
    if (stagePct) stagePct.textContent = formatPctEta(upPct, eta);
    setFillPhase($("#link-stage-fill"), "upload", { width: upPct });
  } else if (phase === "done") {
    if (stageLabel) stageLabel.textContent = "Upload FTP";
    if (stagePct) stagePct.textContent = "100%";
    setFillPhase($("#link-stage-fill"), "done", { width: 100 });
  } else if (phase === "error" || phase === "cancelled") {
    if (stageLabel) stageLabel.textContent = phaseLabel(phase);
    if (stagePct) stagePct.textContent = "—";
    setFillPhase($("#link-stage-fill"), phase, { width: Math.max(upPct, 12) });
  } else {
    if (stageLabel) stageLabel.textContent = "Extraction / Upload";
    if (stagePct) stagePct.textContent = "—";
    setFillPhase($("#link-stage-fill"), "idle", { width: 0 });
  }

  const note = $("#link-phase-note");
  if (note) {
    note.dataset.phase = phase;
    const bits = [phaseLabel(phase)];
    if (phase === "download") bits.push(`${formatBytes(job.download_bytes || 0)} / ${formatBytes(job.download_total || 0)}`);
    if (phase === "extract") bits.push(`${formatBytes(job.extract_bytes || 0)} / ~${formatBytes(job.extract_total || 0)}`);
    if (phase === "upload") bits.push(`${formatBytes(job.upload_bytes || 0)} / ${formatBytes(job.upload_total || 0)}`);
    const etaBit = formatEta(eta);
    if (etaBit) bits.push(`reste ${etaBit}`);
    if (job.current) bits.push(job.current);
    note.textContent = bits.join(" · ");
  }

  $("#link-status").textContent =
    `status=${job.status}\n` +
    `phase=${phase}\n` +
    `current=${job.current || "-"}\n` +
    `remote=${job.remote_path || "-"}\n` +
    `download=${formatBytes(job.download_bytes || 0)} / ${formatBytes(job.download_total || 0)}\n` +
    `extract=${formatBytes(job.extract_bytes || 0)} / ~${formatBytes(job.extract_total || 0)}\n` +
    `upload=${formatBytes(job.upload_bytes || 0)} / ${formatBytes(job.upload_total || 0)}\n` +
    `speed=${job.mbps} Mbps\n` +
    `eta=${formatEta(eta) || "—"}\n` +
    (job.errors?.length ? `errors:\n- ${job.errors.join("\n- ")}` : "errors=0");

  state._xferKeepGlobal = !["done", "done_with_errors", "error", "cancelled"].includes(job.status);
  updateGlobalXfer(job);
  if (!state._xferKeepGlobal) {
    setTimeout(() => {
      state._xferKeepGlobal = false;
      updateGlobalXfer(null);
    }, 4000);
  }
}

async function pollLinkJob(id) {
  state.linkJobId = id;
  setLinkBusy(true);
  clearInterval(state.linkTimer);
  state.linkTimer = setInterval(async () => {
    try {
      const data = await api(`/api/transfer/job?id=${encodeURIComponent(id)}`);
      renderLinkJob(data.job);
      if (["done", "done_with_errors", "error", "cancelled"].includes(data.job.status)) {
        clearInterval(state.linkTimer);
        state.linkJobId = null;
        setLinkBusy(false);
        if (data.job.status === "done") {
          toast("Lien envoyé sur la console");
          refreshHomebrew().catch(() => {});
        } else if (data.job.status === "cancelled") {
          toast("Annulé — fichiers temporaires / partiels supprimés");
        } else {
          toast("Échec du transfert lien");
        }
      }
    } catch (err) {
      clearInterval(state.linkTimer);
      state.linkJobId = null;
      setLinkBusy(false);
      toast(err.message);
    }
  }, 350);
}

async function cancelLinkJob() {
  const id = state.linkJobId;
  if (!id) return toast("Aucun transfert en cours");
  try {
    const data = await api("/api/transfer/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    renderLinkJob(data.job);
    toast("Annulation demandée…");
  } catch (err) {
    toast(err.message);
  }
}

$("#link-dest-preset")?.addEventListener("change", () => {
  if ($("#link-dest-preset").value === "__custom__") {
    $("#link-dest-custom-wrap").hidden = false;
    $("#link-dest-custom")?.focus();
  }
  persistLinkDest();
  updateLinkDestHint();
});
$("#link-dest-custom")?.addEventListener("input", () => {
  persistLinkDest();
  updateLinkDestHint();
});
restoreLinkDest();

$("#link-cancel-btn")?.addEventListener("click", () => cancelLinkJob());
$("#link-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (state.linkJobId) return toast("Un transfert est déjà en cours — annule-le d’abord");
  const url = ($("#link-url").value || "").trim();
  const filename = ($("#link-filename").value || "").trim();
  const password = ($("#link-password")?.value || "").trim();
  const extract = !$("#link-no-extract")?.checked;
  const dest_root = linkDestRoot();
  if (!url) return toast("URL requise");
  if (!dest_root.startsWith("/")) return toast("Destination invalide (doit commencer par /)");
  persistLinkDest();
  setLinkBusy(true);
  try {
    const data = await api("/api/fetch-upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ host: host(), url, filename, dest_root, password, extract }),
    });
    renderLinkJob(data.job);
    toast(`Destination: ${data.dest_root || dest_root}`);
    pollLinkJob(data.job.id);
  } catch (err) {
    setLinkBusy(false);
    state.linkJobId = null;
    toast(err.message);
  }
});

function finderJoin(parent, name) {
  if (!parent || parent === "/") return `/${name}`;
  return `${parent.replace(/\/$/, "")}/${name}`;
}

function iconUse(name) {
  return `<svg class="ic" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
}

function finderIcon(item) {
  if (item.type === "dir") return { html: iconUse("folder"), dir: true };
  const n = item.name.toLowerCase();
  if (n.endsWith(".pkg") || n.endsWith(".fpkg")) return { html: iconUse("pkg"), dir: false };
  if (n.endsWith(".elf") || n.endsWith(".bin")) return { html: iconUse("gear"), dir: false };
  if (n.endsWith(".zip")) return { html: iconUse("zip"), dir: false };
  if (n.endsWith(".log") || n.endsWith(".txt") || n.endsWith(".ini")) return { html: iconUse("logs"), dir: false };
  return { html: iconUse("doc"), dir: false };
}

function selectedFinderItems() {
  return state.finderSelection || [];
}

function selectedFinderItem() {
  const items = selectedFinderItems();
  return items.length ? items[items.length - 1] : null;
}

function visibleFinderRows() {
  return $$("#finder-list .finder-row:not(.empty)");
}

function itemFromRow(row) {
  if (!row || row.classList.contains("empty")) return null;
  return {
    name: row.dataset.name,
    type: row.dataset.type,
    path: row.dataset.path || finderJoin(state.finderPath, row.dataset.name),
    parent: row.dataset.parent || state.finderPath,
    size: Number(row.dataset.size || 0),
  };
}

function syncFinderSelectionUI() {
  const selected = new Set(selectedFinderItems().map((it) => it.path));
  visibleFinderRows().forEach((row) => {
    const path = row.dataset.path || finderJoin(state.finderPath, row.dataset.name);
    row.classList.toggle("selected", selected.has(path));
  });
}

function setFinderSelection(items, { anchorIdx = null } = {}) {
  const uniq = [];
  const seen = new Set();
  for (const it of items || []) {
    if (!it?.path || seen.has(it.path)) continue;
    seen.add(it.path);
    uniq.push(it);
  }
  state.finderSelection = uniq;
  if (anchorIdx !== null) state.finderAnchorIdx = anchorIdx;
  syncFinderSelectionUI();
  updateFinderActions();
}

function clearFinderSelection() {
  setFinderSelection([], { anchorIdx: -1 });
}

function rowIndexForPath(path) {
  return visibleFinderRows().findIndex((row) => (row.dataset.path || finderJoin(state.finderPath, row.dataset.name)) === path);
}

function selectFinderRange(fromIdx, toIdx, { additive = false } = {}) {
  const rows = visibleFinderRows();
  if (!rows.length) return;
  const a = Math.max(0, Math.min(fromIdx, toIdx, rows.length - 1));
  const b = Math.min(rows.length - 1, Math.max(fromIdx, toIdx, 0));
  const ranged = [];
  for (let i = a; i <= b; i += 1) ranged.push(itemFromRow(rows[i]));
  if (additive) {
    const map = new Map(selectedFinderItems().map((it) => [it.path, it]));
    ranged.forEach((it) => map.set(it.path, it));
    setFinderSelection([...map.values()], { anchorIdx: fromIdx });
  } else {
    setFinderSelection(ranged, { anchorIdx: fromIdx });
  }
}

function selectAllFinder() {
  const items = visibleFinderRows().map(itemFromRow).filter(Boolean);
  setFinderSelection(items, { anchorIdx: items.length ? 0 : -1 });
  $("#finder-list")?.focus();
}

function isFinderMod(e) {
  return e.metaKey || e.ctrlKey;
}

function paintFinderProgress() {
  const root = $("#finder-progress");
  const fill = $("#finder-progress-fill");
  const pct = $("#finder-progress-pct");
  if (!root || !fill || root.hidden) return;
  const total = state.finderProgressTotal;
  const done = state.finderProgressDone;
  if (total > 0) {
    const value = Math.max(0, Math.min(100, Math.round((done / total) * 100)));
    fill.classList.remove("indeterminate");
    fill.style.width = `${value}%`;
    const eta = etaFromProgress(done, total, state.finderProgressStarted);
    const etaBit = formatEta(eta);
    if (pct) {
      if (state.finderProgressUnit === "bytes") {
        pct.textContent = `${formatPctEta(value, eta)} · ${formatBytes(done)} / ${formatBytes(total)}`;
      } else {
        pct.textContent = etaBit ? `${value}% · ${done}/${total} · ${etaBit}` : `${value}% · ${done}/${total}`;
      }
    }
  } else {
    fill.classList.add("indeterminate");
    fill.style.width = "38%";
    const fake = Math.round(state.finderProgressFake || 0);
    if (pct) pct.textContent = fake > 0 ? `${fake}%` : "…";
  }
}

function beginFinderProgress(label, { total = 0 } = {}) {
  if (state.finderBusy) {
    const lab = $("#finder-progress-label");
    if (lab && label) lab.textContent = label;
    if (total > 0) {
      state.finderProgressTotal = total;
      state.finderProgressDone = 0;
      paintFinderProgress();
    }
    return;
  }
  state.finderBusy = true;
  state.finderProgressTotal = Math.max(0, total | 0);
  state.finderProgressDone = 0;
  state.finderProgressFake = 8;
  state.finderProgressStarted = Date.now() / 1000;
  clearInterval(state.finderProgressTimer);
  const root = $("#finder-progress");
  const fill = $("#finder-progress-fill");
  const lab = $("#finder-progress-label");
  const status = $("#finder-status-text");
  $(".finder")?.classList.add("busy");
  if (root) root.hidden = false;
  if (fill) {
    fill.classList.remove("done", "error");
    fill.style.width = "0%";
  }
  if (lab) lab.textContent = label || "En cours…";
  if (status) status.textContent = label || "Action en cours…";
  if (state.finderProgressTotal <= 0) {
    state.finderProgressTimer = setInterval(() => {
      // Approche asymptotique pour un ressenti « vivant » pendant les appels FTP
      const cur = state.finderProgressFake || 8;
      state.finderProgressFake = cur + (92 - cur) * 0.08 + Math.random() * 1.4;
      if (state.finderProgressFake > 92) state.finderProgressFake = 92;
      paintFinderProgress();
    }, 160);
  }
  paintFinderProgress();
}

function updateFinderProgress(done, total, detail) {
  if (!state.finderBusy) return;
  if (typeof total === "number" && total > 0) state.finderProgressTotal = total;
  if (typeof done === "number") state.finderProgressDone = Math.max(0, done);
  const lab = $("#finder-progress-label");
  if (lab && detail) {
    const base = lab.dataset.base || lab.textContent.split(" · ")[0];
    lab.dataset.base = base;
    lab.textContent = `${base} · ${detail}`;
  }
  const status = $("#finder-status-text");
  if (status && detail) status.textContent = detail;
  // Stop indeterminate fake once we have real totals
  if (state.finderProgressTotal > 0) {
    clearInterval(state.finderProgressTimer);
    state.finderProgressTimer = null;
  }
  paintFinderProgress();
}

function endFinderProgress({ ok = true, message = "" } = {}) {
  clearInterval(state.finderProgressTimer);
  state.finderProgressTimer = null;
  const fill = $("#finder-progress-fill");
  const pct = $("#finder-progress-pct");
  const lab = $("#finder-progress-label");
  const root = $("#finder-progress");
  if (fill) {
    fill.classList.remove("indeterminate");
    fill.style.width = "100%";
    fill.classList.toggle("done", !!ok);
    fill.classList.toggle("error", !ok);
  }
  if (pct) pct.textContent = ok ? "100%" : "Erreur";
  if (lab && message) lab.textContent = message;
  else if (lab && ok && !lab.textContent.includes("·")) {
    /* keep label */
  }
  const hide = () => {
    if (root) root.hidden = true;
    if (fill) {
      fill.classList.remove("done", "error", "indeterminate");
      fill.style.width = "0%";
    }
    if (lab) {
      lab.textContent = "";
      delete lab.dataset.base;
    }
    $(".finder")?.classList.remove("busy");
    state.finderBusy = false;
    state.finderProgressTotal = 0;
    state.finderProgressDone = 0;
    state.finderProgressFake = 0;
    state.finderProgressStarted = 0;
    state.finderProgressUnit = "";
    updateFinderActions();
  };
  setTimeout(hide, ok ? 420 : 900);
}

async function withFinderProgress(label, fn, { total = 0 } = {}) {
  beginFinderProgress(label, { total });
  try {
    const result = await fn({
      update: (done, tot, detail) => updateFinderProgress(done, tot, detail),
      label: (text) => {
        const lab = $("#finder-progress-label");
        if (lab) {
          lab.textContent = text;
          lab.dataset.base = text;
        }
      },
    });
    endFinderProgress({ ok: true, message: label.replace(/…$/, "") + " — terminé" });
    return result;
  } catch (err) {
    endFinderProgress({ ok: false, message: err.message || "Échec" });
    throw err;
  }
}

async function moveFinderItems(items, dstDir, { onProgress } = {}) {
  const list = (items || []).filter(Boolean);
  if (!list.length || !dstDir) return { moved: 0, mode: null };
  let moved = 0;
  let lastMode = null;
  const errors = [];
  let processed = 0;
  for (const item of list) {
    if (!item.path) continue;
    onProgress?.(processed, list.length, item.name);
    if (item.path === dstDir || dstDir === item.path || dstDir.startsWith(`${item.path}/`)) {
      errors.push(`${item.name}: destination invalide`);
      processed += 1;
      onProgress?.(processed, list.length, item.name);
      continue;
    }
    const parent = item.path.includes("/") ? item.path.slice(0, item.path.lastIndexOf("/")) || "/" : "/";
    if (parent === dstDir) {
      processed += 1;
      onProgress?.(processed, list.length, item.name);
      continue;
    }
    try {
      const res = await api("/api/fs/move", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          host: host(),
          src: item.path,
          dst_dir: dstDir,
          is_dir: item.type === "dir",
        }),
      });
      lastMode = res.mode;
      moved += 1;
    } catch (err) {
      errors.push(`${item.name}: ${err.message}`);
    }
    processed += 1;
    onProgress?.(processed, list.length, item.name);
  }
  if (errors.length && !moved) throw new Error(errors[0]);
  if (errors.length) toast(errors[0]);
  return { moved, mode: lastMode };
}

function updateFinderActions() {
  const sel = selectedFinderItems();
  const one = selectedFinderItem();
  const writable = !!state.finderWritable;
  const clip = state.finderClipboard;
  const clipCount = clip?.items?.length || (clip?.path ? 1 : 0);
  if ($("#finder-new-folder")) $("#finder-new-folder").disabled = !writable;
  if ($("#finder-rename")) $("#finder-rename").disabled = !(writable && sel.length === 1);
  // Copy/cut allowed from read-only (to paste into /data later)
  if ($("#finder-cut")) $("#finder-cut").disabled = !sel.length;
  if ($("#finder-copy")) $("#finder-copy").disabled = !sel.length;
  if ($("#finder-paste")) $("#finder-paste").disabled = !(writable && clipCount);
  if ($("#finder-move-to")) $("#finder-move-to").disabled = !(writable && sel.length);
  if ($("#finder-delete")) $("#finder-delete").disabled = !(writable && sel.length);
  $("#finder-forward").disabled = state.finderHistIdx >= state.finderHistory.length - 1;
  const badge = $("#finder-writable-badge");
  if (badge) {
    badge.textContent = writable ? "Écriture OK" : "Lecture seule";
    badge.classList.toggle("write", writable);
    badge.classList.toggle("ro", !writable);
  }
  const status = $("#finder-status-text");
  if (status && !state.finderBusy) {
    if (!writable) status.textContent = "Lecture seule — écriture: /data, /user, /mnt (pas le système)";
    else if (clipCount) {
      const label = clip.mode === "cut" ? "Couper" : "Copier";
      status.textContent =
        clipCount === 1
          ? `${label}: ${clip.items?.[0]?.name || clip.name} · ⌘V pour coller`
          : `${label}: ${clipCount} éléments · ⌘V pour coller`;
    } else if (sel.length > 1) status.textContent = `${sel.length} éléments sélectionnés · glisse pour déplacer · ⌘A tout sélectionner`;
    else if (one) status.textContent = `${one.type === "dir" ? "Dossier" : "Fichier"} · ${one.name} · glisse · ⌘A · Shift/⌘ clic`;
    else status.textContent = "Glisser-déposer · ⌘A tout sélectionner · Shift/⌘ clic · rectangle de sélection";
  }
}

function hideFinderMenu() {
  const menu = $("#finder-menu");
  if (menu) menu.hidden = true;
}

function showFinderMenu(x, y) {
  const menu = $("#finder-menu");
  if (!menu) return;
  menu.hidden = false;
  const pad = 8;
  const w = menu.offsetWidth || 180;
  const h = menu.offsetHeight || 220;
  menu.style.left = `${Math.min(x, window.innerWidth - w - pad)}px`;
  menu.style.top = `${Math.min(y, window.innerHeight - h - pad)}px`;
  updateFinderActions();
  const writable = !!state.finderWritable;
  const sel = selectedFinderItems();
  const one = selectedFinderItem();
  const clipCount = state.finderClipboard?.items?.length || (state.finderClipboard?.path ? 1 : 0);
  menu.querySelectorAll("button").forEach((btn) => {
    const act = btn.dataset.act;
    let enabled = true;
    if (act === "open") enabled = !!(one && one.type === "dir" && sel.length === 1);
    if (act === "new") enabled = writable;
    if (act === "rename") enabled = writable && sel.length === 1;
    if (act === "cut" || act === "copy") enabled = sel.length > 0;
    if (act === "delete" || act === "move") enabled = writable && sel.length > 0;
    if (act === "paste") enabled = writable && clipCount > 0;
    btn.disabled = !enabled;
    btn.style.opacity = enabled ? "1" : "0.35";
  });
}

function renderCrumbs(path) {
  const root = $("#finder-crumbs");
  const parts = path.split("/").filter(Boolean);
  let acc = "";
  const nodes = [`<button type="button" data-path="/">Console</button>`];
  parts.forEach((part) => {
    acc += `/${part}`;
    nodes.push(`<span class="sep">›</span>`);
    nodes.push(`<button type="button" data-path="${escapeHtml(acc)}">${escapeHtml(part)}</button>`);
  });
  root.innerHTML = nodes.join("");
  root.querySelectorAll("button[data-path]").forEach((btn) => {
    btn.addEventListener("click", () => navigateFinder(btn.dataset.path).catch((e) => toast(e.message)));
  });
}

function pushFinderHistory(path) {
  if (state.finderHistory[state.finderHistIdx] === path) return;
  state.finderHistory = state.finderHistory.slice(0, state.finderHistIdx + 1);
  state.finderHistory.push(path);
  state.finderHistIdx = state.finderHistory.length - 1;
}

async function navigateFinder(path, { history = true } = {}) {
  clearFinderSearchUI(false);
  await loadFinder(path);
  if (history) pushFinderHistory(state.finderPath);
  updateFinderActions();
}

function clearFinderSearchUI(resetInput = true) {
  state.finderSearchMode = false;
  if (resetInput && $("#finder-search")) $("#finder-search").value = "";
  const clearBtn = $("#finder-search-clear");
  if (clearBtn) clearBtn.hidden = true;
  $("#finder-list")?.classList.remove("search-mode");
  $(".finder-head")?.classList.remove("search-mode");
}

async function loadFinder(path) {
  hideFinderMenu();
  const ownProgress = !state.finderBusy;
  if (ownProgress) beginFinderProgress("Chargement du dossier…");
  try {
    const data = await api(`/api/fs/list?host=${encodeURIComponent(host())}&path=${encodeURIComponent(path || "/")}`);
    if (ownProgress) updateFinderProgress(1, 1, data.path);
    state.finderPath = data.path;
    state.finderParent = data.parent || "/";
    state.finderWritable = !!data.writable;
    state.finderSelection = [];
    state.finderAnchorIdx = -1;
    state.finderItems = data.items || [];
    state.finderSearchMode = false;
    renderCrumbs(data.path);
    $$(".fav").forEach((b) => b.classList.toggle("active", b.dataset.path === data.path));
    const q = ($("#finder-search")?.value || "").trim();
    paintFinderList(q ? filterFinderItems(state.finderItems, q) : state.finderItems, { search: false });
    updateFinderActions();
    if (ownProgress) endFinderProgress({ ok: true, message: "Dossier chargé" });
  } catch (err) {
    if (ownProgress) endFinderProgress({ ok: false, message: err.message });
    throw err;
  }
}

function filterFinderItems(items, query) {
  const q = query.trim().toLowerCase();
  if (!q) return items;
  return items.filter((it) => it.name.toLowerCase().includes(q));
}

function paintFinderList(items, { search = false, query = "", truncated = false } = {}) {
  const list = $("#finder-list");
  const head = $(".finder-head");
  state.finderSearchMode = !!search;
  list?.classList.toggle("search-mode", !!search);
  head?.classList.toggle("search-mode", !!search);
  if (head) {
    head.innerHTML = search
      ? `<span>Nom</span><span>Emplacement</span><span>Taille</span><span>Type</span>`
      : `<span>Nom</span><span>Taille</span><span>Type</span>`;
  }
  if (!items?.length) {
    list.innerHTML = `<div class="finder-row empty"><div class="name"><span class="finder-icon dir">${iconUse("folder")}</span><span>${
      query ? "Aucun résultat" : "Dossier vide"
    }</span></div>${search ? "<span></span>" : ""}<span></span><span></span></div>`;
    updateFinderStatusSearch(query, 0, truncated, search);
    return;
  }
  list.innerHTML = items
    .map((it) => {
      const ic = finderIcon(it);
      const fullPath = it.path || finderJoin(state.finderPath, it.name);
      const parent = it.parent || state.finderPath;
      if (search) {
        return `<div class="finder-row search-mode" draggable="${state.finderWritable ? "true" : "false"}" data-type="${it.type}" data-name="${escapeHtml(it.name)}" data-path="${escapeHtml(fullPath)}" data-parent="${escapeHtml(parent)}" data-size="${it.size || 0}">
          <div class="name"><span class="finder-icon ${ic.dir ? "dir" : ""}">${ic.html}</span><span class="label">${escapeHtml(it.name)}</span></div>
          <span class="meta" title="${escapeHtml(parent)}">${escapeHtml(parent)}</span>
          <span class="meta">${it.type === "dir" ? "—" : formatBytes(it.size)}</span>
          <span class="meta">${it.type === "dir" ? "Dossier" : "Fichier"}</span>
        </div>`;
      }
      return `<div class="finder-row" draggable="${state.finderWritable ? "true" : "false"}" data-type="${it.type}" data-name="${escapeHtml(it.name)}" data-path="${escapeHtml(fullPath)}" data-size="${it.size || 0}">
        <div class="name"><span class="finder-icon ${ic.dir ? "dir" : ""}">${ic.html}</span><span class="label">${escapeHtml(it.name)}</span></div>
        <span class="meta">${it.type === "dir" ? "—" : formatBytes(it.size)}</span>
        <span class="meta">${it.type === "dir" ? "Dossier" : "Fichier"}</span>
      </div>`;
    })
    .join("");
  bindFinderRows(list);
  updateFinderStatusSearch(query, items.length, truncated, search);
}

function updateFinderStatusSearch(query, count, truncated, search) {
  const status = $("#finder-status-text");
  if (!status) return;
  if (search && query) {
    status.textContent = truncated
      ? `${count}+ résultats pour « ${query} » (limite atteinte)`
      : `${count} résultat(s) pour « ${query} » sous ${state.finderPath}`;
  }
}

function parseFinderDragPayload(raw) {
  if (!raw) return [];
  try {
    const data = JSON.parse(raw);
    if (Array.isArray(data?.items)) return data.items.filter((it) => it?.path);
    if (data?.path) return [data];
  } catch {
    return [];
  }
  return [];
}

function setFinderDragGhost(e, items) {
  const ghost = document.createElement("div");
  ghost.className = "finder-drag-ghost";
  ghost.innerHTML = `<span class="count">${items.length}</span><span>${
    items.length === 1 ? escapeHtml(items[0].name) : `${items.length} éléments`
  }</span>`;
  document.body.appendChild(ghost);
  e.dataTransfer.setDragImage(ghost, 16, 16);
  requestAnimationFrame(() => ghost.remove());
}

function bindFinderRows(list) {
  list.querySelectorAll(".finder-row:not(.empty)").forEach((row, idx) => {
    const rowPath = () => row.dataset.path || finderJoin(state.finderPath, row.dataset.name);
    row.addEventListener("mousedown", (e) => {
      if (e.button !== 0) return;
      hideFinderMenu();
      const item = itemFromRow(row);
      const already = selectedFinderItems().some((it) => it.path === item.path);
      const mod = isFinderMod(e);
      if (e.shiftKey && state.finderAnchorIdx >= 0) {
        selectFinderRange(state.finderAnchorIdx, idx, { additive: mod });
        e.preventDefault();
        return;
      }
      if (mod) {
        const map = new Map(selectedFinderItems().map((it) => [it.path, it]));
        if (map.has(item.path)) map.delete(item.path);
        else map.set(item.path, item);
        setFinderSelection([...map.values()], { anchorIdx: idx });
        e.preventDefault();
        return;
      }
      if (!already) {
        setFinderSelection([item], { anchorIdx: idx });
      } else {
        // Keep multi-selection for drag; exclusive select on click without drag
        row.dataset.pendingExclusive = "1";
      }
    });
    row.addEventListener("click", (e) => {
      if (e.detail > 1) return;
      if (row.dataset.pendingExclusive === "1" && !state.finderDragActive && !isFinderMod(e) && !e.shiftKey) {
        setFinderSelection([itemFromRow(row)], { anchorIdx: idx });
      }
      delete row.dataset.pendingExclusive;
      list.focus();
    });
    row.addEventListener("dblclick", () => {
      delete row.dataset.pendingExclusive;
      if (row.dataset.type === "dir") {
        navigateFinder(rowPath()).catch((err) => toast(err.message));
      } else if (state.finderSearchMode && row.dataset.parent) {
        navigateFinder(row.dataset.parent).catch((err) => toast(err.message));
      }
    });
    row.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      const item = itemFromRow(row);
      if (!selectedFinderItems().some((it) => it.path === item.path)) {
        setFinderSelection([item], { anchorIdx: idx });
      } else {
        syncFinderSelectionUI();
        updateFinderActions();
      }
      showFinderMenu(e.clientX, e.clientY);
    });
    row.addEventListener("dragstart", (e) => {
      if (!state.finderWritable) {
        e.preventDefault();
        return;
      }
      delete row.dataset.pendingExclusive;
      state.finderDragActive = true;
      let items = selectedFinderItems();
      const current = itemFromRow(row);
      if (!items.some((it) => it.path === current.path)) {
        items = [current];
        setFinderSelection(items, { anchorIdx: idx });
      }
      const payload = { items };
      e.dataTransfer.setData("application/x-pshd-item", JSON.stringify(payload));
      e.dataTransfer.setData("text/plain", items.map((it) => it.path).join("\n"));
      e.dataTransfer.effectAllowed = "move";
      setFinderDragGhost(e, items);
      const selected = new Set(items.map((it) => it.path));
      visibleFinderRows().forEach((r) => {
        const p = r.dataset.path || finderJoin(state.finderPath, r.dataset.name);
        r.classList.toggle("dragging", selected.has(p));
      });
    });
    row.addEventListener("dragend", () => {
      state.finderDragActive = false;
      visibleFinderRows().forEach((r) => r.classList.remove("dragging", "drop-target"));
      $("#finder-drop-zone")?.classList.remove("drop-target");
      $$(".fav.drop-target").forEach((b) => b.classList.remove("drop-target"));
    });
    if (row.dataset.type === "dir" && !state.finderSearchMode) {
      row.addEventListener("dragover", (e) => {
        if (!state.finderWritable) return;
        e.preventDefault();
        e.stopPropagation();
        const hasExternal = [...(e.dataTransfer?.types || [])].includes("Files");
        e.dataTransfer.dropEffect = hasExternal ? "copy" : "move";
        row.classList.add("drop-target");
      });
      row.addEventListener("dragleave", () => row.classList.remove("drop-target"));
      row.addEventListener("drop", async (e) => {
        e.preventDefault();
        e.stopPropagation();
        row.classList.remove("drop-target");
        if (state.finderBusy) return toast("Action déjà en cours…");
        try {
          const items = parseFinderDragPayload(e.dataTransfer.getData("application/x-pshd-item"));
          const dstDir = rowPath();
          if (items.length) {
            await withFinderProgress(`Déplacement → ${row.dataset.name}`, async (p) => {
              const { moved, mode } = await moveFinderItems(items, dstDir, { onProgress: p.update });
              if (!moved) return;
              toast(
                moved === 1
                  ? mode === "copy_delete"
                    ? `Déplacé (copie) → ${row.dataset.name}`
                    : `Déplacé → ${row.dataset.name}`
                  : `${moved} éléments → ${row.dataset.name}`
              );
              await loadFinder(state.finderPath);
            }, { total: items.length });
            return;
          }
          if ([...(e.dataTransfer?.types || [])].includes("Files")) {
            await uploadExternalDropToFinder(e.dataTransfer, dstDir);
          }
        } catch (err) {
          toast(err.message);
        }
      });
    }
  });
}

function endFinderMarquee(commit) {
  const m = state.finderMarquee;
  if (!m) return;
  const { startX, startY, additive, box } = m;
  const move = m.onMove;
  const up = m.onUp;
  window.removeEventListener("mousemove", move);
  window.removeEventListener("mouseup", up);
  box?.remove();
  state.finderMarquee = null;
  if (!commit) return;
  const list = $("#finder-list");
  if (!list) return;
  const rect = {
    left: Math.min(startX, m.curX),
    top: Math.min(startY, m.curY),
    right: Math.max(startX, m.curX),
    bottom: Math.max(startY, m.curY),
  };
  if (Math.abs(rect.right - rect.left) < 4 && Math.abs(rect.bottom - rect.top) < 4) {
    if (!additive) clearFinderSelection();
    return;
  }
  const listRect = list.getBoundingClientRect();
  const hit = [];
  visibleFinderRows().forEach((row, idx) => {
    const r = row.getBoundingClientRect();
    const intersects =
      r.left < rect.right && r.right > rect.left && r.top < rect.bottom && r.bottom > rect.top;
    if (intersects) hit.push({ item: itemFromRow(row), idx });
  });
  if (!hit.length) {
    if (!additive) clearFinderSelection();
    return;
  }
  if (additive) {
    const map = new Map(selectedFinderItems().map((it) => [it.path, it]));
    hit.forEach(({ item }) => map.set(item.path, item));
    setFinderSelection([...map.values()], { anchorIdx: hit[0].idx });
  } else {
    setFinderSelection(
      hit.map((h) => h.item),
      { anchorIdx: hit[0].idx }
    );
  }
  void listRect;
}

function startFinderMarquee(e) {
  if (e.button !== 0) return;
  if (e.target.closest(".finder-row:not(.empty)")) return;
  const list = $("#finder-list");
  if (!list) return;
  hideFinderMenu();
  list.focus();
  const additive = isFinderMod(e) || e.shiftKey;
  if (!additive) clearFinderSelection();
  const box = document.createElement("div");
  box.className = "finder-marquee";
  list.appendChild(box);
  const listRect = list.getBoundingClientRect();
  const startX = e.clientX;
  const startY = e.clientY;
  const originLeft = startX - listRect.left + list.scrollLeft;
  const originTop = startY - listRect.top + list.scrollTop;
  const stateM = {
    startX,
    startY,
    curX: startX,
    curY: startY,
    additive,
    box,
    onMove: null,
    onUp: null,
  };
  const onMove = (ev) => {
    stateM.curX = ev.clientX;
    stateM.curY = ev.clientY;
    const lr = list.getBoundingClientRect();
    const x1 = originLeft;
    const y1 = originTop;
    const x2 = ev.clientX - lr.left + list.scrollLeft;
    const y2 = ev.clientY - lr.top + list.scrollTop;
    const left = Math.min(x1, x2);
    const top = Math.min(y1, y2);
    box.style.left = `${left}px`;
    box.style.top = `${top}px`;
    box.style.width = `${Math.abs(x2 - x1)}px`;
    box.style.height = `${Math.abs(y2 - y1)}px`;
    // live preview selection
    const screen = {
      left: Math.min(startX, ev.clientX),
      top: Math.min(startY, ev.clientY),
      right: Math.max(startX, ev.clientX),
      bottom: Math.max(startY, ev.clientY),
    };
    const base = additive ? new Set(selectedFinderItems().map((it) => it.path)) : new Set();
    // For live preview we temporarily paint without mutating clipboard/anchor permanently until mouseup
    visibleFinderRows().forEach((row) => {
      const r = row.getBoundingClientRect();
      const hit =
        r.left < screen.right && r.right > screen.left && r.top < screen.bottom && r.bottom > screen.top;
      const path = row.dataset.path || finderJoin(state.finderPath, row.dataset.name);
      row.classList.toggle("selected", hit || base.has(path));
    });
  };
  const onUp = () => endFinderMarquee(true);
  stateM.onMove = onMove;
  stateM.onUp = onUp;
  state.finderMarquee = stateM;
  window.addEventListener("mousemove", onMove);
  window.addEventListener("mouseup", onUp);
}

async function runFinderDeepSearch() {
  const input = $("#finder-search");
  const query = (input?.value || "").trim();
  if (query.length < 2) {
    toast("Tape au moins 2 caractères");
    return;
  }
  if (state.finderBusy) return toast("Action déjà en cours…");
  const clearBtn = $("#finder-search-clear");
  if (clearBtn) clearBtn.hidden = false;
  try {
    await withFinderProgress(`Recherche « ${query} »…`, async () => {
      const data = await api(
        `/api/fs/search?host=${encodeURIComponent(host())}&path=${encodeURIComponent(state.finderPath)}&q=${encodeURIComponent(query)}&depth=6&limit=200`
      );
      paintFinderList(data.items || [], {
        search: true,
        query,
        truncated: !!data.truncated,
      });
      toast(`${data.count || 0} résultat(s)`);
      return data;
    });
  } catch (err) {
    toast(err.message);
  }
}

function onFinderSearchInput() {
  const input = $("#finder-search");
  const query = (input?.value || "").trim();
  const clearBtn = $("#finder-search-clear");
  if (clearBtn) clearBtn.hidden = !query;
  clearTimeout(state.finderSearchTimer);
  state.finderSearchMode = false;
  state.finderSearchTimer = setTimeout(() => {
    paintFinderList(filterFinderItems(state.finderItems, query), { search: false, query });
    const status = $("#finder-status-text");
    if (status && query) {
      const n = filterFinderItems(state.finderItems, query).length;
      status.textContent = `${n} dans ce dossier · Entrée ou « Sous-dossiers » pour chercher plus loin`;
    } else {
      updateFinderActions();
    }
  }, 120);
}

async function finderNewFolder() {
  if (!state.finderWritable) return toast("Écriture bloquée ici (dossiers système)");
  if (state.finderBusy) return toast("Action déjà en cours…");
  const name = prompt("Nom du nouveau dossier", "Nouveau dossier");
  if (!name) return;
  try {
    await withFinderProgress("Création du dossier…", async () => {
      await api("/api/fs/mkdir", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ host: host(), path: state.finderPath, name }),
      });
      toast("Dossier créé");
      await loadFinder(state.finderPath);
    });
  } catch (err) {
    toast(err.message);
  }
}

async function finderRename() {
  const sel = selectedFinderItems();
  if (sel.length !== 1 || !state.finderWritable) return;
  if (state.finderBusy) return toast("Action déjà en cours…");
  const item = sel[0];
  const name = prompt("Nouveau nom", item.name);
  if (!name || name === item.name) return;
  try {
    await withFinderProgress("Renommage…", async () => {
      await api("/api/fs/rename", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ host: host(), src: item.path, name }),
      });
      toast("Renommé");
      await loadFinder(state.finderPath);
    });
  } catch (err) {
    toast(err.message);
  }
}

function finderCut() {
  const sel = selectedFinderItems();
  if (!sel.length || !state.finderWritable) return;
  state.finderClipboard = { mode: "cut", items: sel.map((it) => ({ ...it })), name: sel[0].name, path: sel[0].path };
  toast(sel.length === 1 ? `Couper: ${sel[0].name}` : `Couper: ${sel.length} éléments`);
  updateFinderActions();
}

function finderCopy() {
  const sel = selectedFinderItems();
  if (!sel.length || !state.finderWritable) return;
  state.finderClipboard = { mode: "copy", items: sel.map((it) => ({ ...it })), name: sel[0].name, path: sel[0].path };
  toast(sel.length === 1 ? `Copié: ${sel[0].name}` : `Copié: ${sel.length} éléments`);
  updateFinderActions();
}

async function finderPaste() {
  const clip = state.finderClipboard;
  const items = clip?.items?.length ? clip.items : clip?.path ? [clip] : [];
  if (!items.length || !state.finderWritable) return;
  if (state.finderBusy) return toast("Action déjà en cours…");
  try {
    await withFinderProgress(clip.mode === "cut" ? "Déplacement…" : "Copie…", async (p) => {
      if (clip.mode === "cut") {
        const { moved, mode } = await moveFinderItems(items, state.finderPath, { onProgress: p.update });
        state.finderClipboard = null;
        if (!moved) return;
        toast(
          moved === 1
            ? mode === "copy_delete"
              ? "Déplacé ici (via copie)"
              : "Déplacé ici"
            : `${moved} éléments déplacés ici`
        );
      } else {
        let copied = 0;
        for (const item of items) {
          p.update(copied, items.length, item.name);
          await api("/api/fs/copy", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              host: host(),
              src: item.path,
              dst_dir: state.finderPath,
              is_dir: item.type === "dir",
            }),
          });
          copied += 1;
          p.update(copied, items.length, item.name);
        }
        toast(copied === 1 ? "Copié ici" : `${copied} éléments copiés ici`);
      }
      p.label("Actualisation…");
      await loadFinder(state.finderPath);
    }, { total: items.length });
  } catch (err) {
    toast(err.message);
  }
}

async function finderMoveTo() {
  const sel = selectedFinderItems();
  if (!sel.length || !state.finderWritable) return;
  if (state.finderBusy) return toast("Action déjà en cours…");
  const dst = prompt(
    sel.length === 1
      ? "Déplacer vers quel dossier ?\nEx: /user/app · /data/homebrew · /mnt/usb0"
      : `Déplacer ${sel.length} éléments vers quel dossier ?`,
    state.finderPath
  );
  if (!dst) return;
  try {
    await withFinderProgress(`Déplacement → ${dst}`, async (p) => {
      const { moved, mode } = await moveFinderItems(sel, dst, { onProgress: p.update });
      if (!moved) return;
      toast(
        moved === 1
          ? mode === "copy_delete"
            ? `Déplacé (copie) → ${dst}`
            : `Déplacé → ${dst}`
          : `${moved} éléments → ${dst}`
      );
      clearFinderSelection();
      await loadFinder(state.finderPath);
    }, { total: sel.length });
  } catch (err) {
    toast(err.message);
  }
}

async function finderDelete() {
  const sel = selectedFinderItems();
  if (!sel.length || !state.finderWritable) return;
  if (state.finderBusy) return toast("Action déjà en cours…");
  const msg =
    sel.length === 1
      ? sel[0].type === "dir"
        ? `Supprimer le dossier « ${sel[0].name} » et tout son contenu ?`
        : `Supprimer « ${sel[0].name} » ?`
      : `Supprimer ${sel.length} éléments ?`;
  if (!confirm(msg)) return;
  try {
    await withFinderProgress("Suppression…", async (p) => {
      let deleted = 0;
      for (const item of sel) {
        p.update(deleted, sel.length, item.name);
        await api("/api/fs/delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ host: host(), path: item.path, is_dir: item.type === "dir" }),
        });
        deleted += 1;
        p.update(deleted, sel.length, item.name);
      }
      toast(deleted === 1 ? "Supprimé" : `${deleted} éléments supprimés`);
      clearFinderSelection();
      await loadFinder(state.finderPath);
    }, { total: sel.length });
  } catch (err) {
    toast(err.message);
  }
}

function moveFinderSelection(delta) {
  const rows = visibleFinderRows();
  if (!rows.length) return;
  const cur = selectedFinderItem();
  let idx = cur ? rowIndexForPath(cur.path) : -1;
  if (idx < 0) idx = delta > 0 ? -1 : 0;
  idx = Math.max(0, Math.min(rows.length - 1, idx + delta));
  const item = itemFromRow(rows[idx]);
  setFinderSelection([item], { anchorIdx: idx });
  rows[idx].scrollIntoView({ block: "nearest" });
}

$("#finder-back")?.addEventListener("click", async () => {
  if (state.finderHistIdx > 0) {
    state.finderHistIdx -= 1;
    await loadFinder(state.finderHistory[state.finderHistIdx]).catch((e) => toast(e.message));
    updateFinderActions();
    return;
  }
  navigateFinder(state.finderParent || "/").catch((e) => toast(e.message));
});
$("#finder-forward")?.addEventListener("click", async () => {
  if (state.finderHistIdx >= state.finderHistory.length - 1) return;
  state.finderHistIdx += 1;
  await loadFinder(state.finderHistory[state.finderHistIdx]).catch((e) => toast(e.message));
  updateFinderActions();
});
$("#finder-refresh")?.addEventListener("click", () => {
  clearFinderSearchUI(true);
  loadFinder(state.finderPath).catch((e) => toast(e.message));
});
$("#finder-search")?.addEventListener("input", () => onFinderSearchInput());
$("#finder-search")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    runFinderDeepSearch().catch((err) => toast(err.message));
  }
  if (e.key === "Escape") {
    clearFinderSearchUI(true);
    paintFinderList(state.finderItems, { search: false });
    updateFinderActions();
  }
});
$("#finder-search-deep")?.addEventListener("click", () =>
  runFinderDeepSearch().catch((e) => toast(e.message))
);
$("#finder-search-clear")?.addEventListener("click", () => {
  clearFinderSearchUI(true);
  paintFinderList(state.finderItems, { search: false });
  updateFinderActions();
  $("#finder-search")?.focus();
});
$("#finder-new-folder")?.addEventListener("click", () => finderNewFolder());
$("#finder-rename")?.addEventListener("click", () => finderRename());
$("#finder-cut")?.addEventListener("click", () => finderCut());
$("#finder-copy")?.addEventListener("click", () => finderCopy());
$("#finder-paste")?.addEventListener("click", () => finderPaste());
$("#finder-move-to")?.addEventListener("click", () => finderMoveTo());
$("#finder-delete")?.addEventListener("click", () => finderDelete());

$$(".fav").forEach((btn) => {
  btn.addEventListener("click", () => navigateFinder(btn.dataset.path).catch((e) => toast(e.message)));
  btn.addEventListener("dragover", (e) => {
    const p = btn.dataset.path || "";
    const dropOk =
      btn.classList.contains("write") ||
      p.startsWith("/data") ||
      p.startsWith("/user") ||
      p.startsWith("/mnt") ||
      p.startsWith("/usb") ||
      p.startsWith("/homebrew");
    if (!dropOk) return;
    e.preventDefault();
    const hasExternal = [...(e.dataTransfer?.types || [])].includes("Files");
    if (e.dataTransfer) e.dataTransfer.dropEffect = hasExternal && !state.finderDragActive ? "copy" : "move";
    btn.classList.add("drop-target");
  });
  btn.addEventListener("dragleave", () => btn.classList.remove("drop-target"));
  btn.addEventListener("drop", async (e) => {
    btn.classList.remove("drop-target");
    e.preventDefault();
    if (state.finderBusy) return toast("Action déjà en cours…");
    const dstDir = btn.dataset.path;
    try {
      const items = parseFinderDragPayload(e.dataTransfer.getData("application/x-pshd-item"));
      if (items.length) {
        await withFinderProgress(`Déplacement → ${dstDir}`, async (p) => {
          const { moved, mode } = await moveFinderItems(items, dstDir, { onProgress: p.update });
          if (!moved) return;
          toast(
            moved === 1
              ? mode === "copy_delete"
                ? `Déplacé (copie) → ${dstDir}`
                : `Déplacé → ${dstDir}`
              : `${moved} éléments → ${dstDir}`
          );
          await loadFinder(state.finderPath);
        }, { total: items.length });
        return;
      }
      if ([...(e.dataTransfer?.types || [])].includes("Files") || e.dataTransfer?.files?.length) {
        await uploadExternalDropToFinder(e.dataTransfer, dstDir);
      }
    } catch (err) {
      toast(err.message);
    }
  });
});

$("#finder-list")?.addEventListener("mousedown", (e) => {
  if (e.target.closest(".finder-row:not(.empty)")) return;
  startFinderMarquee(e);
});

$("#finder-list")?.addEventListener("contextmenu", (e) => {
  if (e.target.closest(".finder-row:not(.empty)")) return;
  e.preventDefault();
  clearFinderSelection();
  showFinderMenu(e.clientX, e.clientY);
});

$("#finder-menu")?.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn || btn.disabled) return;
  const act = btn.dataset.act;
  hideFinderMenu();
  const one = selectedFinderItem();
  if (act === "open" && one?.type === "dir" && selectedFinderItems().length === 1) {
    navigateFinder(one.path).catch((err) => toast(err.message));
  }
  if (act === "new") finderNewFolder();
  if (act === "cut") finderCut();
  if (act === "copy") finderCopy();
  if (act === "paste") finderPaste();
  if (act === "move") finderMoveTo();
  if (act === "rename") finderRename();
  if (act === "delete") finderDelete();
});

document.addEventListener("click", (e) => {
  if (!e.target.closest("#finder-menu")) hideFinderMenu();
});

document.addEventListener("keydown", (e) => {
  if (!$("#panel-files")?.classList.contains("active")) return;
  if (e.target.matches("input, textarea")) return;
  const meta = e.metaKey || e.ctrlKey;
  const key = e.key.toLowerCase();
  if (meta && key === "a") {
    e.preventDefault();
    selectAllFinder();
  } else if (meta && key === "n") {
    e.preventDefault();
    finderNewFolder();
  } else if (meta && key === "x") {
    e.preventDefault();
    finderCut();
  } else if (meta && key === "c") {
    e.preventDefault();
    finderCopy();
  } else if (meta && key === "v") {
    e.preventDefault();
    finderPaste();
  } else if ((e.key === "Delete" || e.key === "Backspace") && (meta || e.key === "Delete")) {
    e.preventDefault();
    finderDelete();
  } else if (e.key === "Escape") {
    e.preventDefault();
    hideFinderMenu();
    clearFinderSelection();
  } else if (meta && e.key === "ArrowDown" && selectedFinderItem()?.type === "dir") {
    e.preventDefault();
    navigateFinder(selectedFinderItem().path).catch((err) => toast(err.message));
  } else if (e.key === "ArrowDown") {
    e.preventDefault();
    if (e.shiftKey && state.finderAnchorIdx >= 0) {
      const cur = selectedFinderItem();
      const idx = cur ? rowIndexForPath(cur.path) : state.finderAnchorIdx;
      selectFinderRange(state.finderAnchorIdx, Math.min(visibleFinderRows().length - 1, idx + 1));
    } else moveFinderSelection(1);
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    if (e.shiftKey && state.finderAnchorIdx >= 0) {
      const cur = selectedFinderItem();
      const idx = cur ? rowIndexForPath(cur.path) : state.finderAnchorIdx;
      selectFinderRange(state.finderAnchorIdx, Math.max(0, idx - 1));
    } else moveFinderSelection(-1);
  } else if (e.key === "Enter" && selectedFinderItem()?.type === "dir" && selectedFinderItems().length === 1) {
    e.preventDefault();
    navigateFinder(selectedFinderItem().path).catch((err) => toast(err.message));
  } else if (e.key === "F2") {
    e.preventDefault();
    finderRename();
  }
});

// drop onto current folder background (console move OR Mac Finder upload)
["dragenter", "dragover", "dragleave", "drop"].forEach((evt) => {
  $("#finder-drop-zone")?.addEventListener(evt, async (e) => {
    const zone = $("#finder-drop-zone");
    if (!zone) return;
    const types = [...(e.dataTransfer?.types || [])];
    const hasExternal = types.includes("Files");
    const hasInternal = types.includes("application/x-pshd-item") || types.includes("text/plain");
    if (evt === "dragenter" || evt === "dragover") {
      if (!state.finderWritable) return;
      if (!hasExternal && !hasInternal && !state.finderDragActive) return;
      e.preventDefault();
      e.stopPropagation();
      e.dataTransfer.dropEffect = hasExternal && !state.finderDragActive ? "copy" : "move";
      zone.classList.add("drop-target");
      zone.classList.toggle("drop-external", hasExternal && !state.finderDragActive);
      return;
    }
    if (evt === "dragleave") {
      if (e.relatedTarget && zone.contains(e.relatedTarget)) return;
      zone.classList.remove("drop-target", "drop-external");
      return;
    }
    zone.classList.remove("drop-target", "drop-external");
    if (!state.finderWritable) return;
    e.preventDefault();
    e.stopPropagation();
    if (e.target.closest(".finder-row[data-type='dir']")) return;
    if (state.finderBusy) return toast("Action déjà en cours…");
    try {
      const items = parseFinderDragPayload(e.dataTransfer.getData("application/x-pshd-item"));
      if (items.length) {
        await withFinderProgress("Déplacement…", async (p) => {
          const { moved, mode } = await moveFinderItems(items, state.finderPath, { onProgress: p.update });
          if (!moved) return;
          toast(
            moved === 1
              ? mode === "copy_delete"
                ? "Déplacé ici (via copie)"
                : "Déplacé ici"
              : `${moved} éléments déplacés ici`
          );
          await loadFinder(state.finderPath);
        }, { total: items.length });
        return;
      }
      if (hasExternal || e.dataTransfer?.files?.length) {
        await uploadExternalDropToFinder(e.dataTransfer, state.finderPath);
      }
    } catch (err) {
      toast(err.message);
    }
  });
});

$("#nav-burger")?.addEventListener("click", () => {
  document.body.classList.toggle("nav-open");
});
$$(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => document.body.classList.remove("nav-open"));
});
$("#copy-lan-url")?.addEventListener("click", async () => {
  const url = $("#desk-lan-url")?.textContent?.trim();
  if (!url || url === "—") return toast("URL indisponible");
  try {
    await navigator.clipboard.writeText(url);
    toast("URL LAN copiée");
  } catch {
    toast(url);
  }
});
$("#refresh-desk-info")?.addEventListener("click", () => refreshDeskInfo().catch((e) => toast(e.message)));
$("#save-desk-token")?.addEventListener("click", () => {
  const v = ($("#desk-token-input")?.value || "").trim();
  if (v) localStorage.setItem("pshd-token", v);
  else localStorage.removeItem("pshd-token");
  syncTokenField();
  toast(v ? "Token enregistré" : "Token effacé");
  refreshDeskInfo().catch(() => {});
});
$("#clear-desk-token")?.addEventListener("click", () => {
  localStorage.removeItem("pshd-token");
  if ($("#desk-token-input")) $("#desk-token-input").value = "";
  syncTokenField();
  toast("Token effacé");
});
$("#toggle-desk-token")?.addEventListener("click", () => {
  const input = $("#desk-token-input");
  const btn = $("#toggle-desk-token");
  if (!input) return;
  const show = input.type === "password";
  input.type = show ? "text" : "password";
  if (btn) btn.textContent = show ? "Masquer" : "Afficher";
});
$("#hen-auto-send")?.addEventListener("change", () => {
  if ($("#hen-auto-send").checked) localStorage.setItem("pshd-auto-hen", "1");
  else localStorage.removeItem("pshd-auto-hen");
  state.autoHenSent = false;
  syncHenAutoUi(state.relapse?.payloads || []);
  toast($("#hen-auto-send").checked ? "Auto-HEN activé" : "Auto-HEN désactivé");
});
$("#hen-auto-file")?.addEventListener("change", () => {
  const v = ($("#hen-auto-file")?.value || "").trim();
  if (v) localStorage.setItem("pshd-auto-hen-file", v);
  else localStorage.removeItem("pshd-auto-hen-file");
  state.autoHenSent = false;
  syncHenAutoUi(state.relapse?.payloads || []);
});
$("#publish-update-btn")?.addEventListener("click", async () => {
  const notes = prompt("Notes de version (optionnel)", "") ?? "";
  try {
    const data = await api("/api/desk/publish-update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notes }),
    });
    toast(`Update v${data.manifest?.version || "?"} publiée`);
    await refreshDeskInfo();
  } catch (err) {
    toast(err.message);
  }
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

syncTokenField();
syncHenAutoUi([]);
refreshDeskInfo().catch(() => {});
refreshCatalog().catch(() => {});
refreshRelapse().catch(() => {});
ensureAutoHenPolling();
