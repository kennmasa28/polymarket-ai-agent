"""Load Markdown trading skills from the project's ``skills`` directory.

The filename intentionally follows the name requested by the application
(``slills_loader.py``).  Skills are injected into the agent instructions,
which makes their guidance available on every turn.
"""

from __future__ import annotations

from pathlib import Path


# ``skills/`` lives beside ``src/`` so that Markdown guidance remains separate
# from the application code.
DEFAULT_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


def load_skills(skills_dir: Path | str = DEFAULT_SKILLS_DIR) -> list[str]:
    """Return every ``.md`` skill as a labelled instruction string.

    Files are sorted to make the resulting prompt deterministic.  A missing
    skills directory is valid, so the chat application can start before any
    custom skills have been added.
    """
    directory = Path(skills_dir)
    if not directory.is_dir():
        return []

    skills: list[str] = []
    for path in sorted(directory.glob("*.md"), key=lambda item: item.name.lower()):
        text = path.read_text(encoding="utf-8").strip()
        if text:
            skills.append(f"## Skill: {path.stem}\n{text}")
    return skills


def skills_as_instructions(skills_dir: Path | str = DEFAULT_SKILLS_DIR) -> str:
    """Format all local skills for the Agents SDK ``instructions`` field."""
    skills = load_skills(skills_dir)
    if not skills:
        return "No local skills are currently installed."
    return "\n\n".join(skills)
