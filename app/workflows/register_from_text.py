"""
Workflow to turn raw API documentation text into a registry submission.

This module provides functionality to:
1. Parse government API documentation text
2. Convert it into a structured API contract using LLM
3. Validate the contract against the schema
4. Register the contract with the API registry
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from dotenv import load_dotenv
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from prompt_toolkit import prompt

from app.shared.clients import GovApiRegistryClient
from app.shared.models import GovApiContract

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)

# LLM instructions for converting API documentation
LLM_GUARDRAILS = (
    "You convert government API documentation into registry payloads. "
    "Follow the schema exactly. Use HTTPS base URLs, uppercase HTTP verbs, "
    "include Accept headers when the docs specify response types, "
    "and omit headers when the docs only show placeholder secrets such as YOUR_API_KEY."
)

# Template for prompting the LLM with documentation
LLM_PROMPT_TEMPLATE = """{guardrails}

Return ONLY valid JSON that matches the schema and formatting instructions.

Schema:
{schema}

Documentation:
{source_text}

{format_instructions}
"""


def _convert_to_contract(llm_output: Any) -> GovApiContract:
    """
    Convert LLM output to a validated GovApiContract.
    
    Args:
        llm_output: The parsed output from the LLM
        
    Returns:
        A validated GovApiContract instance
    """
    if isinstance(llm_output, GovApiContract):
        return llm_output
    return GovApiContract.model_validate(llm_output)


def _create_error_response(error_message: str, llm_response: str = None) -> str:
    """
    Create a standardized error response in JSON format.
    
    Args:
        error_message: The error message to include
        llm_response: Optional LLM response to include in the error
        
    Returns:
        JSON string with the error details
    """
    error_data: Dict[str, Any] = {"validation_errors": [error_message]}
    if llm_response:
        error_data["llm_response"] = llm_response
    return json.dumps(error_data, indent=2)


def _parse_documentation_with_llm(documentation_text: str) -> tuple[Any | None, str | None]:
    """
    Use LLM to parse API documentation into a structured format.
    
    Args:
        documentation_text: The cleaned API documentation text
        
    Returns:
        A tuple of (parsed_output, error_message). If successful, error_message is None.
    """
    prompt = PromptTemplate.from_template(LLM_PROMPT_TEMPLATE)
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    parser = JsonOutputParser(pydantic_object=GovApiContract)
    schema_json = json.dumps(GovApiContract.model_json_schema(), indent=2)

    chain = prompt | llm | parser
    
    try:
        parsed_output = chain.invoke(
            {
                "guardrails": LLM_GUARDRAILS,
                "schema": schema_json,
                "source_text": documentation_text,
                "format_instructions": parser.get_format_instructions(),
            }
        )
        return parsed_output, None
    except Exception as exc:
        logger.exception("LLM invocation failed")
        return None, f"LLM invocation failed: {exc}"


def _submit_to_registry(contract: GovApiContract) -> str | None:
    """
    Submit the validated contract to the API registry.
    
    Args:
        contract: The validated API contract to register
        
    Returns:
        Error message if submission failed, None if successful
    """
    client = GovApiRegistryClient()
    try:
        client.register(contract, dry_run=False)
        return None
    except Exception as exc:
        logger.exception("Registry submission failed")
        return f"Registry submission failed: {exc}"


def register_from_text(source_text: str) -> str:
    """
    Generate a Gov API contract from pasted documentation text and register it.
    
    This function orchestrates the following steps:
    1. Validates and cleans the input text
    2. Uses LLM to parse documentation into structured contract
    3. Validates the contract against the schema
    4. Submits the contract to the API registry
    
    Args:
        source_text: Raw API documentation text
        
    Returns:
        JSON string containing either:
        - The registered contract (on success)
        - Error details with validation_errors array (on failure)
    """
    # Step 1: Validate input
    cleaned_text = (source_text or "").strip()
    if not cleaned_text:
        return _create_error_response("source_text is required to register an API.")

    # Step 2: Parse documentation with LLM
    llm_output, error = _parse_documentation_with_llm(cleaned_text)
    if error:
        return _create_error_response(error)

    # Step 3: Convert and validate contract
    try:
        contract = _convert_to_contract(llm_output)
    except Exception as exc:
        logger.exception("LLM output failed validation")
        llm_response_json = json.dumps(llm_output, indent=2, default=str)
        return _create_error_response(
            f"LLM output failed validation: {exc}",
            llm_response=llm_response_json
        )

    # Step 4: Submit to registry
    submission_error = _submit_to_registry(contract)
    if submission_error:
        return _create_error_response(
            submission_error,
            llm_response=contract.model_dump_json()
        )

    # Success: return the registered contract
    return contract.model_dump_json(indent=2, exclude_none=True)
