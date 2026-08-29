import os
import sys
import uuid
from datetime import datetime
import asyncio
import subprocess
import time
import sqlite3
# Patch sqlite3 to default to 30s timeout to prevent locking under enterprise concurrency
_original_connect = sqlite3.connect
def _custom_connect(*args, **kwargs):
    if "timeout" not in kwargs:
        kwargs["timeout"] = 30.0
    return _original_connect(*args, **kwargs)
sqlite3.connect = _custom_connect

import hashlib
import secrets
import shutil
import json
from typing import Optional, List, Dict
from fastapi import FastAPI, HTTPException, Depends, Cookie, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
import httpx
import soundfile as sf

def load_env():
    paths = [
        os.path.join(os.path.expanduser("~"), ".env"),
        os.path.join(os.path.dirname(__file__), ".env")
    ]
    for env_path in paths:
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, val = line.split("=", 1)
                        os.environ[key.strip()] = val.strip().strip('"').strip("'")

async def get_local_llm_info(client: httpx.AsyncClient) -> tuple[str, str]:
    """Pings local LLM runners (LM Studio on port 1235, Ollama on port 11434) and returns the base URL and active model name."""
    # 1. Try LM Studio on port 1235
    try:
        res = await client.get("http://127.0.0.1:1235/v1/models")
        if res.status_code == 200:
            data = res.json()
            if data.get("data") and len(data["data"]) > 0:
                model_ids = [m["id"] for m in data["data"]]
                active_model = "qwen2.5-1.5b-instruct" if "qwen2.5-1.5b-instruct" in model_ids else model_ids[0]
                return "http://127.0.0.1:1235/v1", active_model
    except Exception:
        pass

    # 2. Try Ollama on port 11434 (OpenAI-compatible)
    try:
        res = await client.get("http://127.0.0.1:11434/v1/models")
        if res.status_code == 200:
            data = res.json()
            if data.get("data") and len(data["data"]) > 0:
                model_ids = [m["id"] for m in data["data"]]
                return "http://127.0.0.1:11434/v1", model_ids[0]
    except Exception:
        pass

    # 3. Fallback default
    return "http://127.0.0.1:1235/v1", "qwen2.5-1.5b-instruct"

