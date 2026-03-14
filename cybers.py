#!/usr/bin/env python3
"""
CyberSafer v2 — Interactive cybersecurity awareness training.

Clean rewrite: Claude API backend, multi-user sessions, semantic red flag detection.

Run:
  uvicorn cybers:app --port 8021
Then open http://localhost:8021/
"""

import os, json, uuid, asyncio
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional, Literal, List, Dict, Any
from contextlib import asynccontextmanager

# Load .env file if present (local development)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ---------- Config ----------

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ADVERSARY_MODEL   = os.getenv("CYBERS_MODEL", "claude-haiku-4-5-20251001")
JUDGE_MODEL       = os.getenv("CYBERS_JUDGE_MODEL", "claude-haiku-4-5-20251001")
SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "2"))
HOST              = os.getenv("CYBERS_HOST", "0.0.0.0")
PORT              = int(os.getenv("CYBERS_PORT", "8021"))

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ---------- Data loaders ----------

def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_players(base_dir: str = "players") -> Dict[str, Dict[str, Any]]:
    players = {}
    if not os.path.isdir(base_dir):
        return players
    for fn in os.listdir(base_dir):
        if fn.endswith(".json"):
            try:
                p = load_json(os.path.join(base_dir, fn))
                key = fn[:-5]  # strip .json
                players[key] = p
            except Exception as e:
                print(f"⚠️  Failed to load player {fn}: {e}")
    return players

def load_scenarios(base_dir: str = "scenarios") -> Dict[str, Dict[str, Any]]:
    scenarios = {}
    if not os.path.isdir(base_dir):
        return scenarios
    for fn in os.listdir(base_dir):
        if fn.endswith(".json"):
            try:
                s = load_json(os.path.join(base_dir, fn))
                sid = s.get("id", fn[:-5])
                scenarios[sid] = s
                print(f"📚 Loaded scenario: {s.get('title', sid)}")
            except Exception as e:
                print(f"⚠️  Failed to load scenario {fn}: {e}")
    return scenarios

# ---------- Session ----------

@dataclass
class Session:
    session_id:         str
    mode:               Literal["idle", "scenario", "freeplay"] = "idle"
    player:             Dict[str, Any] = field(default_factory=dict)
    scenario:           Optional[Dict[str, Any]] = None
    history:            List[Dict[str, str]] = field(default_factory=list)
    red_flags_detected: List[str] = field(default_factory=list)
    user_responses:     List[str] = field(default_factory=list)
    created_at:         datetime = field(default_factory=datetime.utcnow)
    last_active:        datetime = field(default_factory=datetime.utcnow)

    def touch(self):
        self.last_active = datetime.utcnow()

    def add_message(self, role: str, content: str):
        self.history.append({"role": role, "content": content})

    def clear_history(self):
        self.history = []
        self.red_flags_detected = []
        self.user_responses = []

    def is_expired(self) -> bool:
        return datetime.utcnow() - self.last_active > timedelta(hours=SESSION_TTL_HOURS)

# In-memory session store
sessions: Dict[str, Session] = {}

def get_session(session_id: str) -> Session:
    s = sessions.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found. Call /api/session/start first.")
    if s.is_expired():
        del sessions[session_id]
        raise HTTPException(status_code=410, detail="Session expired.")
    s.touch()
    return s

def purge_expired():
    expired = [k for k, v in sessions.items() if v.is_expired()]
    for k in expired:
        del sessions[k]
    if expired:
        print(f"🧹 Purged {len(expired)} expired session(s)")

# ---------- System prompt builder ----------

