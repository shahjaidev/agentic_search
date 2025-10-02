#!/usr/bin/env python3
"""
Test your running app with Opik tracing enabled.
This will make a request to your app and ensure it gets logged to Comet.
"""

import os
import requests
import json
import time

def main():
    """Test the app with Opik tracing."""
    
    print("🧪 Testing Polymarket App with Opik Tracing")
    print("=" * 50)
    
    # Set environment variables for this process
    os.environ["OPIK_API_KEY"] = "IhcWkQH6koIBliekV1uWcnzrf"
    os.environ["OPIK_WORKSPACE"] = "shahjaidev"
    os.environ["OPIK_PROJECT"] = "polymarket"
    
    print("✅ Environment variables set:")
    print(f"   OPIK_WORKSPACE: {os.environ['OPIK_WORKSPACE']}")
    print(f"   OPIK_PROJECT: {os.environ['OPIK_PROJECT']}")
    
    # Check if backend is running
    try:
        response = requests.get("http://localhost:8000/health", timeout=5)
        if response.status_code == 200:
            print("✅ Backend is running")
        else:
            print("❌ Backend health check failed")
            return
    except requests.exceptions.ConnectionError:
        print("❌ Backend not running. Please start it first:")
        print("   ./start_with_opik.sh")
        return
    
    # Make a test chat request
    print("\n🚀 Making test request to your app...")
    
    chat_data = {
        "conversation_id": f"opik-test-{int(time.time())}",
        "message": "Show me the top 3 most liquid prediction markets about US politics"
    }
    
    try:
        response = requests.post(
            "http://localhost:8000/chat", 
            json=chat_data, 
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Chat request successful!")
            print(f"📝 Assistant response: {result.get('assistant_message', 'No message')[:150]}...")
            
            # Check if we got SQL results
            payload = result.get('payload', {})
            sql_rows = payload.get('sql_rows', [])
            print(f"📊 SQL results: {len(sql_rows)} rows returned")
            
            if sql_rows:
                print("📋 Sample results:")
                for i, row in enumerate(sql_rows[:2], 1):
                    question = row.get('question', 'N/A')[:60]
                    liquidity = row.get('liquidity_num', 'N/A')
                    print(f"   {i}. {question}... (Liquidity: {liquidity})")
            
            print("\n🎯 SUCCESS! This request should now be logged in your Comet dashboard:")
            print("   🌐 https://www.comet.com/shahjaidev/polymarket")
            print("   📊 Look for traces in the 'polymarket' project")
            print("   🔍 The trace should show the Gemini API call details")
            
        else:
            print(f"❌ Chat request failed: {response.status_code}")
            print(f"Error: {response.text}")
            
    except requests.exceptions.Timeout:
        print("❌ Request timed out")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
