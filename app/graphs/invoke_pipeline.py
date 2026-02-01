"""
Modular invoke pipeline with pluggable stages for API discovery and execution.

Stages:
1. CatalogRetriever - Fetch available APIs (with caching)
2. ApiMatcher - Find best matching API(s) using various strategies
3. PayloadGenerator - Create API request payload from natural language
4. ApiExecutor - Execute the API call
5. ResponseFormatter - Format results for user

This pipeline replaces the traditional invoke path with a more scalable,
testable, and maintainable architecture.
"""
from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from langchain_community.vectorstores import FAISS
from langchain_core.output_parsers import JsonOutputParser
from langchain_openai import ChatOpenAI, OpenAIEmbeddings


# ============================================================================
# 1. CORE ABSTRACTIONS
# ============================================================================

class PipelineStage(ABC):
    """Base class for all pipeline stages"""
    
    @abstractmethod
    def execute(self, context: InvokeContext) -> InvokeContext:
        """Process the context and return updated context"""
        pass
    
    @abstractmethod
    def can_skip(self, context: InvokeContext) -> bool:
        """Check if this stage can be skipped based on context"""
        pass


@dataclass
class InvokeContext:
    """Shared context passed through pipeline stages"""
    
    # Input
    user_text: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Catalog stage
    catalog_query: Dict[str, Any] = field(default_factory=dict)
    catalog_response: Dict[str, Any] = field(default_factory=dict)
    
    # Matching stage
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    selected_api: Optional[Dict[str, Any]] = None
    match_scores: List[float] = field(default_factory=list)
    
    # Payload stage
    generated_payload: Optional[Dict[str, Any]] = None
    payload_validation_errors: List[str] = field(default_factory=list)
    
    # Execution stage
    api_response: Optional[Dict[str, Any]] = None
    execution_error: Optional[str] = None
    
    # Formatting stage
    formatted_result: Optional[str] = None
    
    # Pipeline control
    skip_stages: set = field(default_factory=set)
    retry_count: int = 0
    max_retries: int = 2


class MatchStrategy(Enum):
    """Different strategies for matching APIs to user requests"""
    KEYWORD = "keyword"  # Simple keyword matching
    SEMANTIC = "semantic"  # Vector similarity search
    HYBRID = "hybrid"  # Keyword + semantic combined
    LLM_RANKING = "llm_ranking"  # Full LLM comparison


# Example API catalog for testing and reference
# Maps API names to their IDs for quick lookup
# Future: This will be replaced by config center query
EXAMPLE_API_CATALOG = {
    "Taxi Availability": "25afbbc6-e03c-4244-81d3-b2af07df94e9",
    "Retrieve 24 Hour Weather Forecast": "77f5f3f0-6665-408d-ac9d-d0788ffc7ef0",
    "Get Rainfall Readings": "031be742-75b2-4ab2-ab38-7fbb4b9348df",
}


# ============================================================================
# 2. CATALOG RETRIEVAL STAGE
# ============================================================================