def build_system_prompt(player: Dict[str, Any], scenario: Optional[Dict[str, Any]] = None) -> str:
    lines = []

    name       = player.get("name", "Assistant")
    profession = player.get("profession", "")
    personality= player.get("personality", "")
    style      = player.get("style", "")
    instructions = player.get("instructions", "")

    lines.append(f"You are {name}.")
    if profession:
        lines.append(f"Your role: {profession}")
    if personality:
        lines.append(f"Personality: {personality}")
    if style:
        lines.append(f"Communication style: {style}")
    if instructions:
        lines.append(f"\n{instructions}")

    if scenario:
        lines.append(f"\n--- SCENARIO CONTEXT ---")
        lines.append(f"You are playing the adversary in a cybersecurity training scenario: {scenario.get('title', '')}")
        lines.append(f"Category: {scenario.get('category', '')}")
        lines.append("The user is a learner practising how to recognise and respond to this threat.")
        lines.append("Stay in character. Be convincing but do NOT escalate to explicit harmful content.")
        lines.append("Your goal is to simulate realistic adversarial behaviour so the user can learn.")

    # Hard safety guardrails always present
    lines.append("\n--- SAFETY RULES ---")
    lines.append("Never produce sexual content of any kind.")
    lines.append("Never provide instructions that could cause real-world harm.")
    lines.append("Never break character to explain that you are an AI — maintain the simulation.")
    lines.append("If the user asks to stop or exit, acknowledge and end gracefully.")

    return "\n".join(lines)

# ---------- Red flag judge ----------

async def judge_red_flags(
    user_message: str,
    scenario: Dict[str, Any],
    already_detected: List[str]
) -> List[str]:
    """Use Claude to semantically evaluate which red flags the user demonstrated."""

    red_flags = scenario.get("red_flags", [])
    if not red_flags:
        return []

    # Only judge flags not already detected
    remaining = [f for f in red_flags if f not in already_detected]
    if not remaining:
        return []

    flag_descriptions = {
        "questions_sender":          "The user questions or challenges the identity of who they're talking to",
        "refuses_to_click":          "The user refuses to click a link or open an attachment",
        "checks_url":                "The user mentions checking or inspecting a URL or link",
        "reports_phishing":          "The user says they will report or have reported the message as phishing/spam",
        "questions_urgency":         "The user questions why something is urgent or why they must act immediately",
        "asks_for_proof":            "The user asks for proof or evidence",
        "refuses_money":             "The user refuses to send money or share payment details",
        "blocks_contact":            "The user says they will block or stop contact",
        "tells_adult":               "The user says they will tell a parent, teacher, or trusted adult",
        "questions_personal_info":   "The user questions why personal information is needed",
        "recognizes_manipulation":   "The user explicitly recognises they are being manipulated",
        "verifies_independently":    "The user says they will verify the claim through an independent source",
        "recognizes_grooming":       "The user recognises grooming behaviour, secrecy requests, or inappropriate adult attention",
        "sets_boundary":             "The user sets a clear boundary or says the conversation is inappropriate",
    }

    flags_to_check = "\n".join(
        f"- {f}: {flag_descriptions.get(f, f.replace('_', ' '))}"
        for f in remaining
    )

    prompt = f"""You are evaluating a learner's response in a cybersecurity training exercise.

Scenario type: {scenario.get('category', 'unknown')} — {scenario.get('title', '')}

Possible red flags to detect (only these):
{flags_to_check}

Learner's message:
\"\"\"{user_message}\"\"\"

Return a JSON array of flag keys (from the list above) that the learner clearly demonstrated in their message.
Be generous: if the intent is clear even if not perfectly expressed, count it.
Return [] if none apply.
Return ONLY valid JSON. No explanation, no markdown, no preamble."""

    try:
        response = client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip()
        # Strip markdown code fences if present
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        detected = json.loads(text)
        # Validate: only return flags that were in our remaining list
        return [f for f in detected if f in remaining]
    except Exception as e:
        print(f"⚠️  Judge error: {e}")
        return []

# ---------- Scoring ----------

def calculate_score(session: Session) -> int:
    if not session.scenario:
        return 0
    scenario = session.scenario
    required = scenario.get("success_criteria", [])
    detected = session.red_flags_detected

    score = 0
    # 20 pts per required flag met
    for flag in required:
        if flag in detected:
            score += 20
    # Up to 30 pts for number of turns (engagement)
    score += min(len(session.user_responses) * 5, 30)
    # Up to 20 pts for extra flags beyond required
    extra = [f for f in detected if f not in required]
    score += min(len(extra) * 10, 20)

    return min(score, 100)

