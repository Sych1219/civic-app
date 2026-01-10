"""
Component to draft a Gov API contract using an LLM.
"""
from __future__ import annotations

import json
import logging
from typing import Iterable

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.shared.models import GovApiContract
from app.shared.prompts import GUARDRAILS
from app.shared.state import GovApiState

logger = logging.getLogger(__name__)


class PromptBuilder:
    """
    Generates prompts for the LLM using system + human message templates.
    """

    def __init__(self, guardrails: str = GUARDRAILS):
        self.guardrails = guardrails

    def build(self, chunks: Iterable[str]) -> str:
        snippet = "\n\n---\n\n".join(chunks)
        schema = json.dumps(GovApiContract.model_json_schema(), indent=2)
        instructions = (
            "Respond with JSON that strictly matches the following schema. "
            "Prefer the endpoint that best matches the operator intent. "
            "If information is missing, make explicit TODO notes in the description field."
        )
        return f"{self.guardrails}\n\nSchema:\n{schema}\n\nDocumentation Snippets:\n{snippet}\n\n{instructions}"


class DraftComponent:
    def __init__(
        self,
        *,
        prompt_builder: PromptBuilder | None = None,
        llm: ChatOpenAI | None = None,
    ):
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.llm = llm or ChatOpenAI(model="gpt-4o-mini", temperature=0)
        self.parser = JsonOutputParser(pydantic_object=GovApiContract)
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "{system_message}"),
                ("human", "{human_message}"),
            ]
        )

    def run(self, state: GovApiState) -> GovApiState:
        chunks = state.get("context_chunks", [])
        if not chunks:
            errors = list(state.get("validation_errors", []))
            errors.append("Context chunks missing before LLM invocation.")
            return {"validation_errors": errors}

        human_message = self.prompt_builder.build(chunks)
        chain = self.prompt | self.llm | self.parser
        try:
            raw = chain.invoke(
                {"system_message": self.prompt_builder.guardrails, "human_message": human_message}
            )
            contract = GovApiContract.model_validate(raw)
        except Exception as exc:
            logger.exception("LLM invocation failed")
            errors = list(state.get("validation_errors", []))
            errors.append(f"LLM invocation failed: {exc}")
            return {"validation_errors": errors}

        return {
            "llm_response": contract.model_dump_json(),
            "contract": contract.model_dump(mode="python", exclude_none=True),
        }
