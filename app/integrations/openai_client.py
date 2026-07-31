"""OpenAI wrapper. RULE 3 is enforced by function SIGNATURES here:

- narrate(precomputed_metrics: dict) -> str      # narration of numbers we computed
- label_pace(precomputed: dict) -> dict          # labels using numbers we computed
- classify_question(question, allowed) -> dict   # picks from a whitelist, no numbers
- embed(texts) -> list[list[float]]              # embeddings for cosine-sim in SQL

There is deliberately NO compute_and_narrate(raw_question) — the model never
computes metrics. If OPENAI_API_KEY is unset, deterministic stubs are returned
so the whole flow works locally without a key.

Language: narrate, label_pace, and summarize_project_reports all take an
optional `language` param (default "en") -- the frontend passes whatever
language is currently selected in its own UI, and that gets folded into the
prompt as an explicit "respond in {language}" instruction, so the model's
prose output (not the underlying data/labels, which stay deterministic and
language-independent) comes back in the requested language. Stub responses
(no API key configured) stay English-only regardless of the language param,
since there's no model call to instruct in that path.
"""
import json

from app.core.config import settings

# Maps the i18n ISO codes this project actually registers (en/ja/ko/zh/hi)
# to their unambiguous English names for use in prompts. Passing the bare
# code straight into a prompt (e.g. "Respond in ja") is genuinely
# ambiguous to a model -- "ja" is ALSO the German word for "yes", and
# that exact collision caused a real bug: asking for Japanese ("ja")
# returned a response in German that literally opened with "Ja," (German
# for "Yes,"). Every language() call below should go through this map,
# never insert `language` directly into a prompt string.
LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "hi": "Hindi",
}


def _language_name(language: str) -> str:
    """Falls back to the raw code for anything not in LANGUAGE_NAMES --
    better to pass through an unrecognized value than silently default to
    English and hide a real gap (e.g. a new locale added to the frontend
    but not yet added to LANGUAGE_NAMES here)."""
    return LANGUAGE_NAMES.get(language, language)

try:
    from openai import OpenAI
except ImportError:  # allows importing the app without the package during tooling
    OpenAI = None  # type: ignore

_client = None


def _get_client():
    global _client
    if _client is None and OpenAI is not None and settings.OPENAI_API_KEY:
        _client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def narrate(precomputed_metrics: dict, language: str = "en") -> str:
    """One-sentence narration of already-correct metrics. Input MUST be precomputed."""
    client = _get_client()
    if client is None:
        return f"{precomputed_metrics.get('metric', 'value')}: {precomputed_metrics.get('value')}"
    resp = client.chat.completions.create(
        model=settings.OPENAI_TEXT_MODEL,
        messages=[
            {"role": "system", "content": (
                "You narrate workforce metrics for a manager. You are given exact, "
                "precomputed numbers. Restate them in one friendly sentence. "
                "NEVER alter, recompute, or extrapolate the numbers. "
                f"Respond in {_language_name(language)} regardless of what language the input data is in.")},
            {"role": "user", "content": json.dumps(precomputed_metrics)},
        ],
        max_tokens=120,
    )
    return resp.choices[0].message.content.strip()


def _compute_pace_label(todays_hours: float, avg_daily_hours_14d: float) -> str:
    """The one and only place pace_label gets decided -- same formula
    whether or not an OpenAI key is configured. Matches this file's own
    stated rule ("the model never computes metrics") -- previously the
    real (non-stub) path let the model freely decide the label itself,
    which was inconsistent with the stub and with the rest of the codebase's
    design (performance.py explicitly documents pace labels as precomputed,
    not model-decided)."""
    avg = avg_daily_hours_14d or todays_hours
    if todays_hours >= max(avg * 1.3, avg + 2):
        return "heavy"
    if todays_hours <= avg * 0.6:
        return "light"
    return "steady"