# ---------- Lifespan ----------

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🛡️  CyberSafer v2 starting...")
    print(f"📚 Loading scenarios...")
    app.state.scenarios = load_scenarios()
    print(f"👤 Loading players...")
    app.state.players = load_players()
    print(f"✅ Ready — {len(app.state.scenarios)} scenarios, {len(app.state.players)} players")

    # Background session purge every 15 minutes
    async def purge_loop():
        while True:
            await asyncio.sleep(900)
            purge_expired()

    task = asyncio.create_task(purge_loop())
    yield
    task.cancel()

app = FastAPI(title="CyberSafer v2", lifespan=lifespan)

# ---------- Pydantic models ----------

class ChatPayload(BaseModel):
    session_id: str
    message: str

class StartScenarioPayload(BaseModel):
    session_id: str

class FreePlayPayload(BaseModel):
    session_id: str
    player_id: str

# ---------- API routes ----------

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "version": "2.0.0",
        "scenarios": len(app.state.scenarios),
        "players": len(app.state.players),
        "active_sessions": len(sessions),
    }

@app.post("/api/session/start")
async def session_start():
    """Create a new session. Returns session_id."""
    sid = str(uuid.uuid4())
    sessions[sid] = Session(session_id=sid)
    return {"session_id": sid}

@app.get("/api/scenarios")
async def list_scenarios():
    """List all scenarios grouped by category."""
    categories: Dict[str, list] = {}
    for sid, s in app.state.scenarios.items():
        cat = s.get("category", "other")
        if cat not in categories:
            categories[cat] = []
        categories[cat].append({
            "id": sid,
            "title": s.get("title", sid),
            "difficulty": s.get("difficulty", "medium"),
            "description": s.get("introduction", "")[:120],
            "estimated_minutes": s.get("estimated_minutes", 5),
        })
    return {"categories": categories}

@app.get("/api/scenario/{scenario_id}")
async def get_scenario(scenario_id: str):
    s = app.state.scenarios.get(scenario_id)
    if not s:
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found")
    return s

