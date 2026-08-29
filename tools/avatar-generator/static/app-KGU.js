// KGU C-Suite Interactive Avatar Controller

const TWIN_DATA = {
  ceo: {
    name: "Joann Coffey (CEO Twin)",
    bio: "Representing Joann's Present Day Wise Elder self. Directing KGU International towards a $1 trillion valuation using a lifetime of executive strategy, capital tranche management, and joint venture architecture.",
    image: "images/ceo.png"
  },
  cto: {
    name: "Joann Coffey (CTO Twin)",
    bio: "Representing Joann's Future-Focus Tech Explorer self. Designing zero-trust VPN meshes, secure database replication, and PM2 self-healing container recovery systems.",
    image: "images/ceo.png"
  },
  cmo: {
    name: "Joann Coffey (CMO Twin)",
    bio: "Representing Joann's Youthful Creative & Storyteller self. Creating viral brand narratives and vertical media storyboards on CapCut and TikTok to scale corporate networks.",
    image: "images/ceo.png"
  },
  clo: {
    name: "Joann Coffey (CLO Twin)",
    bio: "Representing Joann's Early Career Pragmatist self. Overseeing secure VPN tunnel compliance, joint venture agreements, likeness rights, and NDA templates.",
    image: "images/ceo.png"
  },
  cfo: {
    name: "Joann Coffey (CFO Twin)",
    bio: "Representing Joann's Mid-Career Calculated Investor self. Optimizing compute budget allocations, auditing ledger accumulations, and managing the 5% referral credit program.",
    image: "images/ceo.png"
  },
  cgo: {
    name: "Joann Coffey (CGO Twin)",
    bio: "Representing Joann's Early Days Entrepreneurial Hustler self. Aggressively building leads databases and establishing utility-level contacts for municipal PFAS water recovery campaigns.",
    image: "images/ceo.png"
  }
};

let currentRole = "ceo";
let isSpeaking = false;

// Query Client parameters
const urlParams = new URLSearchParams(window.location.search);
const urlClientId = urlParams.get('client_id');

// DOM Elements
const personalityBtns = document.querySelectorAll(".personality-btn");
const avatarImg = document.getElementById("avatar-image");
const avatarVideo = document.getElementById("avatar-video");
const twinNameEl = document.getElementById("twin-name");
const twinBioEl = document.getElementById("twin-bio");
const chatInput = document.getElementById("chat-input");
const sendBtn = document.getElementById("send-btn");
const micBtn = document.getElementById("mic-btn");
const chatHistory = document.getElementById("chat-history");
const waveform = document.getElementById("waveform");
const mouth = document.getElementById("mouth");
const audioPlayer = document.getElementById("audio-player");

// Switch Personalities
personalityBtns.forEach(btn => {
  btn.addEventListener("click", () => {
    // Remove active state
    personalityBtns.forEach(b => b.classList.remove("active"));
    btn.classList.add("active");

    const role = btn.getAttribute("data-role");
    currentRole = role;

    const data = TWIN_DATA[role];
    twinNameEl.textContent = data.name;
    twinBioEl.textContent = data.bio;
    
    avatarImg.src = data.image;
    avatarImg.onerror = () => {
      avatarImg.src = "images/ceo.png";
    };

    if (isSpeaking) {
      stopSpeaking();
    } else {
      playIdleLoop();
    }

    // Add system info message
    appendMessage("system", `System`, `Connected to ${data.name}`);
  });
});

// Boardroom Mode State Variables
let currentMode = "solo";
let boardroomTurnsQueue = [];
let boardroomCurrentTurnIndex = 0;
let isBoardroomSpeaking = false;
let boardroomAudioElement = new Audio();

function setMode(mode) {
  currentMode = mode;
  
  const btnSolo = document.getElementById("btn-solo");
  const btnBoardroom = document.getElementById("btn-boardroom");
  const btnOpsConsole = document.getElementById("btn-ops-console");
  
  const soloView = document.getElementById("solo-avatar-view");
  const boardroomView = document.getElementById("boardroom-view");
  const opsIframe = document.getElementById("ops-console-iframe");
  
  const leftPanel = document.querySelector(".left-panel");
  const rightPanel = document.querySelector(".right-panel");
  const workspace = document.querySelector(".hud-workspace");
  const terminalLog = document.querySelector(".viewport-terminal");
  
  // Reset all buttons active class
  btnSolo.classList.remove("active");
  btnBoardroom.classList.remove("active");
  if (btnOpsConsole) btnOpsConsole.classList.remove("active");
  
  if (mode === "ops-console") {
    if (btnOpsConsole) btnOpsConsole.classList.add("active");
    
    // Hide standard views and panels
    soloView.style.display = "none";
    boardroomView.style.display = "none";
    if (terminalLog) terminalLog.style.display = "none";
    if (leftPanel) leftPanel.style.display = "none";
    if (rightPanel) rightPanel.style.display = "none";
    
    // Expand workspace to full-width (hide sidebar grids)
    if (workspace) workspace.style.gridTemplateColumns = "1fr";
    
    // Show Ops Console iframe
    if (opsIframe) opsIframe.style.display = "block";
    
    stopSpeaking();
    stopBoardroomSpeaking();
  } else {
    // Restore layout
    if (leftPanel) leftPanel.style.display = "flex";
    if (rightPanel) rightPanel.style.display = "flex";
    if (terminalLog) terminalLog.style.display = "block";
    if (workspace) workspace.style.gridTemplateColumns = "280px 1fr 340px";
    if (opsIframe) opsIframe.style.display = "none";
    
    if (mode === "boardroom") {
      btnBoardroom.classList.add("active");
      soloView.style.display = "none";
      boardroomView.style.display = "block";
      
      stopSpeaking();
      initBoardroomIdleLoops();
    } else {
      btnSolo.classList.add("active");
      soloView.style.display = "flex";
      boardroomView.style.display = "none";
      
      stopBoardroomSpeaking();
      playIdleLoop();
    }
  }
}
window.setMode = setMode;

