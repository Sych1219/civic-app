import importlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class DomainDef:
    name: str
    description: str
    handler: Callable
    supports_request_id: bool = False
    system_notes: str = ""
    streaming_handler: Optional[Callable] = field(default=None)


def _import_fn(dotted_path: str) -> Callable:
    module_path, func_name = dotted_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, func_name)


def scan_domains(domains_dir: Path) -> dict[str, DomainDef]:
    domains: dict[str, DomainDef] = {}
    for md_file in sorted(domains_dir.glob("*/DOMAIN.md")):
        try:
            text = md_file.read_text(encoding="utf-8")
            parts = text.split("---", 2)
            if len(parts) < 3:
                logger.warning("[scanner] %s missing frontmatter, skipping", md_file)
                continue
            _, fm, body = parts
            meta = yaml.safe_load(fm)

            handler_fn = _import_fn(meta["handler"])

            streaming_handler_fn = None
            if "streaming_handler" in meta:
                try:
                    streaming_handler_fn = _import_fn(meta["streaming_handler"])
                except Exception as exc:
                    logger.warning("[scanner] streaming_handler import failed for %s: %s", md_file, exc)

            domains[meta["name"]] = DomainDef(
                name=meta["name"],
                description=meta["description"],
                handler=handler_fn,
                supports_request_id=meta.get("supports_request_id", False),
                system_notes=body.strip(),
                streaming_handler=streaming_handler_fn,
            )
            logger.info("[scanner] loaded domain: %s", meta["name"])
        except Exception as exc:
            logger.warning("[scanner] failed to load %s: %s", md_file, exc)
    return domains
