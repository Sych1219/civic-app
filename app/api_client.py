"""API client for triggering Singapore government data APIs."""

import httpx
from typing import Dict, Any
import logging


class APITrigger:
    """Trigger external API endpoints."""
    
    def __init__(self, base_url: str, timeout: int = 30):
        """
        Initialize the API trigger.
        
        Args:
            base_url: Base URL for the trigger API
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)
    
    async def trigger_endpoint(
        self, 
        endpoint_id: str, 
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Trigger the external API endpoint (async version).
        
        Args:
            endpoint_id: UUID of the endpoint to trigger
            payload: Request payload with queryParams and/or bodyParams
            
        Returns:
            API response data
            
        Raises:
            APIError: If the API call fails
        """
        url = f"{self.base_url}/api/v2/gov/apis/endpoints/{endpoint_id}/trigger"
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                self.logger.info(f"Triggering endpoint {endpoint_id}")
                self.logger.debug(f"Payload: {payload}")
                
                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json"
                    }
                )
                
                response.raise_for_status()
                
                result = response.json()
                
                # Check if the external API call was successful
                if result.get('status') == 'SUCCESS':
                    self.logger.info(f"Successfully triggered endpoint {endpoint_id}")
                    return result
                else:
                    self.logger.error(f"External API returned non-success status: {result.get('status')}")
                    raise APIError(f"API call failed: {result.get('message', 'Unknown error')}")
                    
            except httpx.HTTPStatusError as e:
                self.logger.error(f"HTTP error occurred: {e}")
                raise APIError(f"HTTP {e.response.status_code}: {e.response.text}")
            except httpx.RequestError as e:
                self.logger.error(f"Request error occurred: {e}")
                raise APIError(f"Request failed: {str(e)}")
    
    def trigger_endpoint_sync(
        self, 
        endpoint_id: str, 
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Trigger the external API endpoint (synchronous version).
        
        Args:
            endpoint_id: UUID of the endpoint to trigger
            payload: Request payload with queryParams and/or bodyParams
            
        Returns:
            API response data
            
        Raises:
            APIError: If the API call fails
        """
        import asyncio
        return asyncio.run(self.trigger_endpoint(endpoint_id, payload))


class APIError(Exception):
    """Custom exception for API errors."""
    pass