function initBoardroomIdleLoops() {
  const roles = ["ceo", "cto", "cmo", "clo", "cfo", "cgo"];
  roles.forEach(role => {
    const imgEl = document.getElementById(`boardroom-img-${role}`);
    const videoEl = document.getElementById(`boardroom-video-${role}`);
    const data = TWIN_DATA[role];
    
    imgEl.src = data.image;
    imgEl.onerror = () => { imgEl.src = "images/ceo.png"; };
    
    const videoUrl = data.video || `/static/animations/base_${role}.mp4`;
    videoEl.src = videoUrl;
    videoEl.muted = true;
    videoEl.loop = true;
    videoEl.play().then(() => {
      imgEl.style.display = "none";
      videoEl.style.display = "block";
    }).catch(() => {
      videoEl.style.display = "none";
      imgEl.style.display = "block";
    });
  });
}

async function handleBoardroomSend(text) {
  if (isBoardroomSpeaking) {
    stopBoardroomSpeaking();
  }
  clearListeningAnimations();
  
  chatInput.value = "";
  appendMessage("user", "You", text);
  
  // Show boardroom typing indicator
  const typingMessage = appendMessage("assistant", "Boardroom swarm", "Orchestrating boardroom meeting...");
  
  try {
    const response = await fetch("/api/chat/boardroom", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        client_id: urlClientId || "default"
      })
    });
    
    if (!response.ok) throw new Error("Server Error");
    
    const data = await response.json();
    typingMessage.remove(); // remove the initial orchestrating message
    
    boardroomTurnsQueue = data.turns;
    boardroomCurrentTurnIndex = 0;
    
    playNextBoardroomTurn();
  } catch (error) {
    console.error(error);
    typingMessage.querySelector(".text").textContent = "The boardroom connection failed. Please verify the backend is running.";
  }
}

function playNextBoardroomTurn() {
  if (boardroomCurrentTurnIndex >= boardroomTurnsQueue.length) {
    stopBoardroomSpeaking();
    return;
  }
  
  isBoardroomSpeaking = true;
  const turn = boardroomTurnsQueue[boardroomCurrentTurnIndex];
  const role = turn.speaker;
  
  // 1. Append message bubble to chat log
  const speakerName = TWIN_DATA[role].name;
  appendMessage("assistant", speakerName, turn.text);
  
  // 2. Set boardroom member UI as active speaker
  const members = document.querySelectorAll(".boardroom-member");
  members.forEach(m => {
    if (m.getAttribute("data-boardroom-role") === role) {
      m.classList.add("active");
    } else {
      m.classList.remove("active");
    }
  });
  
  // 3. Play video/audio for the speaking twin
  const videoEl = document.getElementById(`boardroom-video-${role}`);
  const imgEl = document.getElementById(`boardroom-img-${role}`);
  
  if (turn.video_url) {
    // Show speaking video loop (unmuted)
    imgEl.style.display = "none";
    videoEl.style.display = "block";
    videoEl.src = turn.video_url;
    videoEl.muted = false;
    videoEl.loop = false;
    videoEl.play();
    
    videoEl.onended = () => {
      // Transition back to idle loop
      const idleVideoUrl = TWIN_DATA[role].video || `/static/animations/base_${role}.mp4`;
      videoEl.src = idleVideoUrl;
      videoEl.muted = true;
      videoEl.loop = true;
      videoEl.play().catch(() => {});
      
      boardroomCurrentTurnIndex++;
      playNextBoardroomTurn();
    };
  } else {
    // Fallback: play audio on boardroom audio player
    boardroomAudioElement.src = turn.audio_url;
    boardroomAudioElement.play();
    
    boardroomAudioElement.onended = () => {
      boardroomCurrentTurnIndex++;
      playNextBoardroomTurn();
    };
  }
}

function stopBoardroomSpeaking() {
  isBoardroomSpeaking = false;
  boardroomTurnsQueue = [];
  boardroomAudioElement.pause();
  
  // Reset all members to idle loops
  const members = document.querySelectorAll(".boardroom-member");
  members.forEach(m => {
    m.classList.remove("active");
    const role = m.getAttribute("data-boardroom-role");
    const videoEl = document.getElementById(`boardroom-video-${role}`);
    
    if (videoEl) {
      videoEl.pause();
      const idleVideoUrl = TWIN_DATA[role].video || `/static/animations/base_${role}.mp4`;
      videoEl.src = idleVideoUrl;
      videoEl.muted = true;
      videoEl.loop = true;
      videoEl.play().catch(() => {});
    }
  });
}

// Chat Send Handler
let playlist = [];
let isPlayingPlaylist = false;