def label_pace(precomputed: dict, language: str = "en") -> dict:
    """Labels a report's pace given precomputed hours context + summary text.
    May also include late_minutes / early_checkout_minutes (from that day's
    AttendanceSession, see ai_workload.py) -- either can be null/absent.
    Returns {"pace_label": light|steady|heavy|unclear, "reasoning": str}.

    pace_label is ALWAYS computed deterministically (see
    _compute_pace_label) -- the model, when available, only narrates WHY,
    it never decides the label itself. This keeps the label reproducible
    and consistent regardless of how a summary happens to be phrased.

    pace_label itself stays the fixed English enum value
    (light/steady/heavy/unclear) regardless of `language` -- that's a
    stable identifier the frontend maps to its own translated display
    text (see features.*.pace.* keys), not prose. Only `reasoning` (the
    free-text explanation) actually changes language.
    """
    hours = precomputed.get("todays_hours", 0)
    avg = precomputed.get("avg_daily_hours_14d", 0) or hours
    late_minutes = precomputed.get("late_minutes")
    early_checkout_minutes = precomputed.get("early_checkout_minutes")
    label = _compute_pace_label(hours, avg)

    client = _get_client()
    if client is None:  # deterministic local stub
        reasoning = f"Stub: {hours}h today vs {avg}h 14-day average."
        if late_minutes:
            reasoning += f" Checked in {late_minutes} min late."
        if early_checkout_minutes:
            reasoning += f" Checked out {early_checkout_minutes} min early."
        return {"pace_label": label, "reasoning": reasoning}

    resp = client.chat.completions.create(
        model=settings.OPENAI_TEXT_MODEL,
        messages=[
            {"role": "system", "content": (
                f"This workday has ALREADY been classified as pace='{label}' using a fixed, "
                "precomputed rule based on hours worked vs. the 14-day average -- you do not "
                "decide or change this label under any circumstances. Your only job is to write "
                "a one-to-two sentence factual reasoning for why it's labeled this way, using "
                "ONLY the provided numbers and the report summary. You receive precomputed hour "
                "metrics and the report summary, and may also receive late_minutes and/or "
                "early_checkout_minutes if this person checked in late or checked out early that "
                "day (either can be null/absent if neither applies) -- mention these factually if "
                "present and non-zero, but they do not change the label, only the explanation. "
                f"Write the reasoning text in {_language_name(language)}, regardless of what language the report "
                "summary itself is written in. "
                'Respond as JSON: {"reasoning": ...}')},
            {"role": "user", "content": json.dumps({**precomputed, "pace_label": label})},
        ],
        response_format={"type": "json_object"},
        max_tokens=200,
    )
    try:
        out = json.loads(resp.choices[0].message.content)
        return {"pace_label": label, "reasoning": str(out.get("reasoning", ""))[:2000]}
    except (json.JSONDecodeError, KeyError):
        return {"pace_label": label, "reasoning": f"{hours}h today vs {avg}h 14-day average."}


