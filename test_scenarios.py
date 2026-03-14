#!/usr/bin/env python3
"""
CyberSafer v2 — Automated Test Suite
=====================================
Tests scenario JSON integrity, API endpoints, and navigation flow.

Usage:
    # Test JSON only (no server needed):
    python test_scenarios.py --offline

    # Full test including API (server must be running):
    python test_scenarios.py

    # Specific base URL:
    python test_scenarios.py --url http://localhost:8021

    # Verbose output:
    python test_scenarios.py -v
"""

import os, sys, json, argparse, time
from pathlib import Path

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ── Colour helpers ──────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
RED    = "\033[31m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
BLUE   = "\033[34m"
CYAN   = "\033[36m"
DIM    = "\033[2m"

def ok(msg):    print(f"  {GREEN}✓{RESET} {msg}")
def fail(msg):  print(f"  {RED}✗{RESET} {msg}")
def warn(msg):  print(f"  {YELLOW}⚠{RESET}  {msg}")
def info(msg):  print(f"  {BLUE}→{RESET} {msg}")
def header(msg):print(f"\n{BOLD}{CYAN}{msg}{RESET}")
def dim(msg):   print(f"{DIM}  {msg}{RESET}")

# ── Constants ───────────────────────────────────────────────────────────────

SCENARIOS_DIR = Path("scenarios")
PLAYERS_DIR   = Path("players")
STATIC_DIR    = Path("static")

REQUIRED_SCENARIO_FIELDS = ["id", "type", "tier", "category", "difficulty",
                              "title", "introduction"]
REQUIRED_OBSERVE_FIELDS  = ["script", "learning_objectives", "debrief",
                              "participants"]
REQUIRED_CHAT_FIELDS     = ["player", "initial_message", "red_flags",
                              "success_criteria", "learning_objectives", "debrief"]
REQUIRED_SCRIPT_FIELDS   = ["id", "from", "text", "is_red_flag"]
REQUIRED_FLAG_FIELDS     = ["flag_label", "explanation"]

VALID_TIERS       = {"recognise", "respond"}
VALID_TYPES       = {"observe", "chat"}
VALID_CATEGORIES  = {"phishing", "online_scams", "malware", "identity_theft",
                      "cyberbullying", "grooming"}
VALID_DIFFICULTIES= {"beginner", "medium", "intermediate", "hard", "advanced"}

STATIC_PAGES = ["index.html", "scenarios.html", "category.html",
                "observe.html", "onboarding.html", "privacy.html"]
STATIC_INDEX = Path("static/scenarios-index.json")

API_ROUTES = [
    ("GET",  "/api/health",    200),
    ("GET",  "/api/scenarios", 200),
    ("GET",  "/api/players",   200),
    ("POST", "/api/session/start", 200),
]

# ── Test state ───────────────────────────────────────────────────────────────

class Results:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warned = 0
        self.errors = []

    def record(self, passed, message, is_warning=False):
        if passed:
            self.passed += 1
            return True
        elif is_warning:
            self.warned += 1
            self.errors.append(f"WARN  {message}")
            return False
        else:
            self.failed += 1
            self.errors.append(f"FAIL  {message}")
            return False

R = Results()

def check(condition, ok_msg, fail_msg, warning=False):
    if condition:
        ok(ok_msg)
        R.record(True, ok_msg)
    else:
        if warning:
            warn(fail_msg)
        else:
            fail(fail_msg)
        R.record(False, fail_msg, is_warning=warning)
    return condition

# ── JSON Tests ───────────────────────────────────────────────────────────────

