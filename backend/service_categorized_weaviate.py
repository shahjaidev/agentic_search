"""Weaviate service for semantic search over categorized Polymarket markets."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import weaviate
from weaviate.classes.init import Auth

from backend.config import settings

logger = logging.getLogger(__name__)

# Global service instance for singleton pattern
_categorized_weaviate_service_instance = None


class CategorizedWeaviateSearchService:
    """Service for semantic search over categorized Polymarket markets using Weaviate."""
    
    def __init__(self, weaviate_url: str | None = None, weaviate_api_key: str | None = None):
        """Initialize Weaviate client connection."""
        self.weaviate_url = weaviate_url or getattr(settings, 'weaviate_url', None)
        self.weaviate_api_key = weaviate_api_key or getattr(settings, 'weaviate_api_key', None)
        self.collection_name = "CategorizedPolymarketMarkets"
        self.client = None
        self.enabled = bool(self.weaviate_url and self.weaviate_api_key)
        
        if self.enabled:
            try:
                self.client = weaviate.connect_to_weaviate_cloud(
                    cluster_url=self.weaviate_url,
                    auth_credentials=Auth.api_key(self.weaviate_api_key),
                )
                logger.info("Categorized Weaviate client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize categorized Weaviate client: {e}")
                self.enabled = False
                self.client = None
        else:
            logger.warning("Categorized Weaviate not configured - semantic search disabled")
    
    def search_markets(
        self, 
        query: str, 
        limit: int = 10,
        category_filter: Optional[str] = None,
        active_only: bool = True
    ) -> List[Dict[str, Any]]:
        """Search for relevant markets using semantic search on concatenated question + description."""
        if not self.enabled or not self.client:
            logger.warning("Categorized Weaviate search requested but service is not enabled")
            return []
        
        try:
            collection = self.client.collections.get(self.collection_name)
            
            # Perform semantic search on the searchable_text field (question + description)
            response = collection.query.near_text(
                query=query,
                limit=limit,
                return_metadata=weaviate.classes.query.MetadataQuery(distance=True)
            )
            
            results = []
            for obj in response.objects:
                # Apply filters after retrieval (since we can't use where clauses easily)
                if active_only and not obj.properties.get("active", True):
                    continue
                    
                if category_filter and obj.properties.get("category", "") != category_filter:
                    continue
                
                result = {
                    "market_id": obj.properties.get("market_id", ""),
                    "row_id": obj.properties.get("row_id", 0),
                    "question": obj.properties.get("question", ""),
                    "description": obj.properties.get("description", ""),
                    "category": obj.properties.get("category", ""),
                    "category_source": obj.properties.get("category_source", ""),
                    "tags": obj.properties.get("tags", []),
                    "active": obj.properties.get("active", False),
                    "closed": obj.properties.get("closed", False),
                    "archived": obj.properties.get("archived", False),
                    "distance": obj.metadata.distance if obj.metadata else None,
                    "relevance_score": 1 - obj.metadata.distance if obj.metadata and obj.metadata.distance else None
                }
                results.append(result)
            
            logger.info(f"Categorized Weaviate search for '{query}' returned {len(results)} results")
            return results
            
        except Exception as e:
            logger.error(f"Categorized Weaviate search error: {e}")
            return []
    
    def get_market_by_id(self, market_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific market by its ID."""
        if not self.enabled or not self.client:
            return None
        
        try:
            collection = self.client.collections.get(self.collection_name)
            
            # Get all objects and filter by market_id (since we can't use where easily)
            response = collection.query.fetch_objects(limit=1000)  # Adjust limit as needed
            
            for obj in response.objects:
                if obj.properties.get("market_id") == market_id:
                    return {
                        "market_id": obj.properties.get("market_id", ""),
                        "row_id": obj.properties.get("row_id", 0),
                        "question": obj.properties.get("question", ""),
                        "description": obj.properties.get("description", ""),
                        "category": obj.properties.get("category", ""),
                        "category_source": obj.properties.get("category_source", ""),
                        "tags": obj.properties.get("tags", []),
                        "active": obj.properties.get("active", False),
                        "closed": obj.properties.get("closed", False),
                        "archived": obj.properties.get("archived", False),
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"Error retrieving categorized market {market_id}: {e}")
            return None
    
    def get_categories(self) -> List[str]:
        """Get all available market categories."""
        if not self.enabled or not self.client:
            return []
        
        try:
            collection = self.client.collections.get(self.collection_name)
            
            # Get all objects and extract unique categories
            response = collection.query.fetch_objects(limit=10000)  # Adjust limit as needed
            
            categories = set()
            for obj in response.objects:
                category = obj.properties.get("category", "")
                if category:
                    categories.add(category)
            
            return sorted(list(categories))
            
        except Exception as e:
            logger.error(f"Error retrieving categorized categories: {e}")
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
                "inactive_markets": total_count - active_count,
                "collection_name": self.collection_name
            }
            
        except Exception as e:
            logger.error(f"Error retrieving categorized stats: {e}")
            return {"total_markets": 0, "active_markets": 0, "inactive_markets": 0}
    
    def health_check(self) -> Dict[str, Any]:
        """Check Weaviate connection health."""
        if not self.enabled:
            return {"status": "disabled", "reason": "Categorized Weaviate not configured"}
        
        try:
            if self.client and self.client.is_ready():
                stats = self.get_stats()
                return {
                    "status": "healthy",
                    "weaviate_connected": True,
                    "stats": stats
                }
            else:
                return {"status": "unhealthy", "reason": "Categorized Weaviate connection failed"}
        except Exception as e:
            return {"status": "unhealthy", "reason": str(e)}
    
    def close(self):
        """Close the Weaviate client connection."""
        if self.client:
            try:
                self.client.close()
                logger.info("Categorized Weaviate client connection closed")
                self.client = None
            except Exception as e:
                logger.error(f"Error closing categorized Weaviate client: {e}")
    
    def __del__(self):
        """Ensure connection is closed when object is destroyed."""
        self.close()


def get_categorized_weaviate_service() -> CategorizedWeaviateSearchService:
    """Get singleton instance of CategorizedWeaviateSearchService."""
    global _categorized_weaviate_service_instance
    if _categorized_weaviate_service_instance is None:
        _categorized_weaviate_service_instance = CategorizedWeaviateSearchService()
    return _categorized_weaviate_service_instance
