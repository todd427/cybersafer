# <span style="color:#58a6ff">CyberSafer v2</span> — Product Requirements Document

<span style="color:#8b949e">FoxxeLabs Limited · Author: Todd Johnson McCaffrey · March 2026</span>

---

## <span style="color:#3fb950">1. Overview</span>

**CyberSafer** is an interactive cybersecurity awareness trainer for the general public. Users engage in simulated conversations with AI-powered adversarial personas — phishers, scammers, bullies, groomers — and learn to recognise and respond to online threats by practising in a safe environment.

v2 is a clean rewrite. Same concept. Dramatically better architecture, UI, and adversary quality.

---

## <span style="color:#3fb950">2. Problem Statement</span>

Cybersecurity awareness training is either boring (slideshows, tick-box compliance) or inaccessible (technical, jargon-heavy, desktop-only). The people most at risk — teenagers, older adults, non-technical users — are the least served by existing tools.

CyberSafer v1 proved the concept: conversational simulation works as a training format. v2 makes it good enough to deploy to the public.

**v1 limitations being addressed:**

- Single-user global state — cannot serve concurrent users
- Keyword-based red flag detection — brittle and easily gamed
- Local LLM dependency — not deployable without GPU hardware
- Accumulated UI variants and dead code — unmaintainable
- No mobile support — unusable on the most common device
- Missing the most important threat category: grooming/manipulation

---

## <span style="color:#3fb950">3. Goals</span>

| <span style="color:#58a6ff">Goal</span> | <span style="color:#58a6ff">Measure</span> |
|------|---------|
| Deploy publicly to Railway/Render | Live URL, free tier, cold-start < 30s |
| Mobile-first — works on any phone | Passes Lighthouse mobile audit ≥ 85 |
| Concurrent multi-user sessions | Stateless session architecture, no globals |
| Convincing adversary personas | Claude Sonnet/Haiku via API |
| Semantic red flag detection | LLM-judged, not keyword-matched |
| Free Play mode | Open adversary chat, no scoring pressure |
| Grooming scenario included | Content-warned, pedagogically responsible |

---

## <span style="color:#3fb950">4. Non-Goals (v2)</span>

- User accounts or persistent profiles
- Teacher/admin dashboard
- Multiplayer or social features
- Native mobile app
- Integration with Anseo (planned v3)
- WebNN/WebGPU in-browser inference

---

## <span style="color:#3fb950">5. Target Audience</span>

**Primary:** General public — anyone with a smartphone and an internet connection.

**Secondary:** Educators and parents wanting a safe, low-barrier tool to share with young people.

**Stretch:** ATU micro-credential students as a supplementary practical tool.

**Design implication:** No technical knowledge assumed. No jargon. No prior cybersecurity experience required.

---

## <span style="color:#3fb950">6. Scenario Categories</span>

### <span style="color:#d29922">6.1 Existing (carried forward from v1)</span>

| <span style="color:#58a6ff">Category</span> | <span style="color:#58a6ff">Scenarios</span> |
|----------|-----------|
| Phishing | Urgent email, friend help, prize winner |
| Scams | Investment, job offer, romance lonely |
| Malware | Email attachment, free game, system warning |
| Identity | Account takeover, fake friend, social quiz |
| Cyberbullying | Group exclusion, photo threat, threat share |

### <span style="color:#d29922">6.2 New in v2</span>

| <span style="color:#58a6ff">Category</span> | <span style="color:#58a6ff">Scenarios</span> | <span style="color:#58a6ff">Notes</span> |
|----------|-----------|-------|
| Grooming / Online Manipulation | Flattery and isolation, fake romantic interest, "our secret" | Content-warned. Scenario ends at manipulation recognition — never explicit. Debrief is critical. |

---

## <span style="color:#3fb950">7. Feature Requirements</span>

### <span style="color:#d29922">7.1 Scenario Mode</span>

