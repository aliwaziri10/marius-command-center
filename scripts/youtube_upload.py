def build_description(narration_text):
    text = (narration_text or "").strip()
    limit = 1500
    if len(text) > limit:
        snippet = text[:limit]
        last_boundary = max(
            snippet.rfind(". "),
            snippet.rfind(".\n"),
            snippet.rfind("! "),
            snippet.rfind("? "),
        )
        if last_boundary > 0:
            snippet = snippet[: last_boundary + 1]
        else:
            last_space = snippet.rfind(" ")
            snippet = (snippet[:last_space] if last_space > 0 else snippet) + "..."
    else:
        snippet = text
    return (
        f"{snippet}\n\n"
        f"If this story moved you, subscribe - every episode of Erased "
        f"brings back a name history tried to bury.\n\n"
        f"#erased #history #documentary"
    )
