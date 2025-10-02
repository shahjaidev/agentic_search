#!/usr/bin/env python3
"""
Script to ingest Polymarket market data into Weaviate vector database.

This script reads market data from JSONL files and creates vector embeddings
for semantic search capabilities. It uses Weaviate's built-in text2vec-weaviate
vectorizer for automatic embedding generation.

Usage:
    python weaviate_ingestion.py --input polymarket_markets.jsonl
    python weaviate_ingestion.py --input polymarket_markets.jsonl --batch-size 100
"""

import argparse
import json
import os
from pathlib import Path
from typing import Dict, Any, List
import weaviate
from weaviate.classes.init import Auth
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class PolymarketWeaviateIngestion:
    def __init__(self, weaviate_url: str, weaviate_api_key: str):
        """Initialize Weaviate client connection."""
        self.client = weaviate.connect_to_weaviate_cloud(
            cluster_url=weaviate_url,
            auth_credentials=Auth.api_key(weaviate_api_key),
        )
        self.collection_name = "PolymarketMarkets"
        
    def create_collection(self):
        """Create the PolymarketMarkets collection with proper schema."""
        # Check if collection already exists
        if self.client.collections.exists(self.collection_name):
            print(f"Collection '{self.collection_name}' already exists. Deleting...")
            self.client.collections.delete(self.collection_name)
        
        # Create collection with schema
        collection = self.client.collections.create(
            name=self.collection_name,
            description="Polymarket prediction markets for semantic search",
            properties=[
                weaviate.classes.config.Property(
                    name="market_id",
                    data_type=weaviate.classes.config.DataType.TEXT,
                    description="Unique identifier for the market"
                ),
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
                weaviate.classes.config.Property(
                    name="market_slug",
                    data_type=weaviate.classes.config.DataType.TEXT,
                    description="URL-friendly market identifier"
                ),
                weaviate.classes.config.Property(
                    name="tags",
                    data_type=weaviate.classes.config.DataType.TEXT_ARRAY,
                    description="Market tags/categories"
                ),
                weaviate.classes.config.Property(
                    name="end_date_iso",
                    data_type=weaviate.classes.config.DataType.DATE,
                    description="Market resolution date"
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
                weaviate.classes.config.Property(
                    name="market_category",
                    data_type=weaviate.classes.config.DataType.TEXT,
                    description="Market category"
                ),
                weaviate.classes.config.Property(
                    name="market_category_name",
                    data_type=weaviate.classes.config.DataType.TEXT,
                    description="Market category name"
                ),
                weaviate.classes.config.Property(
                    name="market_category_l1_name",
                    data_type=weaviate.classes.config.DataType.TEXT,
                    description="Level 1 category name"
                ),
                weaviate.classes.config.Property(
                    name="market_category_l2_name",
                    data_type=weaviate.classes.config.DataType.TEXT,
                    description="Level 2 category name"
                ),
                weaviate.classes.config.Property(
                    name="market_category_l3_name",
                    data_type=weaviate.classes.config.DataType.TEXT,
                    description="Level 3 category name"
                ),
                weaviate.classes.config.Property(
                    name="tokens",
                    data_type=weaviate.classes.config.DataType.TEXT,
                    description="Market token information as JSON string"
                ),
                weaviate.classes.config.Property(
                    name="raw_data",
                    data_type=weaviate.classes.config.DataType.TEXT,
                    description="Complete raw market data as JSON string"
                )
            ],
            vectorizer_config=weaviate.classes.config.Configure.Vectorizer.text2vec_weaviate(
                # Use the question and description for vectorization
                vectorize_collection_name=False
            ),
            # Configure which properties to vectorize
            vector_index_config=weaviate.classes.config.Configure.VectorIndex.hnsw(
                distance_metric=weaviate.classes.config.VectorDistances.COSINE
            )
        )
        
        print(f"Created collection '{self.collection_name}' successfully")
        return collection
    
    def prepare_market_data(self, market: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare market data for Weaviate insertion."""
        # Extract key fields
        prepared_data = {
            "market_id": str(market.get("condition_id") or market.get("question_id") or market.get("market_slug", "")),
            "question": market.get("question", ""),
            "description": market.get("description", ""),
            "market_slug": market.get("market_slug", ""),
            "tags": market.get("tags", []),
            "end_date_iso": market.get("end_date_iso"),
            "active": market.get("active", False),
            "closed": market.get("closed", False),
            "archived": market.get("archived", False),
            "market_category": market.get("market_category", ""),
            "market_category_name": market.get("market_category_name", ""),
            "market_category_l1_name": market.get("market_category_l1_name", ""),
            "market_category_l2_name": market.get("market_category_l2_name", ""),
            "market_category_l3_name": market.get("market_category_l3_name", ""),
            "tokens": json.dumps(market.get("tokens", [])),
            "raw_data": json.dumps(market)
        }
        
        # Clean up None values
        for key, value in prepared_data.items():
            if value is None:
                prepared_data[key] = "" if isinstance(value, str) else False if isinstance(value, bool) else []
        
        return prepared_data
    
    def ingest_markets(self, input_file: Path, batch_size: int = 50):
        """Ingest markets from JSONL file into Weaviate."""
        collection = self.client.collections.get(self.collection_name)
        
        markets_processed = 0
        markets_skipped = 0
        
        print(f"Starting ingestion from {input_file}")
        
        with open(input_file, 'r', encoding='utf-8') as f:
            batch = []
            
            for line_num, line in enumerate(f, 1):
                try:
                    market_data = json.loads(line.strip())
                    
                    # Skip inactive, closed, or archived markets
                    if not market_data.get("active", False) or market_data.get("closed", False) or market_data.get("archived", False):
                        markets_skipped += 1
                        continue
                    
                    prepared_data = self.prepare_market_data(market_data)
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
        """Search for relevant markets using semantic search."""
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
                "market_id": obj.properties.get("market_id"),
                "question": obj.properties.get("question"),
                "description": obj.properties.get("description"),
                "market_slug": obj.properties.get("market_slug"),
                "tags": obj.properties.get("tags", []),
                "end_date_iso": obj.properties.get("end_date_iso"),
                "active": obj.properties.get("active"),
                "market_category": obj.properties.get("market_category"),
                "market_category_name": obj.properties.get("market_category_name"),
                "distance": obj.metadata.distance if obj.metadata else None
            }
            results.append(result)
        
        return results
    
    def close(self):
        """Close the Weaviate client connection."""
        self.client.close()


def main():
    parser = argparse.ArgumentParser(description="Ingest Polymarket data into Weaviate")
    parser.add_argument("--input", "-i", type=Path, required=True,
                       help="Input JSONL file containing market data")
    parser.add_argument("--batch-size", "-b", type=int, default=50,
                       help="Batch size for ingestion (default: 50)")
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
    ingestion = PolymarketWeaviateIngestion(args.weaviate_url, args.weaviate_api_key)
    
    try:
        # Create collection
        ingestion.create_collection()
        
        # Ingest data
        markets_processed = ingestion.ingest_markets(args.input, args.batch_size)
        
        print(f"Successfully ingested {markets_processed} markets into Weaviate")
        
    except Exception as e:
        print(f"Error during ingestion: {e}")
    finally:
        ingestion.close()


if __name__ == "__main__":
    main()
