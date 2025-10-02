# Polymarket Weaviate Integration

This directory contains scripts and APIs for ingesting Polymarket prediction market data into Weaviate vector database and performing semantic search over the markets.

## Overview

The system consists of three main components:

1. **Data Ingestion Script** (`weaviate_ingestion.py`) - Ingests market data from JSONL files into Weaviate
2. **Search API** (`weaviate_search_api.py`) - FastAPI service for semantic search over markets
3. **Search Client** (`weaviate_search_client.py`) - Command-line client for testing search functionality

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set up Weaviate

1. Create a free Weaviate Cloud sandbox at [Weaviate Cloud Console](https://console.weaviate.cloud/)
2. Note your cluster URL and API key
3. Copy `env.example` to `.env` and fill in your credentials:

```bash
cp env.example .env
```

Edit `.env`:
```
WEAVIATE_URL=https://your-cluster-url.weaviate.network
WEAVIATE_API_KEY=your-weaviate-api-key
```

### 3. Prepare Market Data

Ensure you have Polymarket market data in JSONL format. You can use the existing `polymarket_markets.jsonl` file or fetch fresh data using:

```bash
python polymarket/get_polymarket_markets.py --limit 1000
```

## Usage

### 1. Ingest Data into Weaviate

```bash
python weaviate_ingestion.py --input polymarket_markets.jsonl
```

This will:
- Create a `PolymarketMarkets` collection in Weaviate
- Ingest all active markets with vector embeddings
- Process markets in batches for efficiency

### 2. Start the Search API

```bash
python weaviate_search_api.py
```

The API will be available at `http://localhost:8000` with interactive docs at `http://localhost:8000/docs`.

### 3. Search Markets

#### Using the Command Line Client

```bash
# Basic search
python weaviate_search_client.py "What are the markets about Fed rate cuts?"

# Search with filters
python weaviate_search_client.py "SpaceX launches" --limit 5 --category "Science"

# Include inactive markets
python weaviate_search_client.py "Bitcoin price" --include-inactive

# Check API health
python weaviate_search_client.py "test" --health

# Get database statistics
python weaviate_search_client.py "test" --stats

# List all categories
python weaviate_search_client.py "test" --categories
```

#### Using the API Directly

```bash
# Search markets
curl "http://localhost:8000/search?q=Fed%20rate%20cuts&limit=5"

# Get specific market
curl "http://localhost:8000/market/market-id-here"

# Get all categories
curl "http://localhost:8000/categories"

# Get database stats
curl "http://localhost:8000/stats"
```

#### Using Python Requests

```python
import requests

# Search for markets
response = requests.get("http://localhost:8000/search", params={
    "q": "What are the markets about cryptocurrency?",
    "limit": 10,
    "active_only": True
})

results = response.json()
for market in results["results"]:
    print(f"Question: {market['question']}")
    print(f"Description: {market['description'][:100]}...")
    print(f"Category: {market['market_category_name']}")
    print("-" * 50)
```

## API Endpoints

### Search Markets
- **GET** `/search`
- **Parameters:**
  - `q` (required): Search query
  - `limit` (optional): Number of results (1-100, default: 10)
  - `active_only` (optional): Only active markets (default: true)
  - `category` (optional): Filter by category

### Get Market by ID
- **GET** `/market/{market_id}`

### Get Categories
- **GET** `/categories`

### Database Statistics
- **GET** `/stats`

### Health Check
- **GET** `/health`

## Data Schema

The Weaviate collection includes the following properties:

- `market_id`: Unique market identifier
- `question`: Market question/title
- `description`: Detailed market description
- `market_slug`: URL-friendly identifier
- `tags`: Array of market tags
- `end_date_iso`: Market resolution date
- `active`: Whether market is active
- `closed`: Whether market is closed
- `archived`: Whether market is archived
- `market_category*`: Category hierarchy fields
- `tokens`: Market token information (JSON)
- `raw_data`: Complete raw market data (JSON)

## Vectorization

The system uses Weaviate's built-in `text2vec-weaviate` vectorizer, which automatically creates embeddings from the `question` and `description` fields. This enables semantic search capabilities where users can find relevant markets using natural language queries.

## Performance Considerations

- **Batch Size**: Default batch size is 50 for ingestion. Adjust with `--batch-size` parameter
- **Search Limits**: API limits search results to 100 maximum
- **Filtering**: Use category filters to narrow down results for better performance
- **Indexing**: Weaviate automatically creates vector indexes for fast similarity search

## Troubleshooting

### Common Issues

1. **Connection Error**: Make sure your Weaviate URL and API key are correct
2. **Collection Not Found**: Run the ingestion script first to create the collection
3. **Empty Results**: Check if your data was ingested successfully using the stats endpoint
4. **Slow Search**: Consider using category filters to narrow down results

### Debugging

- Check API health: `curl http://localhost:8000/health`
- View database stats: `curl http://localhost:8000/stats`
- Check logs in the terminal where you started the API

## Integration with Existing System

This Weaviate integration can be used alongside your existing agentic search system:

1. **Query Time**: Use the search API to find relevant markets based on user queries
2. **RAG Pipeline**: Combine market search results with LLM responses for enhanced answers
3. **Background Updates**: Periodically re-run ingestion to keep market data current

## Example Integration

```python
# In your existing query processing system
import requests

def find_relevant_markets(user_query: str) -> List[Dict]:
    """Find relevant markets for a user query."""
    response = requests.get("http://localhost:8000/search", params={
        "q": user_query,
        "limit": 5,
        "active_only": True
    })
    
    if response.status_code == 200:
        return response.json()["results"]
    else:
        return []

# Use in your agentic search pipeline
def process_query_with_markets(query: str):
    """Process query with market context."""
    relevant_markets = find_relevant_markets(query)
    
    # Build context from market data
    market_context = "\n".join([
        f"Market: {m['question']}\nDescription: {m['description']}\n"
        for m in relevant_markets
    ])
    
    # Use market context in your LLM prompt
    enhanced_prompt = f"""
    User Query: {query}
    
    Relevant Markets:
    {market_context}
    
    Please provide an answer considering the relevant prediction markets above.
    """
    
    return enhanced_prompt
```

## References

- [Weaviate Documentation](https://docs.weaviate.io/weaviate/quickstart)
- [Weaviate Python Client](https://weaviate.io/developers/weaviate/client-libraries/python)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
