"""
Shared prompt snippets and guardrails.
"""

GUARDRAILS = (
    "You convert government API documentation into registry payloads. "
    "Follow the schema exactly. Use HTTPS base URLs, uppercase HTTP verbs, "
    "include Accept headers when the docs specify response types, "
    "and omit headers when the docs only show placeholder secrets such as YOUR_API_KEY."
)
