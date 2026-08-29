// Resilience Twin Configurator Admin JavaScript

let currentClientId = null;
let currentTesterRole = null;
let statusPollInterval = null;

// DOM Elements
const authBox = document.getElementById('auth-box');
const authForm = document.getElementById('auth-form');
const authTitle = document.getElementById('auth-title');
const authSubtitle = document.getElementById('auth-subtitle');
const authSubmitBtn = document.getElementById('auth-submit-btn');
const authError = document.getElementById('auth-error');
const usernameInput = document.getElementById('username');
const passwordInput = document.getElementById('password');

const dashboardBox = document.getElementById('dashboard-box');
const adminUserDisplay = document.getElementById('admin-user-display');
const logoutBtn = document.getElementById('logout-btn');
const clientListContainer = document.getElementById('client-list-container');
const addClientBtn = document.getElementById('add-client-btn');
const deleteClientBtn = document.getElementById('delete-client-btn');

const activeClientTitle = document.getElementById('active-client-title');
const activeClientSubtitle = document.getElementById('active-client-subtitle');
const activeQueueBanner = document.getElementById('active-queue-banner');
const queueCountEl = document.getElementById('queue-count');
const personasContainer = document.getElementById('personas-container');

// Client Modal Elements
const createClientModal = document.getElementById('create-client-modal');
const cancelClientBtn = document.getElementById('cancel-client-btn');
const submitClientBtn = document.getElementById('submit-client-btn');
const modalError = document.getElementById('modal-error');
const newClientIdInput = document.getElementById('new-client-id');
const newClientNameInput = document.getElementById('new-client-name');
const newClientEmailInput = document.getElementById('new-client-email');
const newClientStripeInput = document.getElementById('new-client-stripe');

// Tester Elements
const testerDrawer = document.getElementById('tester-drawer');
const closeTesterBtn = document.getElementById('close-tester-btn');
const testerTitle = document.getElementById('tester-title');
const testerPreviewImg = document.getElementById('tester-preview-img');
const testerPreviewVideo = document.getElementById('tester-preview-video');
const testerChatHistory = document.getElementById('tester-chat-history');
const testerChatInput = document.getElementById('tester-chat-input');
const testerSendBtn = document.getElementById('tester-send-btn');

// Startup sequence
document.addEventListener('DOMContentLoaded', () => {
  checkAuth();
  setupEventListeners();
});

// Event Listeners Setup
function setupEventListeners() {
  authForm.addEventListener('submit', handleAuthSubmit);
  logoutBtn.addEventListener('click', handleLogout);
  addClientBtn.addEventListener('click', () => {
    modalError.style.display = 'none';
    createClientModal.style.display = 'flex';
  });
  cancelClientBtn.addEventListener('click', () => {
    createClientModal.style.display = 'none';
  });
  submitClientBtn.addEventListener('click', handleCreateClient);
  deleteClientBtn.addEventListener('click', handleDeleteClient);
  
  // Normalize Client ID slug input on the fly
  newClientIdInput.addEventListener('input', (e) => {
    e.target.value = e.target.value
      .toLowerCase()
      .replace(/[^a-z0-9-_]/g, '-')
      .replace(/-+/g, '-');
  });

  closeTesterBtn.addEventListener('click', () => {
    testerDrawer.style.display = 'none';
    testerPreviewVideo.pause();
    testerPreviewVideo.src = "";
  });
  testerSendBtn.addEventListener('click', handleTesterSend);
  testerChatInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') handleTesterSend();
  });
  
  // Pause tester video on input focus (Active Interruption)
  testerChatInput.addEventListener('focus', () => {
    testerPreviewVideo.pause();
  });

  // Custom drag & drop feedback
  const personas = ['ceo', 'cto', 'cmo', 'clo', 'cfo', 'cgo'];
  personas.forEach(role => {
    const fileInput = document.getElementById(`file-input-${role}`);
    const dropzone = document.getElementById(`dropzone-${role}`);
    
    if (fileInput && dropzone) {
      fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
          uploadAvatarFile(role, e.target.files[0]);
        }
      });

      // Implement native Drag and Drop functionality
      ['dragenter', 'dragover'].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
          e.preventDefault();
          e.stopPropagation();
          dropzone.style.borderColor = 'var(--accent-secondary)';
          dropzone.style.background = 'rgba(0, 242, 254, 0.04)';
        }, false);
      });

      ['dragleave', 'drop'].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
          e.preventDefault();
          e.stopPropagation();
          dropzone.style.borderColor = 'var(--glass-border)';
          dropzone.style.background = 'rgba(0,0,0,0.1)';
        }, false);
      });

      dropzone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        if (files.length > 0) {
          uploadAvatarFile(role, files[0]);
        }
      }, false);
    }
    
    // Save info btn listener
    const card = document.querySelector(`.persona-card[data-persona="${role}"]`);
    if (card) {
      const saveBtn = card.querySelector('.save-card-btn');
      saveBtn.addEventListener('click', () => saveAvatarDetails(role));
      
      const testBtn = card.querySelector('.test-card-btn');
      testBtn.addEventListener('click', () => openTester(role));
    }
  });
}

