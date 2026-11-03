// Frontend logic for the Voice App. Talks to the FastAPI backend.

// When served by FastAPI (http://localhost:8000) use the same origin.
// If index.html is opened straight from disk or another server, fall back to localhost:8000.
// You can also override it by setting window.API_BASE before this script loads.
const API_BASE =
  window.API_BASE ??
  (location.protocol === "file:" || location.port !== "8000" ? "http://localhost:8000" : "");

const $ = (id) => document.getElementById(id);

// ---------- Helpers ----------
function show(el) { el.classList.remove("hidden"); }
function hide(el) { el.classList.add("hidden"); }

function setBusy(button, loadingEl, busy) {
  button.disabled = busy;
  busy ? show(loadingEl) : hide(loadingEl);
}

// Turn any failed response into a readable message.
async function errorMessage(response) {
  try {
    const body = await response.json();
    return [body.error, body.detail].filter(Boolean).join(": ") || `Request failed (${response.status})`;
  } catch {
    return `Request failed (${response.status})`;
  }
}

function networkMessage() {
  return `Could not reach the server at ${API_BASE || location.origin}. Is the backend running?`;
}

// ---------- Tabs ----------
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => {
      t.classList.toggle("active", t === tab);
      t.setAttribute("aria-selected", t === tab);
    });
    ["stt", "tts"].forEach((name) => {
      name === tab.dataset.tab ? show($(`tab-${name}`)) : hide($(`tab-${name}`));
    });
  });
});

// ---------- Server status ----------
async function checkHealth() {
  const el = $("serverStatus");
  try {
    const res = await fetch(`${API_BASE}/health`);
    if (!res.ok) throw new Error();
    el.textContent = "● Server online";
    el.className = "status ok";
  } catch {
    el.textContent = "● Server offline";
    el.className = "status down";
  }
}

// ---------- Speech to Text ----------
let mediaRecorder = null;
let microphoneStream = null;
let recordedBlob = null;
let recordingUrl = null;

function clearRecording() {
  recordedBlob = null;
  hide($("recordingPreview"));
  if (recordingUrl) URL.revokeObjectURL(recordingUrl);
  recordingUrl = null;
}

$("sttFile").addEventListener("change", clearRecording);

$("recordBtn").addEventListener("click", async () => {
  hide($("sttError"));
  clearRecording();
  $("sttFile").value = "";

  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
    $("sttError").textContent = "Audio recording is not supported in this browser. Try a current version of Chrome, Edge, Firefox, or Safari.";
    show($("sttError"));
    return;
  }

  try {
    microphoneStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mimeType = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"]
      .find((type) => MediaRecorder.isTypeSupported(type));
    mediaRecorder = mimeType ? new MediaRecorder(microphoneStream, { mimeType }) : new MediaRecorder(microphoneStream);
    const chunks = [];
    mediaRecorder.addEventListener("dataavailable", (event) => {
      if (event.data.size) chunks.push(event.data);
    });
    mediaRecorder.addEventListener("stop", () => {
      const type = mediaRecorder.mimeType || "audio/webm";
      recordedBlob = new Blob(chunks, { type });
      const extension = type.includes("ogg") ? "ogg" : type.includes("mp4") ? "mp4" : "webm";
      recordedBlob.fileName = `recording.${extension}`;
      recordingUrl = URL.createObjectURL(recordedBlob);
      $("recordingPreview").src = recordingUrl;
      show($("recordingPreview"));
      hide($("recordingStatus"));
      show($("recordBtn"));
      hide($("stopRecordBtn"));
      microphoneStream?.getTracks().forEach((track) => track.stop());
      microphoneStream = null;
      $("sttBtn").disabled = false;
    }, { once: true });
    mediaRecorder.start();
    hide($("recordBtn"));
    show($("stopRecordBtn"));
    show($("recordingStatus"));
    $("sttBtn").disabled = true;
  } catch (err) {
    microphoneStream?.getTracks().forEach((track) => track.stop());
    microphoneStream = null;
    $("sttError").textContent = err.name === "NotAllowedError"
      ? "Microphone permission was denied. Allow microphone access and try again."
      : `Could not start recording: ${err.message}`;
    show($("sttError"));
  }
});

$("stopRecordBtn").addEventListener("click", () => {
  if (mediaRecorder?.state === "recording") mediaRecorder.stop();
});

$("sttBtn").addEventListener("click", async () => {
  const file = $("sttFile").files[0] || (recordedBlob && new File([recordedBlob], recordedBlob.fileName, { type: recordedBlob.type }));
  hide($("sttError"));
  hide($("sttResult"));

  if (!file) {
    $("sttError").textContent = "Choose an audio file or record your voice first.";
    show($("sttError"));
    return;
  }

  const form = new FormData();
  form.append("file", file);
  form.append("model", $("sttModel").value);

  setBusy($("sttBtn"), $("sttLoading"), true);
  try {
    const res = await fetch(`${API_BASE}/stt`, { method: "POST", body: form });
    if (!res.ok) throw new Error(await errorMessage(res));
    const data = await res.json();
    $("sttText").value = data.text || "(no speech recognised)";
    $("sttMeta").textContent = `Model: ${data.model} · ${data.processing_seconds}s`;
    show($("sttResult"));
  } catch (err) {
    $("sttError").textContent = err instanceof TypeError ? networkMessage() : err.message;
    show($("sttError"));
  } finally {
    setBusy($("sttBtn"), $("sttLoading"), false);
  }
});

// ---------- Text to Speech ----------
let lastAudioUrl = null;

$("ttsBtn").addEventListener("click", async () => {
  const text = $("ttsText").value.trim();
  hide($("ttsError"));
  hide($("ttsResult"));

  if (!text) {
    $("ttsError").textContent = "Please enter some Malayalam text.";
    show($("ttsError"));
    return;
  }

  setBusy($("ttsBtn"), $("ttsLoading"), true);
  try {
    const res = await fetch(`${API_BASE}/tts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, model: "mms" }),
    });
    if (!res.ok) throw new Error(await errorMessage(res));

    const blob = await res.blob();
    if (lastAudioUrl) URL.revokeObjectURL(lastAudioUrl); // free the previous audio
    lastAudioUrl = URL.createObjectURL(blob);

    $("ttsAudio").src = lastAudioUrl;
    $("ttsDownload").href = lastAudioUrl;
    show($("ttsResult"));
    $("ttsAudio").play().catch(() => {}); // autoplay may be blocked; the controls still work
  } catch (err) {
    $("ttsError").textContent = err instanceof TypeError ? networkMessage() : err.message;
    show($("ttsError"));
  } finally {
    setBusy($("ttsBtn"), $("ttsLoading"), false);
  }
});

checkHealth();
