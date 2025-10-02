#!/usr/bin/env python3
"""
FastAPI service for searching Polymarket markets using Weaviate vector database.

This API provides semantic search capabilities over Polymarket prediction markets,
allowing users to find relevant markets based on natural language queries.

Usage:
    python weaviate_search_api.py
    # API will be available at http://localhost:8000
"""

import os
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
import weaviate
from weaviate.classes.init import Auth
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI(
    title="Polymarket Search API",
    description="Semantic search API for Polymarket prediction markets",
    version="1.0.0"
)

class MarketSearchResult(BaseModel):
    """Model for market search results."""
    market_id: str
    question: str
    description: str
    market_slug: str
    tags: List[str]
    end_date_iso: Optional[str]
    active: bool
    market_category: Optional[str]
    market_category_name: Optional[str]
    distance: Optional[float]

class SearchResponse(BaseModel):
    """Model for search API response."""
    query: str
    results: List[MarketSearchResult]
    total_results: int
    limit: int

class WeaviateSearchService:
    """Service class for Weaviate operations."""
    
    def __init__(self, weaviate_url: str, weaviate_api_key: str):
        """Initialize Weaviate client connection."""
        self.client = weaviate.connect_to_weaviate_cloud(
            cluster_url=weaviate_url,
            auth_credentials=Auth.api_key(weaviate_api_key),
        )
        self.collection_name = "PolymarketMarkets"
    
    def search_markets(
        self, 
        query: str, 
        limit: int = 10,
        active_only: bool = True,
        category_filter: Optional[str] = None
    ) -> List[MarketSearchResult]:
        """Search for relevant markets using semantic search."""
        collection = self.client.collections.get(self.collection_name)
        
        # Build where filter
        where_filter = None
        if active_only:
            where_filter = weaviate.classes.query.Filter.by_property("active").equal(True)
        
        if category_filter:
            category_condition = weaviate.classes.query.Filter.by_property("market_category_name").equal(category_filter)
            if where_filter:
                where_filter = where_filter & category_condition
            else:
                where_filter = category_condition
        
        # Perform semantic search
        response = collection.query.near_text(
            query=query,
            limit=limit,
            where=where_filter,
            return_metadata=weaviate.classes.query.MetadataQuery(distance=True)
        )
        
        results = []
        for obj in response.objects:
            result = MarketSearchResult(
                market_id=obj.properties.get("market_id", ""),
                question=obj.properties.get("question", ""),
                description=obj.properties.get("description", ""),
                market_slug=obj.properties.get("market_slug", ""),
                tags=obj.properties.get("tags", []),
                end_date_iso=obj.properties.get("end_date_iso"),
                active=obj.properties.get("active", False),
                market_category=obj.properties.get("market_category"),
                market_category_name=obj.properties.get("market_category_name"),
                distance=obj.metadata.distance if obj.metadata else None
            )
            results.append(result)
        
        return results
    
    def get_market_by_id(self, market_id: str) -> Optional[MarketSearchResult]:
        """Get a specific market by its ID."""
        collection = self.client.collections.get(self.collection_name)
        
        response = collection.query.fetch_objects(
            where=weaviate.classes.query.Filter.by_property("market_id").equal(market_id),
            limit=1
        )
        
        if not response.objects:
            return None
        
        obj = response.objects[0]
        return MarketSearchResult(
            market_id=obj.properties.get("market_id", ""),
            question=obj.properties.get("question", ""),
            description=obj.properties.get("description", ""),
            market_slug=obj.properties.get("market_slug", ""),
            tags=obj.properties.get("tags", []),
            end_date_iso=obj.properties.get("end_date_iso"),
            active=obj.properties.get("active", False),
            market_category=obj.properties.get("market_category"),
            market_category_name=obj.properties.get("market_category_name"),
            distance=None
        )
    
    def get_categories(self) -> List[str]:
        """Get all available market categories."""
        collection = self.client.collections.get(self.collection_name)
        
        response = collection.aggregate.over_all(
            group_by=weaviate.classes.query.GroupBy.by_property("market_category_name")
        )
        
        categories = []
        for group in response.groups:
            if group.grouped_by and group.grouped_by.value:
                categories.append(group.grouped_by.value)
        
        return sorted(categories)
    
    def close(self):
        """Close the Weaviate client connection."""
        self.client.close()

# Initialize search service
weaviate_url = os.getenv("WEAVIATE_URL")
weaviate_api_key = os.getenv("WEAVIATE_API_KEY")

if not weaviate_url or not weaviate_api_key:
    raise ValueError("WEAVIATE_URL and WEAVIATE_API_KEY environment variables must be set")

search_service = WeaviateSearchService(weaviate_url, weaviate_api_key)

@app.get("/", response_model=Dict[str, str])
async def root():
    """Root endpoint with API information."""
    return {
        "message": "Polymarket Search API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health"
    }

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        # Test Weaviate connection
        collection = search_service.client.collections.get(search_service.collection_name)
        return {"status": "healthy", "weaviate_connected": True}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

@app.get("/search", response_model=SearchResponse)
async def search_markets(
    q: str = Query(..., description="Search query"),
    limit: int = Query(10, ge=1, le=100, description="Maximum number of results"),
    active_only: bool = Query(True, description="Only return active markets"),
    category: Optional[str] = Query(None, description="Filter by market category")
):
    """
    Search for relevant Polymarket markets using semantic search.
    
    - **q**: Natural language search query
    - **limit**: Maximum number of results to return (1-100)
    - **active_only**: Whether to only return active markets
    - **category**: Optional category filter
    """
    try:
        results = search_service.search_markets(
            query=q,
            limit=limit,
            active_only=active_only,
            category_filter=category
        )
        
        return SearchResponse(
            query=q,
            results=results,
            total_results=len(results),
            limit=limit
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search error: {str(e)}")

@app.get("/market/{market_id}", response_model=MarketSearchResult)
async def get_market(market_id: str):
    """Get a specific market by its ID."""
    try:
        market = search_service.get_market_by_id(market_id)
        if not market:
            raise HTTPException(status_code=404, detail="Market not found")
        return market
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving market: {str(e)}")

@app.get("/categories", response_model=List[str])
async def get_categories():
    """Get all available market categories."""
    try:
        categories = search_service.get_categories()
        return categories
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving categories: {str(e)}")

@app.get("/stats")
async def get_stats():
    """Get database statistics."""
    try:
        collection = search_service.client.collections.get(search_service.collection_name)
        
        # Get total count
        total_response = collection.aggregate.over_all(total_count=True)
        total_count = total_response.total_count if total_response.total_count else 0
        
        # Get active count
        active_response = collection.aggregate.over_all(
            where=weaviate.classes.query.Filter.by_property("active").equal(True),
            total_count=True
        )
        active_count = active_response.total_count if active_response.total_count else 0
        
        return {
            "total_markets": total_count,
            "active_markets": active_count,
            "inactive_markets": total_count - active_count
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving stats: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
