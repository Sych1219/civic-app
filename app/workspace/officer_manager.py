from pathlib import Path
from typing import Optional

import yaml

_OFFICERS_DIR = Path(__file__).parent.parent.parent / "workspace" / "officers"


class OfficerProfileManager:
    def load_index(self, officer_id: Optional[str]) -> str:
        """Return lightweight index (frontmatter only) for System Prompt injection."""
        if not officer_id:
            return ""
        path = _OFFICERS_DIR / f"{officer_id}.md"
        if not path.exists():
            return ""
        text = path.read_text(encoding="utf-8")
        parts = text.split("---", 2)
        if len(parts) < 3:
            return ""
        try:
            meta = yaml.safe_load(parts[1])
        except Exception:
            return ""
        return (
            f"- officer_id: {meta.get('officer_id', officer_id)}\n"
            f"- name: {meta.get('name', '')}\n"
            f"- role: {meta.get('role', '')}\n"
            f'→ Full profile: call read_file("workspace/officers/{officer_id}.md")'
        )


officer_manager = OfficerProfileManager()