// Authentication Check
async function checkAuth() {
  try {
    const res = await fetch('/api/auth/me');
    if (res.ok) {
      const data = await res.json();
      showDashboard(data.username);
    } else {
      showLoginScreen();
    }
  } catch (err) {
    showLoginScreen();
  }
}

async function showLoginScreen() {
  authBox.style.display = 'flex';
  dashboardBox.style.display = 'none';
  logoutBtn.style.display = 'none';
  
  try {
    const res = await fetch('/api/auth/status');
    const data = await res.json();
    if (!data.has_admin) {
      authTitle.textContent = "Register First Admin";
      authSubtitle.textContent = "Database contains 0 admin accounts. Register your main administrator login details.";
      authSubmitBtn.textContent = "Create Account";
      authForm.dataset.mode = "register";
    } else {
      authTitle.textContent = "Admin Console";
      authSubtitle.textContent = "Verify your administrative keynotes";
      authSubmitBtn.textContent = "Sign In";
      authForm.dataset.mode = "login";
    }
  } catch (err) {
    console.error("Failed to fetch auth status", err);
  }
}

function showDashboard(username) {
  authBox.style.display = 'none';
  dashboardBox.style.display = 'grid';
  logoutBtn.style.display = 'inline-block';
  adminUserDisplay.textContent = `admin: ${username}`;
  loadClients();
  startGlobalQueuePolling();
}

// Handler Auth Submit
async function handleAuthSubmit(e) {
  if (e && typeof e.preventDefault === 'function') e.preventDefault();
  
  const username = usernameInput.value.trim();
  const password = passwordInput.value;
  const mode = authForm.dataset.mode || "login";
  
  authError.style.display = 'none';
  
  const endpoint = mode === "register" ? "/api/auth/register-first" : "/api/auth/login";
  
  try {
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });
    
    if (res.ok) {
      if (mode === "register") {
        // Auto log in after register
        authForm.dataset.mode = "login";
        handleAuthSubmit();
      } else {
        const data = await res.json();
        showDashboard(data.username);
      }
    } else {
      const errData = await res.json();
      authError.textContent = errData.detail || "Authentication failed.";
      authError.style.display = 'block';
    }
  } catch (err) {
    authError.textContent = "Connection failed.";
    authError.style.display = 'block';
  }
}

async function handleLogout() {
  await fetch('/api/auth/logout', { method: 'POST' });
  stopStatusPolling();
  location.reload();
}