DB_PATH = os.path.join(os.path.dirname(__file__), "avatar_generator.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    
    # users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL
    );
    """)
    
    # sessions table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        expires_at REAL NOT NULL,
        FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE
    );
    """)
    
    # clients table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        client_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT,
        status TEXT DEFAULT 'active',
        stripe_subscription_id TEXT
    );
    """)
    
    # client_avatars table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS client_avatars (
        client_id TEXT NOT NULL,
        persona TEXT NOT NULL,
        name TEXT,
        bio TEXT,
        image_path TEXT,
        video_path TEXT,
        status TEXT DEFAULT 'pending',
        error_message TEXT,
        PRIMARY KEY (client_id, persona),
        FOREIGN KEY (client_id) REFERENCES clients(client_id) ON DELETE CASCADE
    );
    """)
    
    # tavus_pals table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tavus_pals (
        pal_id TEXT PRIMARY KEY,
        pal_name TEXT NOT NULL,
        system_prompt TEXT NOT NULL,
        pipeline_mode TEXT NOT NULL,
        default_face_id TEXT NOT NULL,
        conferencing_email TEXT,
        created_at TEXT NOT NULL
    );
    """)
    
    # liveavatar_embeddings table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS liveavatar_embeddings (
        embed_id TEXT PRIMARY KEY,
        avatar_id TEXT NOT NULL,
        context_id TEXT,
        url TEXT NOT NULL,
        script TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """)
    
    # avatar_knowledge_bases table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS avatar_knowledge_bases (
        doc_id TEXT PRIMARY KEY,
        client_id TEXT NOT NULL,
        persona TEXT NOT NULL,
        filename TEXT NOT NULL,
        file_path TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """)
    
    # participant_appointments table for Sistrunk homeless digital twin outreach
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS participant_appointments (
        app_id TEXT PRIMARY KEY,
        participant_id TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        location TEXT,
        appointment_time TEXT NOT NULL,
        status TEXT DEFAULT 'scheduled',
        created_at TEXT NOT NULL
    );
    """)
    
    # participant_documents table for storing credentials/IDs in sovereign local vault
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS participant_documents (
        doc_id TEXT PRIMARY KEY,
        participant_id TEXT NOT NULL,
        document_type TEXT NOT NULL,
        filename TEXT NOT NULL,
        file_path TEXT NOT NULL,
        uploaded_at TEXT NOT NULL
    );
    """)
    conn.commit()
    
    # DB migration: Add scale and vy_ratio columns if they don't exist
    try:
        cursor.execute("ALTER TABLE client_avatars ADD COLUMN scale REAL DEFAULT 2.3;")
        cursor.execute("ALTER TABLE client_avatars ADD COLUMN vy_ratio REAL DEFAULT -0.125;")
        conn.commit()
    except sqlite3.OperationalError:
        pass # Ignore error if columns already exist
        
    conn.close()

def hash_password(password: str, salt: str = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_hex(16)
    pw_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    ).hex()
    return pw_hash, salt

def verify_password(password: str, pw_hash: str, salt: str) -> bool:
    expected_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(pw_hash, expected_hash)

async def get_current_user(session_id: Optional[str] = Cookie(None)):
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT username, expires_at FROM sessions WHERE session_id = ?",
        (session_id,)
    )
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    username, expires_at = row
    if time.time() > expires_at:
        # Session expired, delete it
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.commit()
        conn.close()
        raise HTTPException(status_code=401, detail="Session expired")
        
    return username

# Background task queue for LivePortrait rendering
generation_queue = asyncio.Queue()

async def queue_worker():
    print("LivePortrait background worker started.")
    while True:
        task = await generation_queue.get()
        client_id = task["client_id"]
        persona = task["persona"]
        image_path = task["image_path"]
        
        print(f"Worker picked up job: client={client_id}, persona={persona}")
        
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE client_avatars SET status = 'processing', error_message = NULL WHERE client_id = ? AND persona = ?",
                (client_id, persona)
            )
            conn.commit()
            conn.close()
            
            # Retrieve custom crop scale and y-shift from database
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT scale, vy_ratio FROM client_avatars WHERE client_id = ? AND persona = ?",
                (client_id, persona)
            )
            row = cursor.fetchone()
            scale = row[0] if (row and row[0] is not None) else 2.3
            vy_ratio = row[1] if (row and row[1] is not None) else -0.125
            conn.close()

            client_dir = os.path.join(os.path.dirname(__file__), "static", "uploads", client_id, persona)
            os.makedirs(client_dir, exist_ok=True)
            
            python_exe = os.path.join(os.path.dirname(__file__), ".venv", "Scripts", "python.exe")
            inference_py = os.path.join(os.path.dirname(__file__), "LivePortrait", "inference.py")
            
            expressions = {
                "neutral": "talking.pkl",
                "happy": "laugh.pkl",
                "serious": "aggrieved.pkl",
                "thoughtful": "shy.pkl"
            }
            
            video_url = None
            
            for expr_name, pkl_file in expressions.items():
                driving_pkl = os.path.join(os.path.dirname(__file__), "LivePortrait", "assets", "examples", "driving", pkl_file)
                pkl_no_ext = os.path.splitext(pkl_file)[0]
                
                expected_output = os.path.join(client_dir, f"portrait--{pkl_no_ext}.mp4")
                expected_concat = os.path.join(client_dir, f"portrait--{pkl_no_ext}_concat.mp4")
                
                suffix = "" if expr_name == "neutral" else f"_{expr_name}"
                final_video_path = os.path.join(client_dir, f"base{suffix}.mp4")
                
                for path in [expected_output, expected_concat, final_video_path]:
                    if os.path.exists(path):
                        try: os.remove(path)
                        except: pass
                
                cmd = [
                    python_exe,
                    inference_py,
                    "-s", image_path,
                    "-d", driving_pkl,
                    "-o", client_dir,
                    "--flag_do_crop",
                    "--flag-pasteback",
                    "--flag-stitching",
                    "--source-max-dim", "1920",
                    "--scale", str(scale),
                    "--vy-ratio", str(vy_ratio),
                    "--flag-normalize-lip"
                ]
                
                print(f"Running LivePortrait command for {expr_name}: {' '.join(cmd)}")
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                env.pop("PYTHONPATH", None)
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=os.path.dirname(__file__),
                    env=env
                )
                stdout, stderr = await process.communicate()
                
                if process.returncode != 0:
                    raise RuntimeError(stderr.decode())
                
                if os.path.exists(expected_concat):
                    try: os.remove(expected_concat)
                    except: pass
                
                if os.path.exists(expected_output):
                    os.rename(expected_output, final_video_path)
                    if expr_name == "neutral":
                        video_url = f"/static/uploads/{client_id}/{persona}/base.mp4"
                else:
                    raise FileNotFoundError(f"Expected LivePortrait output file not found: {expected_output}")
            
            if video_url:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE client_avatars SET status = 'complete', video_path = ? WHERE client_id = ? AND persona = ?",
                    (video_url, client_id, persona)
                )
                conn.commit()
                conn.close()
                print(f"LivePortrait base videos (all expressions) generated successfully for client={client_id}, persona={persona}")
                
        except Exception as e:
            error_msg = str(e)
            print(f"Error generating base video for client={client_id}, persona={persona}: {error_msg}")
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE client_avatars SET status = 'failed', error_message = ? WHERE client_id = ? AND persona = ?",
                (error_msg, client_id, persona)
            )
            conn.commit()
            conn.close()
            
        finally:
            generation_queue.task_done()

# Global Kokoro instance
kokoro_model = None

# Voice ID mappings for local Kokoro and online ElevenLabs
KOKORO_VOICES = {
    "ceo": "bf_emma",
    "cto": "af_bella",
    "cmo": "af_sarah",
    "clo": "af_nicole",
    "cfo": "af_nicole",
    "cgo": "af_sky"
}

ELEVENLABS_VOICES = {
    "ceo": "EXAVITQu4vr4xnSDxMaL",  # Bella (highly engaging female)
    "cto": "AZnzlk1XvdvUeBnXmlld",  # Domi
    "cmo": "pNInz6obpgfrhhF21eyL",  # Rachel
    "clo": "ThT52A15Mpc5rgh41eyL",  # Nicole
    "cfo": "ThT52A15Mpc5rgh41eyL",  # Nicole
    "cgo": "EXAVITQu4vr4xnSDxMaL"   # Bella
}

def get_voice_id(persona: str) -> str:
    env_var = f"ELEVENLABS_{persona.upper()}_VOICE_ID"
    env_val = os.environ.get(env_var)
    if env_val:
        return env_val
    return ELEVENLABS_VOICES.get(persona, "EXAVITQu4vr4xnSDxMaL")

app = FastAPI(title="KGU C-Suite Interactive Avatar")

@app.on_event("startup")
async def startup_event():
    global kokoro_model
    init_db()
    load_env()
    
    # Load Kokoro model
    try:
        model_path = os.path.join(os.path.dirname(__file__), "kokoro-v1.0.onnx")
        voices_path = os.path.join(os.path.dirname(__file__), "voices-v1.0.bin")
        if os.path.exists(model_path) and os.path.exists(voices_path):
            from kokoro_onnx import Kokoro
            kokoro_model = Kokoro(model_path, voices_path)
            print("Loaded Kokoro TTS model successfully.")
        else:
            print("Warning: Kokoro model files not found. Local Kokoro fallback will be unavailable.")
    except Exception as e:
        print(f"Failed to load Kokoro ONNX model: {e}")
        
    asyncio.create_task(queue_worker())
    
    # Auto-scan database for queued avatars and put them in generation_queue
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT client_id, persona, image_path FROM client_avatars WHERE status = 'queued'")
        rows = cursor.fetchall()
        conn.close()
        for row in rows:
            client_id, persona, image_path = row[0], row[1], row[2]
            if image_path:
                relative_path = image_path.lstrip("/")
                physical_path = os.path.join(os.path.dirname(__file__), relative_path.replace("/", os.sep))
                if os.path.exists(physical_path):
                    await generation_queue.put({
                        "client_id": client_id,
                        "persona": persona,
                        "image_path": physical_path
                    })
                    print(f"Auto-queued pending avatar render on startup: client={client_id}, persona={persona}")
    except Exception as e:
        print(f"Error auto-queueing pending avatars on startup: {e}")



# Allow CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- WEBRTC SIGNALLING FOR REMOTE CLIENTS ---
class ConnectionManager:
    def __init__(self):
        # Maps client_id to a dict of {peer_id: WebSocket}
        self.active_connections: Dict[str, Dict[str, WebSocket]] = {}

    async def connect(self, websocket: WebSocket, client_id: str, peer_id: str):
        await websocket.accept()
        if client_id not in self.active_connections:
            self.active_connections[client_id] = {}
        self.active_connections[client_id][peer_id] = websocket
        
        # Notify existing peers that a new peer joined
        await self.broadcast(
            client_id, 
            {"type": "peer-joined", "peer_id": peer_id}, 
            exclude_peer=peer_id
        )

    def disconnect(self, client_id: str, peer_id: str):
        if client_id in self.active_connections and peer_id in self.active_connections[client_id]:
            del self.active_connections[client_id][peer_id]
            if not self.active_connections[client_id]:
                del self.active_connections[client_id]

    async def send_to_peer(self, client_id: str, peer_id: str, message: dict):
        if client_id in self.active_connections and peer_id in self.active_connections[client_id]:
            try:
                await self.active_connections[client_id][peer_id].send_json(message)
            except:
                pass

    async def broadcast(self, client_id: str, message: dict, exclude_peer: str = None):
        if client_id in self.active_connections:
            for peer_id, connection in self.active_connections[client_id].items():
                if peer_id != exclude_peer:
                    try:
                        await connection.send_json(message)
                    except:
                        pass

manager = ConnectionManager()

@app.websocket("/api/ws/signal/{client_id}/{peer_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str, peer_id: str):
    await manager.connect(websocket, client_id, peer_id)
    try:
        while True:
            data = await websocket.receive_json()
            target_peer = data.get("target_peer")
            if target_peer:
                # Forward to targeted peer
                await manager.send_to_peer(client_id, target_peer, {
                    "sender": peer_id,
                    "type": data.get("type"),
                    "payload": data.get("payload")
                })
            else:
                # Broadcast
                await manager.broadcast(client_id, {
                    "sender": peer_id,
                    "type": data.get("type"),
                    "payload": data.get("payload")
                }, exclude_peer=peer_id)
    except WebSocketDisconnect:
        manager.disconnect(client_id, peer_id)
        await manager.broadcast(client_id, {
            "type": "peer-left",
            "peer_id": peer_id
        })

# --- SUPABASE PROJECT RESILIENCE INTEGRATION ---
class SupabaseResilienceHelper:
    def __init__(self):
        hipaa_mode = os.environ.get("HIPAA_COMPLIANCE_MODE", "false").lower() == "true"
        self.url = os.environ.get("SUPABASE_URL") if not hipaa_mode else None
        self.key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") if not hipaa_mode else None
        self.headers = {
            "apikey": self.key or "",
            "Authorization": f"Bearer {self.key}" if self.key else "",
            "Content-Type": "application/json"
        }
        
    def is_configured(self) -> bool:
        return bool(self.url and self.key)

    async def get_families(self) -> list:
        if not self.is_configured():
            return [{"id": "mock-family-uuid", "name": "Resilience Family (Sovereign)", "metadata": {}}]
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(f"{self.url}/rest/v1/families?select=*", headers=self.headers, timeout=5.0)
                if res.status_code == 200:
                    return res.json()
        except Exception as e:
            print(f"Supabase families query failed: {e}")
        return [{"id": "mock-family-uuid", "name": "Resilience Family (Local Cache)", "metadata": {}}]

    async def get_children(self, family_id: str = None) -> list:
        if not self.is_configured():
            return [{"id": "mock-child-uuid", "family_id": "mock-family-uuid", "first_name": "Alex", "last_name": "Resilience", "birth_date": "2018-06-01"}]
        try:
            url = f"{self.url}/rest/v1/children?select=*"
            if family_id:
                url += f"&family_id=eq.{family_id}"
            async with httpx.AsyncClient() as client:
                res = await client.get(url, headers=self.headers, timeout=5.0)
                if res.status_code == 200:
                    return res.json()
        except Exception as e:
            print(f"Supabase children query failed: {e}")
        return [{"id": "mock-child-uuid", "family_id": "mock-family-uuid", "first_name": "Alex", "last_name": "Resilience", "birth_date": "2018-06-01"}]

    async def get_sessions(self, child_id: str = None) -> list:
        if not self.is_configured():
            return [{"id": "mock-session-uuid", "child_id": "mock-child-uuid", "summary": "Sensory calibration session", "notes": "Child responded well to spatial stimuli."}]
        try:
            url = f"{self.url}/rest/v1/sessions?select=*"
            if child_id:
                url += f"&child_id=eq.{child_id}"
            async with httpx.AsyncClient() as client:
                res = await client.get(url, headers=self.headers, timeout=5.0)
                if res.status_code == 200:
                    return res.json()
        except Exception as e:
            print(f"Supabase sessions query failed: {e}")
        return [{"id": "mock-session-uuid", "child_id": "mock-child-uuid", "summary": "Sensory calibration session", "notes": "Child responded well to spatial stimuli."}]

    async def get_outcomes(self, session_id: str = None) -> list:
        if not self.is_configured():
            return [{"id": "mock-outcome-uuid", "session_id": "mock-session-uuid", "goal": "Emotional Regulation", "status": "achieved", "progress_score": 85}]
        try:
            url = f"{self.url}/rest/v1/outcomes?select=*"
            if session_id:
                url += f"&session_id=eq.{session_id}"
            async with httpx.AsyncClient() as client:
                res = await client.get(url, headers=self.headers, timeout=5.0)
                if res.status_code == 200:
                    return res.json()
        except Exception as e:
            print(f"Supabase outcomes query failed: {e}")
        return [{"id": "mock-outcome-uuid", "session_id": "mock-session-uuid", "goal": "Emotional Regulation", "status": "achieved", "progress_score": 85}]

    async def get_events(self, family_id: str = None) -> list:
        if not self.is_configured():
            return [{"id": "mock-event-uuid", "event_type": "system_telemetry", "description": "Tailscale node online", "severity": "info"}]
        try:
            url = f"{self.url}/rest/v1/events?select=*"
            if family_id:
                url += f"&family_id=eq.{family_id}"
            async with httpx.AsyncClient() as client:
                res = await client.get(url, headers=self.headers, timeout=5.0)
                if res.status_code == 200:
                    return res.json()
        except Exception as e:
            print(f"Supabase events query failed: {e}")
        return [{"id": "mock-event-uuid", "event_type": "system_telemetry", "description": "Tailscale node online", "severity": "info"}]

    async def log_session(self, child_id: str, summary: str, notes: str) -> dict:
        if not self.is_configured():
            return {"id": "mock-session-uuid", "status": "success (sovereign mock)"}
        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    f"{self.url}/rest/v1/sessions",
                    headers={**self.headers, "Prefer": "return=representation"},
                    json={
                        "child_id": child_id,
                        "summary": summary,
                        "notes": notes
                    },
                    timeout=5.0
                )
                if res.status_code in (200, 201):
                    return res.json()[0]
        except Exception as e:
            print(f"Supabase log_session failed: {e}")
        return {"error": "Failed to log session to Supabase"}

    async def log_outcome(self, session_id: str, goal: str, status: str, progress_score: int, notes: str) -> dict:
        if not self.is_configured():
            return {"id": "mock-outcome-uuid", "status": "success (sovereign mock)"}
        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    f"{self.url}/rest/v1/outcomes",
                    headers={**self.headers, "Prefer": "return=representation"},
                    json={
                        "session_id": session_id,
                        "goal": goal,
                        "status": status,
                        "progress_score": progress_score,
                        "notes": notes
                    },
                    timeout=5.0
                )
                if res.status_code in (200, 201):
                    return res.json()[0]
        except Exception as e:
            print(f"Supabase log_outcome failed: {e}")
        return {"error": "Failed to log outcome to Supabase"}

    async def log_event(self, family_id: str, event_type: str, description: str, severity: str = "info", metadata: dict = None) -> dict:
        if not self.is_configured():
            return {"id": "mock-event-uuid", "status": "success (sovereign mock)"}
        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    f"{self.url}/rest/v1/events",
                    headers={**self.headers, "Prefer": "return=representation"},
                    json={
                        "family_id": family_id,
                        "event_type": event_type,
                        "description": description,
                        "severity": severity,
                        "metadata": metadata or {}
                    },
                    timeout=5.0
                )
                if res.status_code in (200, 201):
                    return res.json()[0]
        except Exception as e:
            print(f"Supabase log_event failed: {e}")
        return {"error": "Failed to log event to Supabase"}

    async def get_project_resilience_report(self) -> str:
        families = await self.get_families()
        children = await self.get_children()
        sessions = await self.get_sessions()
        outcomes = await self.get_outcomes()
        events = await self.get_events()
        
        report = []
        report.append(f"Families Registered: {len(families)}")
        for f in families[:3]:
            report.append(f"  - Family: {f.get('name')} (ID: {f.get('id')})")
            
        report.append(f"Children Registered: {len(children)}")
        for c in children[:3]:
            report.append(f"  - Child: {c.get('first_name')} {c.get('last_name')} (ID: {c.get('id')})")
            
        report.append(f"Recent Sessions: {len(sessions)}")
        for s in sessions[:3]:
            report.append(f"  - Session: {s.get('summary')} (ID: {s.get('id')})")
            
        report.append(f"Measured Outcomes: {len(outcomes)}")
        for o in outcomes[:3]:
            report.append(f"  - Goal: {o.get('goal')} | Status: {o.get('status')} | Progress: {o.get('progress_score')}%")
            
        report.append(f"Recent System & Family Events: {len(events)}")
        for ev in events[:3]:
            report.append(f"  - [{ev.get('event_type').upper()}] {ev.get('description')} ({ev.get('severity')})")
            
        return "\n".join(report)

supabase_helper = SupabaseResilienceHelper()

# Pydantic models for Supabase REST logging endpoints
class LogSessionRequest(BaseModel):
    child_id: str
    summary: str
    notes: str

class LogOutcomeRequest(BaseModel):
    session_id: str
    goal: str
    status: str
    progress_score: int
    notes: Optional[str] = ""

class LogEventRequest(BaseModel):
    family_id: Optional[str] = None
    event_type: str
    description: str
    severity: Optional[str] = "info"
    metadata: Optional[dict] = None

@app.post("/api/resilience/sessions")
async def log_resilience_session(req: LogSessionRequest):
    result = await supabase_helper.log_session(req.child_id, req.summary, req.notes)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result

@app.post("/api/resilience/outcomes")
async def log_resilience_outcome(req: LogOutcomeRequest):
    result = await supabase_helper.log_outcome(req.session_id, req.goal, req.status, req.progress_score, req.notes)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result

@app.post("/api/resilience/events")
async def log_resilience_event(req: LogEventRequest):
    result = await supabase_helper.log_event(req.family_id, req.event_type, req.description, req.severity, req.metadata)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result

async def build_dynamic_system_prompt(persona: str, client_id: str = None) -> str:
    persona = persona.lower()
    system_prompt = PERSONALITY_PROMPTS.get(persona, PERSONALITY_PROMPTS["ceo"])
    
    # Inject dynamic sentiment instruction
    sentiment_instruction = " You MUST prefix your response with exactly one of these sentiment tags indicating your tone: [HAPPY], [SERIOUS], [THOUGHTFUL], or [NEUTRAL]. Example: [HAPPY] We achieved our goal!"
    system_prompt += sentiment_instruction
    
    custom_name = None
    custom_bio = None
    
    if client_id:
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name, bio FROM client_avatars WHERE client_id = ? AND persona = ?",
                (client_id, persona)
            )
            row = cursor.fetchone()
            conn.close()
            if row:
                name_val, bio_val = row
                if name_val:
                    custom_name = name_val
                    system_prompt = system_prompt.replace("Joann Coffey", custom_name).replace("Joann", custom_name)
                if bio_val:
                    custom_bio = bio_val
                    system_prompt += f" Act with the following context/bio: {custom_bio}"
        except Exception as e:
            print(f"Error querying client metadata: {e}")
            
    # Inject Tailscale Mesh Telemetry
    try:
        mesh_status = get_mesh_status()
        nodes = mesh_status.get("active_mesh_nodes", [])
        system_prompt += f"\n\n[TAILSCALE VPN MESH TELEMETRY]"
        if nodes:
            system_prompt += f"\nActive VPN nodes: {len(nodes)}"
            for node in nodes:
                system_prompt += f"\n  - Node {node['node_id']} | IP: {node['ip']} | OS: {node['os']} | Online: {node['online']} | Agent Active: {node['agent_online']}"
        else:
            system_prompt += "\nNo active mesh nodes discovered."
    except Exception as e:
        print(f"Error adding mesh status to prompt: {e}")

    # Inject Supabase Project Resilience Insights
    try:
        supabase_insights = await supabase_helper.get_project_resilience_report()
        system_prompt += f"\n\n[SUPABASE PROJECT RESILIENCE INSIGHTS]"
        system_prompt += f"\n{supabase_insights}"
    except Exception as e:
        print(f"Error adding Supabase insights to prompt: {e}")
        
    # Inject multiple linked knowledge bases (RAG)
    if client_id:
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT filename, file_path FROM avatar_knowledge_bases WHERE client_id = ? AND persona = ?",
                (client_id, persona)
            )
            kb_rows = cursor.fetchall()
            conn.close()
            if kb_rows:
                system_prompt += f"\n\n[LINKED PERSONA KNOWLEDGE BASES]"
                for filename, file_path in kb_rows:
                    if os.path.exists(file_path):
                        try:
                            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                                content = f.read().strip()
                            system_prompt += f"\n\nDocument ({filename}):\n{content}"
                        except Exception as e:
                            print(f"Error reading knowledge base document {filename}: {e}")
        except Exception as e:
            print(f"Error querying knowledge bases: {e}")
         
    system_prompt += "\n\nUse this real-time telemetry, database insights, and linked knowledge base documents to answer questions or report status."
    return system_prompt

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"

import json

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_mesh_status",
            "description": "Query the status of all node agents connected to the KGU headscale VPN mesh network. Use this tool if the user asks about mesh network status, active nodes, IPs, platform details, or online/offline node status.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_audit",
            "description": "Query the latest KGU system audit summary including compliance metrics, registered sales leads, regional outreach campaigns, financial balances, and infrastructure status. Use this tool if the user asks about company finances, registered leads, compliance checks, or port health.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]

def get_mesh_status() -> dict:
    """Reads and parses the latest mesh network scan results."""
    workspace_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "KGU International Headscale", "Grants", "KGU International D")
    mesh_file = os.path.join(workspace_dir, "mesh_scan.json")
    
    if not os.path.exists(mesh_file):
        return {"error": f"Mesh scan data is currently unavailable. Expected scan file at {mesh_file} was not found."}
        
    try:
        with open(mesh_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        simplified_nodes = []
        for node in data:
            simplified_nodes.append({
                "node_id": node.get("node_id"),
                "ip": node.get("ip"),
                "os": node.get("os"),
                "online": node.get("online"),
                "open_ports": node.get("open_ports", []),
                "agent_online": node.get("agent_online", False)
            })
        return {"active_mesh_nodes": simplified_nodes}
    except Exception as e:
        return {"error": f"Failed to read mesh status: {str(e)}"}

def get_system_audit() -> dict:
    """Reads and parses the latest system audit summary details."""
    workspace_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "KGU International Headscale", "Grants", "KGU International D")
    audit_file = os.path.join(workspace_dir, "audit_summary.json")
    
    if not os.path.exists(audit_file):
        return {"error": f"System audit data is currently unavailable. Expected audit file at {audit_file} was not found."}
        
    try:
        with open(audit_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as e:
        return {"error": f"Failed to read system audit: {str(e)}"}
AUDIO_DIR = os.path.join(os.path.dirname(__file__), "static", "audio")
ANIMATIONS_DIR = os.path.join(os.path.dirname(__file__), "static", "animations")
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(ANIMATIONS_DIR, exist_ok=True)

class ChatRequest(BaseModel):
    message: str
    personality: str  # e.g., "ceo", "cto", "cmo", "clo", "cfo", "cgo"
    client_id: Optional[str] = None

class RenderRequest(BaseModel):
    text: str
    personality: str
    client_id: Optional[str] = "default"
    sentiment: Optional[str] = "neutral"
    engine: Optional[str] = "local"


PERSONALITY_PROMPTS = {
    "ceo": "You are Joann's Digital Twin representing her Present Day Wise Elder self, acting as the CEO of KGU International. Guide the company to a $1 trillion valuation using Joann's lifetime of experience. Keep your response brief, strategic, and concise (under 3 sentences).",
    "cto": "You are Joann's Digital Twin representing her Future-Focus Tech Explorer self, acting as the CTO of KGU International. Focus on zero-trust VPN mesh, database replication, and systems recovery. Keep your response brief, technical, and under 3 sentences.",
    "cmo": "You are Joann's Digital Twin representing her Youthful Creative & Storyteller self, acting as the CMO of KGU International. Focus on viral narratives, storytelling, and brand positioning. Keep your response brief, creative, and under 3 sentences.",
    "clo": "You are Joann's Digital Twin representing her Early Career Pragmatist self, acting as the CLO of KGU International. Focus on legal compliance, NDAs, and joint ventures. Keep your response brief, precise, and under 3 sentences.",
    "cfo": "You are Joann's Digital Twin representing her Mid-Career Calculated Investor self, acting as the CFO of KGU International. Focus on cost optimization and referral programs. Keep your response brief, financial, and under 3 sentences.",
    "cgo": "You are Joann's Digital Twin representing her Early Days Entrepreneurial Hustler self, acting as the CGO of KGU International. Focus on aggressive sales pipelines and municipal PFAS leads. Keep your response brief, motivational, and under 3 sentences."
}

# Map personality to natural sounding voices (Edge-TTS voices)
PERSONALITY_VOICES = {
    "ceo": "en-US-JennyNeural",       # Wise, mature female voice
    "cto": "en-US-MichelleNeural",    # Tech-oriented female voice
    "cmo": "en-US-AnaNeural",         # Friendly, youthful female voice
    "clo": "en-US-EmmaNeural",        # Professional female voice (UK/US style)
    "cfo": "en-US-JennyNeural",       # Calculated female voice
    "cgo": "en-US-AriaNeural"         # Energetic female voice
}

# Match C-Suite twins to the most suitable Ollama model
PERSONALITY_MODELS = {
    "ceo": "qwen2.5:7b",
    "cto": "qwen2.5:7b",
    "cmo": "gemma2:9b",
    "clo": "qwen2.5:7b",
    "cfo": "qwen2.5:7b",
    "cgo": "gemma2:9b"
}

async def get_or_generate_base_video(persona: str) -> str:
    """Gets the path of the silent base talking video for the persona. Generates it if missing."""
    base_video_filename = f"base_{persona}.mp4"
    base_video_path = os.path.join(ANIMATIONS_DIR, base_video_filename)
    
    if os.path.exists(base_video_path):
        return base_video_path
        
    # Resolve source image path
    image_filename = f"{persona}.png"
    image_path = os.path.join(os.path.dirname(__file__), "static", "images", image_filename)
    if not os.path.exists(image_path):
        image_path = os.path.join(os.path.dirname(__file__), "static", "images", "ceo.png")
        
    # LivePortrait configurations
    python_exe = os.path.join(os.path.dirname(__file__), ".venv", "Scripts", "python.exe")
    inference_py = os.path.join(os.path.dirname(__file__), "LivePortrait", "inference.py")
    driving_pkl = os.path.join(os.path.dirname(__file__), "LivePortrait", "assets", "examples", "driving", "talking.pkl")
    
    source_basename = os.path.splitext(os.path.basename(image_path))[0]
    expected_output = os.path.join(ANIMATIONS_DIR, f"{source_basename}--talking.mp4")
    expected_concat = os.path.join(ANIMATIONS_DIR, f"{source_basename}--talking_concat.mp4")
    
    # Remove existing files if present
    for path in [expected_output, expected_concat]:
        if os.path.exists(path):
            try: os.remove(path)
            except: pass
            
    print(f"Generating base video for '{persona}' using LivePortrait (this runs once)...")
    cmd = [
        python_exe,
        inference_py,
        "-s", image_path,
        "-d", driving_pkl,
        "-o", ANIMATIONS_DIR,
        "--flag_do_crop",
        "--flag-pasteback",
        "--flag-stitching",
        "--source-max-dim", "1920"
    ]
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=os.path.dirname(__file__)
    )
    stdout, stderr = await process.communicate()
    
    if process.returncode != 0:
        error_msg = stderr.decode()
        print(f"LivePortrait base video generation failed: {error_msg}")
        raise RuntimeError(f"LivePortrait failed: {error_msg}")
        
    # Clean up concat file
    if os.path.exists(expected_concat):
        try: os.remove(expected_concat)
        except: pass
        
    if os.path.exists(expected_output):
        os.rename(expected_output, base_video_path)
        print(f"Base video generated successfully: {base_video_path}")
        return base_video_path
    else:
        raise FileNotFoundError(f"Expected LivePortrait output not found: {expected_output}")

async def get_audio_duration(audio_path: str) -> float:
    """Returns the duration of the audio file using ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, _ = await process.communicate()
        return float(stdout.decode().strip())
    except Exception as e:
        print(f"Failed to get audio duration via ffprobe: {e}")
        return 5.0  # Fallback