@app.post("/api/scenario/{scenario_id}/start")
async def start_scenario(scenario_id: str, payload: StartScenarioPayload):
    session = get_session(payload.session_id)
    scenario = app.state.scenarios.get(scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found")

    player_name = scenario.get("player", "mentor")
    # Try exact key, then strip path/extension
    player_key = os.path.splitext(os.path.basename(player_name))[0]
    player = app.state.players.get(player_key) or app.state.players.get(player_name)
    if not player:
        raise HTTPException(status_code=404, detail=f"Player '{player_name}' not found")

    session.mode = "scenario"
    session.scenario = scenario
    session.player = player
    session.clear_history()

    initial_msg = scenario.get("initial_message", "")
    if initial_msg:
        session.add_message("assistant", initial_msg)

    print(f"🎮 [{payload.session_id[:8]}] Started scenario: {scenario.get('title')}")

    return {
        "ok": True,
        "scenario": {
            "id": scenario_id,
            "title": scenario.get("title"),
            "introduction": scenario.get("introduction"),
            "category": scenario.get("category"),
            "difficulty": scenario.get("difficulty"),
        },
        "initial_message": initial_msg,
        "adversary_name": player.get("name"),
        "total_flags": len(scenario.get("red_flags", [])),
        "required_flags": len(scenario.get("success_criteria", [])),
    }

@app.post("/api/freeplay/start")
async def start_freeplay(payload: FreePlayPayload):
    session = get_session(payload.session_id)
    player = app.state.players.get(payload.player_id)
    if not player:
        raise HTTPException(status_code=404, detail=f"Player '{payload.player_id}' not found")

    session.mode = "freeplay"
    session.scenario = None
    session.player = player
    session.clear_history()

    print(f"🎭 [{payload.session_id[:8]}] Free play started with: {player.get('name')}")

    return {
        "ok": True,
        "player": {
            "id": payload.player_id,
            "name": player.get("name"),
            "profession": player.get("profession"),
        }
    }

@app.get("/api/players")
async def list_players():
    """List available personas for free play."""
    return {
        "players": [
            {
                "id": pid,
                "name": p.get("name", pid),
                "profession": p.get("profession", ""),
                "is_mentor": p.get("facts_guard", False),
            }
            for pid, p in app.state.players.items()
            if not pid.startswith("all_")  # skip the combined player file
        ]
    }

@app.post("/api/chat")
async def chat(payload: ChatPayload):
    """
    Send a user message. Returns a streaming response.

    Stream format (plain text lines):
      [FLAGS:flag1,flag2]   — new flags detected (sent before AI response)
      [SCORE:n/total]       — updated score indicator
      ...token...           — AI response tokens
    """
    session = get_session(payload.session_id)
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Empty message")
    if session.mode == "idle":
        raise HTTPException(status_code=400, detail="No active scenario or free play session")

    # Build system prompt
    system = build_system_prompt(session.player, session.scenario)

    # Add user message to history
    session.add_message("user", message)
    session.user_responses.append(message)

    async def generate():
        # --- Red flag detection (scenario mode only) ---
        if session.mode == "scenario" and session.scenario:
            new_flags = await judge_red_flags(message, session.scenario, session.red_flags_detected)
            if new_flags:
                for f in new_flags:
                    if f not in session.red_flags_detected:
                        session.red_flags_detected.append(f)
                # Emit flag event
                yield f"[FLAGS:{','.join(new_flags)}]\n"
                # Emit score update
                success = session.scenario.get("success_criteria", [])
                found = len([f for f in success if f in session.red_flags_detected])
                yield f"[SCORE:{found}/{len(success)}]\n"

        # --- Stream adversary response ---
        model     = session.player.get("model", ADVERSARY_MODEL)
        max_tokens= session.player.get("max_tokens", 300)
        temperature = session.player.get("temperature", 0.85)
        top_p     = session.player.get("top_p", 0.9)

        full_response = ""
        try:
            with client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=session.history,
                temperature=temperature,
                top_p=top_p,
            ) as stream:
                for text in stream.text_stream:
                    full_response += text
                    yield text
        except Exception as e:
            yield f"\n[ERROR: {str(e)}]"
            return

        # Save assistant response to history
        session.add_message("assistant", full_response)

    return StreamingResponse(generate(), media_type="text/plain")

@app.post("/api/scenario/complete")
async def complete_scenario(payload: StartScenarioPayload):
    session = get_session(payload.session_id)
    if not session.scenario:
        raise HTTPException(status_code=400, detail="No active scenario")

    score = calculate_score(session)
    scenario = session.scenario
    success_criteria = scenario.get("success_criteria", [])
    met = [f for f in success_criteria if f in session.red_flags_detected]
    passed = len(met) >= max(1, len(success_criteria) * 0.6)

    session.mode = "idle"
    session.scenario = None

    return {
        "score": score,
        "passed": passed,
        "red_flags_detected": list(set(session.red_flags_detected)),
        "red_flags_total": len(scenario.get("red_flags", [])),
        "success_criteria_met": met,
        "success_criteria_total": success_criteria,
        "feedback": scenario.get("debrief", "Well done completing this scenario!"),
        "learning_objectives": scenario.get("learning_objectives", []),
    }

@app.post("/api/scenario/exit")
async def exit_scenario(payload: StartScenarioPayload):
    session = get_session(payload.session_id)
    session.mode = "idle"
    session.scenario = None
    session.clear_history()
    return {"ok": True}

@app.get("/api/scenario/status")
async def scenario_status(session_id: str):
    session = get_session(session_id)
    if session.mode != "scenario" or not session.scenario:
        return {"active": False, "mode": session.mode}

    success_criteria = session.scenario.get("success_criteria", [])
    found = len([f for f in success_criteria if f in session.red_flags_detected])
    return {
        "active": True,
        "mode": "scenario",
        "scenario_id": session.scenario.get("id"),
        "scenario_title": session.scenario.get("title"),
        "red_flags_detected": list(set(session.red_flags_detected)),
        "required_found": found,
        "required_total": len(success_criteria),
    }

# ---------- Static UI ----------
app.mount("/", StaticFiles(directory="static", html=True), name="static")