function playNextPlaylistItem() {
  if (playlist.length === 0) {
    isPlayingPlaylist = false;
    stopSpeaking();
    return;
  }
  
  isPlayingPlaylist = true;
  isSpeaking = true;
  
  const item = playlist.shift();
  
  if (item.video_url) {
    avatarImg.style.display = "none";
    avatarVideo.style.display = "block";
    avatarVideo.muted = false;
    avatarVideo.loop = false;
    avatarVideo.src = item.video_url;
    avatarVideo.play().catch(err => {
      console.error("Failed to play sentence video, trying audio fallback:", err);
      audioPlayer.src = item.audio_url;
      audioPlayer.play();
    });
    
    waveform.classList.add("active");
    
    avatarVideo.onended = () => {
      playNextPlaylistItem();
    };
  } else {
    audioPlayer.src = item.audio_url;
    audioPlayer.play();
    waveform.classList.add("active");
    mouth.classList.add("speaking");
    
    audioPlayer.onended = () => {
      playNextPlaylistItem();
    };
  }
}

// Chat Send Handler
async function handleSend() {
  const text = chatInput.value.trim();
  if (!text) return;
  
  if (currentMode === "boardroom") {
    handleBoardroomSend(text);
    return;
  }

  clearListeningAnimations();

  if (isSpeaking || isPlayingPlaylist) {
    stopSpeaking();
  }

  // Clear Input
  chatInput.value = "";

  // Append User Message
  appendMessage("user", "You", text);

  // Show Typing Indicator
  const typingMessage = appendMessage("assistant", TWIN_DATA[currentRole].name, "");
  const textBubble = typingMessage.querySelector(".text");

  const advisorModeCheckbox = document.getElementById("advisor-mode-checkbox");
  const isAdvisorMode = advisorModeCheckbox && advisorModeCheckbox.checked;

  if (isAdvisorMode) {
    textBubble.textContent = "Consulting C-Suite Advisor...";
    try {
      const response = await fetch("/api/chat/advisor", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          message: text, 
          personality: currentRole,
          client_id: urlClientId || "default"
        })
      });

      if (!response.ok) throw new Error("Server Error");

      const data = await response.json();
      textBubble.textContent = data.text;
      
      // Play speech and video directly
      playSpeech(data.audio_url, data.video_url);
    } catch (error) {
      console.error(error);
      textBubble.textContent = "Advisor consultation failed. Please verify the backend server is running.";
    }
    return;
  }

  try {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ 
        message: text, 
        personality: currentRole,
        client_id: urlClientId || "default"
      })
    });

    if (!response.ok) throw new Error("Server Error");

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const payload = JSON.parse(line.substring(6));
            if (payload.error) {
              textBubble.textContent = "Error: " + payload.error;
              break;
            }

            const cleanText = payload.text.replace(/^\[(HAPPY|SERIOUS|THOUGHTFUL|NEUTRAL)\]/i, "").trim();
            textBubble.textContent += (textBubble.textContent ? " " : "") + cleanText;

            playlist.push(payload);
            if (!isPlayingPlaylist) {
              playNextPlaylistItem();
            }
          } catch (err) {
            console.error("Error parsing SSE chunk:", err);
          }
        }
      }
    }
  } catch (error) {
    console.error(error);
    textBubble.textContent = "Connection to my cognitive nodes failed. Please verify the backend server is running.";
  }
}

sendBtn.addEventListener("click", handleSend);
chatInput.addEventListener("keypress", (e) => {
  if (e.key === "Enter") handleSend();
});

// Audio & Video Speech Playback
function playSpeech(audioUrl, videoUrl = null) {
  isSpeaking = true;
  
  if (videoUrl) {
    // Hide static image, show video
    avatarImg.style.display = "none";
    avatarVideo.style.display = "block";
    avatarVideo.muted = false;
    avatarVideo.loop = false;
    avatarVideo.src = videoUrl;
    avatarVideo.play();
    
    // Waveform indicator active
    waveform.classList.add("active");
    
    avatarVideo.onended = () => {
      stopSpeaking();
    };
  } else {
    // Fallback: play audio and animate mouth/waveform
    audioPlayer.src = audioUrl;
    audioPlayer.play();
    waveform.classList.add("active");
    mouth.classList.add("speaking");
    
    audioPlayer.onended = () => {
      stopSpeaking();
    };
  }
}

function stopSpeaking() {
  isSpeaking = false;
  isPlayingPlaylist = false;
  playlist = [];
  
  audioPlayer.pause();
  avatarVideo.pause();
  
  playIdleLoop();
  
  waveform.classList.remove("active");
  mouth.classList.remove("speaking");
}

function playIdleLoop() {
  const data = TWIN_DATA[currentRole];
  // Custom video if present, otherwise default base animations
  const videoUrl = data.video || `/static/animations/base_${currentRole}.mp4`;
  
  avatarVideo.muted = true;
  avatarVideo.loop = true;
  avatarVideo.src = videoUrl;
  
  avatarVideo.play().then(() => {
    avatarImg.style.display = "none";
    avatarVideo.style.display = "block";
  }).catch(err => {
    console.log("Idle video loop play failed, using static fallback:", err);
    avatarVideo.style.display = "none";
    avatarImg.style.display = "block";
    avatarImg.src = data.image;
  });
}

// Append Message to History
function appendMessage(senderType, senderName, text) {
  const msgDiv = document.createElement("div");
  msgDiv.className = `message ${senderType}`;
  
  const senderEl = document.createElement("div");
  senderEl.className = "sender";
  senderEl.textContent = senderName;
  
  const textEl = document.createElement("div");
  textEl.className = "text";
  textEl.textContent = text;
  
  msgDiv.appendChild(senderEl);
  msgDiv.appendChild(textEl);
  
  chatHistory.appendChild(msgDiv);
  chatHistory.scrollTop = chatHistory.scrollHeight;

  return msgDiv;
}