// Client Management API calls
async function loadClients() {
  try {
    const res = await fetch('/api/admin/clients');
    if (!res.ok) throw new Error();
    const clients = await res.json();
    
    clientListContainer.innerHTML = "";
    if (clients.length === 0) {
      clientListContainer.innerHTML = '<div style="text-align: center; color: var(--text-muted); padding: 1.5rem 0;">No clients active.</div>';
      return;
    }
    
    clients.forEach(c => {
      const item = document.createElement('div');
      item.className = 'client-item';
      if (c.client_id === currentClientId) item.classList.add('active');
      
      item.innerHTML = `
        <div class="client-item-info">
          <h4>${escapeHTML(c.name)}</h4>
          <p>${escapeHTML(c.client_id)}</p>
        </div>
        <span class="badge badge-${c.status}">${escapeHTML(c.status)}</span>
      `;
      
      item.addEventListener('click', () => selectClient(c));
      clientListContainer.appendChild(item);
    });
  } catch (err) {
    console.error("Failed to load clients", err);
  }
}

async function handleCreateClient() {
  const client_id = newClientIdInput.value.trim().toLowerCase();
  const name = newClientNameInput.value.trim();
  const email = newClientEmailInput.value.trim();
  const stripe_subscription_id = newClientStripeInput.value.trim();
  
  modalError.style.display = 'none';
  if (!client_id || !name) {
    modalError.textContent = "Client ID and Company Name are required.";
    modalError.style.display = 'block';
    return;
  }
  
  try {
    const res = await fetch('/api/admin/clients', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_id, name, email, stripe_subscription_id })
    });
    
    if (res.ok) {
      createClientModal.style.display = 'none';
      newClientIdInput.value = "";
      newClientNameInput.value = "";
      newClientEmailInput.value = "";
      newClientStripeInput.value = "";
      loadClients();
    } else {
      const err = await res.json();
      modalError.textContent = err.detail || "Failed to create client.";
      modalError.style.display = 'block';
    }
  } catch (err) {
    modalError.textContent = "Network error.";
    modalError.style.display = 'block';
  }
}

async function handleDeleteClient() {
  if (!currentClientId) return;
  if (!confirm(`Are you absolutely sure you want to delete client '${currentClientId}'? This will wipe all their custom profile videos and images.`)) return;
  
  try {
    const res = await fetch(`/api/admin/clients/${currentClientId}`, {
      method: 'DELETE'
    });
    if (res.ok) {
      currentClientId = null;
      activeClientTitle.textContent = "Select a Client";
      activeClientSubtitle.textContent = "Configure avatar layers and model bindings";
      deleteClientBtn.style.display = 'none';
      personasContainer.style.display = 'none';
      stopStatusPolling();
      loadClients();
    }
  } catch (err) {
    alert("Deletion failed.");
  }
}

// Client Profile Workspace
function selectClient(client) {
  currentClientId = client.client_id;
  activeClientTitle.textContent = client.name;
  activeClientSubtitle.textContent = `Client ID: ${client.client_id} | Email: ${client.email || 'None'}`;
  deleteClientBtn.style.display = 'block';
  personasContainer.style.display = 'grid';
  
  // Highlight active client item
  document.querySelectorAll('.client-item').forEach(item => {
    item.classList.remove('active');
    if (item.querySelector('p').textContent === client.client_id) {
      item.classList.add('active');
    }
  });
  
  loadClientAvatars();
  startStatusPolling();
}

async function loadClientAvatars() {
  if (!currentClientId) return;
  
  try {
    const res = await fetch(`/api/admin/clients/${currentClientId}/avatars`);
    if (!res.ok) return;
    const avatars = await res.json();
    
    let anyProcessing = false;
    
    Object.keys(avatars).forEach(role => {
      const data = avatars[role];
      updatePersonaCardUI(role, data);
      
      if (data.status === 'queued' || data.status === 'processing') {
        anyProcessing = true;
      }
    });
    
    // Toggle active polling if something is rendering
    if (anyProcessing) {
      startStatusPolling();
    } else {
      stopStatusPolling();
    }
  } catch (err) {
    console.error("Failed to load client avatars", err);
  }
}