def classify_question(question: str, allowed_query_types: list[str],
                      entities: dict | None = None) -> dict:
    """Maps a natural-language question to one whitelisted query type + params.
    Returns {"query_type": str|None, "parameters": dict}. Never returns numbers.

    `entities` is the caller's set of REAL names for this company, e.g.
    {"teams": [...], "employees": [...], "projects": [...], "goals": [...]} —
    the model may only fill parameters with values from these lists, so it
    cannot invent a team/employee/project/goal that doesn't exist. The caller
    still re-resolves every name against the DB, so a hallucinated name fails
    loudly there too.

    No `language` param here on purpose -- this function returns a
    query_type enum value and parameter values copied verbatim from
    `entities` (real names already in whatever language they're stored
    in), not generated prose. There's nothing here for a language
    instruction to actually affect.
    """
    entities = entities or {}

    def _find(names: list[str]) -> str | None:
        q = question.lower()
        for n in names or []:
            if n and n.lower() in q:
                return n
        return None

    client = _get_client()
    if client is None:  # deterministic stub for local dev: entity match first, keywords second
        team = _find(entities.get("teams", []))
        employee = _find(entities.get("employees", []))
        project = _find(entities.get("projects", []))
        goal = _find(entities.get("goals", []))
        q = question.lower()
        if employee and "individual_performance" in allowed_query_types:
            return {"query_type": "individual_performance", "parameters": {"employee_name": employee}}
        if team and "team_summary" in allowed_query_types:
            return {"query_type": "team_summary", "parameters": {"team_name": team}}
        if project and "project_progress" in allowed_query_types:
            return {"query_type": "project_progress", "parameters": {"project_name": project}}
        if goal and "goal_progress" in allowed_query_types:
            return {"query_type": "goal_progress", "parameters": {"goal_title": goal}}
        if any(k in q for k in ("pulse", "overall", "company", "how are we")) \
                and "company_pulse" in allowed_query_types:
            return {"query_type": "company_pulse", "parameters": {}}
        return {"query_type": None, "parameters": {}}

    resp = client.chat.completions.create(
        model=settings.OPENAI_TEXT_MODEL,
        messages=[
            {"role": "system", "content": (
                "Classify the user's question into EXACTLY one of these query types, or null "
                f"if none fit: {allowed_query_types}. Here's what each type actually covers, "
                "including casual/vague phrasings that should still map to it:\n"
                "- company_pulse: overall company status/health -- e.g. \"how's it going\", "
                "\"how are we doing\", \"what's our status\", \"how's the company\", \"give me an overview\"\n"
                "- team_summary: a specific team's performance/status -- only if a team name is mentioned or clearly implied\n"
                "- individual_performance: a specific named employee's performance -- only if a person is named\n"
                "- project_progress: a specific named project's status -- only if a project is named\n"
                "- goal_progress: a specific named goal's progress -- only if a goal is named\n"
                "If the question is vague/general with no specific team, person, project, or goal named, "
                "prefer company_pulse over returning null, as long as it's asking about status/performance "
                "in some form. Only return null if the question isn't about status/performance at all, or "
                "clearly refers to something not in the provided name lists. "
                "Parameter values may ONLY be chosen from these existing names — never invent one:\n"
                f"{json.dumps(entities)}\n"
                'Respond as JSON: {"query_type": <type or null>, "parameters": '
                '{<one of team_name|employee_name|project_name|goal_title, or empty>}}')},
            {"role": "user", "content": question},
        ],
        response_format={"type": "json_object"},
        max_tokens=150,
    )
    try:
        out = json.loads(resp.choices[0].message.content)
        qt = out.get("query_type")
        params = out.get("parameters") or {}
        # Server-side guard: drop any parameter value the model made up.
        allowed_values = {v for names in entities.values() for v in names}
        if entities:
            params = {k: v for k, v in params.items() if v in allowed_values}
        return {"query_type": qt if qt in allowed_query_types else None, "parameters": params}
    except json.JSONDecodeError:
        return {"query_type": None, "parameters": {}}


