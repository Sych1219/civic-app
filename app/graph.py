"""
LangGraph workflow tying together doc fetching, prompt building, LLM drafting, and registry submission.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langsmith.run_helpers import traceable

from app.state import GovApiState, GraphConfig
from app.tools import (
    ContractValidationError,
    GovApiContract,
    GovApiRegistryClient,
    GovApiSchemaValidator,
    PromptBuilder,
    TextChunker,
    TextNormalizer,
)

logger = logging.getLogger(__name__)


def _with_error(state: GovApiState, message: str) -> GovApiState:
    errors = list(state.get("validation_errors", []))
    errors.append(message)
    return {"validation_errors": errors}


def _serialize_contract(contract: GovApiContract) -> Dict[str, Any]:
    return contract.model_dump(mode="python", exclude_none=True)


class GovApiGraphFactory:
    """
    Builds the LangGraph along with shared tool instances.
    """

    def __init__(
        self,
        *,
        normalizer: TextNormalizer | None = None,
        chunker: TextChunker | None = None,
        prompt_builder: PromptBuilder | None = None,
        validator: GovApiSchemaValidator | None = None,
        registry_client: GovApiRegistryClient | None = None,
        llm: ChatOpenAI | None = None,
    ):
        self.normalizer = normalizer or TextNormalizer()
        self.chunker = chunker or TextChunker()
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.validator = validator or GovApiSchemaValidator()
        self.registry_client = registry_client or GovApiRegistryClient()
        self.llm = llm or ChatOpenAI(model="gpt-4o-mini", temperature=0)
        self.parser = JsonOutputParser(pydantic_object=GovApiContract)
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "{system_message}"),
                ("human", "{human_message}"),
            ]
        )

    def compile(self):
        graph = StateGraph(GovApiState)
        graph.add_node("normalize_text", self._normalize_text)
        graph.add_node("chunk_context", self._chunk_context)
        graph.add_node("draft_contract", self._draft_contract)
        graph.add_node("validate_contract", self._validate_contract)
        graph.add_node("register_contract", self._register_contract)

        graph.set_entry_point("normalize_text")
        graph.add_edge("normalize_text", "chunk_context")
        graph.add_edge("chunk_context", "draft_contract")
        graph.add_edge("draft_contract", "validate_contract")
        graph.add_conditional_edges(
            "validate_contract",
            self._should_register,
            {
                "register": "register_contract",
                "complete": END,
            },
        )
        graph.add_edge("register_contract", END)
        return graph.compile()

    @traceable(name="gov.normalize_text")
    def _normalize_text(self, state: GovApiState) -> GovApiState:
        source_text = state.get("source_text")
        if not source_text:
            return _with_error(state, "source_text is required to start the workflow.")
        document = self.normalizer.normalize(source_text)
        metadata = dict(state.get("metadata", {}))
        metadata["source_chars"] = len(source_text)
        metadata["normalized_chars"] = len(document)
        return {"cleaned_document": document, "metadata": metadata}

    @traceable(name="gov.chunk_context")
    def _chunk_context(self, state: GovApiState) -> GovApiState:
        document = state.get("cleaned_document", "")
        chunks = self.chunker.split(document)
        if not chunks:
            return _with_error(state, "No usable content found in the documentation.")
        metadata = dict(state.get("metadata", {}))
        metadata["chunk_count"] = len(chunks)
        metadata["chunk_preview"] = [chunk[:200] for chunk in chunks[:2]]
        return {"context_chunks": chunks, "metadata": metadata}

    @traceable(name="gov.draft_contract")
    def _draft_contract(self, state: GovApiState) -> GovApiState:
        chunks = state.get("context_chunks", [])
        if not chunks:
            return _with_error(state, "Context chunks missing before LLM invocation.")
        system_message = "You convert government API documentation into registry payloads."
        human_message = self.prompt_builder.build(chunks)
        chain = self.prompt | self.llm | self.parser
        try:
            # contract: GovApiContract = chain.invoke(
            #     {"system_message": system_message, "human_message": human_message}
            # )
            raw = chain.invoke(
                {"system_message": system_message, "human_message": human_message}
            )
            contract = GovApiContract.model_validate(raw)
        except Exception as exc:
            logger.exception("LLM invocation failed")
            return _with_error(state, f"LLM invocation failed: {exc}")
        return {
            "llm_response": contract.model_dump_json(),
            "contract": _serialize_contract(contract),
        }

    @traceable(name="gov.validate_contract")
    def _validate_contract(self, state: GovApiState) -> GovApiState:
        if not state.get("contract"):
            return _with_error(state, "LLM contract missing; cannot validate.")
        try:
            contract = self.validator.validate(state["contract"])
        except ContractValidationError as exc:  # type: ignore[name-defined]
            return _with_error(
                state, f"Validation failed: {exc}"
            )
        return {"contract": _serialize_contract(contract)}

    def _should_register(self, state: GovApiState):
        if state.get("validation_errors"):
            return "complete"
        auto_register = state.get("auto_register", True)
        if not auto_register:
            return "complete"
        return "register"

    @traceable(name="gov.register_contract")
    def _register_contract(self, state: GovApiState, config: GraphConfig | None = None) -> GovApiState:
        config = config or {}
        dry_run = bool(config.get("dry_run", False))
        contract_payload = state.get("contract")
        dry_run = dry_run or not state.get("auto_register", True)
        if not contract_payload:
            return _with_error(state, "No contract payload available for registry submission.")
        try:
            contract = self.validator.validate(contract_payload)
        except ContractValidationError as exc:  # type: ignore[name-defined]
            return _with_error(state, f"Validation failed prior to submission: {exc}")
        try:
            response = self.registry_client.register(contract, dry_run=dry_run)
        except Exception as exc:
            logger.exception("Registry submission failed")
            return _with_error(state, f"Registry submission failed: {exc}")
        return {"registry_response": response}


def create_gov_api_graph() -> Any:
    """
    Convenience helper for callers to obtain the compiled graph.
    """

    return GovApiGraphFactory().compile()
