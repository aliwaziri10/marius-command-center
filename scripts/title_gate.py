"""
Marius Command Center - title gate (2026-10-09).

Ported from the MIT-licensed public repo Jakeschincariol/youtube-agent-skill
(skills/yt-package/title.py): the lint rules (60-char desktop cut, 40-char
mobile cut, <=2 all-caps words, vague-word list, number/name/date, no
filler front-loading, thumbnail must not repeat the title). Credit:
Copyright (c) Jakeschincariol, MIT License.

WHY: every live Erased title followed one label template ("The Quarantine
Clerk of the 1908 Messina Port") and carried no hook; the hook lived only
on the thumbnail. Reasoning from the lint rules, the YouTube title and the
thumbnail should say DIFFERENT things. At upload time this module asks
Gemini for 5 alternative titles built only from facts in the narration,
lints all of them against the thumbnail's hook_text, and uses the best one
ONLY if it clearly beats the original topic title. Fails SAFE to the
original topic title on every problem (no GEMINI_API_KEY, quota, bad JSON,
no clear winner) - a title problem must never block an upload.
Set TITLE_GATE_ENABLED=0 to switch it off.
"""

import os
import re
import json
import requests

DESKTOP, MOBILE, HARD = 60, 40, 100
GEMINI_MODEL = "gemini-3.5-flash-lite"  # same model llm_client.py already uses
MIN_SCORE_GAIN = 8  # a candidate must beat the original by this many lint points

VAGUE = {"amazing", "incredible", "insane", "crazy", "huge", "massive", "ultimate", "best",
         "powerful", "secret", "revolutionary", "mindblowing", "epic", "perfect", "complete",
         "everything"}
STOP = {"the", "a", "an", "of", "for", "to", "in", "on", "and", "or", "is", "are", "with", "your",
        "you", "my", "i", "this", "that", "it", "how", "what", "why"}


def _words(t):
    return re.findall(r"[a-z0-9']+", t.lower())


def lint(title, thumb=None):
    t = title.strip()
    n = len(t)
    issues, good = [], []
    if n > HARD:
        issues.append(("length", f"{n} chars, hard limit {HARD}"))
    elif n > DESKTOP:
        issues.append(("length", f"{n} chars, desktop search cuts near {DESKTOP}"))
    else:
        good.append("inside the desktop cut")
    if n > MOBILE:
        issues.append(("mobile", "mobile feed shows only the first ~40 characters"))
    caps = [w for w in t.split() if len(w) > 2 and w.isupper()]
    if len(caps) > 2:
        issues.append(("shouting", "more than 2 all-caps words"))
    vague = [w for w in _words(t) if w in VAGUE]
    if vague:
        issues.append(("vague", ", ".join(sorted(set(vague)))))
    if re.findall(r"\d[\d,.]*%?", t):
        good.append("has a concrete figure")
    else:
        issues.append(("no-number", "no number, date or name"))
    if t.endswith("?"):
        good.append("open question")
    if not [w for w in _words(t)[:3] if w not in STOP]:
        issues.append(("front-load", "first three words are filler"))
    if thumb:
        shared = (set(_words(t)) - STOP) & (set(_words(thumb)) - STOP)
        if shared:
            issues.append(("duplicate", "thumbnail repeats: " + ", ".join(sorted(shared))))
        else:
            good.append("thumbnail and title carry different words")
    score = max(0, min(100, 100 - 14 * len(issues) + 4 * len(good)))
    return {"title": t, "chars": n, "score": score, "issues": issues}


def _ask_gemini_for_titles(topic_title, hook_text, narration_text):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return []
    prompt = (
        "You write YouTube titles for a serious historical documentary channel called Erased "
        "(untold true stories of ordinary people in history).\n"
        f"Current title: {topic_title}\n"
        f"Thumbnail text (do NOT repeat its words in the title): {hook_text or '(none)'}\n"
        f"Opening of the narration (the ONLY source of facts):\n{(narration_text or '')[:900]}\n\n"
        "Write 5 alternative titles. Rules: 55 characters or fewer; include the person's role or name AND "
        "a concrete number, year or place taken from the narration; create curiosity without lying - "
        "never state a fact that is not in the narration; no all-caps words; avoid the words amazing, "
        "incredible, secret, ultimate, epic; the first three words must carry the subject; do not "
        "reuse the thumbnail text's words.\n"
        'Answer ONLY with JSON: {"titles": ["...", "...", "...", "...", "..."]}'
    )
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={key}",
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 400, "responseMimeType": "application/json"},
        },
        timeout=60,
    )
    if resp.status_code >= 400:
        print(f"[title_gate] Gemini error {resp.status_code} - keeping original title.")
        return []
    text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    data = json.loads(text.strip().strip("`").replace("json\n", "", 1))
    return [str(t).strip().strip('"') for t in data.get("titles", []) if str(t).strip()]


def optimize_title(topic_title, hook_text, narration_text):
    """Returns the title to upload with. Never raises."""
    try:
        if os.environ.get("TITLE_GATE_ENABLED", "1").strip() == "0":
            return topic_title
        original = lint(topic_title, hook_text)
        print(f"[title_gate] original {original['score']}/100: {topic_title!r} issues={[k for k, _ in original['issues']]}")
        candidates = _ask_gemini_for_titles(topic_title, hook_text, narration_text)
        scored = [lint(c, hook_text) for c in candidates if 8 <= len(c) <= HARD]
        if not scored:
            return topic_title
        best = max(scored, key=lambda r: r["score"])
        print(f"[title_gate] best candidate {best['score']}/100: {best['title']!r} issues={[k for k, _ in best['issues']]}")
        if best["score"] >= original["score"] + MIN_SCORE_GAIN and not best["issues"] or \
                (best["score"] >= original["score"] + MIN_SCORE_GAIN and all(k in ("mobile",) for k, _ in best["issues"])):
            print("[title_gate] using the improved title.")
            return best["title"]
        print("[title_gate] no clear improvement - keeping the original title.")
        return topic_title
    except Exception as e:
        print(f"[title_gate] failed ({e}) - keeping original title.")
        return topic_title
