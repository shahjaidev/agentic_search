#!/usr/bin/env python3
"""
Test script to validate the Weaviate integration for Polymarket markets.

This script tests the complete pipeline from data ingestion to search functionality.
Run this after setting up your Weaviate credentials and having market data available.

Usage:
    python test_weaviate_integration.py
"""

import os
import json
import time
import requests
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_environment_setup():
    """Test if environment variables are properly set."""
    print("🔧 Testing environment setup...")
    
    weaviate_url = os.getenv("WEAVIATE_URL")
    weaviate_api_key = os.getenv("WEAVIATE_API_KEY")
    
    if not weaviate_url:
        print("❌ WEAVIATE_URL environment variable not set")
        return False
    
    if not weaviate_api_key:
        print("❌ WEAVIATE_API_KEY environment variable not set")
        return False
    
    print(f"✅ WEAVIATE_URL: {weaviate_url}")
    print(f"✅ WEAVIATE_API_KEY: {'*' * (len(weaviate_api_key) - 4) + weaviate_api_key[-4:]}")
    return True

def test_data_availability():
    """Test if market data is available."""
    print("\n📊 Testing data availability...")
    
    data_files = [
        "polymarket_markets.jsonl",
        "polymarket/polymarket_markets.jsonl"
    ]
    
    for file_path in data_files:
        if Path(file_path).exists():
            with open(file_path, 'r') as f:
                lines = sum(1 for _ in f)
            print(f"✅ Found {file_path} with {lines} markets")
            return file_path
    
    print("❌ No market data files found")
    print("   Please run: python polymarket/get_polymarket_markets.py")
    return None

def test_weaviate_connection():
    """Test Weaviate connection."""
    print("\n🔗 Testing Weaviate connection...")
    
    try:
        import weaviate
        from weaviate.classes.init import Auth
        
        client = weaviate.connect_to_weaviate_cloud(
            cluster_url=os.getenv("WEAVIATE_URL"),
            auth_credentials=Auth.api_key(os.getenv("WEAVIATE_API_KEY")),
        )
        
        is_ready = client.is_ready()
        client.close()
        
        if is_ready:
            print("✅ Weaviate connection successful")
            return True
        else:
            print("❌ Weaviate connection failed")
            return False
            
    except Exception as e:
        print(f"❌ Weaviate connection error: {e}")
        return False

def test_data_ingestion(data_file: str):
    """Test data ingestion into Weaviate."""
    print(f"\n📥 Testing data ingestion from {data_file}...")
    
    try:
        # Import and run ingestion
        from weaviate_ingestion import PolymarketWeaviateIngestion
        
        ingestion = PolymarketWeaviateIngestion(
            os.getenv("WEAVIATE_URL"),
            os.getenv("WEAVIATE_API_KEY")
        )
        
        # Create collection
        ingestion.create_collection()
        
        # Ingest a small sample (first 10 markets)
        print("   Ingesting sample data (10 markets)...")
        markets_processed = ingestion.ingest_markets(Path(data_file), batch_size=10)
        
        ingestion.close()
        
        if markets_processed > 0:
            print(f"✅ Successfully ingested {markets_processed} markets")
            return True
        else:
            print("❌ No markets were ingested")
            return False
            
    except Exception as e:
        print(f"❌ Ingestion error: {e}")
        return False

def test_search_api():
    """Test the search API."""
    print("\n🔍 Testing search API...")
    
    # Start API in background (this is a simplified test)
    print("   Note: Start the API manually with: python weaviate_search_api.py")
    
    try:
        # Test if API is running
        response = requests.get("http://localhost:8000/health", timeout=5)
        
        if response.status_code == 200:
            health_data = response.json()
            print(f"✅ API is running: {health_data}")
            return True
        else:
            print(f"❌ API returned status {response.status_code}")
            return False
            
    except requests.exceptions.ConnectionError:
        print("❌ API is not running. Start it with: python weaviate_search_api.py")
        return False
    except Exception as e:
        print(f"❌ API test error: {e}")
        return False

def test_search_functionality():
    """Test search functionality."""
    print("\n🎯 Testing search functionality...")
    
    test_queries = [
        "Fed rate cuts",
        "SpaceX launches",
        "Bitcoin price",
        "Election predictions"
    ]
    
    for query in test_queries:
        try:
            response = requests.get("http://localhost:8000/search", params={
                "q": query,
                "limit": 3
            })
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Query '{query}': Found {data['total_results']} results")
                
                # Show first result
                if data['results']:
                    first_result = data['results'][0]
                    print(f"   Top result: {first_result['question']}")
            else:
                print(f"❌ Query '{query}' failed with status {response.status_code}")
                
        except Exception as e:
            print(f"❌ Query '{query}' error: {e}")

def test_client():
    """Test the command line client."""
    print("\n💻 Testing command line client...")
    
    try:
        import subprocess
        
        # Test health check
        result = subprocess.run([
            "python", "weaviate_search_client.py", 
            "test", "--health", "--api-url", "http://localhost:8000"
        ], capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            print("✅ Command line client working")
            return True
        else:
            print(f"❌ Client error: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ Client test error: {e}")
        return False

def main():
    """Run all tests."""
    print("🚀 Starting Weaviate Integration Tests")
    print("=" * 50)
    
    tests_passed = 0
    total_tests = 6
    
    # Test 1: Environment setup
    if test_environment_setup():
        tests_passed += 1
    
    # Test 2: Data availability
    data_file = test_data_availability()
    if data_file:
        tests_passed += 1
    
    # Test 3: Weaviate connection
    if test_weaviate_connection():
        tests_passed += 1
    
    # Test 4: Data ingestion (only if we have data)
    if data_file and test_data_ingestion(data_file):
        tests_passed += 1
    
    # Test 5: Search API
    if test_search_api():
        tests_passed += 1
        
        # Test 6: Search functionality (only if API is running)
        test_search_functionality()
        tests_passed += 1
    
    # Test 7: Command line client
    if test_client():
        tests_passed += 1
        total_tests = 7
    
    print("\n" + "=" * 50)
    print(f"🏁 Test Results: {tests_passed}/{total_tests} tests passed")
    
    if tests_passed == total_tests:
        print("🎉 All tests passed! Your Weaviate integration is working correctly.")
        print("\nNext steps:")
        print("1. Run: python weaviate_ingestion.py --input polymarket_markets.jsonl")
        print("2. Run: python weaviate_search_api.py")
        print("3. Test: python weaviate_search_client.py 'your search query'")
    else:
        print("⚠️  Some tests failed. Please check the errors above and fix them.")
        print("\nCommon issues:")
        print("- Set WEAVIATE_URL and WEAVIATE_API_KEY in .env file")
        print("- Ensure you have market data available")
        print("- Make sure Weaviate Cloud instance is running")

if __name__ == "__main__":
    main()
