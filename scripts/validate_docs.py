"""Validate repository-local Markdown links and Mermaid fence shape."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
IGNORED_PARTS = {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv", "build", "dist"}
LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
MERMAID_PATTERN = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)
MERMAID_STARTS = ("flowchart ", "graph ", "sequenceDiagram", "classDiagram", "stateDiagram")


def markdown_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*.md")
        if not any(part in IGNORED_PARTS for part in path.relative_to(ROOT).parts)
    )


def validate() -> list[str]:
    errors: list[str] = []
    for path in markdown_files():
        text = path.read_text(encoding="utf-8")
        for raw_target in LINK_PATTERN.findall(text):
            target = raw_target.strip().strip("<>")
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            local = unquote(target.split("#", 1)[0])
            if local and not (path.parent / local).resolve().exists():
                errors.append(f"{path.relative_to(ROOT)}: missing link target {target}")
        if text.count("```mermaid") != len(MERMAID_PATTERN.findall(text)):
            errors.append(f"{path.relative_to(ROOT)}: unclosed Mermaid fence")
        for diagram in MERMAID_PATTERN.findall(text):
            first = next((line.strip() for line in diagram.splitlines() if line.strip()), "")
            if not first.startswith(MERMAID_STARTS):
                errors.append(
                    f"{path.relative_to(ROOT)}: unsupported Mermaid declaration {first!r}"
                )
    return errors


def main() -> None:
    errors = validate()
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"validated {len(markdown_files())} Markdown files")


if __name__ == "__main__":
    main()
