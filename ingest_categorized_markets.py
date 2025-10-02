#!/usr/bin/env python3
"""
Ingest categorized Polymarket markets into Weaviate with optimized semantic search.

This script reads the categorized market data and creates a Weaviate collection
optimized for semantic search on question + description text while preserving
all other market metadata for filtering and querying.

Usage:
    python ingest_categorized_markets.py --input polymarket/data/polymarket_market_categories.jsonl
    python ingest_categorized_markets.py --input polymarket/data/polymarket_market_categories.jsonl --batch-size 100
"""

import argparse
import json
import os
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime
import weaviate
from weaviate.classes.init import Auth
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class CategorizedMarketIngestion:
    def __init__(self, weaviate_url: str, weaviate_api_key: str):
        """Initialize Weaviate client connection."""
        self.client = weaviate.connect_to_weaviate_cloud(
            cluster_url=weaviate_url,
            auth_credentials=Auth.api_key(weaviate_api_key),
        )
        self.collection_name = "CategorizedPolymarketMarkets"
        
    def create_collection(self):
        """Create the CategorizedPolymarketMarkets collection with optimized schema."""
        # Check if collection already exists
        if self.client.collections.exists(self.collection_name):
            print(f"Collection '{self.collection_name}' already exists. Deleting...")
            self.client.collections.delete(self.collection_name)
        
        # Create collection with schema optimized for semantic search
        collection = self.client.collections.create(
            name=self.collection_name,
            description="Categorized Polymarket prediction markets optimized for semantic search",
            properties=[
                # Core market identifiers
                weaviate.classes.config.Property(
                    name="market_id",
                    data_type=weaviate.classes.config.DataType.TEXT,
                    description="Unique identifier for the market"
                ),
                weaviate.classes.config.Property(
                    name="row_id",
                    data_type=weaviate.classes.config.DataType.INT,
                    description="Row ID from the original data"
                ),
                
                # Text content for semantic search (concatenated)
                weaviate.classes.config.Property(
                    name="searchable_text",
                    data_type=weaviate.classes.config.DataType.TEXT,
                    description="Concatenated question + description for semantic search"
                ),
                
                # Individual text fields (for filtering and display)
                weaviate.classes.config.Property(
                    name="question",
                    data_type=weaviate.classes.config.DataType.TEXT,
                    description="The market question/title"
                ),
                weaviate.classes.config.Property(
                    name="description",
                    data_type=weaviate.classes.config.DataType.TEXT,
                    description="Detailed market description"
                ),
                
                # Categorization data
                weaviate.classes.config.Property(
                    name="category",
                    data_type=weaviate.classes.config.DataType.TEXT,
                    description="Market category code (e.g., 2.1.2)"
                ),
                weaviate.classes.config.Property(
                    name="category_source",
                    data_type=weaviate.classes.config.DataType.TEXT,
                    description="Source of categorization (model, manual, etc.)"
                ),
                
                # Market metadata
                weaviate.classes.config.Property(
                    name="tags",
                    data_type=weaviate.classes.config.DataType.TEXT_ARRAY,
                    description="Market tags/categories"
                ),
                weaviate.classes.config.Property(
                    name="active",
                    data_type=weaviate.classes.config.DataType.BOOL,
                    description="Whether the market is currently active"
                ),
                weaviate.classes.config.Property(
                    name="closed",
                    data_type=weaviate.classes.config.DataType.BOOL,
                    description="Whether the market is closed"
                ),
                weaviate.classes.config.Property(
                    name="archived",
                    data_type=weaviate.classes.config.DataType.BOOL,
                    description="Whether the market is archived"
                ),
                
                # Additional metadata
                weaviate.classes.config.Property(
                    name="timestamp",
                    data_type=weaviate.classes.config.DataType.DATE,
                    description="Timestamp when market was processed"
                ),
                weaviate.classes.config.Property(
                    name="raw_data",
                    data_type=weaviate.classes.config.DataType.TEXT,
                    description="Complete raw market data as JSON string"
                )
            ],
            # Configure vectorization to use the concatenated searchable text
            vectorizer_config=weaviate.classes.config.Configure.Vectorizer.text2vec_weaviate(
                vectorize_collection_name=False
            ),
            # Configure vector index for semantic search
            vector_index_config=weaviate.classes.config.Configure.VectorIndex.hnsw(
                distance_metric=weaviate.classes.config.VectorDistances.COSINE
            )
        )
        
        print(f"Created collection '{self.collection_name}' successfully")
        return collection
    
    def is_market_active(self, end_date_iso):
        """Check if market is active (no end date or future end date)."""
        # If no end date, assume market is still active
        if not end_date_iso or end_date_iso is None:
            return True
        
        try:
            # Parse the ISO date string
            if isinstance(end_date_iso, str):
                end_date = datetime.fromisoformat(end_date_iso.replace('Z', '+00:00'))
            else:
                return True  # If not a string, assume active
            
            # Compare with current date
            current_date = datetime.now(end_date.tzinfo)
            return end_date > current_date
        except (ValueError, TypeError):
            return True  # If date parsing fails, assume active
    
    def prepare_market_data(self, market: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare categorized market data for Weaviate insertion."""
        # Extract core fields
        market_id = market.get("market_id", "")
        question = ""
        description = ""
        tags = []
        
        # Extract question, description, tags, and end_date from the prompt data
        end_date_iso = None
        if "prompt" in market:
            try:
                # Parse the markets JSON from the prompt to extract market details
                prompt_data = market["prompt"]
                if "Markets JSON:" in prompt_data:
                    json_start = prompt_data.find("[{")
                    if json_start != -1:
                        json_end = prompt_data.find("}]", json_start) + 2
                        markets_json = prompt_data[json_start:json_end]
                        markets_data = json.loads(markets_json)
                        
                        # Find the market that matches our market_id
                        for m in markets_data:
                            if m.get("market_id") == market_id:
                                question = m.get("question", "")
                                description = m.get("description", "")
                                tags = m.get("tags", [])
                                end_date_iso = m.get("end_date_iso")
                                break
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                print(f"Error parsing prompt data for {market_id}: {e}")
                pass
        
        # Check if market is still active (end date > current date)
        if not self.is_market_active(end_date_iso):
            return None  # Return None for inactive markets
        
        # Create concatenated searchable text
        searchable_text = f"{question}\n\n{description}".strip()
        
        # Prepare data for insertion
        prepared_data = {
            "market_id": market_id,
            "row_id": market.get("row_id", 0),
            "searchable_text": searchable_text,
            "question": question,
            "description": description,
            "category": market.get("category", ""),
            "category_source": market.get("source", ""),
            "tags": tags,
            "active": True,  # Assume active unless specified otherwise
            "closed": False,
            "archived": False,
            "timestamp": market.get("timestamp", ""),
            "raw_data": json.dumps(market)
        }
        
        # Clean up None values
        for key, value in prepared_data.items():
            if value is None:
                if key in ["active", "closed", "archived"]:
                    prepared_data[key] = False
                elif key == "row_id":
                    prepared_data[key] = 0
                else:
                    prepared_data[key] = ""
        
        return prepared_data
    
    def ingest_markets(self, input_file: Path, batch_size: int = 250):
        """Ingest categorized markets from JSONL file into Weaviate."""
        collection = self.client.collections.get(self.collection_name)
        
        markets_processed = 0
        markets_skipped = 0
        
        print(f"Starting ingestion from {input_file}")
        
        with open(input_file, 'r', encoding='utf-8') as f:
            batch = []
            
            for line_num, line in enumerate(f, 1):
                try:
                    market_data = json.loads(line.strip())
                    
                    # Skip if essential fields are missing
                    if not market_data.get("market_id"):
                        markets_skipped += 1
                        continue
                    
                    prepared_data = self.prepare_market_data(market_data)
                    if prepared_data is None:  # Skip inactive markets
                        markets_skipped += 1
                        continue
                    
                    batch.append(prepared_data)
                    
                    # Process batch when it reaches batch_size
                    if len(batch) >= batch_size:
                        self._insert_batch(collection, batch)
                        markets_processed += len(batch)
                        print(f"Processed {markets_processed} markets...")
                        batch = []
                        
                except json.JSONDecodeError as e:
                    print(f"Error parsing line {line_num}: {e}")
                    continue
                except Exception as e:
                    print(f"Error processing line {line_num}: {e}")
                    continue
            
            # Process remaining items in batch
            if batch:
                self._insert_batch(collection, batch)
                markets_processed += len(batch)
        
        print(f"Ingestion complete!")
        print(f"Markets processed: {markets_processed}")
        print(f"Markets skipped: {markets_skipped}")
        
        return markets_processed
    
    def _insert_batch(self, collection, batch: List[Dict[str, Any]]):
        """Insert a batch of markets into Weaviate."""
        try:
            collection.data.insert_many(batch)
        except Exception as e:
            print(f"Error inserting batch: {e}")
            # Try inserting one by one to identify problematic records
            for i, item in enumerate(batch):
                try:
                    collection.data.insert(item)
                except Exception as item_error:
                    print(f"Error inserting item {i}: {item_error}")
                    print(f"Problematic item: {item.get('market_id', 'unknown')}")
    
    def search_markets(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search for relevant markets using semantic search on concatenated text."""
        collection = self.client.collections.get(self.collection_name)
        
        # Perform semantic search on the searchable_text field
        response = collection.query.near_text(
            query=query,
            limit=limit,
            return_metadata=weaviate.classes.query.MetadataQuery(distance=True)
        )
        
        results = []
        for obj in response.objects:
            result = {
                "market_id": obj.properties.get("market_id"),
                "row_id": obj.properties.get("row_id"),
                "question": obj.properties.get("question"),
                "description": obj.properties.get("description"),
                "category": obj.properties.get("category"),
                "category_source": obj.properties.get("category_source"),
                "tags": obj.properties.get("tags", []),
                "active": obj.properties.get("active"),
                "closed": obj.properties.get("closed"),
                "archived": obj.properties.get("archived"),
                "distance": obj.metadata.distance if obj.metadata else None,
                "relevance_score": 1 - obj.metadata.distance if obj.metadata and obj.metadata.distance else None
            }
            results.append(result)
        
        return results
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        try:
            collection = self.client.collections.get(self.collection_name)
            
            # Get total count
            total_response = collection.aggregate.over_all()
            total_count = total_response.total_count if hasattr(total_response, 'total_count') and total_response.total_count else 0
            
            return {
                "total_markets": total_count,
                "collection_name": self.collection_name
            }
            
        except Exception as e:
            print(f"Error retrieving stats: {e}")
            return {"total_markets": 0, "collection_name": self.collection_name}
    
    def close(self):
        """Close the Weaviate client connection."""
        self.client.close()


def main():
    parser = argparse.ArgumentParser(description="Ingest categorized Polymarket data into Weaviate")
    parser.add_argument("--input", "-i", type=Path, required=True,
                       help="Input JSONL file containing categorized market data")
    parser.add_argument("--batch-size", "-b", type=int, default=50,
                       help="Batch size for ingestion (default: 200)")
    parser.add_argument("--weaviate-url", type=str,
                       default=os.getenv("WEAVIATE_URL"),
                       help="Weaviate cluster URL")
    parser.add_argument("--weaviate-api-key", type=str,
                       default=os.getenv("WEAVIATE_API_KEY"),
                       help="Weaviate API key")
    
    args = parser.parse_args()
    
    if not args.weaviate_url or not args.weaviate_api_key:
        print("Error: WEAVIATE_URL and WEAVIATE_API_KEY must be provided")
        print("Set them as environment variables or use --weaviate-url and --weaviate-api-key")
        return
    
    if not args.input.exists():
        print(f"Error: Input file {args.input} does not exist")
        return
    
    # Initialize ingestion
    ingestion = CategorizedMarketIngestion(args.weaviate_url, args.weaviate_api_key)
    
    try:
        # Create collection
        ingestion.create_collection()
        
        # Ingest data
        markets_processed = ingestion.ingest_markets(args.input, args.batch_size)
        
        # Show stats
        stats = ingestion.get_stats()
        print(f"\nFinal Stats:")
        print(f"Total markets in collection: {stats['total_markets']}")
        print(f"Collection name: {stats['collection_name']}")
        
        print(f"\nSuccessfully ingested {markets_processed} categorized markets into Weaviate")
        print(f"Semantic search is optimized for question + description text")
        print(f"All other fields are available for filtering and querying")
        
    except Exception as e:
        print(f"Error during ingestion: {e}")
    finally:
        ingestion.close()


if __name__ == "__main__":
    main()
