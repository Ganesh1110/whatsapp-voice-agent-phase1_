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
    ["stt", "tts", "voice"].forEach((name) => {
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

// ---------- Voice Assistant (STT -> Ollama -> TTS) ----------
let voiceMediaRecorder = null;
let voiceMicStream = null;
let voiceRecordedBlob = null;
let voiceRecordingUrl = null;

function clearVoiceRecording() {
  voiceRecordedBlob = null;
  hide($("voiceRecordingPreview"));
  if (voiceRecordingUrl) URL.revokeObjectURL(voiceRecordingUrl);
  voiceRecordingUrl = null;
}

$("voiceFile").addEventListener("change", clearVoiceRecording);

$("voiceRecordBtn").addEventListener("click", async () => {
  hide($("voiceError"));
  clearVoiceRecording();
  $("voiceFile").value = "";

  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
    $("voiceError").textContent = "Audio recording is not supported in this browser. Try Chrome, Edge, Firefox, or Safari.";
    show($("voiceError"));
    return;
  }

  try {
    voiceMicStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mimeType = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"]
      .find((type) => MediaRecorder.isTypeSupported(type));
    voiceMediaRecorder = mimeType ? new MediaRecorder(voiceMicStream, { mimeType }) : new MediaRecorder(voiceMicStream);
    const chunks = [];
    voiceMediaRecorder.addEventListener("dataavailable", (event) => {
      if (event.data.size) chunks.push(event.data);
    });
    voiceMediaRecorder.addEventListener("stop", () => {
      const type = voiceMediaRecorder.mimeType || "audio/webm";
      voiceRecordedBlob = new Blob(chunks, { type });
      const extension = type.includes("ogg") ? "ogg" : type.includes("mp4") ? "mp4" : "webm";
      voiceRecordedBlob.fileName = `recording.${extension}`;
      voiceRecordingUrl = URL.createObjectURL(voiceRecordedBlob);
      $("voiceRecordingPreview").src = voiceRecordingUrl;
      show($("voiceRecordingPreview"));
      hide($("voiceRecordingStatus"));
      show($("voiceRecordBtn"));
      hide($("voiceStopRecordBtn"));
      voiceMicStream?.getTracks().forEach((track) => track.stop());
      voiceMicStream = null;
      $("voiceBtn").disabled = false;
    }, { once: true });
    voiceMediaRecorder.start();
    hide($("voiceRecordBtn"));
    show($("voiceStopRecordBtn"));
    show($("voiceRecordingStatus"));
    $("voiceBtn").disabled = true;
  } catch (err) {
    voiceMicStream?.getTracks().forEach((track) => track.stop());
    voiceMicStream = null;
    $("voiceError").textContent = err.name === "NotAllowedError"
      ? "Microphone permission was denied. Allow microphone access and try again."
      : `Could not start recording: ${err.message}`;
    show($("voiceError"));
  }
});

$("voiceStopRecordBtn").addEventListener("click", () => {
  if (voiceMediaRecorder?.state === "recording") voiceMediaRecorder.stop();
});

$("voiceBtn").addEventListener("click", async () => {
  const file = $("voiceFile").files[0] || (voiceRecordedBlob && new File([voiceRecordedBlob], voiceRecordedBlob.fileName, { type: voiceRecordedBlob.type }));
  hide($("voiceError"));
  hide($("voiceResult"));

  if (!file) {
    $("voiceError").textContent = "Choose an audio file or record your voice first.";
    show($("voiceError"));
    return;
  }

  const form = new FormData();
  form.append("file", file);
  form.append("stt_model", $("voiceSttModel").value);
  form.append("llm_model", $("voiceLlmModel").value);
  form.append("tts_model", $("voiceTtsModel").value);
  const system = $("voiceSystem").value.trim();
  if (system) form.append("system", system);

  setBusy($("voiceBtn"), $("voiceLoading"), true);
  try {
    const res = await fetch(`${API_BASE}/voice`, { method: "POST", body: form });
    if (!res.ok) throw new Error(await errorMessage(res));

    const blob = await res.blob();
    if (lastAudioUrl) URL.revokeObjectURL(lastAudioUrl);
    lastAudioUrl = URL.createObjectURL(blob);

    $("voiceText").value = res.headers.get("X-Stt-Text") || "";
    $("voiceReply").value = res.headers.get("X-Llm-Reply") || "";
    $("voiceAudio").src = lastAudioUrl;
    $("voiceDownload").href = lastAudioUrl;
    show($("voiceResult"));
    $("voiceAudio").play().catch(() => {});
  } catch (err) {
    $("voiceError").textContent = err instanceof TypeError ? networkMessage() : err.message;
    show($("voiceError"));
  } finally {
    setBusy($("voiceBtn"), $("voiceLoading"), false);
  }
});

// ---------- Start Call: record → STT → LLM → TTS → play back ----------
let callMediaRecorder = null;
let callMicStream = null;
let callRecordedBlob = null;
let callRecordingUrl = null;
let callIsRecording = false;

function clearCallRecording() {
  callRecordedBlob = null;
  const preview = $("callRecordingPreview");
  if (preview) hide(preview);
  if (callRecordingUrl) URL.revokeObjectURL(callRecordingUrl);
  callRecordingUrl = null;
}

function setCallBusy(busy) {
  $("callBtn").disabled = busy;
  $("callStopBtn").disabled = busy;
  busy ? show($("callLoading")) : hide($("callLoading"));
}

$("callBtn").addEventListener("click", async () => {
  if (callIsRecording) {
    // Already recording: stop and respond.
    if (callMediaRecorder?.state === "recording") callMediaRecorder.stop();
    return;
  }

  hide($("callError"));
  hide($("callResult"));
  clearCallRecording();
  $("callAudio").src = "";
  $("callText").value = "";
  $("callReply").value = "";

  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
    $("callError").textContent = "Audio recording is not supported in this browser. Use Chrome, Edge, Firefox, or Safari.";
    show($("callError"));
    return;
  }

  try {
    callMicStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mimeType = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"]
      .find((type) => MediaRecorder.isTypeSupported(type));
    callMediaRecorder = mimeType ? new MediaRecorder(callMicStream, { mimeType }) : new MediaRecorder(callMicStream);
    const chunks = [];
    callMediaRecorder.addEventListener("dataavailable", (event) => {
      if (event.data.size) chunks.push(event.data);
    });
    callMediaRecorder.addEventListener("stop", async () => {
      const type = callMediaRecorder.mimeType || "audio/webm";
      callRecordedBlob = new Blob(chunks, { type });
      const extension = type.includes("ogg") ? "ogg" : type.includes("mp4") ? "mp4" : "webm";
      callRecordedBlob.fileName = `call.${extension}`;
      callRecordingUrl = URL.createObjectURL(callRecordedBlob);

      callIsRecording = false;
      $("callBtn").textContent = "▶ Start Call";
      $("callBtn").classList.remove("recording");
      hide($("callStopBtn"));
      show($("callBtn"));
      callMicStream?.getTracks().forEach((track) => track.stop());
      callMicStream = null;
      callMediaRecorder = null;

      await sendCallAudio();
    }, { once: true });
    callMediaRecorder.start();
    callIsRecording = true;
    hide($("callBtn"));
    show($("callStopBtn"));
    $("callStopBtn").classList.add("call-stop");
    $("callStatus").textContent = "● Recording… speak now";
    $("callStatus").className = "status down";
  } catch (err) {
    callMicStream?.getTracks().forEach((track) => track.stop());
    callMicStream = null;
    callIsRecording = false;
    $("callError").textContent = err.name === "NotAllowedError"
      ? "Microphone permission was denied. Allow microphone access and try again."
      : `Could not start recording: ${err.message}`;
    show($("callError"));
  }
});