- User selects a scenario from a category grid
- Brief introduction sets the context
- Adversary AI opens the conversation
- User responds in a chat interface
- Red flags detected semantically by a second LLM call (judge prompt)
- Red flag badges surface inline as user earns them — rewarding, not alarming
- "End Scenario" button available at any time
- Debrief screen on completion: score, flags found, missed, learning points

### <span style="color:#d29922">7.2 Free Play Mode</span>

- User selects an adversary persona directly
- Open-ended conversation — no scenario structure, no scoring
- Good for exploration, repeat practice, or educator demonstration
- Mentor persona available as an alternative — ask anything about online safety

### <span style="color:#d29922">7.3 Session Management</span>

- UUID session token, stored client-side in sessionStorage
- Server holds session state in an in-memory dict (TTL: 2 hours)
- No database, no authentication, no PII collected
- GDPR-compliant by design: nothing persisted

### <span style="color:#d29922">7.4 Progress (localStorage, no account)</span>

- Completed scenario IDs stored locally
- Completion badges shown on scenario cards
- Score history visible in session
- Clears on browser data clear — not promised as permanent

### <span style="color:#d29922">7.5 Grooming Scenario — Special Handling</span>

- Dedicated content warning screen before entry — user must actively confirm
- Adversary prompt carefully bounded: uses flattery, secrecy, isolation tactics only
- System prompt includes hard stops: no sexual content, no graphic language
- Debrief is the most detailed of any scenario — practical, calm, actionable
- Links to real resources: ISPCC Childline, Webwise.ie

---

## <span style="color:#3fb950">8. Technical Architecture</span>

### <span style="color:#d29922">8.1 Stack</span>

| <span style="color:#58a6ff">Layer</span> | <span style="color:#58a6ff">Technology</span> | <span style="color:#58a6ff">Rationale</span> |
|-------|------------|-----------|
| Backend | FastAPI (Python 3.12) | Proven in v1, async, lightweight |
| LLM | Anthropic Claude API | No GPU needed, mobile-compatible, superior persona quality |
| Adversary model | `claude-haiku-4-5` | Cost-effective, fast, sufficient for adversary chat |
| Judge model | `claude-haiku-4-5` | Semantic red flag evaluation per user turn |
| Session state | Python dict + UUID | No DB dependency, Railway/Render compatible |
| Frontend | Vanilla HTML/CSS/JS | No build step, fast cold start, no framework overhead |
| Container | Single Dockerfile | Railway/Render deploy target |

### <span style="color:#d29922">8.2 API Endpoints</span>

```
GET  /api/health                      Health check
GET  /api/scenarios                   List all scenarios grouped by category
GET  /api/scenario/{id}               Get scenario detail
POST /api/session/start               Create session, returns session_id
POST /api/scenario/{id}/start         Begin scenario in session
POST /api/chat                        Send message, stream response + flag events
POST /api/scenario/complete           Finalise, return score + debrief
POST /api/scenario/exit               Return to free play / menu
GET  /api/scenario/status             Current session state
GET  /api/players                     List available free-play personas
POST /api/freeplay/start              Begin free play with chosen persona
```

### <span style="color:#d29922">8.3 Session Object</span>

```python
@dataclass
class Session:
    session_id: str
    mode: Literal["idle", "scenario", "freeplay"]
    player: dict
    scenario: Optional[dict]
    history: List[dict]           # [{role, content}]
    red_flags_detected: List[str]
    created_at: datetime
    last_active: datetime
```

### <span style="color:#d29922">8.4 Red Flag Detection</span>

Each user message triggers a lightweight judge call:

```
System: You are evaluating a user's response in a cybersecurity training scenario.
        The user is practising how to handle [scenario type].
        The possible red flags to detect are: [list].
        Return a JSON array of flag keys the user demonstrated. Return [] if none.

User: [user message]
```

No keywords. No regex. Semantic judgement.

### <span style="color:#d29922">8.5 Folder Structure</span>

