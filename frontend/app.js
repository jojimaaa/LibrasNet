"use strict";

const $ = (id) => document.getElementById(id);

async function getJson(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`${url}: ${resp.status}`);
  return resp.json();
}

const fmt = (value, unit = "", digits = 1) =>
  value === null || value === undefined
    ? "—"
    : `${Number(value).toFixed(digits)}${unit}`;

async function refreshState() {
  try {
    const s = await getJson("/api/state");
    $("letra").textContent = s.letra_atual ?? "—";
    $("conf-fill").style.width = `${Math.round((s.confianca ?? 0) * 100)}%`;
    $("palavra").textContent = s.palavra_parcial || "…";
    $("ultima").textContent = s.ultima_palavra ?? "—";
    $("fps").textContent = fmt(s.fps, " fps");

    const badge = $("hand-badge");
    badge.textContent = s.mao_presente ? "mão detectada" : "sem mão";
    badge.classList.toggle("on", Boolean(s.mao_presente));

    const hist = $("historico");
    hist.innerHTML = "";
    (s.historico ?? [])
      .slice(-8)
      .reverse()
      .forEach((word) => {
        const li = document.createElement("li");
        li.textContent = word;
        hist.appendChild(li);
      });
  } catch (e) {
    /* servidor pode estar subindo; a próxima atualização tenta de novo */
  }
}

async function refreshMetrics() {
  try {
    const m = await getJson("/api/metrics");
    const p = m.pipeline || {};
    $("m-fps").textContent = fmt(p.fps);
    $("m-frames").textContent = fmt(p.quadros_processados, "", 0);

    const list = $("latencias");
    list.innerHTML = "";
    Object.entries(p.latencia_ms || {}).forEach(([stage, ms]) => {
      const li = document.createElement("li");
      li.textContent = `${stage}: ${fmt(ms, " ms", 2)}`;
      list.appendChild(li);
    });
  } catch (e) {
    /* idem */
  }
}

async function loadInfo() {
  try {
    const i = await getJson("/api/info");
    if (!i || Object.keys(i).length === 0) {
      $("machine-info").textContent = "processamento local · 100% offline";
      return;
    }
    $("machine-info").textContent =
      `${i.hostname ?? "?"} · ${i.sistema ?? "?"} · ${i.processador ?? "?"} · ` +
      `${i.nucleos_logicos ?? "?"} núcleos · Python ${i.python ?? "?"}`;
  } catch (e) {
    /* opcional */
  }
}

$("video").addEventListener("error", () => {
  $("video").hidden = true;
  $("video-placeholder").hidden = false;
});

loadInfo();
refreshState();
refreshMetrics();
setInterval(refreshState, 250);
setInterval(refreshMetrics, 1000);
