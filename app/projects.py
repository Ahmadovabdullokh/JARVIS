"""Определение проекта, названного пользователем в свободной фразе.

JARVIS по умолчанию работал со своей папкой (BASE_DIR). Теперь имя
проекта («python project 10», «PythonProject10», absolute path)
извлекается из запроса и используется как целевой проект.
"""

import difflib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

_NAME_RE = re.compile(
    r"(?i)\b(?:"
    r"python[\s_-]*project|pythonproject|"
    r"питон[\s_-]*проект|пайтон[\s_-]*проект|"
    r"проект|project"
    r")\s*[-_#№]?\s*(\d{1,3})\b"
)
_ABS_PATH_RE = re.compile(r"""(?i)\b[a-z]:[\\/][^\s"'<>|]+""")
_HOME_PATH_RE = re.compile(r"""(?:~|%USERPROFILE%)[\\/][^\s"'<>|]+""")
_QUOTED_RE = re.compile(r"""["']([^"']+[\\/][^"']+)["']""")


@dataclass
class ProjectResolution:
    status: str = "none"
    path: Path | None = None
    name: str = ""
    candidates: list[str] = field(default_factory=list)
    searched: str = ""


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9а-я]+", "", str(name or "").lower())


def _projects_home(projects_home=None) -> Path:
    if projects_home is not None:
        return Path(projects_home)
    return Path.home() / "PycharmProjects"


def _extract_candidates(text: str) -> list[str]:
    raw = str(text or "")
    candidates: list[str] = []
    for match in _QUOTED_RE.finditer(raw):
        candidates.append(match.group(1).strip())
    for match in _ABS_PATH_RE.finditer(raw):
        candidates.append(match.group(0).strip())
    for match in _HOME_PATH_RE.finditer(raw):
        candidates.append(match.group(0).strip())
    for match in _NAME_RE.finditer(raw):
        candidates.append(f"PythonProject{match.group(1)}")
    unique: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _resolve_one(candidate, code_config, projects_home):
    text = str(candidate or "").strip().strip('"').strip("'")
    if not text:
        return None
    expanded = Path(os.path.expandvars(os.path.expanduser(text)))
    options: list[Path] = []
    if expanded.is_absolute():
        options.append(expanded)
    options.extend(
        [
            projects_home / expanded,
            Path.cwd() / expanded,
            Path.home() / expanded,
        ]
    )
    configured = str(
        code_config.get("project") or ""
    ).strip() if isinstance(code_config, dict) else ""
    if configured:
        base = Path(os.path.expandvars(os.path.expanduser(configured)))
        options.extend([base.parent / expanded, base / expanded])

    target_norm = _normalize(expanded.name or text)
    for option in options:
        try:
            if option.exists():
                resolved = option.resolve()
                return resolved if resolved.is_dir() else resolved.parent
        except OSError:
            continue
        try:
            siblings = [p for p in option.parent.iterdir() if p.is_dir()]
        except OSError:
            siblings = []
        for sibling in siblings:
            if _normalize(sibling.name) == target_norm:
                try:
                    return sibling.resolve()
                except OSError:
                    return sibling
    return None


def _similar(candidate, projects_home, limit=5):
    try:
        names = [
            path.name for path in projects_home.iterdir() if path.is_dir()
        ]
    except OSError:
        return []
    mapping: dict[str, list[str]] = {}
    for name in names:
        mapping.setdefault(_normalize(name), []).append(name)
    target = _normalize(candidate)
    matches = difflib.get_close_matches(
        target, list(mapping), n=limit, cutoff=0.6
    )
    hints: list[str] = []
    for match in matches:
        hints.extend(mapping.get(match, []))
    if not hints:
        hints = [
            name
            for name in names
            if target and target in _normalize(name)
        ][:limit]
    return hints[:limit]


def resolve_project_reference(text, code_config=None, projects_home=None):
    code_config = code_config if isinstance(code_config, dict) else {}
    home = _projects_home(projects_home)
    candidates = _extract_candidates(text)
    if not candidates:
        return ProjectResolution(status="none", searched=str(home))

    for candidate in candidates:
        found = _resolve_one(candidate, code_config, home)
        if found is not None:
            return ProjectResolution(
                status="found",
                path=found,
                name=found.name,
                searched=str(home),
            )

    return ProjectResolution(
        status="not_found",
        name=candidates[0],
        candidates=_similar(candidates[0], home),
        searched=str(home),
    )


def format_project_error(resolution: ProjectResolution) -> str:
    name = resolution.name or "указанный проект"
    text = f"Проект «{name}» не найден."
    if resolution.candidates:
        text += " Похожие: " + ", ".join(resolution.candidates) + "."
    if resolution.searched:
        text += f" Искал в: {resolution.searched}."
    text += " Уточните имя или путь проекта."
    return text
