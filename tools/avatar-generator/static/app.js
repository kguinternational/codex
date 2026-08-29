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
    image: "images/cto.png" // We will generate or fallback
  },
  cmo: {
    name: "Joann Coffey (CMO Twin)",
    bio: "Representing Joann's Youthful Creative & Storyteller self. Creating viral brand narratives and vertical media storyboards on CapCut and TikTok to scale corporate networks.",
    image: "images/cmo.png"
  },
  clo: {
    name: "Joann Coffey (CLO Twin)",
    bio: "Representing Joann's Early Career Pragmatist self. Overseeing secure VPN tunnel compliance, joint venture agreements, likeness rights, and NDA templates.",
    image: "images/clo.png"
  },
  cfo: {
    name: "Joann Coffey (CFO Twin)",
    bio: "Representing Joann's Mid-Career Calculated Investor self. Optimizing compute budget allocations, auditing ledger accumulations, and managing the 5% referral credit program.",
    image: "images/cfo.png"
  },
  cgo: {
    name: "Joann Coffey (CGO Twin)",
    bio: "Representing Joann's Early Days Entrepreneurial Hustler self. Aggressively building leads databases and establishing utility-level contacts for municipal PFAS water recovery campaigns.",
    image: "images/cgo.png"
  }
};

let currentRole = "ceo";
let isSpeaking = false;

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
const motionSelect = document.getElementById("motion-select");
const filterSelect = document.getElementById("filter-select");

// Switch Personalities
personalityBtns.forEach(btn => {
  btn.addEventListener("click", () => {
    // Remove active state
    personalityBtns.forEach(b => b.classList.remove("active"));
    btn.classList.add("active");

    const role = btn.getAttribute("data-role");
    currentRole = role;

    // Update Details
    const data = TWIN_DATA[role];
    twinNameEl.textContent = data.name;
    twinBioEl.textContent = data.bio;
    
    // Check if the specific avatar image exists, otherwise fallback to ceo.png
    avatarImg.src = data.image;
    avatarImg.onerror = () => {
      avatarImg.src = "images/ceo.png";
    };

    // Add system info message
    appendMessage("system", `System`, `Connected to ${data.name}`);
  });
});

// Chat Send Handler
async function handleSend() {
  const text = chatInput.value.trim();
  if (!text) return;
  if (isSpeaking) {
    audioPlayer.pause();
    stopSpeaking();
  }

  // Clear Input
  chatInput.value = "";

  // Append User Message
  appendMessage("user", "You", text);

  // Show Typing Indicator
  const typingMessage = appendMessage("assistant", TWIN_DATA[currentRole].name, "Thinking...");

  try {
    const motion = motionSelect ? motionSelect.value : "none";
    const filter = filterSelect ? filterSelect.value : "none";

    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ 
        message: text, 
        personality: currentRole,
        motion: motion,
        filter: filter
      })
    });

    if (!response.ok) throw new Error("Server Error");

    const data = await response.json();
    
    // Update Typing Message with actual response
    typingMessage.querySelector(".text").textContent = data.text;
    
    // Speak response and play avatar video
    playSpeech(data.audio_url, data.video_url);
  } catch (error) {
    console.error(error);
    typingMessage.querySelector(".text").textContent = "Connection to my cognitive nodes failed. Please verify the backend server is running.";
  }
}

sendBtn.addEventListener("click", handleSend);
chatInput.addEventListener("keypress", (e) => {
  if (e.key === "Enter") handleSend();
});

// Audio & Video Speech Playback
function playSpeech(audioUrl, videoUrl) {
  isSpeaking = true;
  audioPlayer.src = audioUrl;
  audioPlayer.play();

  // Trigger animations
  waveform.classList.add("active");
  mouth.classList.add("speaking");

  if (videoUrl) {
    avatarVideo.src = videoUrl;
    avatarVideo.style.display = "block";
    avatarImg.style.display = "none";
    avatarVideo.muted = true; // Muted for autoplay policy safety
    avatarVideo.loop = false;
    avatarVideo.play();
  }

  audioPlayer.onended = () => {
    stopSpeaking();
  };
}

function stopSpeaking() {
  isSpeaking = false;
  waveform.classList.remove("active");
  mouth.classList.remove("speaking");
  
  avatarVideo.pause();
  avatarVideo.style.display = "none";
  avatarImg.style.display = "block";
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

// Speech-to-Text Recognition (Web Speech API)
let recognition;
let isRecording = false;

if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.lang = "en-US";

  recognition.onstart = () => {
    isRecording = true;
    micBtn.classList.add("recording");
    chatInput.placeholder = "Listening...";
  };

  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    chatInput.value = transcript;
    chatInput.placeholder = "Enter your directive to the C-Suite...";
    handleSend();
  };

  recognition.onerror = (event) => {
    console.error("Speech recognition error:", event.error);
    stopRecording();
  };

  recognition.onend = () => {
    stopRecording();
  };

  function stopRecording() {
    isRecording = false;
    micBtn.classList.remove("recording");
    chatInput.placeholder = "Enter your directive to the C-Suite...";
  }

  micBtn.addEventListener("click", () => {
    if (isRecording) {
      recognition.stop();
    } else {
      recognition.start();
    }
  });
} else {
  micBtn.style.display = "none";
  console.log("Web Speech API not supported in this browser.");
}