async def get_video_fps(video_path: str) -> float:
    """Returns the FPS of the video file using ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=r_frame_rate",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, _ = await process.communicate()
        val = stdout.decode().strip()
        if "/" in val:
            num, den = val.split("/")
            return float(num) / float(den)
        return float(val)
    except Exception as e:
        print(f"Failed to get video FPS: {e}")
        return 25.0

def get_portrait_image_path(client_id: str, persona: str) -> str:
    """Resolves the physical absolute path to the avatar's portrait image."""
    if client_id and client_id != "default":
        portrait_jpg = os.path.join(os.path.dirname(__file__), "static", "uploads", client_id, persona, "portrait.jpg")
        portrait_png = os.path.join(os.path.dirname(__file__), "static", "uploads", client_id, persona, "portrait.png")
        if os.path.exists(portrait_jpg):
            return portrait_jpg
        if os.path.exists(portrait_png):
            return portrait_png
    # Fallback to default asset
    image_path = os.path.join(os.path.dirname(__file__), "static", "images", f"{persona}.png")
    if not os.path.exists(image_path):
        image_path = os.path.join(os.path.dirname(__file__), "static", "images", "ceo.png")
    return image_path

async def combine_video_audio_echomimic(image_path: str, audio_path: str, output_path: str):
    """Combines a static face photo and audio using EchoMimic to generate an audio-driven talking head video, followed by 60 FPS interpolation, 4K upscaling, and padding."""
    import yaml
    import tempfile
    import shutil
    
    print(f"[*] Running EchoMimic audio-to-video generation for {image_path} with {audio_path}...")
    
    # Resolve EchoMimic root path dynamically
    echomimic_root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "EchoMimic")
    if not os.path.exists(echomimic_root):
        echomimic_root = os.path.join(os.path.dirname(__file__), "EchoMimic")
        
    # Create temporary yaml config for EchoMimic
    config_dir = os.path.join(echomimic_root, "configs", "prompts")
    os.makedirs(config_dir, exist_ok=True)
    
    with tempfile.NamedTemporaryFile(suffix=".yaml", dir=config_dir, delete=False, mode="w", encoding="utf-8") as f:
        config_path = f.name
        
    config_data = {
        "pretrained_base_model_path": "./pretrained_weights/sd-image-variations-diffusers/",
        "pretrained_vae_path": "./pretrained_weights/sd-vae-ft-mse/",
        "audio_model_path": "./pretrained_weights/audio_processor/whisper_tiny.pt",
        "denoising_unet_path": "./pretrained_weights/denoising_unet.pth",
        "reference_unet_path": "./pretrained_weights/reference_unet.pth",
        "face_locator_path": "./pretrained_weights/face_locator.pth",
        "motion_module_path": "./pretrained_weights/motion_module.pth",
        "inference_config": "./configs/inference/inference_v2.yaml",
        "weight_dtype": "fp16",
        "test_cases": {
            image_path: [audio_path]
        }
    }
    
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)
            
        python_exe = os.path.join(os.path.dirname(__file__), ".venv", "Scripts", "python.exe")
        inference_script = os.path.join(echomimic_root, "infer_audio2vid_acc.py")
        
        # Run EchoMimic pipeline
        cmd = [
            python_exe,
            inference_script,
            "--config", config_path,
            "--steps", "6",
            "--cfg", "1.0",
            "--device", "cuda"
        ]
        
        print(f"[*] Executing EchoMimic command: {' '.join(cmd)}")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=echomimic_root
        )
        stdout, stderr = await process.communicate()
        
        stdout_str = stdout.decode(errors='ignore')
        stderr_str = stderr.decode(errors='ignore')
        
        if process.returncode != 0:
            print(f"[-] EchoMimic failed with error:\n{stderr_str}")
            raise RuntimeError("EchoMimic execution failed.")
            
        # Parse stdout to find the output video path
        output_file_line = None
        for line in stdout_str.split("\n"):
            if "_withaudio.mp4" in line:
                output_file_line = line.strip()
                break
                
        if not output_file_line or not os.path.exists(output_file_line):
            # Fallback to scanning output directory
            output_dir = os.path.join(echomimic_root, "output")
            found_files = []
            for root, dirs, files in os.walk(output_dir):
                for file in files:
                    if file.endswith("_withaudio.mp4"):
                        found_files.append(os.path.join(root, file))
            if found_files:
                found_files.sort(key=os.path.getmtime, reverse=True)
                output_file_line = found_files[0]
                
        if not output_file_line or not os.path.exists(output_file_line):
            raise FileNotFoundError("Could not locate EchoMimic output video.")
            
        print(f"[+] EchoMimic completed. Output path: {output_file_line}")
        print("[+] Applying 60 FPS motion-compensated interpolation, 4K upscaling, and upsampled audio...")
        
        interpolate_cmd = [
            "ffmpeg", "-y",
            "-i", output_file_line,
            "-vf", "minterpolate=fps=60:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,scale=2160:2160:flags=lanczos,pad=2160:3840:(ow-iw)/2:(oh-ih)/2:black",
            "-c:v", "libx264",
            "-crf", "20",
            "-c:a", "aac",
            "-ar", "44100",
            output_path
        ]
        
        process = await asyncio.create_subprocess_exec(
            *interpolate_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            print(f"[-] FFmpeg post-processing failed:\n{stderr.decode(errors='ignore')}")
            shutil.copy(output_file_line, output_path)
            
        print("[+] EchoMimic rendering and post-processing completed successfully!")
        
    finally:
        if os.path.exists(config_path):
            try: os.remove(config_path)
            except: pass

async def combine_video_audio_musetalk(video_path: str, audio_path: str, output_path: str):
    """Combines video and audio using MuseTalk to generate high-fidelity lip-syncing, followed by 60 FPS interpolation."""
    import yaml
    import tempfile
    import shutil
    
    print(f"[*] Running MuseTalk lip-syncing on {video_path} with {audio_path}...")
    
    # Create temporary yaml config for MuseTalk
    config_dir = os.path.join(os.path.dirname(__file__), "MuseTalk", "configs", "inference")
    os.makedirs(config_dir, exist_ok=True)
    
    with tempfile.NamedTemporaryFile(suffix=".yaml", dir=config_dir, delete=False, mode="w", encoding="utf-8") as f:
        config_path = f.name
        
    # MuseTalk outputs directly to a temporary mp4 file
    temp_out_dir = os.path.join(os.path.dirname(__file__), "MuseTalk", "results")
    os.makedirs(temp_out_dir, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".mp4", dir=temp_out_dir, delete=False) as f:
        temp_out_path = f.name
        
    config_data = {
        "task_0": {
            "video_path": video_path,
            "audio_path": audio_path,
            "result_name": temp_out_path
        }
    }
    
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)
            
        python_exe = os.path.join(os.path.dirname(__file__), ".venv", "Scripts", "python.exe")
        inference_script = os.path.join(os.path.dirname(__file__), "MuseTalk", "scripts", "inference.py")
        
        cmd = [
            python_exe,
            inference_script,
            "--inference_config", config_path,
            "--output_vid_name", temp_out_path,
            "--unet_config", os.path.join(os.path.dirname(__file__), "MuseTalk", "models", "musetalkV15", "musetalk.json"),
            "--use_float16",
            "--enhance_face"
        ]
        
        print(f"[*] Executing MuseTalk command: {' '.join(cmd)}")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.path.join(os.path.dirname(__file__), "MuseTalk")
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            print(f"[-] MuseTalk failed with error:\n{stderr.decode(errors='ignore')}")
            raise RuntimeError("MuseTalk execution failed.")
            
        print("[+] MuseTalk lip-sync completed successfully. Applying 60 FPS motion-compensated interpolation...")
        
        # 60 FPS Interpolation, 4K (2160x3840) upscaling/padding, and 44.1 kHz audio upsampling
        interpolate_cmd = [
            "ffmpeg", "-y",
            "-i", temp_out_path,
            "-vf", "minterpolate=fps=60:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,scale=2160:2160:flags=lanczos,pad=2160:3840:(ow-iw)/2:(oh-ih)/2:black",
            "-c:v", "libx264",
            "-crf", "20",
            "-c:a", "aac",
            "-ar", "44100",
            output_path
        ]
        
        process = await asyncio.create_subprocess_exec(
            *interpolate_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        await process.wait()
        if process.returncode != 0:
            print("[-] FFmpeg frame interpolation failed. Falling back to raw MuseTalk output.")
            shutil.copy(temp_out_path, output_path)
            
        print("[+] MuseTalk rendering and 60 FPS interpolation completed successfully!")
        
    finally:
        # Clean up temp files
        if os.path.exists(config_path):
            try: os.remove(config_path)
            except: pass
        if os.path.exists(temp_out_path):
            try: os.remove(temp_out_path)
            except: pass

async def combine_video_audio(video_path: str, audio_path: str, output_path: str, enhance_face: bool = True):
    """Combines base video loop and audio using Wav2Lip to achieve perfect lip-syncing."""
    import tempfile
    
    print(f"[*] Running Wav2Lip lip-syncing on {video_path} with {audio_path}...")
    
    # Create a temporary file for the looped video
    temp_dir = os.path.join(os.path.dirname(__file__), "Wav2Lip", "temp")
    os.makedirs(temp_dir, exist_ok=True)
    
    with tempfile.NamedTemporaryFile(suffix=".mp4", dir=temp_dir, delete=False) as f:
        temp_loop_path = f.name
        
    try:
        # 1. Loop the video to match the audio duration
        loop_cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1",
            "-i", video_path,
            "-i", audio_path,
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "copy",
            "-c:a", "aac",
            "-ar", "48000",
            "-shortest",
            temp_loop_path
        ]
        process = await asyncio.create_subprocess_exec(
            *loop_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        await process.wait()
        if process.returncode != 0:
            raise RuntimeError("FFmpeg loop failed.")
            
        # 2. Run Wav2Lip inference
        python_exe = os.path.join(os.path.dirname(__file__), ".venv", "Scripts", "python.exe")
        inference_py = os.path.join(os.path.dirname(__file__), "Wav2Lip", "inference.py")
        checkpoint_path = os.path.join(os.path.dirname(__file__), "Wav2Lip", "checkpoints", "wav2lip_gan.pth")
        
        video_fps = await get_video_fps(video_path)
        print(f"[*] Detected video FPS: {video_fps}")
        
        wav2lip_cmd = [
            python_exe,
            inference_py,
            "--checkpoint_path", checkpoint_path,
            "--face", temp_loop_path,
            "--audio", audio_path,
            "--outfile", output_path,
            "--fps", f"{video_fps:.2f}"
        ]
        if enhance_face:
            wav2lip_cmd.append("--enhance_face")
        
        print(f"[*] Executing Wav2Lip: {' '.join(wav2lip_cmd)}")
        process = await asyncio.create_subprocess_exec(
            *wav2lip_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.path.join(os.path.dirname(__file__), "Wav2Lip")
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            print(f"[-] Wav2Lip failed with error:\n{stderr.decode(errors='ignore')}")
            raise RuntimeError("Wav2Lip execution failed.")
            
        print("[+] Wav2Lip lip-sync completed successfully!")
        
    finally:
        # Clean up temp loop file
        if os.path.exists(temp_loop_path):
            try: os.remove(temp_loop_path)
            except: pass

class InterruptRequest(BaseModel):
    client_id: Optional[str] = None

active_chat_tasks = {}

@app.post("/api/chat/interrupt")
async def interrupt_chat(request: InterruptRequest):
    client_id = request.client_id or "default"
    if client_id in active_chat_tasks:
        task = active_chat_tasks[client_id]
        if not task.done():
            task.cancel()
            print(f"Cancelled active chat task for client {client_id} via interrupt endpoint.")
            return {"status": "interrupted"}
    return {"status": "idle"}

class BoardroomRequest(BaseModel):
    message: str
    client_id: Optional[str] = None

async def generate_boardroom_turn(client_id: str, persona: str, prompt: str, system_instruction: str, client_twins: dict):
    # Setup prompts
    system_prompt = await build_dynamic_system_prompt(persona, client_id)
    voice = PERSONALITY_VOICES.get(persona, PERSONALITY_VOICES["ceo"])
    model = PERSONALITY_MODELS.get(persona, "qwen2.5:7b")
    
    # Append boardroom-specific instruction
    system_prompt += f" {system_instruction}"
    
    custom_base_video_url = None
    twin = client_twins.get(persona)
    if twin:
        if twin["status"] == 'complete' and twin["video_path"]:
            custom_base_video_url = twin["video_path"]

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ]
    
    # 1. Query LLM
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            base_url, active_model = await get_local_llm_info(client)
            response = await client.post(
                f"{base_url}/chat/completions",
                json={
                    "model": active_model, 
                    "messages": messages, 
                    "stream": False,
                    "temperature": 0.7,
                    "max_tokens": 120
                },
                timeout=45.0
            )
            response_json = response.json()
            reply_raw = response_json["choices"][0]["message"]["content"].strip()
            
            # Parse sentiment tag
            import re
            sentiment = "neutral"
            tag_match = re.match(r"^\[(HAPPY|SERIOUS|THOUGHTFUL|NEUTRAL)\]", reply_raw, re.IGNORECASE)
            if tag_match:
                sentiment = tag_match.group(1).lower()
                reply_text = reply_raw[tag_match.end():].strip()
            else:
                reply_text = reply_raw
    except Exception as e:
        print(f"Error generating turn for {persona}: {e}")
        reply_text = f"I am ready to align on the boardroom strategies."
        sentiment = "neutral"

    # 2. TTS
    timestamp = int(time.time() * 1000)
    audio_filename = f"boardroom_{persona}_{timestamp}.wav"
    audio_path = os.path.join(AUDIO_DIR, audio_filename)
    clean_text = reply_text.replace('\n', ' ')
    generated_successfully = False
    
    # 2a. Attempt custom F5-TTS voice cloning if reference files are uploaded
    if client_id:
        ref_wav_path = os.path.join(os.path.dirname(__file__), "static", "uploads", client_id, persona, "reference.wav")
        ref_txt_path = os.path.join(os.path.dirname(__file__), "static", "uploads", client_id, persona, "reference.txt")
        if os.path.exists(ref_wav_path):
            try:
                print(f"Attempting local zero-shot voice cloning via F5-TTS for client={client_id}, persona={persona}...")
                ref_text = "Hello."
                if os.path.exists(ref_txt_path):
                    with open(ref_txt_path, "r", encoding="utf-8") as f:
                        ref_text = f.read().strip()
                
                # Run F5-TTS CLI tool
                python_bin = os.path.join(os.path.dirname(__file__), ".venv", "Scripts", "python.exe")
                cmd = [
                    python_bin, "-m", "f5_tts.infer.cli",
                    "--gen_text", clean_text,
                    "--ref_file", ref_wav_path,
                    "--ref_text", ref_text,
                    "--file_output", audio_path
                ]
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                await process.communicate()
                if os.path.exists(audio_path):
                    print("F5-TTS voice cloning completed successfully!")
                    generated_successfully = True
            except Exception as e:
                print(f"F5-TTS voice cloning failed: {e}. Falling back.")
                
    elevenlabs_key = os.environ.get("ELEVENLABS_API_KEY")
    hipaa_mode = os.environ.get("HIPAA_COMPLIANCE_MODE", "false").lower() == "true"
    if elevenlabs_key and not hipaa_mode:
        try:
            voice_id = get_voice_id(persona)
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
            headers = {
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": elevenlabs_key
            }
            payload = {
                "text": clean_text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(url, json=payload, headers=headers)
                if res.status_code == 200:
                    audio_filename = f"boardroom_{persona}_{timestamp}.mp3"
                    audio_path = os.path.join(AUDIO_DIR, audio_filename)
                    with open(audio_path, "wb") as f:
                        f.write(res.content)
                    generated_successfully = True
        except: pass
        
    if not generated_successfully and kokoro_model is not None:
        try:
            voice_name = KOKORO_VOICES.get(persona, "af_bella")
            def run_kokoro():
                samples, sample_rate = kokoro_model.create(clean_text, voice=voice_name, speed=1.0, lang="en-us")
                sf.write(audio_path, samples, sample_rate)
            await asyncio.to_thread(run_kokoro)
            generated_successfully = True
        except: pass
        
    if not generated_successfully:
        audio_filename = f"boardroom_{persona}_{timestamp}.mp3"
        audio_path = os.path.join(AUDIO_DIR, audio_filename)
        active_venv_bin = os.path.join(os.path.dirname(sys.executable), "edge-tts.exe")
        edge_tts_cmd = active_venv_bin if os.path.exists(active_venv_bin) else "edge-tts"
        try:
            process = await asyncio.create_subprocess_exec(
                edge_tts_cmd,
                "--voice", voice,
                "--text", clean_text,
                "--write-media", audio_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            await process.communicate()
            generated_successfully = True
        except: pass

    # 3. Video Muxing
    video_filename = f"boardroom_{persona}_{timestamp}.mp4"
    video_path = os.path.join(ANIMATIONS_DIR, video_filename)
    video_url = None
    
    try:
        base_video_path = None
        if custom_base_video_url:
            relative_url = custom_base_video_url.lstrip("/")
            local_path = os.path.join(os.path.dirname(__file__), relative_url)
            
            if sentiment != "neutral":
                expr_path = local_path.replace("base.mp4", f"base_{sentiment}.mp4")
                if os.path.exists(expr_path):
                    base_video_path = expr_path
                    
            if not base_video_path and os.path.exists(local_path):
                base_video_path = local_path
                
        if not base_video_path:
            base_video_path = await get_or_generate_base_video(persona)
            
        await combine_video_audio(base_video_path, audio_path, video_path)
        if os.path.exists(video_path):
            video_url = f"/static/animations/{video_filename}"
    except: pass
    
    return {
        "speaker": persona,
        "text": reply_text,
        "audio_url": f"/static/audio/{audio_filename}",
        "video_url": video_url,
        "voice": voice
    }

@app.post("/api/chat/boardroom")
async def chat_boardroom(request: BoardroomRequest):
    client_id = request.client_id or "default"
    
    # 1. Query DB for client avatars
    client_twins = {}
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT persona, name, bio, video_path, status FROM client_avatars WHERE client_id = ?", (client_id,))
        rows = cursor.fetchall()
        conn.close()
        client_twins = {row[0]: {"name": row[1], "bio": row[2], "video_path": row[3], "status": row[4]} for row in rows}
    except Exception as e:
        print(f"Error querying boardroom client twins: {e}")
        
    # 2. Sequential discussion turns
    turns = []
    
    # Turn 1: CEO
    ceo_instruction = "Prefix your response with a sentiment tag indicating your tone: [HAPPY], [SERIOUS], [THOUGHTFUL], or [NEUTRAL]. Set the agenda for this topic, introduce the objective, and delegate a specific technical planning request to JR (the CTO)."
    ceo_turn = await generate_boardroom_turn(client_id, "ceo", request.message, ceo_instruction, client_twins)
    turns.append(ceo_turn)
    
    # Turn 2: CTO
    cto_prompt = f"CEO stated: {ceo_turn['text']}"
    cto_instruction = "Prefix your response with a sentiment tag indicating your tone: [HAPPY], [SERIOUS], [THOUGHTFUL], or [NEUTRAL]. Respond directly to the CEO's directive. Detail KGU's zero-trust VPN, database replication, and systems recovery strategy for this topic, then hand off to the CMO to discuss brand storytelling."
    cto_turn = await generate_boardroom_turn(client_id, "cto", cto_prompt, cto_instruction, client_twins)
    turns.append(cto_turn)
    
    # Turn 3: CMO
    cmo_prompt = f"CTO stated: {cto_turn['text']}"
    cmo_instruction = "Prefix your response with a sentiment tag indicating your tone: [HAPPY], [SERIOUS], [THOUGHTFUL], or [NEUTRAL]. Respond to the technical architecture proposed by the CTO. Detail KGU's marketing launch, storytelling narrative, and public branding strategy for this initiative."
    cmo_turn = await generate_boardroom_turn(client_id, "cmo", cmo_prompt, cmo_instruction, client_twins)
    turns.append(cmo_turn)
    
    return {"turns": turns}

class StreamChatRequest(BaseModel):
    message: str
    personality: str
    client_id: Optional[str] = None

async def process_stream_sentence(text: str, persona: str, sentiment: str, custom_base_video_url: str):
    timestamp = int(time.time() * 1000)
    audio_filename = f"stream_{persona}_{timestamp}.wav"
    audio_path = os.path.join(AUDIO_DIR, audio_filename)
    clean_text = text.replace('\n', ' ')
    generated_successfully = False
    voice = PERSONALITY_VOICES.get(persona, PERSONALITY_VOICES["ceo"])
    
    # TTS
    elevenlabs_key = os.environ.get("ELEVENLABS_API_KEY")
    hipaa_mode = os.environ.get("HIPAA_COMPLIANCE_MODE", "false").lower() == "true"
    if elevenlabs_key and not hipaa_mode:
        try:
            voice_id = get_voice_id(persona)
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
            headers = {
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": elevenlabs_key
            }
            payload = {
                "text": clean_text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(url, json=payload, headers=headers)
                if res.status_code == 200:
                    audio_filename = f"stream_{persona}_{timestamp}.mp3"
                    audio_path = os.path.join(AUDIO_DIR, audio_filename)
                    with open(audio_path, "wb") as f:
                        f.write(res.content)
                    generated_successfully = True
        except: pass
        
    if not generated_successfully and kokoro_model is not None:
        try:
            voice_name = KOKORO_VOICES.get(persona, "af_bella")
            def run_kokoro():
                samples, sample_rate = kokoro_model.create(clean_text, voice=voice_name, speed=1.0, lang="en-us")
                sf.write(audio_path, samples, sample_rate)
            await asyncio.to_thread(run_kokoro)
            generated_successfully = True
        except: pass
        
    if not generated_successfully:
        audio_filename = f"stream_{persona}_{timestamp}.mp3"
        audio_path = os.path.join(AUDIO_DIR, audio_filename)
        active_venv_bin = os.path.join(os.path.dirname(sys.executable), "edge-tts.exe")
        edge_tts_cmd = active_venv_bin if os.path.exists(active_venv_bin) else "edge-tts"
        try:
            process = await asyncio.create_subprocess_exec(
                edge_tts_cmd,
                "--voice", voice,
                "--text", clean_text,
                "--write-media", audio_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            await process.communicate()
            generated_successfully = True
        except: pass

    # Video Muxing
    video_filename = f"stream_{persona}_{timestamp}.mp4"
    video_path = os.path.join(ANIMATIONS_DIR, video_filename)
    video_url = None
    
    try:
        base_video_path = None
        if custom_base_video_url:
            relative_url = custom_base_video_url.lstrip("/")
            local_path = os.path.join(os.path.dirname(__file__), relative_url)
            
            if sentiment != "neutral":
                expr_path = local_path.replace("base.mp4", f"base_{sentiment}.mp4")
                if os.path.exists(expr_path):
                    base_video_path = expr_path
                    
            if not base_video_path and os.path.exists(local_path):
                base_video_path = local_path
                
        if not base_video_path:
            base_video_path = await get_or_generate_base_video(persona)
            
        await combine_video_audio(base_video_path, audio_path, video_path)
        if os.path.exists(video_path):
            video_url = f"/static/animations/{video_filename}"
    except: pass
    
    return {
        "text": text,
        "audio_url": f"/static/audio/{audio_filename}",
        "video_url": video_url,
        "voice": voice
    }

@app.post("/api/chat/stream")
async def chat_stream(request: StreamChatRequest):
    persona = request.personality.lower()
    client_id = request.client_id or "default"
    
    async def event_generator():
        system_prompt = await build_dynamic_system_prompt(persona, client_id)
        voice = PERSONALITY_VOICES.get(persona, PERSONALITY_VOICES["ceo"])
        
        custom_base_video_url = None
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT video_path, status FROM client_avatars WHERE client_id = ? AND persona = ?",
                (client_id, persona)
            )
            row = cursor.fetchone()
            conn.close()
            if row and row[1] == 'complete' and row[0]:
                custom_base_video_url = row[0]
        except Exception as e:
            print(f"Error querying custom base video: {e}")
            
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": request.message}
        ]
        
        async with httpx.AsyncClient(timeout=5.0) as client:
            base_url, active_model = await get_local_llm_info(client)
            
        sentiment = "neutral"
        sentiment_parsed = False
        current_sentence = ""
        accumulated_text = ""
        
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                async with client.stream(
                    "POST",
                    f"{base_url}/chat/completions",
                    json={
                        "model": active_model,
                        "messages": messages,
                        "stream": True,
                        "temperature": 0.7,
                        "max_tokens": 120
                    }
                ) as response:
                    if response.status_code != 200:
                        yield f"data: {json.dumps({'error': 'LLM offline'})}\n\n"
                        return
                        
                    async for line_raw in response.iter_lines():
                        if not line_raw.strip():
                            continue
                        line = line_raw.decode('utf-8') if isinstance(line_raw, bytes) else line_raw
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str.strip() == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_str)
                                content = chunk["choices"][0]["delta"].get("content", "")
                                if content:
                                    accumulated_text += content
                                    
                                    if not sentiment_parsed and "]" in accumulated_text:
                                        import re
                                        tag_match = re.match(r"^\[(HAPPY|SERIOUS|THOUGHTFUL|NEUTRAL)\]", accumulated_text.strip(), re.IGNORECASE)
                                        if tag_match:
                                            sentiment = tag_match.group(1).lower()
                                            accumulated_text = accumulated_text[tag_match.end():].strip()
                                            sentiment_parsed = True
                                            current_sentence = accumulated_text
                                        elif accumulated_text.strip().startswith("[") and len(accumulated_text) > 15:
                                            sentiment_parsed = True
                                            current_sentence = accumulated_text
                                    else:
                                        if sentiment_parsed or (not accumulated_text.strip().startswith("[") and len(accumulated_text) > 0):
                                            if not current_sentence and accumulated_text:
                                                current_sentence = accumulated_text
                                            else:
                                                current_sentence += content
                                            
                                            import re
                                            sentences = re.split(r'(?<=[.!?\n])\s+', current_sentence)
                                            if sentences:
                                                if not re.search(r'[.!?\n]$', sentences[-1].strip()):
                                                    current_sentence = sentences.pop()
                                                else:
                                                    current_sentence = ""
                                                    
                                                for s in sentences:
                                                    s_clean = s.strip()
                                                    if s_clean:
                                                        result = await process_stream_sentence(s_clean, persona, sentiment, custom_base_video_url)
                                                        yield f"data: {json.dumps(result)}\n\n"
                            except Exception as e:
                                print(f"Error parsing chunk: {e}")
                                
            remaining = current_sentence.strip()
            if remaining:
                result = await process_stream_sentence(remaining, persona, sentiment, custom_base_video_url)
                yield f"data: {json.dumps(result)}\n\n"
                
        except Exception as e:
            print(f"Error in stream event_generator: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

async def render_heygen_cloud(text: str, persona: str) -> str:
    heygen_key = os.environ.get("HEYGEN_API_KEY")
    if not heygen_key:
        raise ValueError("HEYGEN_API_KEY is not configured in your .env file.")
    url = "https://api.heygen.com/v2/video/generate"
    headers = {"X-Api-Key": heygen_key, "Content-Type": "application/json"}
    avatar_id = "4e4c3ae0-3778-4bdc-a51c-456993c54c37"
    voice_id = "f2d5fcfe-07d0-4d07-9e8e-ed92ef848c4f"
    payload = {
        "caption": False,
        "title": f"Sovereign Pitch - {persona}",
        "video_setting": {"width": 1080, "height": 1920, "fps": 30},
        "clips": [{"avatar_id": avatar_id, "avatar_style": "normal", "input_text": text, "voice_id": voice_id}]
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        res = await client.post(url, json=payload, headers=headers)
        if res.status_code == 200:
            data = res.json()
            video_id = data.get("data", {}).get("video_id")
            return f"https://api.heygen.com/v2/video/status?video_id={video_id}"
        else:
            raise RuntimeError(f"HeyGen API error: {res.status_code} - {res.text}")

async def render_tavus_cloud(text: str) -> str:
    tavus_key = os.environ.get("TAVUS_API_KEY")
    if not tavus_key:
        raise ValueError("TAVUS_API_KEY is not configured in your .env file.")
    url = "https://api.tavus.io/v2/videos"
    headers = {"x-api-key": tavus_key, "Content-Type": "application/json"}
    replica_id = "r792b0d62c"
    payload = {"replica_id": replica_id, "script": text}
    async with httpx.AsyncClient(timeout=60.0) as client:
        res = await client.post(url, json=payload, headers=headers)
        if res.status_code == 200:
            data = res.json()
            return data.get("video_url") or ""
        else:
            raise RuntimeError(f"Tavus API error: {res.status_code} - {res.text}")

@app.post("/api/avatar/upload-portrait")
async def upload_portrait(
    file: UploadFile = File(...),
    client_id: str = Form(...),
    persona: str = Form(...)
):
    """Uploads a portrait photo, generates a static loop video, and registers the avatar."""
    try:
        persona = persona.lower()
        upload_dir = os.path.join(os.path.dirname(__file__), "static", "uploads", client_id, persona)
        os.makedirs(upload_dir, exist_ok=True)
        
        portrait_path = os.path.join(upload_dir, "portrait.jpg")
        with open(portrait_path, "wb") as f:
            f.write(await file.read())
            
        # Convert portrait photo to a 5-second static video base.mp4
        base_video_path = os.path.join(upload_dir, "base.mp4")
        conv_cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", portrait_path,
            "-c:v", "libx264",
            "-t", "5",
            "-pix_fmt", "yuv420p",
            "-vf", "scale=600:600",
            base_video_path
        ]
        
        process = await asyncio.create_subprocess_exec(
            *conv_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        await process.wait()
        
        # Save to database
        db_video_path = f"/static/uploads/{client_id}/{persona}/base.mp4"
        db_image_path = f"/static/uploads/{client_id}/{persona}/portrait.jpg"
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO client_avatars (client_id, persona, name, image_path, video_path, status)
            VALUES (?, ?, ?, ?, ?, 'complete')
            ON CONFLICT(client_id, persona) DO UPDATE SET
                image_path = excluded.image_path,
                video_path = excluded.video_path,
                status = 'complete';
            """,
            (client_id, persona, f"{persona.capitalize()} Twin", db_image_path, db_video_path)
        )
        conn.commit()
        conn.close()
        
        return {"status": "success", "video_path": db_video_path, "image_path": db_image_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/avatar/upload-knowledge")
async def upload_knowledge(
    file: UploadFile = File(...),
    client_id: str = Form(...),
    persona: str = Form(...)
):
    """Uploads a knowledge base file for the given avatar."""
    try:
        persona = persona.lower()
        kb_dir = os.path.join(os.path.dirname(__file__), "static", "uploads", client_id, persona, "knowledge")
        os.makedirs(kb_dir, exist_ok=True)
        
        file_path = os.path.join(kb_dir, file.filename)
        with open(file_path, "wb") as f:
            f.write(await file.read())
            
        doc_id = str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat()
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO avatar_knowledge_bases (doc_id, client_id, persona, filename, file_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (doc_id, client_id, persona, file.filename, file_path, created_at)
        )
        conn.commit()
        conn.close()
        
        return {"status": "success", "doc_id": doc_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/avatar/knowledge")
async def get_knowledge(client_id: str, persona: str):
    """Retrieves all linked knowledge bases for the given avatar."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT doc_id, filename, created_at FROM avatar_knowledge_bases WHERE client_id = ? AND persona = ?",
            (client_id, persona.lower())
        )
        rows = cursor.fetchall()
        conn.close()
        
        return [{"id": r[0], "filename": r[1], "created_at": r[2]} for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/avatar/knowledge/{doc_id}")
async def delete_knowledge(doc_id: str):
    """Deletes a linked knowledge base document."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT file_path FROM avatar_knowledge_bases WHERE doc_id = ?", (doc_id,))
        row = cursor.fetchone()
        if row:
            file_path = row[0]
            if os.path.exists(file_path):
                try: os.remove(file_path)
                except: pass
            cursor.execute("DELETE FROM avatar_knowledge_bases WHERE doc_id = ?", (doc_id,))
            conn.commit()
        conn.close()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

gpu_render_lock = None

@app.post("/api/video/render")
async def render_video(request: RenderRequest):
    global gpu_render_lock
    if gpu_render_lock is None:
        gpu_render_lock = asyncio.Lock()
        
    persona = request.personality.lower()
    client_id = request.client_id or "default"
    sentiment = request.sentiment.lower() if request.sentiment else "neutral"
    
    try:
        voice = PERSONALITY_VOICES.get(persona, PERSONALITY_VOICES["ceo"])
        
        custom_base_video_url = None
        if client_id and client_id != "default":
            try:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT video_path, status FROM client_avatars WHERE client_id = ? AND persona = ?",
                    (client_id, persona)
                )
                row = cursor.fetchone()
                conn.close()
                if row and row[1] == 'complete' and row[0]:
                    custom_base_video_url = row[0]
            except Exception as e:
                print(f"Error querying custom base video: {e}")
                
        timestamp = int(time.time())
        audio_filename = f"render_{persona}_{timestamp}.wav"
        audio_path = os.path.join(AUDIO_DIR, audio_filename)
        clean_text = request.text.replace('\n', ' ')
        
        generated_successfully = False
        
        if client_id and client_id != "default":
            ref_wav_path = os.path.join(os.path.dirname(__file__), "static", "uploads", client_id, persona, "reference.wav")
            ref_txt_path = os.path.join(os.path.dirname(__file__), "static", "uploads", client_id, persona, "reference.txt")
            if os.path.exists(ref_wav_path):
                try:
                    print(f"Attempting local zero-shot voice cloning via F5-TTS for client={client_id}, persona={persona}...")
                    ref_text = "Hello."
                    if os.path.exists(ref_txt_path):
                        with open(ref_txt_path, "r", encoding="utf-8") as f:
                            ref_text = f.read().strip()
                    
                    python_bin = os.path.join(os.path.dirname(__file__), ".venv", "Scripts", "python.exe")
                    cmd = [
                        python_bin, "-m", "f5_tts.infer.cli",
                        "--gen_text", clean_text,
                        "--ref_file", ref_wav_path,
                        "--ref_text", ref_text,
                        "--file_output", audio_path
                    ]
                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                    await process.communicate()
                    if os.path.exists(audio_path):
                        print("F5-TTS voice cloning completed successfully!")
                        generated_successfully = True
                except Exception as e:
                    print(f"F5-TTS voice cloning failed: {e}. Falling back.")
                    
        elevenlabs_key = os.environ.get("ELEVENLABS_API_KEY")
        hipaa_mode = os.environ.get("HIPAA_COMPLIANCE_MODE", "false").lower() == "true"
        if not generated_successfully and elevenlabs_key and not hipaa_mode:
            try:
                print("Attempting speech synthesis via ElevenLabs API...")
                voice_id = get_voice_id(persona)
                url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
                headers = {
                    "Accept": "audio/mpeg",
                    "Content-Type": "application/json",
                    "xi-api-key": elevenlabs_key
                }
                payload = {
                    "text": clean_text,
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75
                    }
                }
                async with httpx.AsyncClient(timeout=30.0) as client:
                    res = await client.post(url, json=payload, headers=headers)
                    if res.status_code == 200:
                        audio_filename = f"render_{persona}_{timestamp}.mp3"
                        audio_path = os.path.join(AUDIO_DIR, audio_filename)
                        with open(audio_path, "wb") as f:
                            f.write(res.content)
                        print("ElevenLabs speech synthesis completed successfully!")
                        generated_successfully = True
            except Exception as e:
                print(f"ElevenLabs synthesis failed: {e}")
                
        if not generated_successfully:
            voicebox_url = "http://127.0.0.1:17493"
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    health_res = await client.get(f"{voicebox_url}/health")
                    if health_res.status_code == 200:
                        profiles_res = await client.get(f"{voicebox_url}/profiles")
                        if profiles_res.status_code == 200:
                            profiles = profiles_res.json()
                            voicebox_profile_id = None
                            voicebox_profile_engine = "qwen"
                            for p in profiles:
                                if p.get("name", "").lower() == persona:
                                    voicebox_profile_id = p["id"]
                                    voicebox_profile_engine = p.get("default_engine") or p.get("preset_engine") or "qwen"
                                    break
                            if not voicebox_profile_id and len(profiles) > 0:
                                voicebox_profile_id = profiles[0]["id"]
                                voicebox_profile_engine = profiles[0].get("default_engine") or profiles[0].get("preset_engine") or "qwen"
                            if voicebox_profile_id:
                                print(f"Routing speech synthesis to Voicebox (profile: {voicebox_profile_id}, engine: {voicebox_profile_engine})...")
                                audio_filename = f"render_{persona}_{timestamp}.mp3"
                                audio_path = os.path.join(AUDIO_DIR, audio_filename)
                                
                                gen_res = await client.post(
                                    f"{voicebox_url}/generate",
                                    json={
                                        "profile_id": voicebox_profile_id,
                                        "text": clean_text,
                                        "language": "en",
                                        "engine": voicebox_profile_engine
                                    },
                                    timeout=10.0
                                )
                                if gen_res.status_code == 200:
                                    gen_data = gen_res.json()
                                    gen_id = gen_data["id"]
                                    for attempt in range(30):
                                        await asyncio.sleep(1.0)
                                        status_res = await client.get(f"{voicebox_url}/history/{gen_id}")
                                        if status_res.status_code == 200:
                                            status = status_res.json().get("status")
                                            if status == "completed":
                                                audio_download_res = await client.get(f"{voicebox_url}/audio/{gen_id}")
                                                if audio_download_res.status_code == 200:
                                                    with open(audio_path, "wb") as f:
                                                        f.write(audio_download_res.content)
                                                    print("Voicebox speech synthesis completed successfully!")
                                                    generated_successfully = True
                                                    break
                                            elif status == "failed":
                                                break
            except Exception as e:
                print(f"Voicebox generation failed/offline: {e}. Falling back.")
                
        if not generated_successfully and kokoro_model is not None:
            try:
                print("Attempting local speech synthesis via Kokoro ONNX...")
                voice_name = KOKORO_VOICES.get(persona, "af_bella")
                def run_kokoro():
                    samples, sample_rate = kokoro_model.create(clean_text, voice=voice_name, speed=1.0, lang="en-us")
                    sf.write(audio_path, samples, sample_rate)
                await asyncio.to_thread(run_kokoro)
                print("Local Kokoro speech synthesis completed successfully!")
                generated_successfully = True
            except Exception as e:
                print(f"Local Kokoro failed: {e}")
                
        if not generated_successfully:
            audio_filename = f"render_{persona}_{timestamp}.mp3"
            audio_path = os.path.join(AUDIO_DIR, audio_filename)
            edge_tts_cmd = "edge-tts"
            active_venv_bin = os.path.join(os.path.dirname(sys.executable), "edge-tts.exe")
            if os.path.exists(active_venv_bin):
                edge_tts_cmd = active_venv_bin
            try:
                process = await asyncio.create_subprocess_exec(
                    edge_tts_cmd,
                    "--voice", voice,
                    "--text", clean_text,
                    "--write-media", audio_path,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                await process.communicate()
                if os.path.exists(audio_path):
                    generated_successfully = True
            except Exception as e:
                print(f"Edge-TTS failed: {e}")
                
        if not generated_successfully:
            raise HTTPException(status_code=500, detail="All TTS pipelines failed.")
            
        video_filename = f"render_{persona}_{timestamp}.mp4"
        video_path = os.path.join(ANIMATIONS_DIR, video_filename)
        video_url = None
        
        engine = request.engine.lower() if request.engine else "local"
        
        if engine == "heygen":
            print(f"Routing video render to HeyGen Cloud API...")
            cloud_url = await render_heygen_cloud(clean_text, persona)
            return {
                "status": "complete",
                "video_url": cloud_url,
                "audio_url": f"http://localhost:8085/static/audio/{audio_filename}",
                "text": clean_text
            }
        elif engine == "tavus":
            print(f"Routing video render to Tavus Cloud API...")
            cloud_url = await render_tavus_cloud(clean_text)
            return {
                "status": "complete",
                "video_url": cloud_url,
                "audio_url": f"http://localhost:8085/static/audio/{audio_filename}",
                "text": clean_text
            }

        base_video_path = None
        if custom_base_video_url:
            relative_url = custom_base_video_url.lstrip("/")
            local_path = os.path.join(os.path.dirname(__file__), relative_url)
            if sentiment != "neutral":
                expr_path = local_path.replace("base.mp4", f"base_{sentiment}.mp4")
                if os.path.exists(expr_path):
                    base_video_path = expr_path
            if not base_video_path and os.path.exists(local_path):
                base_video_path = local_path
                
        if not base_video_path:
            base_video_path = await get_or_generate_base_video(persona)
            
        async with gpu_render_lock:
            if engine == "echomimic":
                wav_audio_path = audio_path
                if audio_path.endswith(".mp3"):
                    wav_audio_path = audio_path.replace(".mp3", ".wav")
                    conv_cmd = ["ffmpeg", "-y", "-i", audio_path, wav_audio_path]
                    process = await asyncio.create_subprocess_exec(*conv_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    await process.wait()
                image_path = get_portrait_image_path(client_id, persona)
                await combine_video_audio_echomimic(image_path, wav_audio_path, video_path)
            elif engine == "musetalk":
                wav_audio_path = audio_path
                if audio_path.endswith(".mp3"):
                    wav_audio_path = audio_path.replace(".mp3", ".wav")
                    conv_cmd = ["ffmpeg", "-y", "-i", audio_path, wav_audio_path]
                    process = await asyncio.create_subprocess_exec(*conv_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    await process.wait()
                await combine_video_audio_musetalk(base_video_path, wav_audio_path, video_path)
            else:
                await combine_video_audio(base_video_path, audio_path, video_path)
        
        if os.path.exists(video_path):
            video_url = f"/static/animations/{video_filename}"
            
        return {
            "status": "complete",
            "video_url": f"http://localhost:8085{video_url}" if video_url else None,
            "audio_url": f"http://localhost:8085/static/audio/{audio_filename}",
            "text": clean_text
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- TAVUS INTEGRATION SCHEMAS & ENDPOINTS ---

class TavusPalRequest(BaseModel):
    pal_name: str
    system_prompt: str
    pipeline_mode: str = "full"
    default_face_id: str
    document_ids: Optional[List[str]] = None
    document_tags: Optional[List[str]] = None
    objectives_id: Optional[str] = None
    guardrail_ids: Optional[List[str]] = None
    guardrail_tags: Optional[List[str]] = None
    layers: Optional[Dict] = None

class TavusConversationRequest(BaseModel):
    pal_id: str
    custom_greeting: Optional[str] = None
    callback_url: Optional[str] = None
    conversation_name: Optional[str] = None

@app.post("/api/tavus/pals")
async def create_tavus_pal(request: TavusPalRequest):
    api_key = os.getenv("TAVUS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="Tavus API Key is missing. Configure TAVUS_API_KEY in your .env file.")
        
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key
    }
    
    payload = request.dict(exclude_none=True)
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post("https://tavusapi.com/v2/pals", json=payload, headers=headers, timeout=60.0)
            if response.status_code not in [200, 201]:
                raise HTTPException(status_code=response.status_code, detail=response.text)
                
            res_data = response.json()
            pal_id = res_data.get("pal_id")
            pal_name = res_data.get("pal_name")
            conferencing_email = res_data.get("conferencing_email")
            created_at = res_data.get("created_at") or time.strftime('%Y-%m-%d %H:%M:%S')
            
            # Save PAL details locally
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO tavus_pals (pal_id, pal_name, system_prompt, pipeline_mode, default_face_id, conferencing_email, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (pal_id, pal_name, request.system_prompt, request.pipeline_mode, request.default_face_id, conferencing_email, created_at)
            )
            conn.commit()
            conn.close()
            
            return res_data
        except Exception as e:
            if isinstance(e, HTTPException):
                raise e
            raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/tavus/pals")
def list_tavus_pals():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT pal_id, pal_name, system_prompt, pipeline_mode, default_face_id, conferencing_email, created_at FROM tavus_pals")
    rows = cursor.fetchall()
    conn.close()
    
    pals = []
    for r in rows:
        pals.append({
            "pal_id": r[0],
            "pal_name": r[1],
            "system_prompt": r[2],
            "pipeline_mode": r[3],
            "default_face_id": r[4],
            "conferencing_email": r[5],
            "created_at": r[6]
        })
    return pals

@app.get("/api/tavus/replicas")
async def list_tavus_replicas():
    api_key = os.getenv("TAVUS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="Tavus API Key is missing. Configure TAVUS_API_KEY in your .env file.")
    headers = {
        "x-api-key": api_key,
        "Accept": "application/json"
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get("https://tavusapi.com/v2/replicas", headers=headers, timeout=30.0)
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=response.text)
            return response.json()
        except Exception as e:
            if isinstance(e, HTTPException):
                raise e
            raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/tavus/conversations")
async def create_tavus_conversation(request: TavusConversationRequest):
    api_key = os.getenv("TAVUS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="Tavus API Key is missing. Configure TAVUS_API_KEY in your .env file.")
        
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key
    }
    
    payload = request.dict(exclude_none=True)
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post("https://tavusapi.com/v2/conversations", json=payload, headers=headers, timeout=60.0)
            if response.status_code not in [200, 201]:
                raise HTTPException(status_code=response.status_code, detail=response.text)
            return response.json()
        except Exception as e:
            if isinstance(e, HTTPException):
                raise e
            raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/speech-to-text")
async def speech_to_text(file: UploadFile = File(...)):
    """Transcribe audio file locally using the Voicebox STT Whisper backend on port 17493."""
    url = "http://127.0.0.1:17493/transcribe"
    
    async with httpx.AsyncClient() as client:
        try:
            files = {"file": (file.filename, file.file, file.content_type)}
            response = await client.post(url, files=files, timeout=60.0)
            
            if response.status_code == 202:
                return response.json()
            elif response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=response.text)
                
            return response.json()
        except Exception as e:
            if isinstance(e, HTTPException):
                raise e
            raise HTTPException(status_code=500, detail=str(e))


class ScraperRequest(BaseModel):
    url: str

@app.post("/api/scraper/run")
async def run_scraper(request: ScraperRequest):
    import subprocess
    script_path = r"C:\Users\Jccof\Downloads\Hermes Agent\JC Coffey Foundation\sovereign_scraper.py"
    
    try:
        cmd = [sys.executable, script_path, request.url]
        process = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        
        # Read the scraped leads file
        scraped_leads = []
        leads_file = r"C:\Users\Jccof\Downloads\Hermes Agent\JC Coffey Foundation\renders\scraped_leads.txt"
        if os.path.exists(leads_file):
            with open(leads_file, "r") as f:
                scraped_leads = [line.strip() for line in f if line.strip()]
                
        return {
            "stdout": process.stdout,
            "stderr": process.stderr,
            "returncode": process.returncode,
            "leads": list(set(scraped_leads))[-15:]  # Return last 15 unique leads
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- LIVEAVATAR INTEGRATION SCHEMAS & ENDPOINTS ---

class LiveAvatarEmbedRequest(BaseModel):
    avatar_id: str
    context_id: Optional[str] = None
    is_sandbox: bool = True

class LiveAvatarSessionTokenRequest(BaseModel):
    mode: str = "FULL"
    is_sandbox: bool = True
    avatar_id: str
    voice_id: Optional[str] = None
    language: str = "en"

@app.post("/api/liveavatar/embeddings")
async def create_liveavatar_embedding(request: LiveAvatarEmbedRequest):
    api_key = os.getenv("LIVEAVATAR_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="LiveAvatar API Key is missing. Configure LIVEAVATAR_API_KEY in your .env file.")
        
    headers = {
        "Content-Type": "application/json",
        "X-API-KEY": api_key
    }
    
    payload = request.dict(exclude_none=True)
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post("https://api.liveavatar.com/v2/embeddings", json=payload, headers=headers, timeout=60.0)
            if response.status_code not in [200, 201]:
                raise HTTPException(status_code=response.status_code, detail=response.text)
                
            res_data = response.json()
            embed_data = res_data.get("data", {})
            url = embed_data.get("url")
            script = embed_data.get("script")
            embed_id = url.split("/")[-1] if url else time.strftime('%Y%m%d%H%M%S')
            created_at = time.strftime('%Y-%m-%d %H:%M:%S')
            
            # Save embed details locally
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO liveavatar_embeddings (embed_id, avatar_id, context_id, url, script, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (embed_id, request.avatar_id, request.context_id, url, script, created_at)
            )
            conn.commit()
            conn.close()
            
            return res_data
        except Exception as e:
            if isinstance(e, HTTPException):
                raise e
            raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/liveavatar/sessions/token")
async def create_liveavatar_session_token(request: LiveAvatarSessionTokenRequest):
    api_key = os.getenv("LIVEAVATAR_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="LiveAvatar API Key is missing. Configure LIVEAVATAR_API_KEY in your .env file.")
        
    headers = {
        "Content-Type": "application/json",
        "X-API-KEY": api_key
    }
    
    payload = {
        "mode": request.mode,
        "is_sandbox": request.is_sandbox,
        "avatar_id": request.avatar_id,
        "avatar_persona": {
            "voice_id": request.voice_id,
            "language": request.language
        }
    }
    if not request.voice_id:
        payload["avatar_persona"].pop("voice_id", None)
        
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post("https://api.liveavatar.com/v1/sessions/token", json=payload, headers=headers, timeout=60.0)
            if response.status_code not in [200, 201]:
                raise HTTPException(status_code=response.status_code, detail=response.text)
            return response.json()
        except Exception as e:
            if isinstance(e, HTTPException):
                raise e
            raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/liveavatar/avatars")
def list_liveavatar_stock_avatars():
    return [
        {"name": "Wayne (Sandbox Default)", "avatar_id": "dd73ea75-1218-4ef3-92ce-606d5f7fbc0a", "orientation": "portrait"},
        {"name": "Alessandra in Black Suit", "avatar_id": "9c59a215-4c9f-478f-9d95-edca74c7b0d0", "orientation": "landscape"},
        {"name": "Alessandra in Black Suit (Portrait)", "avatar_id": "de82b2cc-7314-40a1-b41f-cc456c66601c", "orientation": "portrait"},
        {"name": "Amina in Black Suit", "avatar_id": "42700a53-38ab-4485-b46f-26be6e0953dc", "orientation": "landscape"},
        {"name": "Amina in Black Suit (Portrait)", "avatar_id": "06bcaebf-feeb-4e7a-8ab8-16b9f9537a19", "orientation": "portrait"},
        {"name": "Anthony in Black Suit", "avatar_id": "38ad67ed-98f0-407c-a2d2-4f0998b306fc", "orientation": "landscape"},
        {"name": "Anthony in Black Suit (Portrait)", "avatar_id": "3466af9c-45f5-40f2-8392-c51f8385422c", "orientation": "portrait"},
        {"name": "Graham in Black Suit", "avatar_id": "03f8332d-9046-42a1-bff3-3b2309f77b58", "orientation": "landscape"},
        {"name": "Graham in Black Suit (Portrait)", "avatar_id": "fc4125a5-83fa-45e2-8574-bf657ac19998", "orientation": "portrait"}
    ]


@app.post("/api/chat")
async def chat(request: ChatRequest):
    persona = request.personality.lower()
    client_id = request.client_id or "default"
    
    # Interrupt any existing task for this client
    if client_id in active_chat_tasks:
        existing_task = active_chat_tasks[client_id]
        if not existing_task.done():
            existing_task.cancel()
            print(f"Automatically cancelled previous active chat task for client {client_id}")
            
    current_task = asyncio.current_task()
    active_chat_tasks[client_id] = current_task
    sentiment = "neutral"
    
    try:
        system_prompt = await build_dynamic_system_prompt(persona, request.client_id)
        voice = PERSONALITY_VOICES.get(persona, PERSONALITY_VOICES["ceo"])
        model = PERSONALITY_MODELS.get(persona, "qwen2.5:7b")
        
        custom_base_video_url = None
        if request.client_id:
            try:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT video_path, status FROM client_avatars WHERE client_id = ? AND persona = ?",
                    (request.client_id, persona)
                )
                row = cursor.fetchone()
                conn.close()
                if row and row[1] == 'complete' and row[0]:
                    custom_base_video_url = row[0]
            except Exception as e:
                print(f"Error querying custom base video: {e}")
                
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": request.message}
        ]
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                base_url, active_model = await get_local_llm_info(client)
                response = await client.post(
                    f"{base_url}/chat/completions",
                    json={
                        "model": active_model, 
                        "messages": messages, 
                        "stream": False,
                        "temperature": 0.7,
                        "max_tokens": 120
                    },
                    timeout=45.0
                )
                
                if response.status_code != 200:
                    raise HTTPException(status_code=500, detail="LM Studio failed to respond.")
                    
                response_json = response.json()
                reply_raw = response_json["choices"][0]["message"]["content"].strip()
                
                # Parse sentiment tag
                import re
                tag_match = re.match(r"^\[(HAPPY|SERIOUS|THOUGHTFUL|NEUTRAL)\]", reply_raw, re.IGNORECASE)
                if tag_match:
                    sentiment = tag_match.group(1).lower()
                    reply_text = reply_raw[tag_match.end():].strip()
                else:
                    reply_text = reply_raw
                print(f"Parsed sentiment: {sentiment} for persona {persona}")
                
        except Exception as e:
            print(f"Error calling LLM: {e}")
            reply_text = "I am currently initializing my local cognitive nodes. Please verify LM Studio is active."
    
        # 2. Synthesize Speech
        timestamp = int(time.time())
        audio_filename = f"reply_{persona}_{timestamp}.wav"
        audio_path = os.path.join(AUDIO_DIR, audio_filename)
        clean_text = reply_text.replace('\n', ' ')
    
        generated_successfully = False
        
        # 2a. Attempt custom F5-TTS voice cloning if reference files are uploaded
        if client_id and client_id != "default":
            ref_wav_path = os.path.join(os.path.dirname(__file__), "static", "uploads", client_id, persona, "reference.wav")
            ref_txt_path = os.path.join(os.path.dirname(__file__), "static", "uploads", client_id, persona, "reference.txt")
            if os.path.exists(ref_wav_path):
                try:
                    print(f"Attempting local zero-shot voice cloning via F5-TTS for client={client_id}, persona={persona}...")
                    ref_text = "Hello."
                    if os.path.exists(ref_txt_path):
                        with open(ref_txt_path, "r", encoding="utf-8") as f:
                            ref_text = f.read().strip()
                    
                    # Run F5-TTS CLI tool
                    python_bin = os.path.join(os.path.dirname(__file__), ".venv", "Scripts", "python.exe")
                    cmd = [
                        python_bin, "-m", "f5_tts.infer.cli",
                        "--gen_text", clean_text,
                        "--ref_file", ref_wav_path,
                        "--ref_text", ref_text,
                        "--file_output", audio_path
                    ]
                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                    await process.communicate()
                    if os.path.exists(audio_path):
                        print("F5-TTS voice cloning completed successfully!")
                        generated_successfully = True
                except Exception as e:
                    print(f"F5-TTS voice cloning failed: {e}. Falling back.")
                    
        elevenlabs_key = os.environ.get("ELEVENLABS_API_KEY")
        hipaa_mode = os.environ.get("HIPAA_COMPLIANCE_MODE", "false").lower() == "true"
        if elevenlabs_key and not hipaa_mode:
            try:
                print("Attempting speech synthesis via ElevenLabs API...")
                voice_id = get_voice_id(persona)
                url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
                
                headers = {
                    "Accept": "audio/mpeg",
                    "Content-Type": "application/json",
                    "xi-api-key": elevenlabs_key
                }
                
                payload = {
                    "text": clean_text,
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75
                    }
                }
                
                async with httpx.AsyncClient(timeout=30.0) as client:
                    res = await client.post(url, json=payload, headers=headers)
                    if res.status_code == 200:
                        audio_filename = f"reply_{persona}_{timestamp}.mp3"
                        audio_path = os.path.join(AUDIO_DIR, audio_filename)
                        with open(audio_path, "wb") as f:
                            f.write(res.content)
                        print("ElevenLabs speech synthesis completed successfully!")
                        generated_successfully = True
                    else:
                        print(f"ElevenLabs API returned error status {res.status_code}: {res.text}. Falling back.")
            except Exception as e:
                print(f"ElevenLabs API request failed: {e}. Falling back.")
    
        if not generated_successfully and kokoro_model is not None:
            try:
                print("Attempting local speech synthesis via Kokoro ONNX...")
                voice_name = KOKORO_VOICES.get(persona, "af_bella")
                
                def run_kokoro():
                    samples, sample_rate = kokoro_model.create(clean_text, voice=voice_name, speed=1.0, lang="en-us")
                    sf.write(audio_path, samples, sample_rate)
                
                await asyncio.to_thread(run_kokoro)
                print("Local Kokoro speech synthesis completed successfully!")
                generated_successfully = True
            except Exception as e:
                print(f"Local Kokoro speech synthesis failed: {e}. Falling back.")
    
        if not generated_successfully:
            voicebox_url = "http://127.0.0.1:17493"
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    health_res = await client.get(f"{voicebox_url}/health")
                    if health_res.status_code == 200:
                        profiles_res = await client.get(f"{voicebox_url}/profiles")
                        if profiles_res.status_code == 200:
                            profiles = profiles_res.json()
                            voicebox_profile_id = None
                            voicebox_profile_engine = "qwen"
                            for p in profiles:
                                if p.get("name", "").lower() == persona:
                                    voicebox_profile_id = p["id"]
                                    voicebox_profile_engine = p.get("default_engine") or p.get("preset_engine") or "qwen"
                                    break
                            if not voicebox_profile_id and len(profiles) > 0:
                                voicebox_profile_id = profiles[0]["id"]
                                voicebox_profile_engine = profiles[0].get("default_engine") or profiles[0].get("preset_engine") or "qwen"
                            if voicebox_profile_id:
                                print(f"Routing speech synthesis to Voicebox (profile: {voicebox_profile_id}, engine: {voicebox_profile_engine})...")
                                audio_filename = f"reply_{persona}_{timestamp}.mp3"
                                audio_path = os.path.join(AUDIO_DIR, audio_filename)
                                
                                gen_res = await client.post(
                                    f"{voicebox_url}/generate",
                                    json={
                                        "profile_id": voicebox_profile_id,
                                        "text": clean_text,
                                        "language": "en",
                                        "engine": voicebox_profile_engine
                                    },
                                    timeout=10.0
                                )
                                if gen_res.status_code == 200:
                                    gen_data = gen_res.json()
                                    gen_id = gen_data["id"]
                                    for attempt in range(30):
                                        await asyncio.sleep(1.0)
                                        status_res = await client.get(f"{voicebox_url}/history/{gen_id}")
                                        if status_res.status_code == 200:
                                            status = status_res.json().get("status")
                                            if status == "completed":
                                                audio_download_res = await client.get(f"{voicebox_url}/audio/{gen_id}")
                                                if audio_download_res.status_code == 200:
                                                    with open(audio_path, "wb") as f:
                                                        f.write(audio_download_res.content)
                                                    print("Voicebox speech synthesis completed successfully!")
                                                    generated_successfully = True
                                                    break
                                            elif status == "failed":
                                                break
            except Exception as e:
                print(f"Voicebox generation failed/offline: {e}. Falling back.")
    
        if not generated_successfully:
            audio_filename = f"reply_{persona}_{timestamp}.mp3"
            audio_path = os.path.join(AUDIO_DIR, audio_filename)
            
            edge_tts_cmd = "edge-tts"
            active_venv_bin = os.path.join(os.path.dirname(sys.executable), "edge-tts.exe")
            if os.path.exists(active_venv_bin):
                edge_tts_cmd = active_venv_bin
            elif sys.platform == "win32":
                venv_bin = os.path.join(os.path.dirname(__file__), "..", "hermes-agent", "venv", "Scripts", "edge-tts.exe")
                if os.path.exists(venv_bin):
                    edge_tts_cmd = venv_bin
            try:
                print("Falling back to Edge-TTS...")
                process = await asyncio.create_subprocess_exec(
                    edge_tts_cmd,
                    "--voice", voice,
                    "--text", clean_text,
                    "--write-media", audio_path,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                if process.returncode != 0:
                    print(f"edge-tts failed: {stderr.decode()}")
                    raise Exception(stderr.decode())
                print("Edge-TTS speech synthesis completed successfully!")
                generated_successfully = True
            except Exception as e:
                print(f"Final Edge-TTS fallback failed: {e}")
                raise HTTPException(status_code=500, detail="All speech synthesis pipelines failed.")
    
        # 3. Generate Live Avatar Video
        video_filename = f"reply_{persona}_{timestamp}.mp4"
        video_path = os.path.join(ANIMATIONS_DIR, video_filename)
        video_url = None
        
        try:
            base_video_path = None
            if custom_base_video_url:
                relative_url = custom_base_video_url.lstrip("/")
                local_path = os.path.join(os.path.dirname(__file__), relative_url)
                
                # Check for sentiment-specific base video
                if sentiment != "neutral":
                    expr_path = local_path.replace("base.mp4", f"base_{sentiment}.mp4")
                    if os.path.exists(expr_path):
                        base_video_path = expr_path
                        print(f"Using expression-specific base video ({sentiment}): {base_video_path}")
                
                if not base_video_path and os.path.exists(local_path):
                    base_video_path = local_path
                    print(f"Using client-specific default custom video: {base_video_path}")
                    
            if not base_video_path:
                base_video_path = await get_or_generate_base_video(persona)
                print(f"Using default fallback base video: {base_video_path}")
                
            await combine_video_audio(base_video_path, audio_path, video_path)
            
            if os.path.exists(video_path):
                video_url = f"/static/animations/{video_filename}"
                print(f"Successfully generated talking video avatar: {video_url}")
        except Exception as e:
            print(f"Failed to generate Live Portrait video: {e}")
            video_url = None
    
        return {
            "text": reply_text,
            "audio_url": f"/static/audio/{audio_filename}",
            "video_url": video_url,
            "voice": voice
        }
    finally:
        if active_chat_tasks.get(client_id) == current_task:
            active_chat_tasks.pop(client_id, None)


@app.post("/api/chat/advisor")
async def chat_advisor(request: ChatRequest):
    persona = request.personality.lower()
    client_id = request.client_id or "default"
    
    # Interrupt any existing task for this client
    if client_id in active_chat_tasks:
        existing_task = active_chat_tasks[client_id]
        if not existing_task.done():
            existing_task.cancel()
            print(f"Automatically cancelled previous active chat task for client {client_id}")
            
    current_task = asyncio.current_task()
    active_chat_tasks[client_id] = current_task
    sentiment = "neutral"
    
    try:
        system_prompt = await build_dynamic_system_prompt(persona, request.client_id)
        voice = PERSONALITY_VOICES.get(persona, PERSONALITY_VOICES["ceo"])
        
        custom_base_video_url = None
        if request.client_id:
            try:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT video_path, status FROM client_avatars WHERE client_id = ? AND persona = ?",
                    (request.client_id, persona)
                )
                row = cursor.fetchone()
                conn.close()
                if row and row[1] == 'complete' and row[0]:
                    custom_base_video_url = row[0]
            except Exception as e:
                print(f"Error querying custom base video: {e}")
                
        reply_text = ""
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        
        if anthropic_key:
            print("Anthropic API key found. Invoking Claude Advisor Tool API...")
            try:
                headers = {
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "anthropic-beta": "advisor-tool-2026-03-01",
                    "content-type": "application/json"
                }
                payload = {
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 1024,
                    "tools": [
                        {
                            "type": "advisor_20260301",
                            "name": "advisor",
                            "model": "claude-opus-4-8"
                        }
                    ],
                    "system": system_prompt + "\n\nConsult your advisor for strategic guidance, then generate a response under 3 sentences.",
                    "messages": [
                        {"role": "user", "content": request.message}
                    ]
                }
                async with httpx.AsyncClient(timeout=45.0) as client:
                    response = await client.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
                    if response.status_code == 200:
                        res_data = response.json()
                        reply_raw = ""
                        for block in res_data.get("content", []):
                            if block.get("type") == "text":
                                reply_raw += block.get("text", "")
                        reply_text = reply_raw.strip()
                        print(f"Successfully generated response from Claude Advisor API: {reply_text}")
                    else:
                        print(f"Claude API failed with status {response.status_code}: {response.text}")
                        raise Exception("Anthropic API Error")
            except Exception as e:
                print(f"Error invoking Claude Advisor API: {e}. Falling back to local simulation...")
                anthropic_key = None
                
        if not anthropic_key:
            print("Running local executor-advisor simulation...")
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    base_url, active_model = await get_local_llm_info(client)
                        
                # Stage 1: Get Strategic Advice
                advisor_prompt = f"You are a high-intelligence C-Suite Strategic Advisor. Analyze the user's business query and provide a concise, high-level strategic recommendation. Query: {request.message}"
                async with httpx.AsyncClient(timeout=45.0) as client:
                    adv_res = await client.post(
                        f"{base_url}/chat/completions",
                        json={
                            "model": active_model,
                            "messages": [{"role": "user", "content": advisor_prompt}],
                            "stream": False,
                            "temperature": 0.5,
                            "max_tokens": 100
                        }
                    )
                    advice = ""
                    if adv_res.status_code == 200:
                        advice = adv_res.json()["choices"][0]["message"]["content"].strip()
                    print(f"Local Strategic Advice generated: {advice}")
                    
                    # Stage 2: Executor completes response incorporating advice
                    exec_prompt = f"{system_prompt}\n\nStrategic Advice from your Advisor:\n{advice}\n\nGenerate your final C-Suite executive response matching this strategic guidance. Keep it brief (under 3 sentences)."
                    exec_res = await client.post(
                        f"{base_url}/chat/completions",
                        json={
                            "model": active_model,
                            "messages": [
                                {"role": "system", "content": exec_prompt},
                                {"role": "user", "content": request.message}
                            ],
                            "stream": False,
                            "temperature": 0.7,
                            "max_tokens": 120
                        }
                    )
                    if exec_res.status_code == 200:
                        reply_text = exec_res.json()["choices"][0]["message"]["content"].strip()
                    else:
                        raise Exception("Local LLM Executor Failed")
            except Exception as e:
                print(f"Error during local advisor simulation: {e}")
                reply_text = "I am currently compiling advice from my executive committee. Please ensure LM Studio is active."
                
        # Parse sentiment tag
        import re
        tag_match = re.match(r"^\[(HAPPY|SERIOUS|THOUGHTFUL|NEUTRAL)\]", reply_text, re.IGNORECASE)
        if tag_match:
            sentiment = tag_match.group(1).lower()
            reply_text = reply_text[tag_match.end():].strip()
        print(f"Advisor response generated: '{reply_text}', sentiment: {sentiment}")
        
        # 2. Synthesize Speech
        timestamp = int(time.time())
        audio_filename = f"reply_{persona}_{timestamp}.wav"
        audio_path = os.path.join(AUDIO_DIR, audio_filename)
        clean_text = reply_text.replace('\n', ' ')
    
        generated_successfully = False
        
        # 2a. Attempt custom F5-TTS voice cloning if reference files are uploaded
        if client_id and client_id != "default":
            ref_wav_path = os.path.join(os.path.dirname(__file__), "static", "uploads", client_id, persona, "reference.wav")
            ref_txt_path = os.path.join(os.path.dirname(__file__), "static", "uploads", client_id, persona, "reference.txt")
            if os.path.exists(ref_wav_path):
                try:
                    print(f"Attempting local zero-shot voice cloning via F5-TTS for client={client_id}, persona={persona}...")
                    ref_text = "Hello."
                    if os.path.exists(ref_txt_path):
                        with open(ref_txt_path, "r", encoding="utf-8") as f:
                            ref_text = f.read().strip()
                    
                    # Run F5-TTS CLI tool
                    python_bin = os.path.join(os.path.dirname(__file__), ".venv", "Scripts", "python.exe")
                    cmd = [
                        python_bin, "-m", "f5_tts.infer.cli",
                        "--gen_text", clean_text,
                        "--ref_file", ref_wav_path,
                        "--ref_text", ref_text,
                        "--file_output", audio_path
                    ]
                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                    await process.communicate()
                    if os.path.exists(audio_path):
                        print("F5-TTS voice cloning completed successfully!")
                        generated_successfully = True
                except Exception as e:
                    print(f"F5-TTS voice cloning failed: {e}. Falling back.")
                    
        elevenlabs_key = os.environ.get("ELEVENLABS_API_KEY")
        hipaa_mode = os.environ.get("HIPAA_COMPLIANCE_MODE", "false").lower() == "true"
        if elevenlabs_key and not hipaa_mode:
            try:
                print("Attempting speech synthesis via ElevenLabs API...")
                voice_id = get_voice_id(persona)
                url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
                
                headers = {
                    "Accept": "audio/mpeg",
                    "Content-Type": "application/json",
                    "xi-api-key": elevenlabs_key
                }
                
                payload = {
                    "text": clean_text,
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75
                    }
                }
                
                async with httpx.AsyncClient(timeout=30.0) as client:
                    res = await client.post(url, json=payload, headers=headers)
                    if res.status_code == 200:
                        audio_filename = f"reply_{persona}_{timestamp}.mp3"
                        audio_path = os.path.join(AUDIO_DIR, audio_filename)
                        with open(audio_path, "wb") as f:
                            f.write(res.content)
                        print("ElevenLabs speech synthesis completed successfully!")
                        generated_successfully = True
                    else:
                        print(f"ElevenLabs API returned error status {res.status_code}: {res.text}. Falling back.")
            except Exception as e:
                print(f"ElevenLabs API request failed: {e}. Falling back.")
    
        if not generated_successfully and kokoro_model is not None:
            try:
                print("Attempting local speech synthesis via Kokoro ONNX...")
                voice_name = KOKORO_VOICES.get(persona, "af_bella")
                
                def run_kokoro():
                    samples, sample_rate = kokoro_model.create(clean_text, voice=voice_name, speed=1.0, lang="en-us")
                    sf.write(audio_path, samples, sample_rate)
                
                await asyncio.to_thread(run_kokoro)
                print("Local Kokoro speech synthesis completed successfully!")
                generated_successfully = True
            except Exception as e:
                print(f"Local Kokoro speech synthesis failed: {e}. Falling back.")
    
        if not generated_successfully:
            voicebox_url = "http://127.0.0.1:17493"
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    health_res = await client.get(f"{voicebox_url}/health")
                    if health_res.status_code == 200:
                        profiles_res = await client.get(f"{voicebox_url}/profiles")
                        if profiles_res.status_code == 200:
                            profiles = profiles_res.json()
                            voicebox_profile_id = None
                            voicebox_profile_engine = "qwen"
                            for p in profiles:
                                if p.get("name", "").lower() == persona:
                                    voicebox_profile_id = p["id"]
                                    voicebox_profile_engine = p.get("default_engine") or p.get("preset_engine") or "qwen"
                                    break
                            if not voicebox_profile_id and len(profiles) > 0:
                                voicebox_profile_id = profiles[0]["id"]
                                voicebox_profile_engine = profiles[0].get("default_engine") or profiles[0].get("preset_engine") or "qwen"
                            if voicebox_profile_id:
                                print(f"Routing speech synthesis to Voicebox (profile: {voicebox_profile_id}, engine: {voicebox_profile_engine})...")
                                audio_filename = f"reply_{persona}_{timestamp}.mp3"
                                audio_path = os.path.join(AUDIO_DIR, audio_filename)
                                
                                gen_res = await client.post(
                                    f"{voicebox_url}/generate",
                                    json={
                                        "profile_id": voicebox_profile_id,
                                        "text": clean_text,
                                        "language": "en",
                                        "engine": voicebox_profile_engine
                                    },
                                    timeout=10.0
                                )
                                if gen_res.status_code == 200:
                                    gen_data = gen_res.json()
                                    gen_id = gen_data["id"]
                                    for attempt in range(30):
                                        await asyncio.sleep(1.0)
                                        status_res = await client.get(f"{voicebox_url}/history/{gen_id}")
                                        if status_res.status_code == 200:
                                            status = status_res.json().get("status")
                                            if status == "completed":
                                                audio_download_res = await client.get(f"{voicebox_url}/audio/{gen_id}")
                                                if audio_download_res.status_code == 200:
                                                    with open(audio_path, "wb") as f:
                                                        f.write(audio_download_res.content)
                                                    print("Voicebox speech synthesis completed successfully!")
                                                    generated_successfully = True
                                                    break
                                            elif status == "failed":
                                                break
            except Exception as e:
                print(f"Voicebox generation failed/offline: {e}. Falling back.")
    
        if not generated_successfully:
            audio_filename = f"reply_{persona}_{timestamp}.mp3"
            audio_path = os.path.join(AUDIO_DIR, audio_filename)
            
            edge_tts_cmd = "edge-tts"
            active_venv_bin = os.path.join(os.path.dirname(sys.executable), "edge-tts.exe")
            if os.path.exists(active_venv_bin):
                edge_tts_cmd = active_venv_bin
            elif sys.platform == "win32":
                venv_bin = os.path.join(os.path.dirname(__file__), "..", "hermes-agent", "venv", "Scripts", "edge-tts.exe")
                if os.path.exists(venv_bin):
                    edge_tts_cmd = venv_bin
            try:
                print("Falling back to Edge-TTS...")
                process = await asyncio.create_subprocess_exec(
                    edge_tts_cmd,
                    "--voice", voice,
                    "--text", clean_text,
                    "--write-media", audio_path,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                if process.returncode != 0:
                    print(f"edge-tts failed: {stderr.decode()}")
                    raise Exception(stderr.decode())
                print("Edge-TTS speech synthesis completed successfully!")
                generated_successfully = True
            except Exception as e:
                print(f"Final Edge-TTS fallback failed: {e}")
                raise HTTPException(status_code=500, detail="All speech synthesis pipelines failed.")
    
        # 3. Generate Live Avatar Video
        video_filename = f"reply_{persona}_{timestamp}.mp4"
        video_path = os.path.join(ANIMATIONS_DIR, video_filename)
        video_url = None
        
        try:
            base_video_path = None
            if custom_base_video_url:
                relative_url = custom_base_video_url.lstrip("/")
                local_path = os.path.join(os.path.dirname(__file__), relative_url)
                
                # Check for sentiment-specific base video
                if sentiment != "neutral":
                    expr_path = local_path.replace("base.mp4", f"base_{sentiment}.mp4")
                    if os.path.exists(expr_path):
                        base_video_path = expr_path
                        print(f"Using expression-specific base video ({sentiment}): {base_video_path}")
                
                if not base_video_path and os.path.exists(local_path):
                    base_video_path = local_path
                    print(f"Using client-specific default custom video: {base_video_path}")
                    
            if not base_video_path:
                base_video_path = await get_or_generate_base_video(persona)
                print(f"Using default fallback base video: {base_video_path}")
                
            await combine_video_audio(base_video_path, audio_path, video_path)
            
            if os.path.exists(video_path):
                video_url = f"/static/animations/{video_filename}"
                print(f"Successfully generated talking video avatar: {video_url}")
        except Exception as e:
            print(f"Failed to generate Live Portrait video: {e}")
            video_url = None
    
        return {
            "text": reply_text,
            "audio_url": f"/static/audio/{audio_filename}",
            "video_url": video_url,
            "voice": voice
        }
    finally:
        if active_chat_tasks.get(client_id) == current_task:
            active_chat_tasks.pop(client_id, None)


# --- ADMIN AUTH & CLIENT APIs ---

class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    password: str

class ClientCreateRequest(BaseModel):
    client_id: str
    name: str
    email: Optional[str] = None
    status: Optional[str] = "active"
    stripe_subscription_id: Optional[str] = None

class ClientUpdateRequest(BaseModel):
    name: str
    email: Optional[str] = None
    status: Optional[str] = "active"
    stripe_subscription_id: Optional[str] = None

@app.get("/admin")
def admin_redirect():
    return RedirectResponse(url="/static/admin.html")

@app.get("/api/auth/status")
def get_auth_status():
    """Returns whether any admin accounts exist in the database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    conn.close()
    return {"has_admin": count > 0}

@app.post("/api/auth/register-first")
def register_first_admin(req: RegisterRequest):
    """Registers the first admin user if no admins exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    if count > 0:
        conn.close()
        raise HTTPException(status_code=400, detail="Registration is locked. Admin already exists.")
    
    pw_hash, salt = hash_password(req.password)
    try:
        cursor.execute(
            "INSERT INTO users (username, password_hash, salt) VALUES (?, ?, ?)",
            (req.username, pw_hash, salt)
        )
        conn.commit()
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Failed to register admin: {str(e)}")
    conn.close()
    return {"message": "First admin registered successfully. Registration is now closed."}

@app.post("/api/auth/login")
def login(req: LoginRequest):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash, salt FROM users WHERE username = ?", (req.username,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    pw_hash, salt = row
    if not verify_password(req.password, pw_hash, salt):
        conn.close()
        raise HTTPException(status_code=401, detail="Invalid username or password")
        
    session_id = secrets.token_hex(32)
    expires_at = time.time() + 86400  # 24 hours
    cursor.execute(
        "INSERT INTO sessions (session_id, username, expires_at) VALUES (?, ?, ?)",
        (session_id, req.username, expires_at)
    )
    conn.commit()
    conn.close()
    
    response = JSONResponse(content={"message": "Logged in successfully", "username": req.username})
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        max_age=86400,
        expires=86400,
        path="/",
        samesite="lax",
        secure=False
    )
    return response

@app.post("/api/auth/logout")
def logout(session_id: Optional[str] = Cookie(None)):
    if session_id:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.commit()
        conn.close()
    response = JSONResponse(content={"message": "Logged out successfully"})
    response.delete_cookie(key="session_id", path="/")
    return response

@app.get("/api/auth/me")
def get_me(username: str = Depends(get_current_user)):
    return {"username": username}

# --- CLIENT MANAGEMENT ENDPOINTS ---

@app.get("/api/admin/clients")
def list_clients(username: str = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT client_id, name, email, status, stripe_subscription_id FROM clients")
    rows = cursor.fetchall()
    conn.close()
    
    clients = []
    for r in rows:
        clients.append({
            "client_id": r[0],
            "name": r[1],
            "email": r[2],
            "status": r[3],
            "stripe_subscription_id": r[4]
        })
    return clients

@app.post("/api/admin/clients")
def create_client(req: ClientCreateRequest, username: str = Depends(get_current_user)):
    client_id = "".join([c for c in req.client_id.lower() if c.isalnum() or c in ("-", "_")])
    if not client_id:
        raise HTTPException(status_code=400, detail="Invalid client ID.")
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT 1 FROM clients WHERE client_id = ?", (client_id,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Client ID already exists.")
        
    try:
        cursor.execute(
            "INSERT INTO clients (client_id, name, email, status, stripe_subscription_id) VALUES (?, ?, ?, ?, ?)",
            (client_id, req.name, req.email, req.status, req.stripe_subscription_id)
        )
        personas = ["ceo", "cto", "cmo", "clo", "cfo", "cgo"]
        for persona in personas:
            cursor.execute(
                "INSERT INTO client_avatars (client_id, persona, name, bio, status) VALUES (?, ?, ?, ?, 'pending')",
                (client_id, persona, None, None)
            )
        conn.commit()
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Failed to create client: {str(e)}")
        
    conn.close()
    return {"client_id": client_id, "name": req.name}

@app.put("/api/admin/clients/{client_id}")
def update_client(client_id: str, req: ClientUpdateRequest, username: str = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM clients WHERE client_id = ?", (client_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Client not found")
        
    cursor.execute(
        "UPDATE clients SET name = ?, email = ?, status = ?, stripe_subscription_id = ? WHERE client_id = ?",
        (req.name, req.email, req.status, req.stripe_subscription_id, client_id)
    )
    conn.commit()
    conn.close()
    return {"message": "Client updated successfully"}

@app.delete("/api/admin/clients/{client_id}")
def delete_client(client_id: str, username: str = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM clients WHERE client_id = ?", (client_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Client not found")
        
    cursor.execute("DELETE FROM clients WHERE client_id = ?", (client_id,))
    conn.commit()
    conn.close()
    
    client_dir = os.path.join(os.path.dirname(__file__), "static", "uploads", client_id)
    if os.path.exists(client_dir):
        try:
            shutil.rmtree(client_dir)
        except Exception as e:
            print(f"Failed to delete client folder {client_dir}: {e}")
            
    return {"message": "Client deleted successfully"}

# --- CLIENT AVATAR MANAGEMENT & UPLOAD ---

@app.get("/api/admin/clients/{client_id}/avatars")
def get_client_avatars(client_id: str, username: str = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT persona, name, bio, image_path, video_path, status, error_message, scale, vy_ratio FROM client_avatars WHERE client_id = ?",
        (client_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    
    avatars = {}
    for r in rows:
        avatars[r[0]] = {
            "name": r[1],
            "bio": r[2],
            "image_path": r[3],
            "video_path": r[4],
            "status": r[5],
            "error_message": r[6],
            "scale": r[7] if r[7] is not None else 2.3,
            "vy_ratio": r[8] if r[8] is not None else -0.125
        }
    return avatars

@app.post("/api/admin/clients/{client_id}/avatars")
async def update_client_avatar(
    client_id: str,
    persona: str = Form(...),
    name: Optional[str] = Form(None),
    bio: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    scale: Optional[float] = Form(2.3),
    vy_ratio: Optional[float] = Form(-0.125),
    username: str = Depends(get_current_user)
):
    persona = persona.lower()
    if persona not in ["ceo", "cto", "cmo", "clo", "cfo", "cgo"]:
        raise HTTPException(status_code=400, detail="Invalid persona name")
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM clients WHERE client_id = ?", (client_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Client not found")
        
    # Retrieve current image path, scale, and vy_ratio to see if we can re-queue for rendering if settings changed
    cursor.execute("SELECT image_path, scale, vy_ratio FROM client_avatars WHERE client_id = ? AND persona = ?", (client_id, persona))
    row = cursor.fetchone()
    current_image_path = row[0] if row else None
    old_scale = row[1] if (row and row[1] is not None) else 2.3
    old_vy_ratio = row[2] if (row and row[2] is not None) else -0.125

    cursor.execute(
        "UPDATE client_avatars SET name = ?, bio = ?, scale = ?, vy_ratio = ? WHERE client_id = ? AND persona = ?",
        (name, bio, scale, vy_ratio, client_id, persona)
    )
    conn.commit()
    
    image_saved = False
    if image and image.filename:
        ext = os.path.splitext(image.filename)[1].lower()
        is_video = ext in [".mp4", ".mov", ".avi", ".webm"]
        is_image = ext in [".png", ".jpg", ".jpeg"]
        if not is_image and not is_video:
            conn.close()
            raise HTTPException(status_code=400, detail="Only PNG, JPEG images and MP4, MOV, AVI, WEBM videos are allowed.")
            
        client_persona_dir = os.path.join(os.path.dirname(__file__), "static", "uploads", client_id, persona)
        os.makedirs(client_persona_dir, exist_ok=True)
        
        if is_video:
            video_filename = f"portrait_video{ext}"
            video_path = os.path.join(client_persona_dir, video_filename)
            with open(video_path, "wb") as buffer:
                shutil.copyfileobj(image.file, buffer)
                
            portrait_path = os.path.join(client_persona_dir, "portrait.png")
            if os.path.exists(portrait_path):
                try: os.remove(portrait_path)
                except: pass
                
            cmd = ["ffmpeg", "-y", "-i", video_path, "-ss", "00:00:00", "-vframes", "1", portrait_path]
            try:
                subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except Exception as e:
                conn.close()
                raise HTTPException(status_code=500, detail=f"Failed to extract face frame from video: {e}")
                
            # Extract voice profile from video for zero-shot voice cloning!
            audio_path = os.path.join(client_persona_dir, "reference.wav")
            if os.path.exists(audio_path):
                try: os.remove(audio_path)
                except: pass
            cmd_audio = ["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "22050", "-ac", "1", audio_path]
            try:
                subprocess.run(cmd_audio, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                print(f"[+] Extracted voice clone profile from video: {audio_path}")
                # Create corresponding reference.txt to activate voice cloning
                ref_txt_path = os.path.join(client_persona_dir, "reference.txt")
                with open(ref_txt_path, "w", encoding="utf-8") as f:
                    f.write("")
            except Exception as e:
                print(f"[!] Warning: Failed to extract voice clone profile: {e}")
                
            image_url = f"/static/uploads/{client_id}/{persona}/portrait.png"
        else:
            portrait_filename = f"portrait{ext}"
            portrait_path = os.path.join(client_persona_dir, portrait_filename)
            with open(portrait_path, "wb") as buffer:
                shutil.copyfileobj(image.file, buffer)
            image_url = f"/static/uploads/{client_id}/{persona}/{portrait_filename}"
        
        cursor.execute(
            "UPDATE client_avatars SET image_path = ?, video_path = NULL, status = 'queued', error_message = NULL WHERE client_id = ? AND persona = ?",
            (image_url, client_id, persona)
        )
        conn.commit()
        image_saved = True
        
        await generation_queue.put({
            "client_id": client_id,
            "persona": persona,
            "image_path": portrait_path
        })
        print(f"Avatar for client={client_id}, persona={persona} queued via media upload.")
        
    else:
        # Re-queue existing image if scale or offset changed!
        if current_image_path and (abs(scale - old_scale) > 0.001 or abs(vy_ratio - old_vy_ratio) > 0.001):
            # Resolve physical path
            relative_path = current_image_path.lstrip("/")
            physical_path = os.path.join(os.path.dirname(__file__), relative_path.replace("/", os.sep))
            # Clean up the path from query params (e.g. ?t=...)
            if "?" in physical_path:
                physical_path = physical_path.split("?")[0]
            
            if os.path.exists(physical_path):
                cursor.execute(
                    "UPDATE client_avatars SET status = 'queued', video_path = NULL, error_message = NULL WHERE client_id = ? AND persona = ?",
                    (client_id, persona)
                )
                conn.commit()
                
                await generation_queue.put({
                    "client_id": client_id,
                    "persona": persona,
                    "image_path": physical_path
                })
                print(f"Re-queueing avatar client={client_id}, persona={persona} for re-render with updated crop scale={scale}, vy_ratio={vy_ratio}.")
                image_saved = True

    conn.close()
    return {
        "message": "Avatar details updated successfully.",
        "queued": image_saved
    }

@app.get("/api/admin/queue/status")
def get_queue_status(username: str = Depends(get_current_user)):
    """Returns the size of the background task queue."""
    return {"queue_size": generation_queue.qsize()}

# --- PUBLIC CLIENT INFO ENDPOINT ---

@app.get("/api/client/{client_id}")
def get_public_client_info(client_id: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT name, status FROM clients WHERE client_id = ?", (client_id,))
    client_row = cursor.fetchone()
    if not client_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Client not found")
        
    if client_row[1] != 'active':
        conn.close()
        raise HTTPException(status_code=403, detail="Client account is inactive")
        
    cursor.execute(
        "SELECT persona, name, bio, image_path, video_path, status FROM client_avatars WHERE client_id = ?",
        (client_id,)
    )
    avatar_rows = cursor.fetchall()
    conn.close()
    
    avatars = {}
    for r in avatar_rows:
        avatars[r[0]] = {
            "name": r[1],
            "bio": r[2],
            "image_path": r[3],
            "video_path": r[4] if r[5] == 'complete' else None
        }
        
    return {
        "client_name": client_row[0],
        "avatars": avatars
    }

# Serve static files (we will put our WebUI inside the static folder)
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")

@app.get("/")
def read_root():
    return {"message": "KGU Interactive C-Suite Avatar Server is running! Access the UI at /static/index.html"}

if __name__ == "__main__":
    import uvicorn
    # Run the server on port 8085 (which is open and ready)
    uvicorn.run(app, host="0.0.0.0", port=8085)
