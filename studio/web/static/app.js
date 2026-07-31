// Canal Meteo Studio — frontend vanilla.
// Flujo: POST /api/jobs → PUT prefirmado directo a Spaces → confirm → polling.

const $ = (id) => document.getElementById(id);
let pollTimer = null;

function operations() {
  const ops = {};
  document.querySelectorAll("input[data-op]").forEach((el) => {
    ops[el.dataset.op] = el.checked;
  });
  return ops;
}

async function api(path, opts = {}) {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json();
}

// PUT directo a Spaces con barra de progreso (XHR para tener onprogress).
// Enviamos un blob SIN tipo (slice con contentType "") para que el navegador
// no añada la cabecera Content-Type → el preflight no la pide → no depende del
// campo "Allowed Headers" del CORS del bucket. slice() no copia los bytes.
function uploadToSpaces(url, file) {
  return new Promise((resolve, reject) => {
    const body = file.slice(0, file.size, "");
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        const pct = Math.round((e.loaded / e.total) * 100);
        $("upfill").style.width = pct + "%";
        $("upmsg").textContent = `Subiendo… ${pct}%`;
      }
    };
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new Error("PUT " + xhr.status)));
    xhr.onerror = () => reject(new Error("error de red en la subida (¿CORS del bucket?)"));
    xhr.send(body);
  });
}

async function start() {
  const file = $("file").files[0];
  if (!file) return alert("Elige un vídeo primero.");
  $("go").disabled = true;
  $("upbar").classList.remove("hidden");
  $("upmsg").textContent = "Creando job…";

  try {
    const job = await api("/api/jobs", {
      method: "POST",
      body: JSON.stringify({
        filename: file.name,
        content_type: file.type || "video/mp4",
        script_text: $("script").value,
        language: "es",
        operations: operations(),
      }),
    });

    await uploadToSpaces(job.upload_url, file);
    $("upmsg").textContent = "Subida completa, registrando…";
    await api(`/api/jobs/${job.job_id}/confirm`, { method: "POST" });

    $("upmsg").textContent = "Job en cola ✓";
    watch(job.job_id);
    refreshJobs();
  } catch (e) {
    $("upmsg").textContent = "Error: " + e.message;
  } finally {
    $("go").disabled = false;
  }
}

function watch(jobId) {
  $("status").classList.remove("hidden");
  $("st-id").textContent = jobId;
  clearInterval(pollTimer);
  const tick = async () => {
    try {
      const { status } = await api(`/api/jobs/${jobId}`);
      $("st-fill").style.width = (status.progress || 0) + "%";
      $("st-msg").textContent = `${status.state} — ${status.message || ""}`;
      renderOutputs(status.outputs || []);
      if (status.state === "done" || status.state === "error") {
        clearInterval(pollTimer);
        refreshJobs();
      }
    } catch (e) {
      $("st-msg").textContent = "Error consultando estado: " + e.message;
    }
  };
  tick();
  pollTimer = setInterval(tick, 3000);
}

function renderOutputs(outputs) {
  const box = $("st-outputs");
  if (!outputs.length) {
    box.innerHTML = "";
    return;
  }
  box.innerHTML = outputs
    .map(
      (o) => `
    <div class="bg-slate-900 rounded p-3">
      <div class="flex items-center justify-between mb-2">
        <span class="font-medium">${o.label}${o.width ? ` · ${o.width}×${o.height}` : ""}</span>
        <a href="${o.url}" download class="text-sky-400 hover:underline text-sm">Descargar</a>
      </div>
      <video src="${o.url}" controls class="w-full rounded max-h-72"></video>
    </div>`
    )
    .join("");
}

async function refreshJobs() {
  try {
    const { jobs } = await api("/api/jobs");
    $("jobs").innerHTML = jobs
      .map(
        (j) => `
      <button class="w-full text-left flex items-center gap-3 px-3 py-1.5 rounded hover:bg-slate-800" data-id="${j.job_id}">
        <span class="font-mono text-slate-400">${j.job_id}</span>
        <span class="truncate flex-1">${j.filename}</span>
        <span class="text-xs px-2 py-0.5 rounded bg-slate-700">${j.state}</span>
      </button>`
      )
      .join("");
    $("jobs").querySelectorAll("button[data-id]").forEach((b) => {
      b.onclick = () => watch(b.dataset.id);
    });
  } catch (_) {}
}

$("go").onclick = start;
refreshJobs();
