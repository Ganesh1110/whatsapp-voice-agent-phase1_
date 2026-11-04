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

// Text travels URL-encoded because HTTP headers cannot carry Malayalam directly.
function headerText(response, name) {
  const raw = response.headers.get(name);
  if (!raw) return "";
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
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

    $("voiceText").value = headerText(res, "X-Stt-Text") || "";
    $("voiceReply").value = headerText(res, "X-Llm-Reply") || "";
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

// ---------- Phone Call: AI greets first, then continuous listen → reply ----------
const CALL_GREETING = window.CALL_GREETING ?? "ഹലോ! നിങ്ങൾ ആരാണ്?";
const CALL_SILENCE_MS = 1200;      // stop a turn after this much silence
const CALL_MAX_TURN_MS = 15000;    // hard cap on one caller turn
const CALL_MIN_SPEECH_MS = 300;    // ignore blips shorter than this
const CALL_ENERGY_THRESHOLD = 0.02;
const CALL_SYSTEM =
  "You are a helpful voice assistant on a phone call. Reply in Malayalam with " +
  "one short sentence of about 15-20 words. English technical words are fine; " +
  "natural Malayalam-English mixing is allowed. Keep it natural for " +
  "text-to-speech. No markdown, no bullet points, no special characters.";

let callActive = false;
let callMicStream = null;
let callAudioCtx = null;
let callAnalyser = null;
let callAnalyserData = null;
let callRecorder = null;
let callChunks = [];
let callDiscardTurn = false;
let callVadFrame = null;
let callHeardSpeech = false;
let callSpeechStart = 0;
let callSilenceStart = 0;
let callAudioUrl = null;
let callAudioDone = null;
let callSession = 0;
let callHistory = [];
let callSuspended = false;
let callBusy = false;

function setCallStatus(text, cls = "") {
  $("callStatus").textContent = text;
  $("callStatus").className = `status ${cls}`.trim();
}

function callMimeType() {
  return ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"]
    .find((type) => MediaRecorder.isTypeSupported(type));
}

function recorderOptions() {
  const mimeType = callMimeType();
  return mimeType ? { mimeType } : undefined;
}

function playCallAudio(url) {
  return new Promise((resolve) => {
    const audio = $("callAudio");
    const done = () => {
      audio.removeEventListener("ended", done);
      audio.removeEventListener("error", done);
      if (callAudioDone === done) callAudioDone = null;
      resolve();
    };
    callAudioDone = done;
    audio.addEventListener("ended", done);
    audio.addEventListener("error", done);
    audio.src = url;
    audio.play().catch(() => {
      // Autoplay can be blocked; the controls remain usable.
      setCallStatus("Tap play on the audio player to hear the AI", "down");
      done();
    });
  });
}

async function synthesizeCallText(text) {
  const res = await fetch(`${API_BASE}/tts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return URL.createObjectURL(await res.blob());
}

function stopVad() {
  if (callVadFrame) cancelAnimationFrame(callVadFrame);
  callVadFrame = null;
}

function startVad() {
  if (!callAnalyser) return;
  const data = callAnalyserData;
  const tick = () => {
    if (!callActive || !callRecorder || callRecorder.state !== "recording") return;

    callAnalyser.getFloatTimeDomainData(data);
    let sum = 0;
    for (let i = 0; i < data.length; i += 1) sum += data[i] * data[i];
    const rms = Math.sqrt(sum / data.length);
    const now = performance.now();

    if (rms >= CALL_ENERGY_THRESHOLD) {
      if (!callHeardSpeech) {
        callHeardSpeech = true;
        callSpeechStart = now;
      }
      callSilenceStart = 0;
    } else if (callHeardSpeech) {
      if (!callSilenceStart) callSilenceStart = now;
      if (now - callSilenceStart >= CALL_SILENCE_MS) {
        if (callRecorder?.state === "recording") callRecorder.stop();
        return;
      }
    }

    const spokeLongEnough = callHeardSpeech && now - callSpeechStart >= CALL_MIN_SPEECH_MS;
    if (spokeLongEnough && now - callSpeechStart >= CALL_MAX_TURN_MS) {
      if (callRecorder?.state === "recording") callRecorder.stop();
      return;
    }

    callVadFrame = requestAnimationFrame(tick);
  };
  callVadFrame = requestAnimationFrame(tick);
}

function startListening() {
  if (!callActive || !callMicStream || callSuspended) return;
  if (callRecorder?.state === "recording") return;

  hide($("callError"));
  setCallStatus("● Listening… speak now", "ok");
  callDiscardTurn = false;
  callChunks = [];
  callHeardSpeech = false;
  callSpeechStart = 0;
  callSilenceStart = 0;
  const session = callSession;

  const recorder = new MediaRecorder(callMicStream, recorderOptions());
  callRecorder = recorder;
  recorder.addEventListener("dataavailable", (event) => {
    if (event.data.size) callChunks.push(event.data);
  });
  recorder.addEventListener("stop", async () => {
    stopVad();
    if (callRecorder === recorder) callRecorder = null;
    if (session !== callSession) return;

    const shouldSend = callActive && !callDiscardTurn && callHeardSpeech;
    callDiscardTurn = false;

    if (!shouldSend) {
      if (callActive && !callSuspended) startListening();
      return;
    }

    const type = recorder.mimeType || "audio/webm";
    const extension = type.includes("ogg") ? "ogg" : type.includes("mp4") ? "mp4" : "webm";
    const blob = new Blob(callChunks, { type });
    callChunks = [];
    await sendCallTurn(blob, `call.${extension}`);
  }, { once: true });

  recorder.start();
  startVad();
}

function callSystemPrompt() {
  if (!callHistory.length) return CALL_SYSTEM;
  const transcript = callHistory
    .slice(-6)
    .map((turn) => `Caller: ${turn.user}\nAssistant: ${turn.ai}`)
    .join("\n");
  return `${CALL_SYSTEM}\n\nConversation so far:\n${transcript}`;
}

async function sendCallTurn(blob, filename) {
  if (!callActive || callBusy) return;
  callBusy = true;
  const session = callSession;

  const form = new FormData();
  form.append("file", new File([blob], filename, { type: blob.type }));
  if (callHistory.length) form.append("system", callSystemPrompt());

  setCallStatus("● AI is thinking…");
  try {
    const res = await fetch(`${API_BASE}/voice`, { method: "POST", body: form });
    if (!res.ok) throw new Error(await errorMessage(res));
    if (!callActive || session !== callSession) return;

    const audioBlob = await res.blob();
    if (!callActive || session !== callSession) return;
    if (callAudioUrl) URL.revokeObjectURL(callAudioUrl);
    callAudioUrl = URL.createObjectURL(audioBlob);

    $("callText").value = headerText(res, "X-Stt-Text") || "(no speech recognised)";
    $("callReply").value = headerText(res, "X-Llm-Reply") || "";
    $("callDownload").href = callAudioUrl;
    show($("callResult"));

    if ($("callText").value && $("callReply").value) {
      callHistory.push({ user: $("callText").value, ai: $("callReply").value });
    }

    setCallStatus("● AI is speaking…", "ok");
    await playCallAudio(callAudioUrl);
    if (callActive && session === callSession) startListening();
  } catch (err) {
    if (!callActive || session !== callSession) return;
    $("callError").textContent = err instanceof TypeError ? networkMessage() : err.message;
    show($("callError"));
    setCallStatus("● Could not respond — listening again…", "down");
    setTimeout(() => { if (callActive && session === callSession) startListening(); }, 2000);
  } finally {
    callBusy = false;
  }
}

async function sendTypedTurn() {
  const text = $("callText").value.trim();
  if (!text || callBusy) return;
  if (!callActive) {
    setCallStatus("● Start the call first", "down");
    return;
  }

  callBusy = true;
  $("callSendBtn").disabled = true;
  const session = callSession;
  const wasActive = callActive;
  if (wasActive) {
    callSuspended = true;
    stopVad();
    if (callRecorder?.state === "recording") {
      callDiscardTurn = true;
      try { callRecorder.stop(); } catch { /* already stopped */ }
    }
  }

  const form = new FormData();
  form.append("text", text);
  if (callHistory.length) form.append("system", callSystemPrompt());

  hide($("callError"));
  setCallStatus("● AI is thinking…");
  let ok = false;
  try {
    const res = await fetch(`${API_BASE}/voice/text`, { method: "POST", body: form });
    if (!res.ok) throw new Error(await errorMessage(res));
    if (session !== callSession) return;

    const audioBlob = await res.blob();
    if (session !== callSession) return;
    if (callAudioUrl) URL.revokeObjectURL(callAudioUrl);
    callAudioUrl = URL.createObjectURL(audioBlob);

    $("callText").value = headerText(res, "X-Input-Text") || text;
    $("callReply").value = headerText(res, "X-Llm-Reply") || "";
    $("callDownload").href = callAudioUrl;
    show($("callResult"));

    if ($("callReply").value) {
      callHistory.push({ user: $("callText").value, ai: $("callReply").value });
    }
    ok = true;

    setCallStatus("● AI is speaking…", "ok");
    await playCallAudio(callAudioUrl);
  } catch (err) {
    if (session !== callSession) return;
    $("callError").textContent = err instanceof TypeError ? networkMessage() : err.message;
    show($("callError"));
    setCallStatus("● Could not respond", "down");
  } finally {
    callBusy = false;
    $("callSendBtn").disabled = false;
    if (session === callSession && callActive) {
      // Stay in typing mode after a typed turn so the microphone cannot
      // compete with TTS or transcribe background noise.
      callSuspended = true;
      if (ok) setCallStatus("● Typed reply ready — type again or click 🎙 Speak");
    } else if (ok) {
      setCallStatus("Typed reply ready");
    }
  }
}

function pauseCallListening() {
  if (!callActive) return;
  callSuspended = true;
  stopVad();
  if (callRecorder?.state === "recording") {
    callDiscardTurn = true;
    try { callRecorder.stop(); } catch { /* already stopped */ }
  }
  setCallStatus("● Typing… press Send when ready");
}

function resumeCallListening() {
  if (!callActive) {
    setCallStatus("● Start the call first", "down");
    return;
  }
  if (!callMicStream) {
    setCallStatus("● Microphone unavailable — use the typed box", "down");
    return;
  }
  callSuspended = false;
  startListening();
}

async function beginCall() {
  hide($("callError"));
  hide($("callResult"));
  $("callText").value = "";
  $("callReply").value = "";
  $("callAudio").src = "";

  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
    $("callError").textContent = "Audio recording is not supported in this browser. Use Chrome, Edge, Firefox, or Safari.";
    show($("callError"));
    return;
  }

  setCallStatus("● Connecting…");
  try {
    callSession += 1;
    callDiscardTurn = false;
    callSuspended = false;
    callHistory = [];
    callMicStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    callAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (callAudioCtx.state === "suspended") await callAudioCtx.resume();
    const source = callAudioCtx.createMediaStreamSource(callMicStream);
    callAnalyser = callAudioCtx.createAnalyser();
    callAnalyser.fftSize = 1024;
    callAnalyser.smoothingTimeConstant = 0.8;
    source.connect(callAnalyser);
    callAnalyserData = new Float32Array(callAnalyser.fftSize);

    callActive = true;
    $("callBtn").textContent = "⏹ End Call";
    $("callBtn").classList.add("call-stop");

    // The AI speaks first, then the caller's turn is recorded automatically.
    setCallStatus("● AI is greeting you…");
    const greetingUrl = await synthesizeCallText(CALL_GREETING);
    if (!callActive) {
      URL.revokeObjectURL(greetingUrl);
      return;
    }

    $("callReply").value = CALL_GREETING;
    show($("callResult"));
    await playCallAudio(greetingUrl);
    URL.revokeObjectURL(greetingUrl);
    callHistory = [{ user: "(call started)", ai: CALL_GREETING }];
    if (callActive) startListening();
  } catch (err) {
    callMicStream?.getTracks().forEach((track) => track.stop());
    callMicStream = null;
    callActive = false;
    $("callBtn").textContent = "▶ Start Call";
    $("callBtn").classList.remove("call-stop");
    $("callError").textContent = err.name === "NotAllowedError"
      ? "Microphone permission was denied. Allow microphone access and try again."
      : err instanceof TypeError ? networkMessage() : `Could not start the call: ${err.message}`;
    show($("callError"));
    setCallStatus("");
  }
}

function endCall() {
  callActive = false;
  callSuspended = false;
  callSession += 1;
  callDiscardTurn = true;
  stopVad();
  if (callAudioDone) {
    const done = callAudioDone;
    callAudioDone = null;
    done();
  }
  if (callRecorder?.state === "recording") {
    try { callRecorder.stop(); } catch { /* already stopped */ }
  }
  callRecorder = null;
  callMicStream?.getTracks().forEach((track) => track.stop());
  callMicStream = null;
  if (callAudioCtx) {
    callAudioCtx.close().catch(() => {});
    callAudioCtx = null;
  }
  callAnalyser = null;
  callAnalyserData = null;
  if (callAudioUrl) URL.revokeObjectURL(callAudioUrl);
  callAudioUrl = null;
  const audio = $("callAudio");
  audio.pause();
  audio.removeAttribute("src");

  $("callBtn").textContent = "▶ Start Call";
  $("callBtn").classList.remove("call-stop");
  setCallStatus("Call ended");
}

$("callBtn").addEventListener("click", () => {
  if (callActive) endCall();
  else beginCall();
});

$("callSendBtn").addEventListener("click", sendTypedTurn);
$("callListenBtn").addEventListener("click", resumeCallListening);
$("callText").addEventListener("focus", pauseCallListening);
$("callText").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    sendTypedTurn();
  }
});

checkHealth();
