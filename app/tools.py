"""
Compatibility layer: re-export shared models/clients/components for legacy imports.
"""
from app.components.draft import PromptBuilder  # noqa: F401
from app.shared.clients import GovApiRegistryClient  # noqa: F401
from app.shared.models import (  # noqa: F401
    ALLOWED_METHODS,
    ALLOWED_PARAM_TYPES,
    ContractValidationError,
    GovApiContract,
    GovApiSchemaValidator,
    Header,
    Parameter,
)
from app.shared.text import TextChunker, TextNormalizer  # noqa: F401