function updatePersonaCardUI(role, data) {
  const card = document.querySelector(`.persona-card[data-persona="${role}"]`);
  if (!card) return;
  
  // Update name & bio inputs if they are not currently being focused
  const nameInput = card.querySelector(`#name-input-${role}`);
  const bioInput = card.querySelector(`#bio-input-${role}`);
  if (document.activeElement !== nameInput) {
    nameInput.value = data.name || "";
  }
  if (document.activeElement !== bioInput) {
    bioInput.value = data.bio || "";
  }
  
  // Update sliders
  const scaleInput = card.querySelector(`#scale-input-${role}`);
  const vyInput = card.querySelector(`#vy-input-${role}`);
  const scaleVal = card.querySelector(`#scale-val-${role}`);
  const vyVal = card.querySelector(`#vy-val-${role}`);
  
  if (scaleInput && vyInput) {
    const scale = data.scale !== undefined && data.scale !== null ? data.scale : 2.3;
    const vyRatio = data.vy_ratio !== undefined && data.vy_ratio !== null ? data.vy_ratio : -0.125;
    
    // Only update values if the user is not actively dragging the slider
    if (document.activeElement !== scaleInput) {
      scaleInput.value = scale;
      if (scaleVal) scaleVal.textContent = scale;
    }
    if (document.activeElement !== vyInput) {
      vyInput.value = vyRatio;
      if (vyVal) vyVal.textContent = vyRatio;
    }
  }
  
  // Update status indicator
  const dot = card.querySelector(`#status-dot-${role}`);
  const text = card.querySelector(`#status-text-${role}`);
  dot.className = `status-dot ${data.status}`;
  
  let statusLabel = data.status.toUpperCase();
  if (data.status === 'failed' && data.error_message) {
    statusLabel += ` (Error: ${data.error_message.slice(0, 30)}...)`;
  }
  text.textContent = statusLabel;
  
  // Update Preview Image box
  const previewBox = card.querySelector(`#preview-box-${role}`);
  if (data.image_path) {
    previewBox.innerHTML = `<img src="${data.image_path}?t=${new Date().getTime()}" alt="${role}">`;
  } else {
    previewBox.innerHTML = `<span class="placeholder-icon">👤</span>`;
  }
  
  // Enable / Disable Test button
  const testBtn = card.querySelector(`#test-btn-${role}`);
  if (data.status === 'complete' && data.video_path) {
    testBtn.disabled = false;
    testBtn.classList.remove('btn-secondary');
    testBtn.classList.add('btn-primary');
  } else {
    testBtn.disabled = true;
    testBtn.classList.remove('btn-primary');
    testBtn.classList.add('btn-secondary');
  }
}

// Save Card details (name / bio / crop parameters)
async function saveAvatarDetails(role) {
  if (!currentClientId) return;
  
  const name = document.getElementById(`name-input-${role}`).value.trim();
  const bio = document.getElementById(`bio-input-${role}`).value.trim();
  const scale = document.getElementById(`scale-input-${role}`).value;
  const vyRatio = document.getElementById(`vy-input-${role}`).value;
  
  const formData = new FormData();
  formData.append('persona', role);
  formData.append('name', name);
  formData.append('bio', bio);
  formData.append('scale', scale);
  formData.append('vy_ratio', vyRatio);
  
  try {
    const res = await fetch(`/api/admin/clients/${currentClientId}/avatars`, {
      method: 'POST',
      body: formData
    });
    if (res.ok) {
      alert(`${role.toUpperCase()} Twin configuration details saved!`);
      loadClientAvatars();
    } else {
      alert("Failed to save details.");
    }
  } catch (err) {
    alert("Network error.");
  }
}

