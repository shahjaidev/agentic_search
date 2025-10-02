#!/usr/bin/env python3
"""
Client script to demonstrate Weaviate search functionality for Polymarket markets.

This script shows how to search for relevant markets and can be used for testing
or as a reference for integrating the search API into other applications.

Usage:
    python weaviate_search_client.py "What are the markets about Fed rate cuts?"
    python weaviate_search_client.py "SpaceX launches" --limit 5
"""

import argparse
import requests
import json
from typing import List, Dict, Any

class PolymarketSearchClient:
    """Client for interacting with the Polymarket Search API."""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        """Initialize the search client."""
        self.base_url = base_url.rstrip('/')
    
    def search_markets(
        self, 
        query: str, 
        limit: int = 10,
        active_only: bool = True,
        category: str = None
    ) -> Dict[str, Any]:
        """Search for relevant markets."""
        params = {
            "q": query,
            "limit": limit,
            "active_only": active_only
        }
        if category:
            params["category"] = category
        
        response = requests.get(f"{self.base_url}/search", params=params)
        response.raise_for_status()
        return response.json()
    
    def get_market(self, market_id: str) -> Dict[str, Any]:
        """Get a specific market by ID."""
        response = requests.get(f"{self.base_url}/market/{market_id}")
        response.raise_for_status()
        return response.json()
    
    def get_categories(self) -> List[str]:
        """Get all available categories."""
        response = requests.get(f"{self.base_url}/categories")
        response.raise_for_status()
        return response.json()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        response = requests.get(f"{self.base_url}/stats")
        response.raise_for_status()
        return response.json()
    
    def health_check(self) -> Dict[str, Any]:
        """Check API health."""
        response = requests.get(f"{self.base_url}/health")
        response.raise_for_status()
        return response.json()

def format_search_results(results: Dict[str, Any]) -> str:
    """Format search results for display."""
    output = []
    output.append(f"Query: {results['query']}")
    output.append(f"Found {results['total_results']} results (showing {len(results['results'])}):")
    output.append("=" * 80)
    
    for i, result in enumerate(results['results'], 1):
        output.append(f"\n{i}. {result['question']}")
        output.append(f"   Market ID: {result['market_id']}")
        output.append(f"   Category: {result['market_category_name'] or 'N/A'}")
        output.append(f"   Active: {result['active']}")
        output.append(f"   End Date: {result['end_date_iso'] or 'N/A'}")
        output.append(f"   Tags: {', '.join(result['tags']) if result['tags'] else 'None'}")
        if result['distance'] is not None:
            output.append(f"   Relevance Score: {1 - result['distance']:.3f}")
        
        # Truncate description if too long
        description = result['description']
        if len(description) > 200:
            description = description[:200] + "..."
        output.append(f"   Description: {description}")
        output.append("-" * 40)
    
    return "\n".join(output)

def main():
    parser = argparse.ArgumentParser(description="Search Polymarket markets using Weaviate")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--limit", "-l", type=int, default=10,
                       help="Maximum number of results (default: 10)")
    parser.add_argument("--category", "-c", type=str,
                       help="Filter by market category")
    parser.add_argument("--include-inactive", action="store_true",
                       help="Include inactive markets in results")
    parser.add_argument("--api-url", default="http://localhost:8000",
                       help="API base URL (default: http://localhost:8000)")
    parser.add_argument("--stats", action="store_true",
                       help="Show database statistics")
    parser.add_argument("--categories", action="store_true",
                       help="List all available categories")
    parser.add_argument("--health", action="store_true",
                       help="Check API health")
    
    args = parser.parse_args()
    
    client = PolymarketSearchClient(args.api_url)
    
    try:
        # Health check
        if args.health:
            health = client.health_check()
            print("API Health Check:")
            print(json.dumps(health, indent=2))
            return
        
        # Show stats
        if args.stats:
            stats = client.get_stats()
            print("Database Statistics:")
            print(json.dumps(stats, indent=2))
            return
        
        # Show categories
        if args.categories:
            categories = client.get_categories()
            print("Available Categories:")
            for category in categories:
                print(f"  - {category}")
            return
        
        # Perform search
        results = client.search_markets(
            query=args.query,
            limit=args.limit,
            active_only=not args.include_inactive,
            category=args.category
        )
        
        print(format_search_results(results))
        
    except requests.exceptions.ConnectionError:
        print(f"Error: Could not connect to API at {args.api_url}")
        print("Make sure the Weaviate Search API is running (python weaviate_search_api.py)")
    except requests.exceptions.HTTPError as e:
        print(f"API Error: {e}")
        if e.response.status_code == 404:
            print("Make sure the API is running and the collection exists")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