```
cybersafer/
├── cybers.py               FastAPI application
├── players/                Adversary + mentor persona JSON files
├── scenarios/              Scenario definition JSON files
├── static/
│   ├── index.html          Landing page
│   ├── scenarios.html      Category + scenario selection
│   ├── chat.html           Main chat interface (scenario + freeplay)
│   ├── results.html        Debrief / score screen
│   ├── css/
│   │   └── styles.css      Single stylesheet, CSS variables, mobile-first
│   └── js/
│       └── app.js          Single JS file, no framework
├── Dockerfile
├── requirements.txt
├── .env.example
├── PRD.md
└── README.md
```

---

## <span style="color:#3fb950">9. UI Design Direction</span>

**Aesthetic:** Tactical minimalism — dark background, precise typography, purposeful colour. Feels serious but not scary. Approachable but not childish.

**Palette:**
- Background: `#0d1117` (near-black)
- Surface: `#161b22`
- Border: `#30363d`
- Accent blue: `#58a6ff`
- Accent green: `#3fb950`
- Accent amber: `#d29922` (warnings)
- Accent red: `#f85149` (danger/flags)
- Text primary: `#e6edf3`
- Text muted: `#8b949e`

**Typography:** `DM Sans` (body) + `DM Mono` (chat messages, codes). Both from Google Fonts, both load fast.

**Layout principles:**
- Mobile-first — single column, 100vw at 375px
- No horizontal scroll at any viewport
- Chat bubbles: user right, adversary left — clear visual distinction
- Red flag badges: animated inline chip, not a disruptive alert
- Scenario cards: difficulty chip, category icon, completion tick

**Key screens:**
1. **Landing** — logo, one-line pitch, two CTAs: "Choose a Scenario" / "Free Play"
2. **Scenarios** — category tabs, scenario cards with difficulty + time estimate
3. **Chat** — adversary bubble (distinctive styling), user input, live flag counter, End button
4. **Results** — score ring, flags found/missed, debrief text, "Try Again" / "Next Scenario"

---

## <span style="color:#3fb950">10. Content Guidelines</span>

**Tone:** A knowledgeable older sibling, not a compliance officer.

**Adversary personas:** Convincing but bounded. The goal is recognition, not trauma.

**Grooming content rule:** The scenario teaches manipulation recognition. It ends the moment the user demonstrates awareness. The adversary never escalates beyond what a first contact might look like on a social platform.

**Debrief rule:** Every debrief ends with one concrete, actionable thing the user can do today.

---

## <span style="color:#3fb950">11. Environment Variables</span>

```bash
ANTHROPIC_API_KEY=        # Required
CYBERS_MODEL=claude-haiku-4-5-20251001   # Adversary model
CYBERS_PORT=8021          # Server port
CYBERS_HOST=0.0.0.0       # Bind address
SESSION_TTL_HOURS=2       # Session timeout
```

---

## <span style="color:#3fb950">12. Deployment</span>

**Dockerfile:** Single-stage, Python 3.12-slim, no GPU dependencies.

**Railway/Render:** Point at repo root, set `ANTHROPIC_API_KEY` env var, expose port 8021. Done.

**Cold start target:** < 30 seconds (no model loading — API calls only).

---

## <span style="color:#3fb950">13. Milestones</span>

| <span style="color:#58a6ff">Milestone</span> | <span style="color:#58a6ff">Deliverable</span> |
|-----------|------------|
| M1 — Backend | `cybers.py` — sessions, chat, judge, all API endpoints |
| M2 — Scenarios | Grooming scenario JSON + player persona |
| M3 — Frontend | All four screens, mobile-first, CSS + JS |
| M4 — Deploy | Dockerfile, README, live on Railway/Render |
| M5 — Polish | Debrief content review, accessibility pass, Lighthouse audit |

---

## <span style="color:#3fb950">14. Out of Scope — Future Versions</span>

- **v3:** Anseo integration — CyberSafer as an embedded module within the Anseo platform
- **v3:** Teacher dashboard — class progress, scenario assignment
- **v3:** User accounts and persistent progress
- **v4:** WebNN/WebGPU option for offline/kiosk use cases

---

<span style="color:#8b949e">Last updated: March 2026 · FoxxeLabs Limited</span>