// Local Speech-to-Text (GPU Whisper Integration)
let mediaRecorder;
let audioChunks = [];
let isRecording = false;

async function startLocalRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = new MediaRecorder(stream);
    audioChunks = [];
    
    mediaRecorder.ondataavailable = event => {
      audioChunks.push(event.data);
    };
    
    mediaRecorder.onstop = async () => {
      const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
      const formData = new FormData();
      formData.append('file', audioBlob, 'recording.webm');
      
      chatInput.placeholder = "Transcribing locally...";
      try {
        const response = await fetch('/api/speech-to-text', {
          method: 'POST',
          body: formData
        });
        const data = await response.json();
        
        // Handle model downloading
        if (data.detail && data.detail.downloading) {
          appendMessage("system", "System", `Whisper model downloading: ${data.detail.message}`);
          chatInput.placeholder = "Model caching, try again in a few seconds...";
          return;
        }
        
        if (data.text && data.text.trim()) {
          chatInput.value = data.text;
          handleSend();
        }
      } catch (err) {
        console.error("Local STT failed:", err);
      } finally {
        chatInput.placeholder = "Enter your directive to the C-Suite...";
      }
    };
    
    mediaRecorder.start();
    isRecording = true;
    micBtn.classList.add("recording");
    chatInput.placeholder = "Listening locally (speak now)...";
  } catch (err) {
    console.error("Microphone access denied:", err);
    chatInput.placeholder = "Mic permission denied.";
  }
}

function stopLocalRecording() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
  }
  isRecording = false;
  micBtn.classList.remove("recording");
  chatInput.placeholder = "Enter your directive to the C-Suite...";
}

micBtn.addEventListener("click", () => {
  if (isRecording) {
    stopLocalRecording();
  } else {
    startLocalRecording();
  }
});

// Active VAD Interruption Engine (HeyGen/Tavus Style)
let micStream = null;
let audioContext = null;
let micAnalyser = null;
let consecutiveSpeechFrames = 0;
const VAD_VOLUME_THRESHOLD = 0.035; // Voice threshold (RMS)
const VAD_CONSECUTIVE_FRAMES = 3;  // Require continuous speech frames to prevent noise spikes

async function initBackgroundVAD() {
  if (audioContext) return;
  try {
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    audioContext = new AudioContextClass();
    
    const source = audioContext.createMediaStreamSource(micStream);
    micAnalyser = audioContext.createAnalyser();
    micAnalyser.fftSize = 512;
    source.connect(micAnalyser);
    
    checkMicVADVolume();
    console.log("VAD Background Audio Stream Active.");
  } catch (err) {
    console.log("VAD voice monitoring inactive (permission denied or no mic).");
  }
}

function checkMicVADVolume() {
  if (!micAnalyser) return;
  
  const bufferLength = micAnalyser.fftSize;
  const dataArray = new Float32Array(bufferLength);
  micAnalyser.getFloatTimeDomainData(dataArray);
  
  let sum = 0;
  for (let i = 0; i < bufferLength; i++) {
    sum += dataArray[i] * dataArray[i];
  }
  const rms = Math.sqrt(sum / bufferLength);
  
  if (rms > VAD_VOLUME_THRESHOLD) {
    consecutiveSpeechFrames++;
    if (consecutiveSpeechFrames >= VAD_CONSECUTIVE_FRAMES) {
      if (isSpeaking) {
        console.log(`[VAD Interruption] Voice activity detected (RMS: ${rms.toFixed(4)}). Interrupting avatar...`);
        triggerInterruption();
      }
    }
  } else {
    consecutiveSpeechFrames = 0;
  }
  
  requestAnimationFrame(checkMicVADVolume);
}

async function triggerInterruption() {
  stopSpeaking();
  
  try {
    await fetch("/api/chat/interrupt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ client_id: urlClientId || "default" })
    });
  } catch (err) {
    console.error("Failed to notify server of VAD interruption:", err);
  }
}

// Initialize VAD on first interaction
document.addEventListener("click", initBackgroundVAD, { once: true });
document.addEventListener("keypress", initBackgroundVAD, { once: true });

// Active input-focus interruption listener
chatInput.addEventListener('focus', () => {
  if (isSpeaking) triggerInterruption();
});

// Client Dynamic Onboarding Context loader
async function loadClientContext() {
  if (!urlClientId) {
    playIdleLoop();
    return;
  }
  try {
    const res = await fetch(`/api/client/${urlClientId}`);
    if (!res.ok) {
      playIdleLoop();
      return;
    }
    const clientData = await res.json();
    
    // Dynamically override twin configs
    Object.keys(clientData.avatars).forEach(role => {
      const customAvatar = clientData.avatars[role];
      if (!TWIN_DATA[role]) return;
      if (customAvatar.name) TWIN_DATA[role].name = customAvatar.name;
      if (customAvatar.bio) TWIN_DATA[role].bio = customAvatar.bio;
      
      const cacheBust = "?t=" + new Date().getTime();
      if (customAvatar.image_path) TWIN_DATA[role].image = customAvatar.image_path + cacheBust;
      if (customAvatar.video_path) TWIN_DATA[role].video = customAvatar.video_path + cacheBust;
    });
    
    // Refresh displayed UI
    const activeBtn = document.querySelector(".personality-btn.active");
    if (activeBtn) {
      activeBtn.click();
    } else {
      const data = TWIN_DATA[currentRole];
      twinNameEl.textContent = data.name;
      twinBioEl.textContent = data.bio;
      avatarImg.src = data.image;
      playIdleLoop();
    }
  } catch (e) {
    console.error("Failed to load client context metadata", e);
    playIdleLoop();
  }
}

