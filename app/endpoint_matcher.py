"""Endpoint matcher for natural language queries using semantic search and LLM."""

from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
import json
from datetime import datetime
from typing import Dict, List
import os


class EndpointMatcher:
    """Optimized endpoint matcher using semantic search + LLM."""
    
    def __init__(self, schema_file_path: str):
        """
        Initialize the endpoint matcher.
        
        Args:
            schema_file_path: Path to the endpoint schema JSON file
        """
        self.llm = ChatOpenAI(model="gpt-4", temperature=0)
        self.embeddings = OpenAIEmbeddings()
        
        # Load schemas
        with open(schema_file_path, 'r') as f:
            schemas_data = json.load(f)['schemas']
        
        # Create optimized data structures
        self.endpoint_index = {}  # id -> full schema
        self.descriptions = []    # List of descriptions
        self.endpoint_ids = []    # Corresponding IDs
        
        for schema in schemas_data:
            endpoint_id = schema['id']
            description = schema['description']
            
            self.endpoint_index[endpoint_id] = schema
            self.descriptions.append(description)
            self.endpoint_ids.append(endpoint_id)
        
        # Pre-compute embeddings for all descriptions (one-time cost)
        print("Computing embeddings for endpoint descriptions...")
        self.description_embeddings = self.embeddings.embed_documents(self.descriptions)
        print(f"Loaded {len(self.endpoint_ids)} endpoints")
    
    def match_endpoint(self, user_query: str, top_k: int = 2) -> Dict:
        """
        Two-stage matching:
        1. Semantic search to find relevant endpoints (fast, no LLM)
        2. LLM parameter extraction (only for matched endpoints)
        
        Args:
            user_query: Natural language query from user
            top_k: Number of top endpoints to consider
            
        Returns:
            Dict containing endpoint_id, query_params, body_params, confidence, reasoning
        """
        
        # Stage 1: Find most relevant endpoints using embeddings
        relevant_endpoints = self._semantic_search(user_query, top_k=top_k)
        
        # Stage 2: Use LLM only for parameter extraction from relevant endpoints
        result = self._extract_parameters(user_query, relevant_endpoints)
        
        return result
    
    def _semantic_search(self, query: str, top_k: int = 2) -> List[Dict]:
        """Find top-k most relevant endpoints using semantic similarity."""
        
        # Embed the user query
        query_embedding = self.embeddings.embed_query(query)
        
        # Calculate cosine similarity
        similarities = cosine_similarity(
            [query_embedding],
            self.description_embeddings
        )[0]
        
        # Get top-k indices
        top_indices = np.argsort(similarities)[-top_k:][::-1]
        
        # Return relevant endpoints with similarity scores
        relevant = []
        for idx in top_indices:
            endpoint_id = self.endpoint_ids[idx]
            relevant.append({
                'endpoint': self.endpoint_index[endpoint_id],
                'similarity': float(similarities[idx])
            })
        
        return relevant
    
    def _extract_parameters(
        self, 
        user_query: str, 
        relevant_endpoints: List[Dict]
    ) -> Dict:
        """Use LLM to extract parameters from top matched endpoint(s)."""
        
        # Prepare compact schema info for LLM (only relevant endpoints)
        compact_schemas = []
        for item in relevant_endpoints:
            endpoint = item['endpoint']
            compact_schemas.append({
                'id': endpoint['id'],
                'description': endpoint['description'][:200],  # Truncate long descriptions
                'parameters': endpoint.get('parameters', [])
            })
        
        # Focused prompt with only relevant endpoints
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an API parameter extractor. 

Given a user query and 1-2 relevant API endpoints, determine:
1. Which endpoint best matches the user's intent
2. What parameters to extract from the query

Relevant endpoints:
{schemas}

Return JSON:
{{
    "endpoint_id": "UUID of best matching endpoint",
    "query_params": {{"param": "value"}},
    "body_params": {{"param": "value"}},
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation"
}}

Date/time rules:
- "today" = {current_date}
- "now" = {current_datetime}
- Parse relative dates (yesterday, last week, etc.)
- For time formats, use YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS
"""),
            ("human", "{query}")
        ])
        
        chain = prompt | self.llm | JsonOutputParser()
        
        result = chain.invoke({
            "schemas": json.dumps(compact_schemas, indent=2),
            "query": user_query,
            "current_date": datetime.now().strftime("%Y-%m-%d"),
            "current_datetime": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        })
        
        return result
