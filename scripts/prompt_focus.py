"""
Marius Command Center - per-shot anchor focusing (2026-10-09).

PROTAGONIST-EVERYWHERE FIX: Zia reported the protagonist appearing in ~95%
of shots, with faces morphing from one person into another. Measured live:
the PLANNED shots name the protagonist in at most ~8 of 35 shots, but
prompt_builder.build_agnes_prompt sent the full setting_and_characters
anchor ("The recurring protagonist is Renee, a nineteen-year-old...") with
EVERY shot, ledgers and buildings included, so the video model painted her
into nearly everything and swapped her face with other people in frame.
Also, prompt_builder's own group-shot stripper only matched the phrases
"recurring character" / "main character", so an anchor worded "recurring
protagonist" was never stripped at all.

This module keeps the protagonist sentence only for shots that actually
name or tag the protagonist, and tells the model when a shot has no
people. Fails SAFE: if no protagonist name can be found in the anchor, the
anchor is returned unchanged (the old behaviour).
"""

import re

_NAME_RE = re.compile(
    r"recurring (?:protagonist|character)(?:,?\s+(?:is|named|called))?\s+(?:named\s+|called\s+)?([A-Z][^\s,.;:]+)"
)

_PEOPLE_RE = re.compile(
    r"\b(man|men|woman|women|person|persons|people|child|children|girl|boy|clerk|clerks|"
    r"worker|workers|soldier|soldiers|officer|officers|guard|guards|figure|figures|crowd|"
    r"crowds|villager|villagers|family|families|couple|silhouette|silhouettes|hand|hands|"
    r"face|faces|he|she|they|his|her|their|him|them|staff|passengers|residents|neighbors|"
    r"neighbours|onlookers|bystanders|pedestrians|mother|father|son|daughter|doctor|nurse|"
    r"priest|farmer|farmers|prisoner|prisoners|inmates|refugees|civilians|youth|elder|"
    r"elders|boys|girls|students|teacher|teachers|merchant|merchants)\b",
    re.IGNORECASE,
)

NO_PEOPLE_CLAUSE = (
    "no people, faces, or human figures appear anywhere in this frame - "
    "the subject is the object, place or document only"
)


def protagonist_name(anchor):
    match = _NAME_RE.search(anchor or "")
    return match.group(1).strip() if match else None


def visual_has_people(visual):
    return bool(_PEOPLE_RE.search(visual or ""))


def shot_features_protagonist(shot, anchor):
    """True if this shot should carry the protagonist's description. True
    (leave anchor untouched) when no protagonist name can be found."""
    name = protagonist_name(anchor)
    if not name:
        return True
    text = " ".join([
        shot.get("visual_description") or "",
        shot.get("primary_subject") or "",
    ]).lower()
    return name.lower() in text or "protagonist" in text or "main character" in text


def focus_anchor(shot, anchor):
    """Anchor to send with this shot: unchanged if the shot features the
    protagonist, otherwise with every sentence that describes the
    protagonist removed (setting, era and background-people sentences stay)."""
    anchor = (anchor or "").strip()
    if not anchor or shot_features_protagonist(shot, anchor):
        return anchor
    name = (protagonist_name(anchor) or "").lower()
    pieces = re.split(r"(?<=[.;])\s+", anchor)
    kept = []
    for p in pieces:
        low = p.lower()
        if "recurring" in low or "protagonist" in low or "main character" in low:
            continue
        if name and name in low:
            continue
        kept.append(p)
    return " ".join(kept).strip()


def no_people_clause(shot, anchor):
    """The 'no people in frame' clause, only for shots that clearly have no
    people: no people words in the description, no primary_subject tag, and
    the protagonist is not featured."""
    if visual_has_people(shot.get("visual_description") or ""):
        return ""
    if (shot.get("primary_subject") or "").strip():
        return ""
    if shot_features_protagonist(shot, anchor or ""):
        return ""
    return NO_PEOPLE_CLAUSE
