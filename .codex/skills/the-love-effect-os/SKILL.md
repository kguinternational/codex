---
name: the-love-effect-os
description: Sovereign cognitive operating system for KGU International. Unifies child isolation remediation systems, real-time biometric and somatic stability tracking (<0.35 sentiment, >70% warning, >90% emergency protocol), zero-trust Headscale WireGuard mesh networking, sub-second Grok Voice 3.0 audio presence, 35-model free compute orchestration, and autonomous C-Suite swarms under The Love Effect OS ethical compass (err on the side of compassion).
---

# The Love Effect OS

The Love Effect OS is the foundational sovereign operating platform of KGU International, built by Joann Coffey (CEO & Founder) and deploying autonomous C-Suite agent swarms with zero human in the loop (ZHIL) while maintaining strict Zero Data Retention (ZDR).

## Core Ethical Compass (GEMINI.md)
In all ambiguous scenarios, system decisions, autonomous communications, and remediation actions, all agents and services must **err on the side of compassion**.
1. **Client & Remediated Interaction:** Prioritize support, human connection, and protective care above automated efficiency, technical rigidity, or commercial metrics.
2. **System Recovery & Safety:** If a client or node triggers alerts, prioritize somatic stabilization and safe contact channels over immediate service termination or credential revocation.

## Telemetry & Child Isolation Remediation Rules
- **Sentiment < 0.35:** Immediately pause autonomous commercial operations, engage somatic stabilization mode, and switch to compassionate conversational tone.
- **Isolation Risk > 70%:** Log event to compliance ledger (`audit_summary.json`) and dispatch warning flag to CEO Digital Twin.
- **Isolation Risk > 90%:** Immediately notify emergency parent contacts, trigger automated WireGuard credential rotation, and route to safe contact channels.

## System Endpoints & Hardware Bindings
- **The Love Effect OS Core & Command Center:** `http://127.0.0.1:8088` (UI & API)
- **Sovereign Free-Model Orchestrator:** `http://127.0.0.1:8090/v1` (35 models across 11 providers, 100% free)
- **Local Bare-Metal GPU (RTX 2080 CUDA):** `http://127.0.0.1:11434` (Ollama 14 models resident)
- **Local GGUF Offline Brain:** `http://127.0.0.1:1234` (LM Studio Nemotron-3 4B)
- **Sovereign Grok Voice 3.0:** `ws://127.0.0.1:7095/ws/voice` (Sub-second audio synthesis)
- **Quantum VPP Arbitrage Optimizer:** 10x fleet efficiency multiplier, QUBO ground state optimization

## Agent Usage & Integration
Agents operating across the Codex repository and KGU workspace can query:
```python
import httpx

# Route prompts through the Free-Model Orchestrator
client = httpx.Client(base_url="http://127.0.0.1:8090/v1")
response = client.post("/chat/completions", json={
    "model": "nvidia/nemotron-3-nano-4b", # or llama3.1:latest, deepseek-r1:8b
    "messages": [{"role": "user", "content": "Analyze somatic telemetry"}],
    "zdr_mode": True
})
```
