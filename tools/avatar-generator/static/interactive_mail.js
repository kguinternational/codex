// Interactive Avatar Mail Controller
// Supports both Sovereign Local AI (MuseTalk/LivePortrait/Kokoro) and Cloud (Tavus/HeyGen)

document.addEventListener("DOMContentLoaded", () => {
    // 1. Personalization from URL parameters
    const params = new URLSearchParams(window.location.search);
    const recipientName = params.get("name") || "Partner";
    const companyName = params.get("company") || "your company";
    
    const greetingTitle = document.getElementById("greeting-title");
    const greetingSub = document.getElementById("greeting-sub");
    
    greetingTitle.textContent = `Hello, ${recipientName}!`;
    greetingSub.textContent = `You are invited to speak directly with Joann Coffey's interactive digital twin about the Montserrat Volcanic-Geothermal Brine project and partnership opportunities.`;

    // 2. Elements and state
    const startBtn = document.getElementById("start-btn");
    const subtitlesBox = document.getElementById("subtitles");
    const videoElement = document.getElementById("avatar-video");
    const placeholder = document.getElementById("video-placeholder");
    const loader = document.getElementById("avatar-loader");
    const placeholderIcon = document.getElementById("placeholder-icon");
    const waveform = document.getElementById("waveform");
    
    // Mode Buttons
    const modeSovereignBtn = document.getElementById("mode-sovereign");
    const modeCloudBtn = document.getElementById("mode-cloud");
    let selectedMode = "sovereign"; // Default: Sovereign Local AI

    modeSovereignBtn.addEventListener("click", () => {
        if (isConnected) return; // Prevent changing mode during active session
        selectedMode = "sovereign";
        modeSovereignBtn.classList.add("active");
        modeCloudBtn.classList.remove("active");
        addLog("Switched to Sovereign Local AI Mode");
    });

    modeCloudBtn.addEventListener("click", () => {
        if (isConnected) return;
        selectedMode = "cloud";
        modeCloudBtn.classList.add("active");
        modeSovereignBtn.classList.remove("active");
        addLog("Switched to Cloud API Mode (HeyGen/Tavus)");
    });

    let isConnected = false;
    let isSpeaking = false;
    let mediaRecorder = null;
    let audioChunks = [];
    let peerConnection = null;
    let localStream = null;
    let audioContext = null;
    let analyser = null;
    let animationFrameId = null;
    
    // VAD settings for Sovereign Local Mode
    let silenceTimer = null;
    const SILENCE_THRESHOLD = 15; // Noise threshold
    const SILENCE_DURATION = 1500; // 1.5 seconds of silence to auto-send

    // 3. Main Action Button
    startBtn.addEventListener("click", async () => {
        if (isConnected) {
            disconnectSession();
        } else {
            await connectSession();
        }
    });

    // 4. Connection Handler
    async function connectSession() {
        startBtn.disabled = true;
        loader.style.display = "block";
        placeholderIcon.style.display = "none";
        subtitlesBox.textContent = "Initializing connection...";
        
        try {
            if (selectedMode === "sovereign") {
                await startSovereignLocalSession();
            } else {
                await startCloudSession();
            }
        } catch (error) {
            console.error("Connection failed:", error);
            subtitlesBox.textContent = `Connection failed: ${error.message}.`;
            resetUI();
        }
    }

    // ==========================================
    // SOVEREIGN LOCAL MODE
    // ==========================================
    async function startSovereignLocalSession() {
        addLog("Requesting microphone permissions...");
        localStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        
        // Hide placeholder, show video element for local rendering
        placeholder.style.display = "none";
        videoElement.style.display = "block";
        videoElement.src = "/static/animations/base_ceo.mp4";
        videoElement.muted = true;
        videoElement.loop = true;
        await videoElement.play();

        setupAudioAnalyzer(localStream);
        startWaveformAnimation();
        
        isConnected = true;
        startBtn.disabled = false;
        startBtn.querySelector("span").textContent = "End Conversation";
        startBtn.classList.add("recording");
        
        subtitlesBox.textContent = "Status: Sovereign Local Session active. Speak now, I am listening...";
        
        // Start recording the initial turn
        startRecordingTurn();
    }

    function startRecordingTurn() {
        if (!isConnected || isSpeaking) return;
        audioChunks = [];
        mediaRecorder = new MediaRecorder(localStream);
        mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0) audioChunks.push(event.data);
        };
        mediaRecorder.onstop = async () => {
            if (audioChunks.length > 0) {
                const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                await submitAudioToLocalPortal(audioBlob);
            }
        };
        mediaRecorder.start();
        addLog("Listening to your voice...");
    }

    async function submitAudioToLocalPortal(blob) {
        if (!isConnected) return;
        isSpeaking = true;
        subtitlesBox.textContent = "Status: Processing your query (STT, LLM & MuseTalk Rendering)...";
        
        const formData = new FormData();
        formData.append("file", blob, "recording.webm");
        formData.append("participant_id", recipientName);
        formData.append("client_id", "kgu-international");
        formData.append("persona", "ceo");

        try {
            const res = await fetch("/api/voice/portal", {
                method: "POST",
                body: formData
            });

            if (!res.ok) throw new Error("Local Portal returned an error");
            const data = await res.json();
            
            if (data.transcript) {
                console.log("Transcribed speech:", data.transcript);
            }

            if (data.reply) {
                subtitlesBox.textContent = `Joann (Digital Twin): "${data.reply}"`;
            }

            // Play the rendered lip-synced video output if available, else play audio
            if (data.video_url) {
                playLocalVideoOutput(data.video_url);
            } else if (data.audio_url) {
                playLocalAudioOutput(data.audio_url);
            } else {
                isSpeaking = false;
                startRecordingTurn();
            }
        } catch (err) {
            console.error("Local portal query failed:", err);
            subtitlesBox.textContent = "Error communicating with local AI engine. Resuming listening...";
            isSpeaking = false;
            startRecordingTurn();
        }
    }

    function playLocalVideoOutput(videoUrl) {
        videoElement.src = videoUrl;
        videoElement.muted = false;
        videoElement.loop = false;
        videoElement.play();
        
        videoElement.onended = () => {
            // Restore idle loop
            videoElement.src = "/static/animations/base_ceo.mp4";
            videoElement.muted = true;
            videoElement.loop = true;
            videoElement.play().catch(() => {});
            
            isSpeaking = false;
            startRecordingTurn();
        };
    }

    function playLocalAudioOutput(audioUrl) {
        const audio = new Audio(audioUrl);
        audio.play();
        audio.onended = () => {
            isSpeaking = false;
            startRecordingTurn();
        };
    }

    // ==========================================
    // CLOUD MODE (TAVUS & HEYGEN)
    // ==========================================
    async function startCloudSession() {
        addLog("Checking active Tavus Pal instances...");
        const palsRes = await fetch("/api/tavus/pals");
        
        if (palsRes.ok) {
            const pals = await palsRes.json();
            if (pals && pals.length > 0) {
                addLog(`Tavus active pal found: ${pals[0].pal_name}. Starting conversation...`);
                await startTavusConversation(pals[0].pal_id);
                return;
            }
        }
        
        addLog("Tavus not configured. Attempting connection to HeyGen Streaming API...");
        await startHeyGenStream();
    }

    async function startTavusConversation(palId) {
        const res = await fetch("/api/tavus/conversations", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                pal_id: palId,
                custom_greeting: `Hi ${recipientName}! Thank you for taking the time to speak with me. Let's talk about Montserrat.`,
                conversation_name: `Outreach Session for ${recipientName}`
            })
        });

        if (!res.ok) {
            const errData = await res.json();
            throw new Error(errData.detail || "Failed to create conversation.");
        }

        const data = await res.json();
        const callUrl = data.conversation_url;
        
        if (!callUrl) throw new Error("No conversation URL returned from Tavus.");

        placeholder.innerHTML = "";
        const iframe = document.createElement("iframe");
        iframe.src = callUrl;
        iframe.style.width = "100%";
        iframe.style.height = "100%";
        iframe.style.border = "none";
        iframe.allow = "microphone; camera";
        placeholder.appendChild(iframe);
        
        subtitlesBox.textContent = "Status: Conversational Video Stream Connected. You are now speaking with Joann's twin.";
        
        isConnected = true;
        startBtn.disabled = false;
        startBtn.querySelector("span").textContent = "End Conversation";
        startBtn.classList.add("recording");
        
        startWaveformAnimation();
    }

    async function startHeyGenStream() {
        const tokenRes = await fetch("/api/heygen/streaming/token", { method: "POST" });
        if (!tokenRes.ok) throw new Error("Failed to get HeyGen Streaming token from backend.");
        const { token } = await tokenRes.json();
        
        addLog("Obtained HeyGen Streaming token. Starting WebRTC session...");
        
        const newSessionRes = await fetch("https://api.heygen.com/v1/streaming.new", {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${token}`,
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                quality: "medium",
                avatar_name: "joann_avatar_id",
                voice: { voice_id: "default" }
            })
        });

        if (!newSessionRes.ok) throw new Error("HeyGen session initialization failed.");
        const sessionData = await newSessionRes.json();
        const { session_id, sdp, ice_servers } = sessionData.data;

        peerConnection = new RTCPeerConnection({ iceServers: ice_servers });
        
        localStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        localStream.getTracks().forEach(track => peerConnection.addTrack(track, localStream));

        await peerConnection.setRemoteDescription(new RTCSessionDescription(sdp));

        const answer = await peerConnection.createAnswer();
        await peerConnection.setLocalDescription(answer);

        await fetch("https://api.heygen.com/v1/streaming.answer", {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${token}`,
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ session_id, sdp: answer })
        });

        peerConnection.ontrack = (event) => {
            if (event.streams && event.streams[0]) {
                videoElement.srcObject = event.streams[0];
                videoElement.style.display = "block";
                placeholder.style.display = "none";
            }
        };

        peerConnection.onicecandidate = async (event) => {
            if (event.candidate) {
                await fetch("https://api.heygen.com/v1/streaming.candidate", {
                    method: "POST",
                    headers: {
                        "Authorization": `Bearer ${token}`,
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({ session_id, candidate: event.candidate })
                });
            }
        };

        subtitlesBox.textContent = `Status: HeyGen Stream Connected. Speak to Joann.`;
        isConnected = true;
        startBtn.disabled = false;
        startBtn.querySelector("span").textContent = "End Conversation";
        startBtn.classList.add("recording");
        
        setupAudioAnalyzer(localStream);
        startWaveformAnimation();
    }

    // ==========================================
    // AUDIO UTILITIES
    // ==========================================
    function setupAudioAnalyzer(stream) {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        analyser = audioContext.createAnalyser();
        const source = audioContext.createMediaStreamSource(stream);
        source.connect(analyser);
        analyser.fftSize = 64;
    }

    function startWaveformAnimation() {
        waveform.classList.add("active");
        const bars = document.querySelectorAll(".wave-bar");
        
        function animate() {
            animationFrameId = requestAnimationFrame(animate);
            
            if (analyser) {
                const dataArray = new Uint8Array(analyser.frequencyBinCount);
                analyser.getByteFrequencyData(dataArray);
                
                let sum = 0;
                bars.forEach((bar, idx) => {
                    const value = dataArray[idx % dataArray.length] || 0;
                    sum += value;
                    const height = Math.max(8, (value / 255) * 50);
                    bar.style.height = `${height}px`;
                });

                // Voice Activity Detection (Silence triggers submission)
                const averageVolume = sum / bars.length;
                if (selectedMode === "sovereign" && isConnected && !isSpeaking) {
                    if (averageVolume > SILENCE_THRESHOLD) {
                        // User is actively speaking, reset silence timer
                        if (silenceTimer) {
                            clearTimeout(silenceTimer);
                            silenceTimer = null;
                        }
                    } else {
                        // User is quiet, start silence timer to auto-send
                        if (!silenceTimer && mediaRecorder && mediaRecorder.state === "recording") {
                            silenceTimer = setTimeout(() => {
                                addLog("Silence detected. Generating response...");
                                mediaRecorder.stop();
                            }, SILENCE_DURATION);
                        }
                    }
                }
            } else {
                bars.forEach((bar) => {
                    const height = 8 + Math.sin(Date.now() * 0.005 + bar.offsetLeft) * 15;
                    bar.style.height = `${height}px`;
                });
            }
        }
        
        animate();
    }

    function disconnectSession() {
        addLog("Disconnecting current session...");
        
        if (peerConnection) {
            peerConnection.close();
            peerConnection = null;
        }

        if (mediaRecorder && mediaRecorder.state === "recording") {
            mediaRecorder.stop();
        }
        mediaRecorder = null;
        
        if (localStream) {
            localStream.getTracks().forEach(track => track.stop());
            localStream = null;
        }

        if (animationFrameId) {
            cancelAnimationFrame(animationFrameId);
            animationFrameId = null;
        }

        if (audioContext) {
            audioContext.close();
            audioContext = null;
            analyser = null;
        }

        if (silenceTimer) {
            clearTimeout(silenceTimer);
            silenceTimer = null;
        }

        // Restore original video placeholder
        placeholder.innerHTML = `
            <div class="avatar-loader" id="avatar-loader"></div>
            <svg id="placeholder-icon" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="feather feather-user" style="color: var(--primary-glow);">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                <circle cx="12" cy="7" r="4"></circle>
            </svg>
            <p id="placeholder-text" style="font-weight: 500;">Interactive Digital Twin is offline</p>
            <p style="font-size: 0.85rem; color: rgba(255,255,255,0.4);">Click \"Start Conversation\" below to connect WebRTC stream</p>
        `;
        
        videoElement.srcObject = null;
        videoElement.src = "";
        videoElement.style.display = "none";
        placeholder.style.display = "flex";

        resetUI();
    }

    function resetUI() {
        isConnected = false;
        isSpeaking = false;
        startBtn.disabled = false;
        startBtn.querySelector("span").textContent = "Start Conversation";
        startBtn.classList.remove("recording");
        waveform.classList.remove("active");
        
        const bars = document.querySelectorAll(".wave-bar");
        bars.forEach(bar => bar.style.height = "8px");
        
        subtitlesBox.textContent = "Status: Connection Idle. Click \"Start Conversation\" to begin.";
    }

    function addLog(msg) {
        console.log(`[Interactive Avatar] ${msg}`);
        subtitlesBox.textContent = `Status: ${msg}`;
    }
});