// Active Listening Typing Animation
let typingTimer = null;

function clearListeningAnimations() {
  clearTimeout(typingTimer);
  const frames = document.querySelectorAll(".avatar-frame, .boardroom-avatar-frame");
  frames.forEach(f => f.classList.remove("listening-nod", "listening-tilt"));
}

chatInput.addEventListener("input", () => {
  const activeFrame = currentMode === "boardroom" 
    ? document.querySelector(".boardroom-member.active .boardroom-avatar-frame")
    : document.querySelector(".avatar-frame");
    
  if (activeFrame) {
    if (!activeFrame.classList.contains("listening-nod") && !activeFrame.classList.contains("listening-tilt")) {
      const animClass = Math.random() > 0.5 ? "listening-nod" : "listening-tilt";
      activeFrame.classList.add(animClass);
    }
    
    clearTimeout(typingTimer);
    typingTimer = setTimeout(() => {
      activeFrame.classList.remove("listening-nod", "listening-tilt");
    }, 1500);
  }
});

// Cursor Gaze Tracking
window.addEventListener("mousemove", (e) => {
  const mouseX = e.clientX;
  const mouseY = e.clientY;
  
  const mediaElements = document.querySelectorAll("#avatar-image, #avatar-video, .boardroom-avatar-frame img, .boardroom-avatar-frame video");
  
  mediaElements.forEach(media => {
    if (media.style.display === "none") return;
    
    const frameRect = media.parentElement.getBoundingClientRect();
    const frameCenterX = frameRect.left + frameRect.width / 2;
    const frameCenterY = frameRect.top + frameRect.height / 2;
    
    const dx = mouseX - frameCenterX;
    const dy = mouseY - frameCenterY;
    const distance = Math.sqrt(dx * dx + dy * dy);
    
    const maxOffset = 10;
    let offsetX = 0;
    let offsetY = 0;
    
    if (distance > 0) {
      const scaleFactor = Math.min(distance / 500, 1.0);
      offsetX = (dx / distance) * maxOffset * scaleFactor;
      offsetY = (dy / distance) * maxOffset * scaleFactor;
    }
    
    media.style.transform = `translate(${offsetX.toFixed(1)}px, ${offsetY.toFixed(1)}px) scale(1.1)`;
    media.style.transition = "transform 0.1s cubic-bezier(0.25, 0.46, 0.45, 0.94)";
  });
});

// Initialize client context
loadClientContext();

// --- ZOOM APP SIMULATION INTERACTIONS ---

// 1. Meeting Timer (Counts up from 0)
let meetingSeconds = 0;
const timerEl = document.getElementById("meeting-timer");
if (timerEl) {
  setInterval(() => {
    meetingSeconds++;
    const hrs = String(Math.floor(meetingSeconds / 3600)).padStart(2, "0");
    const mins = String(Math.floor((meetingSeconds % 3600) / 60)).padStart(2, "0");
    const secs = String(meetingSeconds % 60).padStart(2, "0");
    timerEl.textContent = `${hrs}:${mins}:${secs}`;
  }, 1000);
}

// 2. Zoom Drawer Toggle Logic
function toggleDrawer(name) {
  const drawer = document.getElementById(`${name}-drawer`);
  const btn = document.getElementById(`btn-show-${name}`);
  if (!drawer) return;
  
  if (drawer.style.display === "none") {
    drawer.style.display = "flex";
    if (btn) btn.classList.add("active");
  } else {
    drawer.style.display = "none";
    if (btn) btn.classList.remove("active");
  }
}
window.toggleDrawer = toggleDrawer;

// 3. User Webcam Video Streaming (All is Real with WebRTC P2P conferencing!)
let userWebcamStream = null;
const toolbarCamBtn = document.getElementById("toolbar-cam-btn");
const camStatusIcon = document.getElementById("user-cam-status-icon");
const camControlIcon = document.getElementById("cam-control-icon");
const camControlLabel = document.getElementById("cam-control-label");

// WebRTC and Signaling State
const myPeerId = "peer_" + Math.random().toString(36).substring(2, 9);
let wsSignal = null;
let peerConnections = {}; // peerId -> RTCPeerConnection
let reconnectAttempts = 0;
const maxReconnectDelay = 30000; // max 30s
const iceConfig = {
  iceServers: [
    { urls: "stun:stun.l.google.com:19302" }
  ]
};

