"""Formats proposed GitHub review comments (drafts). Publishing is implemented in a later phase."""
LABEL = {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low", "info": "Info"}
FOOTER = "_AI-generated suggestion by SYNAXYS. Verify before acting; this is not a confirmed vulnerability._"


def format_inline_comment(f: dict, limit: int = 4000) -> str:
    """The AI disclaimer footer is always kept; only the variable body is truncated."""
    body = [f"**{LABEL.get(f['severity'], f['severity'])} · {f['category']}: {f['title']}**", "", f["explanation"]]
    if f.get("remediation"):
        body += ["", f"**Suggested fix:** {f['remediation']}"]
    if f.get("patch"):
        body += ["", "```", f["patch"], "```"]
    footer = f"\n\nConfidence: {round(f['confidence'] * 100)}%\n\n{FOOTER}"
    text = "\n".join(body)
    if len(text) + len(footer) > limit:
        text = text[: limit - len(footer) - 1].rstrip() + "…"
        if text.count("```") % 2:  # never leave a code fence open
            text += "\n```"
    return text + footer