$("callStopBtn").addEventListener("click", () => {
  if (callMediaRecorder?.state === "recording") callMediaRecorder.stop();
});

async function sendCallAudio() {
  const file = callRecordedBlob && new File([callRecordedBlob], callRecordedBlob.fileName, { type: callRecordedBlob.type });
  hide($("callError"));
  hide($("callResult"));

  if (!file) {
    $("callError").textContent = "No audio was recorded. Try again.";
    show($("callError"));
    $("callStatus").textContent = "";
    return;
  }

  const form = new FormData();
  form.append("file", file);
  // Rely on backend defaults (whisper → remote gemma → indic-parler-tts) set in .env.
  // Uncomment to override per-call:
  // form.append("stt_model", "whisper");
  // form.append("llm_model", "remote");
  // form.append("tts_model", "indic-parler-tts");

  setCallBusy(true);
  $("callStatus").textContent = "● Processing…";
  try {
    const res = await fetch(`${API_BASE}/voice`, { method: "POST", body: form });
    if (!res.ok) throw new Error(await errorMessage(res));

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    $("callAudio").src = url;
    $("callDownload").href = url;
    $("callText").value = res.headers.get("X-Stt-Text") || "(no speech recognised)";
    $("callReply").value = res.headers.get("X-Llm-Reply") || "";
    show($("callResult"));
    $("callAudio").play().catch(() => {}); // autoplay may be blocked; controls still work
    $("callStatus").textContent = "● AI responded — audio playing above";
    $("callStatus").className = "status ok";
  } catch (err) {
    $("callError").textContent = err instanceof TypeError ? networkMessage() : err.message;
    show($("callError"));
    $("callStatus").textContent = "";
  } finally {
    setCallBusy(false);
    clearCallRecording();
  }
}

checkHealth();