function initSignaling() {
  if (wsSignal) return;
  
  const clientSession = urlClientId || "default";
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/api/ws/signal/${clientSession}/${myPeerId}`;
  
  wsSignal = new WebSocket(wsUrl);
  
  wsSignal.onopen = () => {
    console.log("WebSocket Signaling Connected. Peer ID:", myPeerId);
    reconnectAttempts = 0; // Reset attempts on successful open
  };
  
  wsSignal.onmessage = async (event) => {
    const data = JSON.parse(event.data);
    const sender = data.sender;
    
    if (data.type === "peer-joined") {
      console.log("Remote peer joined:", sender);
      await createPeerConnection(sender, true);
    } else if (data.type === "offer") {
      console.log("Received WebRTC offer from:", sender);
      await createPeerConnection(sender, false);
      const pc = peerConnections[sender];
      await pc.setRemoteDescription(new RTCSessionDescription(data.payload.sdp));
      const answer = await pc.createAnswer();
      await pc.setLocalDescription(answer);
      sendSignal(sender, "answer", { sdp: answer });
    } else if (data.type === "answer") {
      console.log("Received WebRTC answer from:", sender);
      const pc = peerConnections[sender];
      if (pc) {
        await pc.setRemoteDescription(new RTCSessionDescription(data.payload.sdp));
      }
    } else if (data.type === "candidate") {
      console.log("Received ICE candidate from:", sender);
      const pc = peerConnections[sender];
      if (pc) {
        await pc.addIceCandidate(new RTCIceCandidate(data.payload.candidate));
      }
    } else if (data.type === "peer-left") {
      console.log("Remote peer left:", data.peer_id);
      removeRemoteParticipant(data.peer_id);
    }
  };
  
  wsSignal.onclose = () => {
    console.log("WebSocket Signaling Disconnected.");
    wsSignal = null;
    disconnectAllPeers();
    
    // Auto-reconnect if local webcam is still streaming
    if (userWebcamStream) {
      reconnectAttempts++;
      const delay = Math.min(Math.pow(2, reconnectAttempts) * 1000, maxReconnectDelay);
      console.log(`Reconnecting signaling in ${(delay/1000).toFixed(1)}s (Attempt ${reconnectAttempts})...`);
      setTimeout(initSignaling, delay);
    }
  };
}

function sendSignal(target, type, payload) {
  if (wsSignal && wsSignal.readyState === WebSocket.OPEN) {
    wsSignal.send(JSON.stringify({
      target_peer: target,
      type: type,
      payload: payload
    }));
  }
}

async function createPeerConnection(peerId, isInitiator) {
  if (peerConnections[peerId]) return;
  
  const pc = new RTCPeerConnection(iceConfig);
  peerConnections[peerId] = pc;
  
  // Add local tracks
  if (userWebcamStream) {
    userWebcamStream.getTracks().forEach(track => {
      pc.addTrack(track, userWebcamStream);
    });
  }
  
  pc.onicecandidate = (event) => {
    if (event.candidate) {
      sendSignal(peerId, "candidate", { candidate: event.candidate });
    }
  };
  
  pc.ontrack = (event) => {
    console.log("Received remote stream track from:", peerId);
    addRemoteParticipantVideo(peerId, event.streams[0]);
  };
  
  if (isInitiator) {
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    sendSignal(peerId, "offer", { sdp: offer });
  }
}

function addRemoteParticipantVideo(peerId, stream) {
  const grid = document.querySelector(".boardroom-grid");
  if (grid) {
    let memberBox = document.getElementById(`peer-grid-${peerId}`);
    if (!memberBox) {
      memberBox = document.createElement("div");
      memberBox.className = "boardroom-member remote-member";
      memberBox.id = `peer-grid-${peerId}`;
      memberBox.innerHTML = `
        <div class="boardroom-avatar-frame user-video-bg">
          <video id="peer-video-${peerId}" autoplay playsinline></video>
        </div>
        <div class="boardroom-label">Remote Partner (${peerId.substring(5)})</div>
      `;
      grid.appendChild(memberBox);
    }
    const video = document.getElementById(`peer-video-${peerId}`);
    if (video) {
      video.srcObject = stream;
      video.play().catch(e => console.error("Play failed:", e));
    }
  }

  const strip = document.querySelector(".speaker-top-strip");
  if (strip) {
    let stripBox = document.getElementById(`peer-strip-${peerId}`);
    if (!stripBox) {
      stripBox = document.createElement("div");
      stripBox.className = "strip-participant remote-strip-box";
      stripBox.id = `peer-strip-${peerId}`;
      stripBox.innerHTML = `
        <div class="strip-thumb user-video-bg">
          <video id="peer-video-strip-${peerId}" autoplay playsinline muted></video>
        </div>
        <span class="strip-label">Partner (${peerId.substring(5)})</span>
      `;
      strip.appendChild(stripBox);
    }
    const videoStrip = document.getElementById(`peer-video-strip-${peerId}`);
    if (videoStrip) {
      videoStrip.srcObject = stream;
      videoStrip.play().catch(e => console.error("Play failed:", e));
    }
  }
  
  refreshParticipantsDrawerList();
}

function removeRemoteParticipant(peerId) {
  if (peerConnections[peerId]) {
    try { peerConnections[peerId].close(); } catch(e){}
    delete peerConnections[peerId];
  }
  
  const memberBox = document.getElementById(`peer-grid-${peerId}`);
  if (memberBox) memberBox.remove();
  
  const stripBox = document.getElementById(`peer-strip-${peerId}`);
  if (stripBox) stripBox.remove();
  
  refreshParticipantsDrawerList();
}

function disconnectAllPeers() {
  Object.keys(peerConnections).forEach(peerId => {
    removeRemoteParticipant(peerId);
  });
  peerConnections = {};
}

function refreshParticipantsDrawerList() {
  const plist = document.querySelector(".participants-list");
  if (!plist) return;
  
  const remoteRows = plist.querySelectorAll(".remote-participant-row");
  remoteRows.forEach(r => r.remove());
  
  const userRow = document.getElementById("participant-user-row");
  const totalCountEl = document.querySelector("#btn-show-participants .control-label");
  const drawerHeaderEl = document.querySelector("#participants-drawer h3");
  
  const count = 7 + Object.keys(peerConnections).length;
  if (totalCountEl) totalCountEl.textContent = `Participants (${count})`;
  if (drawerHeaderEl) drawerHeaderEl.textContent = `Participants (${count})`;
  
  Object.keys(peerConnections).forEach(peerId => {
    const li = document.createElement("li");
    li.className = "participant-item remote-participant-row";
    li.innerHTML = `
      <span class="avatar-dot user-dot" style="background:#10b981;">P</span>
      <div class="participant-info">
        <span class="participant-name">Remote Partner (${peerId.substring(5)})</span>
      </div>
      <div class="participant-icons">🎙️ 📷</div>
    `;
    plist.insertBefore(li, userRow);
  });
}

async function toggleUserWebcam() {
  const selfVideoSolo = document.getElementById("self-view-video-solo");
  const selfVideoGrid = document.getElementById("self-view-video-grid");
  const placeholderSolo = document.getElementById("self-placeholder-solo");
  const placeholderGrid = document.getElementById("self-placeholder-grid");

  if (userWebcamStream) {
    // Stop webcam streaming
    userWebcamStream.getTracks().forEach(track => track.stop());
    userWebcamStream = null;
    
    if (selfVideoSolo) selfVideoSolo.srcObject = null;
    if (selfVideoGrid) selfVideoGrid.srcObject = null;
    if (placeholderSolo) placeholderSolo.style.display = "block";
    if (placeholderGrid) placeholderGrid.style.display = "block";
    
    camControlIcon.textContent = "📷";
    camControlLabel.textContent = "Start Video";
    if (camStatusIcon) camStatusIcon.textContent = "❌";
    if (toolbarCamBtn) toolbarCamBtn.classList.remove("active");
    
    // Disconnect signaling and peers
    if (wsSignal) wsSignal.close();
  } else {
    // Start webcam streaming
    try {
      userWebcamStream = await navigator.mediaDevices.getUserMedia({ video: true });
      
      if (selfVideoSolo) {
        selfVideoSolo.srcObject = userWebcamStream;
        selfVideoSolo.style.display = "block";
      }
      if (selfVideoGrid) {
        selfVideoGrid.srcObject = userWebcamStream;
        selfVideoGrid.style.display = "block";
      }
      if (placeholderSolo) placeholderSolo.style.display = "none";
      if (placeholderGrid) placeholderGrid.style.display = "none";
      
      camControlIcon.textContent = "📹";
      camControlLabel.textContent = "Stop Video";
      if (camStatusIcon) camStatusIcon.textContent = "📷";
      if (toolbarCamBtn) toolbarCamBtn.classList.add("active");
      
      // Connect signaling P2P
      initSignaling();
    } catch (err) {
      console.error("Camera access failed:", err);
      alert("Could not access your webcam. Please check permissions.");
    }
  }
}

if (toolbarCamBtn) {
  toolbarCamBtn.addEventListener("click", toggleUserWebcam);
}

// 4. Microphone Mute & VAD Toggle
let isMicMuted = false;
const toolbarMicBtn = document.getElementById("toolbar-mic-btn");
const micStatusIcon = document.getElementById("user-mic-status-icon");
const micControlIcon = document.getElementById("mic-control-icon");
const micControlLabel = document.getElementById("mic-control-label");

function toggleUserMic() {
  if (isMicMuted) {
    // Unmute
    isMicMuted = false;
    micControlIcon.textContent = "🎙️";
    micControlLabel.textContent = "Mute";
    if (micStatusIcon) micStatusIcon.textContent = "🎙️";
    if (toolbarMicBtn) toolbarMicBtn.classList.remove("muted");
    
    // Resume VAD monitoring
    initBackgroundVAD();
  } else {
    // Mute
    isMicMuted = true;
    micControlIcon.textContent = "🔇";
    micControlLabel.textContent = "Unmute";
    if (micStatusIcon) micStatusIcon.textContent = "🔇";
    if (toolbarMicBtn) toolbarMicBtn.classList.add("muted");
    
    // Stop active mic stream tracks if any to release mic hardware
    if (micStream) {
      micStream.getTracks().forEach(track => track.stop());
      micStream = null;
      audioContext = null;
      micAnalyser = null;
    }
  }
}

if (toolbarMicBtn) {
  toolbarMicBtn.addEventListener("click", toggleUserMic);
}

// 5. Click Strip Participant to Switch Active Speaker (Speaker View)
const stripParticipants = document.querySelectorAll(".strip-participant[data-role]");
stripParticipants.forEach(strip => {
  strip.addEventListener("click", () => {
    // Remove active selector highlight
    stripParticipants.forEach(s => s.classList.remove("active-selector"));
    strip.classList.add("active-selector");
    
    const role = strip.getAttribute("data-role");
    currentRole = role;
    
    // Dynamically query data
    const data = TWIN_DATA[role];
    twinNameEl.textContent = data.name;
    twinBioEl.textContent = data.bio;
    
    avatarImg.src = data.image;
    avatarImg.onerror = () => {
      avatarImg.src = "images/ceo.png";
    };
    
    if (isSpeaking) {
      stopSpeaking();
    } else {
      playIdleLoop();
    }
    
    appendMessage("system", `System`, `Switched active speaker to ${data.name}`);
  });
});

// --- PALANTIR HUD INTEGRATION LOGIC ---

// Helper to add log entries to the Operations Telemetry window
function addTerminalLog(message) {
  const logDiv = document.getElementById("terminal-body-log");
  if (!logDiv) return;
  const now = new Date();
  const timeStr = now.toTimeString().split(' ')[0];
  logDiv.innerHTML += `<br>[${timeStr}] ${message}`;
  logDiv.scrollTop = logDiv.scrollHeight;
}

// Scrape Lead Handler
async function runSovereignScraper() {
  const urlInput = document.getElementById("scraper-url-input");
  const logDiv = document.getElementById("scraper-log");
  const leadsList = document.getElementById("scraped-leads-list");
  
  if (!urlInput || !urlInput.value) {
    alert("Please enter a valid target URL.");
    return;
  }
  
  const targetUrl = urlInput.value;
  logDiv.textContent = `[Crawling ${targetUrl}...]`;
  addTerminalLog(`[SCRAPER] Dispatched lead extraction worker to: ${targetUrl}`);
  
  try {
    const res = await fetch("/api/scraper/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: targetUrl })
    });
    
    if (!res.ok) {
      throw new Error(`Scraper returned status ${res.status}`);
    }
    
    const data = await res.json();
    logDiv.textContent = `[COMPLETED] Extracted ${data.leads.length} unique leads.`;
    addTerminalLog(`[SCRAPER] Extraction finished. Return code: ${data.returncode}`);
    
    // Clear and rebuild scraped leads list UI
    if (leadsList && data.leads) {
      leadsList.innerHTML = "";
      data.leads.forEach(email => {
        const li = document.createElement("li");
        li.className = "lead-item synced";
        li.innerHTML = `
          <span class="lead-email">${email}</span>
          <span class="lead-status-badge">Odoo Synced</span>
        `;
        leadsList.appendChild(li);
        addTerminalLog(`[CRM] Synced lead: ${email} to Odoo opportunity ledger.`);
      });
    }
  } catch (err) {
    logDiv.textContent = `[ERROR] ${err.message}`;
    addTerminalLog(`[SCRAPER] Failed to complete job: ${err.message}`);
  }
}

// WebRTC Conversational Call Handler
async function startTavusCall() {
  const modal = document.getElementById("tavus-modal");
  const iframe = document.getElementById("tavus-iframe");
  const statusDiv = document.getElementById("tavus-status");
  
  if (!modal || !iframe || !statusDiv) return;
  
  modal.style.display = "flex";
  statusDiv.style.display = "block";
  statusDiv.textContent = "Connecting to Tavus Conversational API...";
  iframe.src = "";
  
  try {
    addTerminalLog("[WEBRTC] Initiating handshake with Tavus Orchestration Layer...");
    
    // Retrieve list of Pals to find the first registered Pal instance
    const palsRes = await fetch("/api/tavus/pals");
    let palId = "p44ab2e53efb"; // Bruce from PitchPro default fallback
    
    if (palsRes.ok) {
      const pals = await palsRes.json();
      if (pals && pals.length > 0) {
        palId = pals[0].pal_id;
        addTerminalLog(`[WEBRTC] Selected active local pal instance: ${pals[0].pal_name} (${palId})`);
      } else {
        addTerminalLog(`[WEBRTC] Warning: No custom pals registered in local DB. Using default sandbox pal.`);
      }
    }
    
    // Create conversation session
    const res = await fetch("/api/tavus/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pal_id: palId,
        custom_greeting: "KGU Operations Command active. I am Joann's Digital Twin. Initiating secure strategic advisory session."
      })
    });
    
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || "Failed to create conversation.");
    }
    
    const data = await res.json();
    const callUrl = data.conversation_url;
    if (!callUrl) {
      throw new Error("No conversation URL returned from Tavus.");
    }
    
    statusDiv.style.display = "none";
    iframe.src = callUrl;
    addTerminalLog(`[WEBRTC] Connection established. Session ID: ${data.conversation_id}`);
  } catch (err) {
    statusDiv.textContent = `Connection Failure: ${err.message}`;
    addTerminalLog(`[WEBRTC] Handshake aborted: ${err.message}`);
  }
}

function closeTavusCall() {
  const modal = document.getElementById("tavus-modal");
  const iframe = document.getElementById("tavus-iframe");
  if (iframe) iframe.src = "";
  if (modal) modal.style.display = "none";
  addTerminalLog("[WEBRTC] Connection terminated by operator.");
}

// Injects prompt suggestions into chat channel
function injectPrompt(text) {
  const chatInput = document.getElementById("chat-input");
  if (chatInput) {
    chatInput.value = text;
    chatInput.focus();
  }
}

// Bind Swarm Participant Click Listeners (Palantir style list items)
document.addEventListener("DOMContentLoaded", () => {
  const participantRows = document.querySelectorAll(".participant-item[data-role]");
  participantRows.forEach(row => {
    row.addEventListener("click", () => {
      participantRows.forEach(r => r.classList.remove("active-selector"));
      row.classList.add("active-selector");
      
      const role = row.getAttribute("data-role");
      currentRole = role;
      
      const data = TWIN_DATA[role];
      if (data) {
        twinNameEl.textContent = data.name;
        twinBioEl.textContent = data.bio;
        avatarImg.src = data.image;
        avatarImg.onerror = () => {
          avatarImg.src = "images/ceo.png";
        };
        
        if (isSpeaking) {
          stopSpeaking();
        } else {
          playIdleLoop();
        }
        
        addTerminalLog(`[SYSTEM] Switched active speaker focus to: ${data.name}`);
        appendMessage("system", `System`, `Connected to ${data.name}`);
      }
    });
  });
});