class CatalogRetriever(PipelineStage):
    """Retrieves APIs from catalog with intelligent caching"""
    
    def __init__(self, catalog_service, cache_ttl: int = 300):
        """
        Args:
            catalog_service: The API catalog service agent
            cache_ttl: Cache time-to-live in seconds (default: 5 minutes)
        """
        self.catalog_service = catalog_service
        self.cache_ttl = cache_ttl
        self._cache: Optional[Dict[str, Any]] = None
        self._cache_timestamp: float = 0
        self._schema_cache: Dict[str, Dict[str, Any]] = {}  # Cache for individual schemas
    
    def execute(self, context: InvokeContext) -> InvokeContext:
        """Fetch catalog with caching"""
        # Use cache if valid
        if self._is_cache_valid():
            context.catalog_response = self._cache
            context.metadata["cache_hit"] = True
            return context
        
        # Build query
        if not context.catalog_query:
            context.catalog_query = {"page": 0, "size": 100}
        
        # Fetch from service
        state = {"metadata": {"catalog_query": context.catalog_query}}
        result = self.catalog_service.run(state)
        
        context.catalog_response = result.get("catalog_response", {})
        
        # Update cache
        self._cache = context.catalog_response
        self._cache_timestamp = time.time()
        context.metadata["cache_hit"] = False
        
        return context
    
    def can_skip(self, context: InvokeContext) -> bool:
        """Skip if API ID already provided in metadata"""
        return bool(context.metadata.get("api_id"))
    
    def _is_cache_valid(self) -> bool:
        """Check if cache is still valid"""
        if not self._cache:
            return False
        age = time.time() - self._cache_timestamp
        return age < self.cache_ttl
    
    def fetch_schema_by_id(self, api_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch full API schema by ID from catalog service.
        
        This simulates: GET /api/catalog/{id}
        Returns full contract with baseUrl, headers, queryParams, bodyParams, etc.
        
        Args:
            api_id: The API identifier
            
        Returns:
            Full API schema or None if not found
        """
        # Check cache first
        if api_id in self._schema_cache:
            return self._schema_cache[api_id]
        
        try:
            # Call catalog service with specific ID query
            state = {
                "metadata": {
                    "catalog_query": {"id": api_id}
                }
            }
            result = self.catalog_service.run(state)
            response = result.get("catalog_response", {})
            
            # Extract schema from response
            schema = None
            if isinstance(response, dict):
                # Try different response formats
                items = response.get("items") or response.get("content") or response.get("data")
                if isinstance(items, list) and items:
                    schema = items[0]
                elif "id" in response:
                    # Single item response
                    schema = response
            
            if schema:
                self._schema_cache[api_id] = schema
            
            return schema
        except Exception as e:
            # Log error but don't crash
            import logging
            logging.error(f"Failed to fetch schema for API {api_id}: {e}")
            return None


# ============================================================================
# 3. API MATCHING STAGE (with multiple strategies)
# ============================================================================

class ApiMatcher(PipelineStage):
    """Matches user request to best API using configurable strategy"""
    
    def __init__(
        self,
        llm: ChatOpenAI,
        strategy: MatchStrategy = MatchStrategy.HYBRID,
        top_k: int = 5
    ):
        """
        Args:
            llm: Language model for ranking decisions
            strategy: Matching strategy to use
            top_k: Number of top candidates to consider
        """
        self.llm = llm
        self.strategy = strategy
        self.top_k = top_k
        self.embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
        self._vector_store: Optional[FAISS] = None
        self._last_catalog_hash: Optional[int] = None
    
    def execute(self, context: InvokeContext) -> InvokeContext:
        """Match user request to best API"""
        # Quick lookup: Check if user text mentions a known API name
        matched_id = self._check_example_catalog(context.user_text)
        if matched_id:
            context.metadata["api_id"] = matched_id
            context.metadata["match_source"] = "example_catalog"
            # Selected API will be populated by schema fetch
            return context
        
        # Extract candidates from catalog
        context.candidates = self._extract_candidates(context.catalog_response)
        
        if not context.candidates:
            context.execution_error = "No APIs found in catalog"
            return context
        
        # Apply matching strategy
        if self.strategy == MatchStrategy.KEYWORD:
            matches = self._keyword_match(context)
        elif self.strategy == MatchStrategy.SEMANTIC:
            matches = self._semantic_match(context)
        elif self.strategy == MatchStrategy.HYBRID:
            matches = self._hybrid_match(context)
        else:  # LLM_RANKING
            matches = self._llm_ranking_match(context)
        
        if matches:
            context.selected_api = matches[0]
            context.match_scores = [m.get("score", 0) for m in matches[:self.top_k]]
            context.metadata["match_strategy"] = self.strategy.value
        
        return context
    
    def can_skip(self, context: InvokeContext) -> bool:
        """Skip if API already selected"""
        return context.selected_api is not None
    
    def _extract_candidates(self, catalog_response: Dict) -> List[Dict[str, Any]]:
        """Extract candidates with full API contract details"""
        candidates = []
        
        def add_item(item: Dict[str, Any]):
            """Helper to add a single API to candidates"""
            api_id = item.get("id") or item.get("apiId")
            if not api_id:
                return
            candidates.append({
                "id": str(api_id),
                "name": item.get("name", ""),
                "description": item.get("description", ""),
                "method": item.get("httpMethod") or item.get("method", ""),
                "baseUrl": item.get("baseUrl", ""),
                "headers": item.get("headers", []),
                "queryParams": item.get("queryParams", []),
                "bodyParams": item.get("bodyParams", []),
            })
        
        # Handle various response formats
        if isinstance(catalog_response, dict):
            for key in ("content", "items", "results", "data", "apis"):
                items = catalog_response.get(key)
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict):
                            add_item(item)
                    if items:  # Found items in this key
                        return candidates
            # Try as single item
            add_item(catalog_response)
        
        return candidates
    
    def _keyword_match(self, context: InvokeContext) -> List[Dict]:
        """Fast keyword-based matching"""
        user_words = set(context.user_text.lower().split())
        matches = []
        
        for candidate in context.candidates:
            text = f"{candidate['name']} {candidate['description']}".lower()
            score = sum(1 for word in user_words if word in text)
            if score > 0:
                matches.append({**candidate, "score": score})
        
        return sorted(matches, key=lambda x: x["score"], reverse=True)
    
    def _semantic_match(self, context: InvokeContext) -> List[Dict]:
        """Vector similarity matching using embeddings"""
        # Build/update vector store
        catalog_hash = hash(str(context.candidates))
        if self._vector_store is None or catalog_hash != self._last_catalog_hash:
            texts = [
                f"{c['name']} - {c['description']} - {c['method']} {c['baseUrl']}"
                for c in context.candidates
            ]
            metadatas = [{"index": i} for i in range(len(context.candidates))]
            self._vector_store = FAISS.from_texts(texts, self.embeddings, metadatas=metadatas)
            self._last_catalog_hash = catalog_hash
        
        # Semantic search
        results = self._vector_store.similarity_search_with_score(
            context.user_text, k=self.top_k
        )
        
        matches = []
        for doc, score in results:
            idx = doc.metadata["index"]
            candidate = context.candidates[idx]
            # Invert distance to similarity (lower distance = higher similarity)
            matches.append({**candidate, "score": 1.0 - min(score, 1.0)})
        
        return matches
    
    def _hybrid_match(self, context: InvokeContext) -> List[Dict]:
        """Combine keyword + semantic matching for best results"""
        keyword_matches = {m["id"]: m for m in self._keyword_match(context)[:10]}
        semantic_matches = self._semantic_match(context)
        
        # Merge and boost items in both
        merged = {}
        for match in semantic_matches:
            api_id = match["id"]
            semantic_score = match["score"]
            keyword_score = keyword_matches.get(api_id, {}).get("score", 0)
            
            # Weighted combination (70% semantic, 30% keyword)
            combined_score = 0.7 * semantic_score + 0.3 * min(keyword_score / 10.0, 1.0)
            merged[api_id] = {**match, "score": combined_score}
        
        return sorted(merged.values(), key=lambda x: x["score"], reverse=True)
    
    def _llm_ranking_match(self, context: InvokeContext) -> List[Dict]:
        """Full LLM comparison (fallback for small catalogs)"""
        candidates = context.candidates[:]
        
        # For large catalogs, pre-filter with hybrid approach
        if len(candidates) > 20:
            candidates = self._hybrid_match(context)[:5]
        
        prompt = self._build_ranking_prompt(context.user_text, candidates)
        
        try:
            completion = self.llm.invoke(prompt)
            content = str(completion.content).strip()
            
            # Parse LLM choice - look for API ID in response
            for candidate in candidates:
                if candidate["id"] in content:
                    return [candidate]
            
            # Fallback to first candidate
            return candidates[:1] if candidates else []
        except Exception:
            # On error, return first candidate
            return candidates[:1] if candidates else []
    
    def _build_ranking_prompt(self, user_text: str, candidates: List[Dict]) -> str:
        """Build prompt for LLM ranking"""
        lines = [f"User request: {user_text}", "", "Available APIs:"]
        for idx, c in enumerate(candidates, 1):
            lines.append(
                f"{idx}. id={c['id']} name={c['name']} method={c['method']} "
                f"url={c['baseUrl']} description={c['description']}"
            )
        lines.append("")
        lines.append("Pick the best matching API. Respond with the id only.")
        return "\n".join(lines)
    
    def _check_example_catalog(self, user_text: str) -> Optional[str]:
        """Check if user text mentions a known API from EXAMPLE_API_CATALOG."""
        user_lower = user_text.lower()
        
        # Check each API name for matches
        for api_name, api_id in EXAMPLE_API_CATALOG.items():
            # Simple keyword matching
            api_keywords = api_name.lower().split()
            if any(keyword in user_lower for keyword in api_keywords if len(keyword) > 3):
                return api_id
        
        return None


# ============================================================================
# 4. PAYLOAD GENERATION STAGE
# ============================================================================

class PayloadGenerator(PipelineStage):
    """Generates API request payload from user intent"""
    
    def __init__(self, llm: ChatOpenAI, validate: bool = True):
        """
        Args:
            llm: Language model for payload generation
            validate: Whether to validate generated payload
        """
        self.llm = llm
        self.validate = validate
    
    def execute(self, context: InvokeContext) -> InvokeContext:
        """Generate payload from user text and API contract"""
        if not context.selected_api:
            context.execution_error = "No API selected for payload generation"
            return context
        
        # Generate payload
        payload = self._draft_payload(context.selected_api, context.user_text)
        
        if not payload:
            # Fallback to example defaults
            payload = {"useExampleDefaults": True}
        else:
            payload.setdefault("useExampleDefaults", True)
        
        context.generated_payload = payload
        
        # Validate if enabled
        if self.validate:
            errors = self._validate_payload(payload, context.selected_api)
            context.payload_validation_errors = errors
        
        return context
    
    def can_skip(self, context: InvokeContext) -> bool:
        """Skip if payload already generated"""
        return context.generated_payload is not None
    
    def _draft_payload(self, api: Dict[str, Any], user_text: str) -> Optional[Dict]:
        """Use LLM to draft payload from natural language using full API schema"""
        # Extract detailed schema information
        api_shape = {
            "name": api["name"],
            "description": api["description"],
            "method": api["method"],
            "baseUrl": api.get("baseUrl", ""),
            "headers": self._format_params(api.get("headers", [])),
            "queryParams": self._format_params(api.get("queryParams", [])),
            "bodyParams": self._format_params(api.get("bodyParams", [])),
        }
        
        prompt = (
            "Draft an API request payload based on the user's request.\n"
            "Use ONLY fields defined in the API contract.\n"
            "For nested parameters (type=OBJECT), include their children.\n"
            "Use exampleValue as guidance for format.\n"
            "Allowed top-level keys: query, body, headerOverrides, useExampleDefaults.\n"
            "Return compact JSON only.\n\n"
            f"User request: {user_text}\n\n"
            f"API contract:\n{json.dumps(api_shape, indent=2)}\n\n"
            "Payload JSON:"
        )
        
        try:
            completion = self.llm.invoke(prompt)
            return self._parse_json(str(completion.content))
        except Exception:
            return None
    
    def _validate_payload(self, payload: Dict, api: Dict) -> List[str]:
        """Validate payload against API contract"""
        errors = []
        
        # Check required query params
        required_query = [
            p["name"] for p in api.get("queryParams", [])
            if p.get("required") and not p.get("example")
        ]
        
        if required_query and not payload.get("useExampleDefaults"):
            provided = set(payload.get("query", {}).keys())
            missing = set(required_query) - provided
            if missing:
                errors.append(f"Missing required query params: {missing}")
        
        # Check required body params
        required_body = [
            p["name"] for p in api.get("bodyParams", [])
            if p.get("required") and not p.get("example")
        ]
        
        if required_body and not payload.get("useExampleDefaults"):
            provided = set(payload.get("body", {}).keys())
            missing = set(required_body) - provided
            if missing:
                errors.append(f"Missing required body params: {missing}")
        
        return errors
    
    def _format_params(self, params: List[Dict]) -> List[Dict]:
        """Format parameters with their details for LLM prompt."""
        formatted = []
        for param in params:
            param_info = {
                "name": param.get("key") or param.get("name", ""),
                "type": param.get("type", "STRING"),
                "description": param.get("description", ""),
                "required": param.get("required", False),
                "exampleValue": param.get("exampleValue") or param.get("example", "")
            }
            
            # Handle nested parameters (type=OBJECT)
            if param.get("children"):
                param_info["children"] = self._format_params(param["children"])
            
            formatted.append(param_info)
        return formatted
    
    @staticmethod
    def _parse_json(text: str) -> Optional[Dict]:
        """Extract JSON from LLM response (handles markdown blocks)"""
        if not text:
            return None
        
        # Try direct parse
        try:
            return json.loads(text)
        except:
            pass
        
        # Extract from code blocks
        if "```" in text:
            for block in text.split("```"):
                clean_block = block.strip()
                if clean_block.startswith("json"):
                    clean_block = clean_block[4:]
                try:
                    return json.loads(clean_block.strip())
                except:
                    continue
        
        # Extract {...} from anywhere in text
        if "{" in text:
            start = text.find("{")
            end = text.rfind("}")
            if end > start:
                try:
                    return json.loads(text[start:end+1])
                except:
                    pass
        
        return None


# ============================================================================
# 5. MAIN PIPELINE ORCHESTRATOR
# ============================================================================

class InvokePipeline:
    """Main pipeline that orchestrates all stages"""
    
    def __init__(
        self,
        catalog_service,
        trigger_agent,
        summary_agent,
        llm: Optional[ChatOpenAI] = None,
        match_strategy: MatchStrategy = MatchStrategy.HYBRID,
        cache_ttl: int = 300
    ):
        """
        Args:
            catalog_service: Service to fetch API catalog
            trigger_agent: Agent to execute API calls
            summary_agent: Agent to format API responses
            llm: Language model (defaults to gpt-4o-mini)
            match_strategy: Strategy for matching APIs
            cache_ttl: Catalog cache TTL in seconds
        """
        self.llm = llm or ChatOpenAI(model="gpt-4o-mini", temperature=0)
        
        # Store catalog retriever separately for schema fetching
        self.catalog_retriever = CatalogRetriever(catalog_service, cache_ttl=cache_ttl)
        
        # Build pipeline stages
        self.stages: List[PipelineStage] = [
            self.catalog_retriever,
            ApiMatcher(self.llm, strategy=match_strategy),
            PayloadGenerator(self.llm, validate=True),
        ]
        
        self.trigger_agent = trigger_agent
        self.summary_agent = summary_agent
    
    def execute(self, user_text: str, metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Execute the full pipeline.
        
        Args:
            user_text: User's natural language request
            metadata: Optional metadata (e.g., pre-selected API ID)
            
        Returns:
            Dictionary with success status, summary, and metadata
        """
        # Initialize context
        context = InvokeContext(
            user_text=user_text,
            metadata=metadata or {}
        )
        
        # Run through stages
        for stage in self.stages:
            if stage.can_skip(context):
                continue
            
            context = stage.execute(context)
            
            # Early exit on error
            if context.execution_error:
                return self._build_error_response(context)
        
        # If API ID is in metadata but no selected_api, fetch full schema
        if context.metadata.get("api_id") and not context.selected_api:
            api_id = context.metadata["api_id"]
            schema = self.catalog_retriever.fetch_schema_by_id(api_id)
            if schema:
                context.selected_api = {
                    "id": str(schema.get("id")),
                    "name": schema.get("name", ""),
                    "description": schema.get("description", ""),
                    "method": schema.get("httpMethod") or schema.get("method", ""),
                    "baseUrl": schema.get("baseUrl", ""),
                    "headers": schema.get("headers", []),
                    "queryParams": schema.get("queryParams", []),
                    "bodyParams": schema.get("bodyParams", []),
                }
                context.metadata["schema_fetched"] = True
            else:
                context.execution_error = f"Failed to fetch schema for API ID: {api_id}"
                return self._build_error_response(context)
        
        # Execute API call
        context = self._execute_api(context)
        
        if context.execution_error:
            return self._build_error_response(context)
        
        # Format response
        context = self._format_response(context)
        
        return self._build_success_response(context)
    
    def _execute_api(self, context: InvokeContext) -> InvokeContext:
        """Execute the API using trigger agent"""
        if not context.selected_api or not context.generated_payload:
            context.execution_error = "Missing API or payload for execution"
            return context
        
        trigger_input = {
            "api_id": context.selected_api["id"],
            "request": context.generated_payload
        }
        
        state = {"metadata": {"trigger": trigger_input}}
        
        try:
            result = self.trigger_agent.run(state)
            context.api_response = result.get("trigger_response")
        except Exception as e:
            context.execution_error = str(e)
        
        return context
    
    def _format_response(self, context: InvokeContext) -> InvokeContext:
        """Format the API response for user"""
        if context.execution_error:
            return context
        
        state = {"trigger_response": context.api_response}
        
        try:
            result = self.summary_agent.run(state)
            context.formatted_result = result.get("summary")
        except Exception as e:
            # Fallback to raw response
            context.formatted_result = json.dumps(context.api_response, indent=2)
        
        return context
    
    def _build_success_response(self, context: InvokeContext) -> Dict[str, Any]:
        """Build success response dictionary"""
        return {
            "success": True,
            "summary": context.formatted_result,
            "api_used": context.selected_api["name"] if context.selected_api else None,
            "match_score": context.match_scores[0] if context.match_scores else None,
            "metadata": {
                "strategy": context.metadata.get("match_strategy"),
                "cache_hit": context.metadata.get("cache_hit"),
                "retry_count": context.retry_count,
                "api_id": context.selected_api["id"] if context.selected_api else None,
            }
        }
    
    def _build_error_response(self, context: InvokeContext) -> Dict[str, Any]:
        """Build error response dictionary"""
        return {
            "success": False,
            "error": context.execution_error,
            "validation_errors": context.payload_validation_errors,
            "metadata": context.metadata
        }
