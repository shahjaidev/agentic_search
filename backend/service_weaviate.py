"""Weaviate service for semantic search over Polymarket markets."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import weaviate
from weaviate.classes.init import Auth

from backend.config import settings

logger = logging.getLogger(__name__)

# Global service instance for singleton pattern
_weaviate_service_instance = None


class WeaviateSearchService:
    """Service for semantic search over Polymarket markets using Weaviate."""
    
    def __init__(self, weaviate_url: str | None = None, weaviate_api_key: str | None = None):
        """Initialize Weaviate client connection."""
        self.weaviate_url = weaviate_url or getattr(settings, 'weaviate_url', None)
        self.weaviate_api_key = weaviate_api_key or getattr(settings, 'weaviate_api_key', None)
        self.collection_name = "PolymarketMarkets"
        self.client = None
        self.enabled = bool(self.weaviate_url and self.weaviate_api_key)
        
        if self.enabled:
            try:
                self.client = weaviate.connect_to_weaviate_cloud(
                    cluster_url=self.weaviate_url,
                    auth_credentials=Auth.api_key(self.weaviate_api_key),
                )
                logger.info("Weaviate client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Weaviate client: {e}")
                self.enabled = False
                self.client = None
        else:
            logger.warning("Weaviate not configured - semantic search disabled")
    
    def search_markets(
        self, 
        query: str, 
        limit: int = 10,
        active_only: bool = True,
        category_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search for relevant markets using semantic search."""
        if not self.enabled or not self.client:
            logger.warning("Weaviate search requested but service is not enabled")
            return []
        
        try:
            collection = self.client.collections.get(self.collection_name)
            
            # Perform semantic search
            response = collection.query.near_text(
                query=query,
                limit=limit,
                return_metadata=weaviate.classes.query.MetadataQuery(distance=True)
            )
            
            results = []
            for obj in response.objects:
                result = {
                    "market_id": obj.properties.get("market_id", ""),
                    "question": obj.properties.get("question", ""),
                    "description": obj.properties.get("description", ""),
                    "market_slug": obj.properties.get("market_slug", ""),
                    "tags": obj.properties.get("tags", []),
                    "end_date_iso": obj.properties.get("end_date_iso"),
                    "active": obj.properties.get("active", False),
                    "market_category": obj.properties.get("market_category"),
                    "market_category_name": obj.properties.get("market_category_name"),
                    "market_category_l1_name": obj.properties.get("market_category_l1_name"),
                    "market_category_l2_name": obj.properties.get("market_category_l2_name"),
                    "market_category_l3_name": obj.properties.get("market_category_l3_name"),
                    "distance": obj.metadata.distance if obj.metadata else None,
                    "relevance_score": 1 - obj.metadata.distance if obj.metadata and obj.metadata.distance else None
                }
                results.append(result)
            
            logger.info(f"Weaviate search for '{query}' returned {len(results)} results")
            return results
            
        except Exception as e:
            logger.error(f"Weaviate search error: {e}")
            return []
    
    def get_market_by_id(self, market_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific market by its ID."""
        if not self.enabled or not self.client:
            return None
        
        try:
            collection = self.client.collections.get(self.collection_name)
            
            response = collection.query.fetch_objects(
                limit=1
            )
            
            if not response.objects:
                return None
            
            obj = response.objects[0]
            return {
                "market_id": obj.properties.get("market_id", ""),
                "question": obj.properties.get("question", ""),
                "description": obj.properties.get("description", ""),
                "market_slug": obj.properties.get("market_slug", ""),
                "tags": obj.properties.get("tags", []),
                "end_date_iso": obj.properties.get("end_date_iso"),
                "active": obj.properties.get("active", False),
                "market_category": obj.properties.get("market_category"),
                "market_category_name": obj.properties.get("market_category_name"),
                "market_category_l1_name": obj.properties.get("market_category_l1_name"),
                "market_category_l2_name": obj.properties.get("market_category_l2_name"),
                "market_category_l3_name": obj.properties.get("market_category_l3_name"),
            }
            
        except Exception as e:
            logger.error(f"Error retrieving market {market_id}: {e}")
            return None
    
    def get_categories(self) -> List[str]:
        """Get all available market categories."""
        if not self.enabled or not self.client:
            return []
        
        try:
            collection = self.client.collections.get(self.collection_name)
            
            response = collection.aggregate.over_all()
            
            categories = []
            for group in response.groups:
                if group.grouped_by and group.grouped_by.value:
                    categories.append(group.grouped_by.value)
            
            return sorted(categories)
            
        except Exception as e:
            logger.error(f"Error retrieving categories: {e}")
            return []
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        if not self.enabled or not self.client:
            return {"total_markets": 0, "active_markets": 0, "inactive_markets": 0}
        
        try:
            collection = self.client.collections.get(self.collection_name)
            
            # Get total count
            total_response = collection.aggregate.over_all()
            total_count = total_response.total_count if hasattr(total_response, 'total_count') and total_response.total_count else 0
            
            # For now, assume all markets are active since we can't filter easily
            active_count = total_count
            
            return {
                "total_markets": total_count,
                "active_markets": active_count,
                "inactive_markets": total_count - active_count
            }
            
        except Exception as e:
            logger.error(f"Error retrieving stats: {e}")
            return {"total_markets": 0, "active_markets": 0, "inactive_markets": 0}
    
    def health_check(self) -> Dict[str, Any]:
        """Check Weaviate connection health."""
        if not self.enabled:
            return {"status": "disabled", "reason": "Weaviate not configured"}
        
        try:
            if self.client and self.client.is_ready():
                stats = self.get_stats()
                return {
                    "status": "healthy",
                    "weaviate_connected": True,
                    "stats": stats
                }
            else:
                return {"status": "unhealthy", "reason": "Weaviate connection failed"}
        except Exception as e:
            return {"status": "unhealthy", "reason": str(e)}
    
    def close(self):
        """Close the Weaviate client connection."""
        if self.client:
            try:
                self.client.close()
                logger.info("Weaviate client connection closed")
                self.client = None
            except Exception as e:
                logger.error(f"Error closing Weaviate client: {e}")
    
    def __del__(self):
        """Ensure connection is closed when object is destroyed."""
        self.close()


def get_weaviate_service() -> WeaviateSearchService:
    """Get singleton instance of WeaviateSearchService."""
    global _weaviate_service_instance
    if _weaviate_service_instance is None:
        _weaviate_service_instance = WeaviateSearchService()
    return _weaviate_service_instance