def test_json_files():
    header("1. SCENARIO JSON INTEGRITY")

    if not SCENARIOS_DIR.exists():
        fail(f"scenarios/ directory not found")
        R.record(False, "scenarios/ directory missing")
        return []

    files = sorted(SCENARIOS_DIR.glob("*.json"))
    check(len(files) > 0, f"Found {len(files)} scenario files", "No scenario files found")

    scenarios = []
    for path in files:
        print(f"\n  {BOLD}{path.name}{RESET}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            fail(f"Invalid JSON: {e}")
            R.record(False, f"{path.name}: invalid JSON")
            continue

        # Required base fields
        for field in REQUIRED_SCENARIO_FIELDS:
            check(field in data,
                  f"{field} present",
                  f"{path.name}: missing required field '{field}'")

        # ID matches filename
        expected_id = path.stem
        check(data.get("id") == expected_id,
              f"id matches filename ({expected_id})",
              f"{path.name}: id '{data.get('id')}' doesn't match filename '{expected_id}'",
              warning=True)

        # Valid enum values
        check(data.get("type") in VALID_TYPES,
              f"type is valid ({data.get('type')})",
              f"{path.name}: type '{data.get('type')}' not in {VALID_TYPES}")

        check(data.get("tier") in VALID_TIERS,
              f"tier is valid ({data.get('tier')})",
              f"{path.name}: tier '{data.get('tier')}' not in {VALID_TIERS}")

        check(data.get("category") in VALID_CATEGORIES,
              f"category is valid ({data.get('category')})",
              f"{path.name}: category '{data.get('category')}' not in {VALID_CATEGORIES}",
              warning=True)

        check(data.get("difficulty") in VALID_DIFFICULTIES,
              f"difficulty is valid ({data.get('difficulty')})",
              f"{path.name}: difficulty '{data.get('difficulty')}' not in {VALID_DIFFICULTIES}",
              warning=True)

        # Type-specific fields
        stype = data.get("type")
        if stype == "observe":
            _test_observe_scenario(path.name, data)
        elif stype == "chat":
            _test_chat_scenario(path.name, data)

        # Content sanity
        title = data.get("title", "")
        check(len(title) >= 5,
              f"title is meaningful ({len(title)} chars)",
              f"{path.name}: title too short ('{title}')")

        intro = data.get("introduction", "")
        check(len(intro) >= 20,
              f"introduction present ({len(intro)} chars)",
              f"{path.name}: introduction too short")

        debrief = data.get("debrief", "")
        check(len(debrief) >= 50,
              f"debrief present ({len(debrief)} chars)",
              f"{path.name}: debrief too short")

        scenarios.append(data)

    return scenarios


def _test_observe_scenario(name, data):
    """Validate observe-specific fields."""
    for field in REQUIRED_OBSERVE_FIELDS:
        check(field in data,
              f"{field} present",
              f"{name}: missing observe field '{field}'")

    script = data.get("script", [])
    check(len(script) >= 3,
          f"script has {len(script)} messages (≥3)",
          f"{name}: script too short ({len(script)} messages)")

    participants = data.get("participants", {})
    check(len(participants) >= 2,
          f"participants defined ({len(participants)})",
          f"{name}: need at least 2 participants")

    red_flag_count = 0
    msg_ids = set()

    for i, msg in enumerate(script):
        # Required fields
        for field in REQUIRED_SCRIPT_FIELDS:
            if field not in msg:
                fail(f"{name}: script[{i}] missing '{field}'")
                R.record(False, f"{name}: script[{i}] missing '{field}'")

        # Unique IDs
        mid = msg.get("id", "")
        if mid in msg_ids:
            fail(f"{name}: duplicate message id '{mid}'")
            R.record(False, f"{name}: duplicate message id '{mid}'")
        msg_ids.add(mid)

        # Participant exists
        sender = msg.get("from", "")
        if sender and sender not in participants:
            warn(f"{name}: message from '{sender}' not in participants")
            R.record(False, f"{name}: unknown participant '{sender}'", is_warning=True)

        # Red flag fields
        if msg.get("is_red_flag"):
            red_flag_count += 1
            for field in REQUIRED_FLAG_FIELDS:
                check(field in msg,
                      f"red flag message has '{field}'",
                      f"{name}: script[{i}] is_red_flag=true but missing '{field}'")

    check(red_flag_count >= 2,
          f"has {red_flag_count} red flag messages (≥2)",
          f"{name}: fewer than 2 red flag messages ({red_flag_count})")

    learning = data.get("learning_objectives", [])
    check(len(learning) >= 3,
          f"has {len(learning)} learning objectives (≥3)",
          f"{name}: fewer than 3 learning objectives",
          warning=True)

    # Content warning scenarios must have warning text
    if data.get("content_warning"):
        check("content_warning_text" in data,
              "content_warning_text present",
              f"{name}: content_warning=true but no content_warning_text")


def _test_chat_scenario(name, data):
    """Validate chat-specific fields."""
    for field in REQUIRED_CHAT_FIELDS:
        check(field in data,
              f"{field} present",
              f"{name}: missing chat field '{field}'")

    # Player file exists
    player = data.get("player", "")
    if player:
        player_key = Path(player).stem
        player_path = PLAYERS_DIR / f"{player_key}.json"
        check(player_path.exists(),
              f"player file exists ({player_key}.json)",
              f"{name}: player '{player}' not found at {player_path}")

    # Success criteria are subset of red_flags
    red_flags = set(data.get("red_flags", []))
    success    = set(data.get("success_criteria", []))
    orphans    = success - red_flags
    check(len(orphans) == 0,
          "success_criteria all in red_flags",
          f"{name}: success_criteria {orphans} not in red_flags",
          warning=True)

    check(len(success) >= 1,
          f"has {len(success)} success criteria",
          f"{name}: no success criteria defined")


def test_player_files():
    header("2. PLAYER / INDEX INTEGRITY")

    # Check static scenarios index
    check(STATIC_INDEX.exists(),
          f"scenarios-index.json exists",
          f"Missing static/scenarios-index.json — run build script")

    if STATIC_INDEX.exists():
        idx = json.loads(STATIC_INDEX.read_text())
        total = idx.get('total', 0)
        check(total > 0,
              f"Index contains {total} scenarios",
              "Index is empty")
        # Verify every scenario file has an entry
        scenario_files = list(SCENARIOS_DIR.glob('*.json'))
        check(total == len(scenario_files),
              f"Index total ({total}) matches scenario files ({len(scenario_files)})",
              f"Index ({total}) out of sync with files ({len(scenario_files)}) — rebuild index")

    if not PLAYERS_DIR.exists():
        info("players/ directory not present (expected for static build)")
        return

    files = sorted(PLAYERS_DIR.glob("*.json"))
    check(len(files) > 0, f"Found {len(files)} player files", "No player files found")

    for path in files:
        print(f"\n  {BOLD}{path.name}{RESET}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            fail(f"Invalid JSON: {e}")
            R.record(False, f"{path.name}: invalid JSON")
            continue

        for field in ["name", "instructions"]:
            check(field in data,
                  f"{field} present",
                  f"{path.name}: missing field '{field}'")

        # Check for banned teen-targeting language
        instructions = data.get("instructions", "").lower()
        banned_phrases = [
            "age-appropriate for teens",
            "targeting teens",
            "keep it teen",
        ]
        for phrase in banned_phrases:
            check(phrase not in instructions,
                  f"no banned phrase '{phrase}'",
                  f"{path.name}: contains banned phrase '{phrase}'")


def test_static_files():
    header("3. STATIC FILE PRESENCE")

    for page in STATIC_PAGES:
        path = STATIC_DIR / page
        check(path.exists(),
              f"{page} exists",
              f"Missing static file: static/{page}")

    # Check all pages have onboarding guard (except onboarding itself and privacy)
    skip_guard = {"onboarding.html", "privacy.html"}
    for page in STATIC_PAGES:
        if page in skip_guard:
            continue
        path = STATIC_DIR / page
        if path.exists():
            content = path.read_text(encoding="utf-8")
            check("cs_onboarded" in content,
                  f"{page} has onboarding guard",
                  f"{page}: missing onboarding guard",
                  warning=True)
            check("noindex" in content,
                  f"{page} has noindex meta",
                  f"{page}: missing noindex meta",
                  warning=True)

    # CSS and JS
    check((STATIC_DIR / "css" / "styles.css").exists(),
          "css/styles.css exists",
          "Missing css/styles.css")


def test_navigation_consistency(scenarios):
    header("4. NAVIGATION CONSISTENCY")

    # Check every scenario has a valid category that appears in VALID_CATEGORIES
    cats_found = set()
    for s in scenarios:
        cats_found.add(s.get("category"))

    for cat in cats_found:
        check(cat in VALID_CATEGORIES,
              f"category '{cat}' is defined",
              f"Unknown category '{cat}' — add to VALID_CATEGORIES and categories.html",
              warning=True)

    # Each category should have at least one recognise and one respond (except grooming)
    grooming_only = {"grooming"}
    cat_tiers = {}
    for s in scenarios:
        cat = s.get("category")
        tier = s.get("tier")
        cat_tiers.setdefault(cat, set()).add(tier)

    for cat, tiers in sorted(cat_tiers.items()):
        if cat in grooming_only:
            dim(f"{cat}: grooming-only category, single tier acceptable")
            continue
        has_both = "recognise" in tiers and "respond" in tiers
        check(has_both,
              f"{cat}: has both recognise and respond tiers",
              f"{cat}: missing tier(s) — found {tiers}",
              warning=True)

    # Check scenario IDs are unique
    ids = [s.get("id") for s in scenarios]
    unique_ids = set(ids)
    check(len(ids) == len(unique_ids),
          f"All {len(ids)} scenario IDs are unique",
          f"Duplicate scenario IDs found: {[i for i in ids if ids.count(i) > 1]}")

    # Observe scenarios must not reference a player
    for s in scenarios:
        if s.get("type") == "observe":
            check("player" not in s or not s["player"],
                  f"{s['id']}: observe scenario has no player reference",
                  f"{s['id']}: observe scenario should not have player field",
                  warning=True)


# ── API Tests ─────────────────────────────────────────────────────────────────

def test_api(base_url, scenarios, verbose=False):
    header("5. API ENDPOINT TESTS")

    if not HAS_REQUESTS:
        warn("requests library not installed — skipping API tests")
        warn("Install with: pip install requests --break-system-packages")
        return

    # Health check
    try:
        r = requests.get(f"{base_url}/api/health", timeout=5)
        check(r.status_code == 200,
              f"GET /api/health → 200",
              f"GET /api/health → {r.status_code} (server may not be running)")
        if r.status_code == 200 and verbose:
            data = r.json()
            info(f"Server: {data.get('version','?')} | "
                 f"Scenarios: {data.get('scenarios','?')} | "
                 f"Players: {data.get('players','?')}")
    except requests.exceptions.ConnectionError:
        fail("Cannot connect to server — is it running?")
        R.record(False, f"Server not reachable at {base_url}")
        warn("Skipping all remaining API tests")
        return

    # Core routes
    print()
    for method, path, expected in API_ROUTES:
        try:
            if method == "GET":
                r = requests.get(f"{base_url}{path}", timeout=5)
            else:
                r = requests.post(f"{base_url}{path}", timeout=5)
            check(r.status_code == expected,
                  f"{method} {path} → {expected}",
                  f"{method} {path} → {r.status_code} (expected {expected})")
        except Exception as e:
            fail(f"{method} {path} → error: {e}")
            R.record(False, f"{method} {path} failed: {e}")

    # Scenarios endpoint — validate structure
    print()
    r = requests.get(f"{base_url}/api/scenarios", timeout=5)
    if r.status_code == 200:
        data = r.json()
        cats = data.get("categories", {})
        total = sum(len(v) for v in cats.values())
        check(total == len(scenarios),
              f"/api/scenarios returns {total} scenarios (matches {len(scenarios)} files)",
              f"/api/scenarios returns {total} but {len(scenarios)} JSON files exist")

        # Every file scenario should be accessible individually
        print()
        info("Testing individual scenario endpoints...")
        errors = []
        for s in scenarios:
            sid = s.get("id")
            try:
                r2 = requests.get(f"{base_url}/api/scenario/{sid}", timeout=5)
                if r2.status_code != 200:
                    errors.append(f"/api/scenario/{sid} → {r2.status_code}")
            except Exception as e:
                errors.append(f"/api/scenario/{sid} → {e}")

        check(len(errors) == 0,
              f"All {len(scenarios)} scenarios individually accessible",
              f"{len(errors)} scenario(s) not accessible: {errors[:3]}")

    # Session creation
    print()
    r = requests.post(f"{base_url}/api/session/start", timeout=5)
    session_id = None
    if r.status_code == 200:
        session_id = r.json().get("session_id")
        check(bool(session_id),
              f"Session created: {session_id[:8]}...",
              "Session start returned no session_id")

    # Players endpoint
    r = requests.get(f"{base_url}/api/players", timeout=5)
    if r.status_code == 200:
        players = r.json().get("players", [])
        check(len(players) > 0,
              f"/api/players returns {len(players)} players",
              "/api/players returned empty list")

    # 404 handling
    r = requests.get(f"{base_url}/api/scenario/this_does_not_exist", timeout=5)
    check(r.status_code == 404,
          "Non-existent scenario returns 404",
          f"Non-existent scenario returned {r.status_code} (expected 404)")

    # Static files served
    print()
    info("Testing static file serving...")
    for page in ["index.html", "scenarios.html", "observe.html"]:
        r = requests.get(f"{base_url}/{page}", timeout=5)
        check(r.status_code == 200,
              f"/{page} served (200)",
              f"/{page} → {r.status_code}")


def test_content_quality(scenarios, verbose=False):
    header("6. CONTENT QUALITY CHECKS")

    for s in scenarios:
        if s.get("type") != "observe":
            continue

        sid = s.get("id")
        script = s.get("script", [])

        # Check explanations are substantial
        short_explanations = []
        for msg in script:
            if msg.get("is_red_flag"):
                explanation = msg.get("explanation", "")
                if len(explanation) < 40:
                    short_explanations.append(msg.get("id"))

        check(len(short_explanations) == 0,
              f"{sid}: all explanations substantial",
              f"{sid}: short explanations on messages: {short_explanations}",
              warning=True)

        # Debrief should not be suspiciously short
        debrief = s.get("debrief", "")
        check(len(debrief) >= 100,
              f"{sid}: debrief is substantive ({len(debrief)} chars)",
              f"{sid}: debrief may be too short ({len(debrief)} chars)",
              warning=True)

        # Resources present on high-severity scenarios
        high_severity = {"grooming_new_friend", "bully_photo_threat",
                          "scam_romance_lonely"}
        if sid in high_severity:
            resources = s.get("resources", [])
            check(len(resources) > 0,
                  f"{sid}: has support resources",
                  f"{sid}: high-severity scenario missing resources",
                  warning=True)

        # No broken markdown (unpaired **)
        for field in ["debrief"]:
            text = s.get(field, "")
            bold_markers = text.count("**")
            check(bold_markers % 2 == 0,
                  f"{sid}: balanced ** markers in {field}",
                  f"{sid}: odd number of ** in {field} (broken bold)",
                  warning=True)

        if verbose:
            red_flags = [m for m in script if m.get("is_red_flag")]
            dim(f"{sid}: {len(script)} messages, {len(red_flags)} red flags")


# ── Summary ──────────────────────────────────────────────────────────────────

def print_summary():
    header("SUMMARY")
    total = R.passed + R.failed + R.warned
    print(f"\n  {GREEN}Passed:  {R.passed}{RESET}")
    if R.warned:
        print(f"  {YELLOW}Warned:  {R.warned}{RESET}")
    if R.failed:
        print(f"  {RED}Failed:  {R.failed}{RESET}")
    print(f"  {DIM}Total:   {total}{RESET}")

    if R.errors:
        print(f"\n{BOLD}Issues to address:{RESET}")
        failures = [e for e in R.errors if e.startswith("FAIL")]
        warnings = [e for e in R.errors if e.startswith("WARN")]
        for e in failures:
            print(f"  {RED}✗{RESET} {e[6:]}")
        if warnings and R.failed == 0:
            for e in warnings:
                print(f"  {YELLOW}⚠{RESET}  {e[6:]}")

    if R.failed == 0:
        print(f"\n{GREEN}{BOLD}  All critical tests passed.{RESET}")
    else:
        print(f"\n{RED}{BOLD}  {R.failed} critical failure(s) — fix before deploying.{RESET}")

    return R.failed == 0


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="CyberSafer v2 test suite")
    parser.add_argument("--offline", action="store_true",
                        help="Skip API tests (no server required)")
    parser.add_argument("--url", default="http://localhost:8021",
                        help="Server base URL (default: http://localhost:8021)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show extra detail")
    args = parser.parse_args()

    print(f"\n{BOLD}CyberSafer v2 — Test Suite{RESET}")
    print(f"{DIM}Working directory: {os.getcwd()}{RESET}")
    if not args.offline:
        print(f"{DIM}Server URL: {args.url}{RESET}")

    # Change to project root if running from elsewhere
    script_dir = Path(__file__).parent
    os.chdir(script_dir)

    scenarios = test_json_files()
    test_player_files()
    test_static_files()
    test_navigation_consistency(scenarios)

    if not args.offline:
        test_api(args.url, scenarios, verbose=args.verbose)
    else:
        header("5. API TESTS")
        info("Skipped (--offline mode)")

    test_content_quality(scenarios, verbose=args.verbose)

    passed = print_summary()
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
