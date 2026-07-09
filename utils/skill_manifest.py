#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Skill manifest loader.

The manifest is a small machine-readable contract for each skill plugin. It
keeps runtime discovery, prompt generation, and interview-facing documentation
aligned without forcing every agent implementation to change at once.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


MANIFEST_FILE = "skill.yaml"
REQUIRED_FIELDS = {
    "name",
    "display_name",
    "description",
    "agent_name",
    "entrypoint",
    "timeout_seconds",
    "requires",
    "input_schema",
    "output_schema",
}


@dataclass(frozen=True)
class SkillManifest:
    name: str
    display_name: str
    description: str
    agent_name: str
    entrypoint: str
    timeout_seconds: int
    requires: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    triggers: List[str] = field(default_factory=list)
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    sop: List[str] = field(default_factory=list)
    path: Optional[Path] = None

    @property
    def entrypoint_path(self) -> Path:
        if self.path is None:
            return Path(self.entrypoint)
        return self.path.parent / self.entrypoint

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "agent_name": self.agent_name,
            "entrypoint": self.entrypoint,
            "timeout_seconds": self.timeout_seconds,
            "requires": list(self.requires),
            "permissions": list(self.permissions),
            "triggers": list(self.triggers),
            "input_schema": dict(self.input_schema),
            "output_schema": dict(self.output_schema),
            "sop": list(self.sop),
        }


class SkillManifestError(ValueError):
    """Raised when a skill manifest is missing required fields or invalid."""


class SkillManifestLoader:
    def __init__(self, skills_root: str | Path = ".claude/skills"):
        self.skills_root = Path(skills_root)

    def discover(self) -> Dict[str, SkillManifest]:
        manifests: Dict[str, SkillManifest] = {}
        if not self.skills_root.exists():
            return manifests

        for skill_dir in sorted(self.skills_root.iterdir()):
            if not skill_dir.is_dir():
                continue

            manifest_path = skill_dir / MANIFEST_FILE
            if not manifest_path.exists():
                continue

            manifest = self.load(manifest_path)
            manifests[manifest.name] = manifest

        return manifests

    def load(self, manifest_path: str | Path) -> SkillManifest:
        path = Path(manifest_path)
        with path.open("r", encoding="utf-8") as file:
            raw = yaml.safe_load(file) or {}

        self._validate(path, raw)

        manifest = SkillManifest(
            name=raw["name"],
            display_name=raw["display_name"],
            description=raw["description"],
            agent_name=raw["agent_name"],
            entrypoint=raw["entrypoint"],
            timeout_seconds=int(raw["timeout_seconds"]),
            requires=list(raw.get("requires", [])),
            permissions=list(raw.get("permissions", [])),
            triggers=list(raw.get("triggers", [])),
            input_schema=dict(raw.get("input_schema", {})),
            output_schema=dict(raw.get("output_schema", {})),
            sop=list(raw.get("sop", [])),
            path=path,
        )

        if not manifest.entrypoint_path.exists():
            raise SkillManifestError(
                f"{path}: entrypoint does not exist: {manifest.entrypoint}"
            )

        return manifest

    def _validate(self, path: Path, raw: Dict[str, Any]) -> None:
        missing = sorted(REQUIRED_FIELDS - set(raw.keys()))
        if missing:
            raise SkillManifestError(f"{path}: missing required fields: {', '.join(missing)}")

        if not isinstance(raw["timeout_seconds"], int) or raw["timeout_seconds"] <= 0:
            raise SkillManifestError(f"{path}: timeout_seconds must be a positive integer")

        for field_name in ("requires", "permissions", "triggers", "sop"):
            if field_name in raw and not isinstance(raw[field_name], list):
                raise SkillManifestError(f"{path}: {field_name} must be a list")

        for field_name in ("input_schema", "output_schema"):
            if not isinstance(raw[field_name], dict):
                raise SkillManifestError(f"{path}: {field_name} must be a mapping")