// Upload Avatar file
async function uploadAvatarFile(role, file) {
  if (!currentClientId) return;
  
  const name = document.getElementById(`name-input-${role}`).value.trim();
  const bio = document.getElementById(`bio-input-${role}`).value.trim();
  const scale = document.getElementById(`scale-input-${role}`).value;
  const vyRatio = document.getElementById(`vy-input-${role}`).value;
  
  const formData = new FormData();
  formData.append('persona', role);
  formData.append('name', name);
  formData.append('bio', bio);
  formData.append('image', file);
  formData.append('scale', scale);
  formData.append('vy_ratio', vyRatio);
  
  // Update visual indicators instantly to Queued
  const dot = document.getElementById(`status-dot-${role}`);
  const text = document.getElementById(`status-text-${role}`);
  dot.className = `status-dot queued`;
  text.textContent = "QUEUING PORTRAIT...";
  
  try {
    const res = await fetch(`/api/admin/clients/${currentClientId}/avatars`, {
      method: 'POST',
      body: formData
    });
    
    if (res.ok) {
      loadClientAvatars();
      startStatusPolling();
    } else {
      const err = await res.json();
      alert(err.detail || "Failed to upload avatar image.");
      loadClientAvatars();
    }
  } catch (err) {
    alert("Upload failed.");
    loadClientAvatars();
  }
}

// Polling loops
function startStatusPolling() {
  if (statusPollInterval) return;
  statusPollInterval = setInterval(loadClientAvatars, 3000);
}

function stopStatusPolling() {
  if (statusPollInterval) {
    clearInterval(statusPollInterval);
    statusPollInterval = null;
  }
}

function startGlobalQueuePolling() {
  setInterval(async () => {
    try {
      const res = await fetch('/api/admin/queue/status');
      if (res.ok) {
        const data = await res.json();
        if (data.queue_size > 0) {
          activeQueueBanner.style.display = 'flex';
          queueCountEl.textContent = data.queue_size;
        } else {
          activeQueueBanner.style.display = 'none';
        }
      }
    } catch(e) {}
  }, 3000);
}

// Drawer Tester
async function openTester(role) {
  currentTesterRole = role;
  testerTitle.textContent = `Test Client Twin (${role.toUpperCase()})`;
  testerChatHistory.innerHTML = '<div class="chat-bubble chat-bubble-ai">Ready! Send a prompt to test your C-Suite twin.</div>';
  
  try {
    const res = await fetch(`/api/admin/clients/${currentClientId}/avatars`);
    const avatars = await res.json();
    const avatar = avatars[role];
    
    if (avatar.image_path) {
      testerPreviewImg.src = avatar.image_path + '?t=' + new Date().getTime();
    } else {
      testerPreviewImg.src = "/static/images/ceo.png";
    }
    testerPreviewImg.style.display = 'block';
    
    testerPreviewVideo.style.display = 'none';
    testerDrawer.style.display = 'flex';
  } catch (e) {
    alert("Failed to initialize tester.");
  }
}

async function handleTesterSend() {
  const msg = testerChatInput.value.trim();
  if (!msg) return;
  
  testerChatInput.value = "";
  appendTestBubble('user', msg);
  
  const aiBubble = appendTestBubble('ai', 'Generating speech & mapping facial animation on RTX 2080...');
  
  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: msg,
        personality: currentTesterRole,
        client_id: currentClientId
      })
    });
    
    if (res.ok) {
      const data = await res.json();
      aiBubble.textContent = data.text;
      
      if (data.video_url) {
        testerPreviewImg.style.display = 'none';
        testerPreviewVideo.src = data.video_url;
        testerPreviewVideo.style.display = 'block';
        testerPreviewVideo.play();
      }
    } else {
      aiBubble.textContent = "Error communicating with twin backend.";
    }
  } catch (err) {
    aiBubble.textContent = "Network error communicating with local nodes.";
  }
}

function appendTestBubble(sender, text) {
  const bubble = document.createElement('div');
  bubble.className = `chat-bubble chat-bubble-${sender === 'user' ? 'user' : 'ai'}`;
  bubble.textContent = text;
  testerChatHistory.appendChild(bubble);
  testerChatHistory.scrollTop = testerChatHistory.scrollHeight;
  return bubble;
}

// Utility Helpers
function escapeHTML(str) {
  if (!str) return '';
  return str.replace(/[&<>'"]/g, 
    tag => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      "'": '&#39;',
      '"': '&quot;'
    }[tag] || tag)
  );
}