def embed(texts: list[str]) -> list[list[float]]:
    """text-embedding-3-small vectors (1536 dims). Similarity math happens in SQL/Python."""
    client = _get_client()
    if client is None:  # deterministic pseudo-embedding stub for local dev
        import hashlib
        out = []
        for t in texts:
            h = hashlib.sha256(t.encode()).digest()
            base = [((b / 255) - 0.5) for b in h]  # 32 dims of signal
            vec = (base * (1536 // 32 + 1))[:1536]
            out.append(vec)
        return out
    resp = client.embeddings.create(model=settings.OPENAI_EMBEDDING_MODEL, input=texts)
    return [d.embedding for d in resp.data]


def summarize_project_reports(precomputed: dict, language: str = "en") -> dict:
    """New, additive -- powers the AI Insights per-project summary. This is
    a deliberate, narrow exception to the "AI never computes numbers" rule:
    the contribution percentage here IS an AI judgment call, not arithmetic
    -- reading what each person's reports actually describe having done,
    since raw hours-logged can misrepresent real contribution (someone
    logging a long report about a small task vs. a short report about a
    big one). This is why it's always returned separately from, and
    alongside, the deterministic hours-share percentage the caller already
    computed -- so it's never mistaken for a hard measurement.

    Two hard constraints enforced in the prompt itself:
      1. Neutral, descriptive tone ONLY -- what tasks were done, never
         judgments about effort, attitude, or work ethic. No "underperformed",
         "didn't try hard", "wasted time", etc., regardless of how the
         percentages land. If someone did fewer/smaller tasks, state
         plainly what they did -- never why, and never how that reflects
         on them as a person.
      2. Focus on substantive completed work, filtering out cosmetic/trivial
         changes (e.g. "changed a button color") in favor of real progress
         (features shipped, bugs fixed, systems built).

    `language`: both summary_bullets and each contribution's "note" come
    back in this language -- employee names and estimated_pct numbers are
    unaffected (names aren't translated, percentages aren't prose).

    precomputed shape:
      {
        "project_name": str, "deal_price": float | None, "currency": str,
        "deadline": str | None, "period_start": str, "period_end": str,
        "employees": [
          {"name": str, "hours": float, "hours_share_pct": float,
           "report_summaries": [str, ...]},
          ...
        ],
      }

    Returns:
      {
        "summary_bullets": [str, ...],
        "contributions": {
          employee_name: {"estimated_pct": float, "note": str},
          ...
        },
      }
    """
    client = _get_client()
    employees = precomputed.get("employees", [])

    if client is None:  # deterministic local stub -- falls back to hours-share as the estimate
        bullets = []
        for emp in employees:
            for summary in emp.get("report_summaries", [])[:3]:
                bullets.append(f"{emp['name']}: {summary}")
        contributions = {
            emp["name"]: {
                "estimated_pct": emp.get("hours_share_pct", 0.0),
                "note": f"Stub: based on {emp.get('hours', 0)}h logged (no OpenAI key configured for report-based estimation).",
            }
            for emp in employees
        }
        return {"summary_bullets": bullets[:10], "contributions": contributions}

    resp = client.chat.completions.create(
        model=settings.OPENAI_TEXT_MODEL,
        messages=[
            {"role": "system", "content": (
                "You summarize a project's actual progress for a company Owner, based on daily "
                "report summaries employees wrote. You are given, for each employee: their name, "
                "hours logged, their hours-share percentage of the project's total (a precomputed "
                "fact, not yours to change), and their raw report summaries for this period.\n\n"
                "Produce two things:\n"
                "1. summary_bullets: a short bullet list (4-8 items) of SUBSTANTIVE completed work "
                "only -- real features shipped, bugs fixed, systems built. Explicitly ignore or "
                "skip cosmetic/trivial changes (e.g. button color changes, minor text tweaks) unless "
                "that's genuinely all that happened.\n"
                "2. contributions: for EACH employee, an estimated_pct (your best estimate of their "
                "share of real contribution, based on what their reports actually describe having "
                "been done -- NOT simply copying their hours-share percentage) and a short neutral "
                "note explaining what they did.\n\n"
                "CRITICAL constraint on tone: describe WHAT was done, never HOW WELL or HOW HARD "
                "someone worked. Never use judgmental language (no 'underperformed', 'didn't try', "
                "'wasted time', 'was unproductive', etc.) even if someone's estimated_pct is low. If "
                "someone did less, simply state what they did plainly -- do not explain or speculate "
                "on why, and do not characterize their effort or attitude. This must read as a factual "
                "activity log, never as a performance judgment.\n\n"
                f"Write summary_bullets and every contribution's note in {_language_name(language)}, regardless of "
                "what language the underlying report summaries are written in. Do not translate "
                "employee names.\n\n"
                'Respond as JSON: {"summary_bullets": [...], "contributions": '
                '{"<employee name>": {"estimated_pct": <number>, "note": "<short neutral sentence>"}}}')},
            {"role": "user", "content": json.dumps(precomputed)},
        ],
        response_format={"type": "json_object"},
        max_tokens=900,
    )
    try:
        out = json.loads(resp.choices[0].message.content)
        bullets = [str(b) for b in out.get("summary_bullets", [])][:10]
        raw_contributions = out.get("contributions", {})
        contributions = {}
        for emp in employees:
            name = emp["name"]
            entry = raw_contributions.get(name, {})
            contributions[name] = {
                "estimated_pct": float(entry.get("estimated_pct", emp.get("hours_share_pct", 0.0))),
                "note": str(entry.get("note", ""))[:300],
            }
        return {"summary_bullets": bullets, "contributions": contributions}
    except (json.JSONDecodeError, KeyError, ValueError):
        # Fall back to the same deterministic stub shape on any parse failure.
        contributions = {
            emp["name"]: {"estimated_pct": emp.get("hours_share_pct", 0.0), "note": "Estimate unavailable this time."}
            for emp in employees
        }
        return {"summary_bullets": [], "contributions": contributions}