# Backend Weaviate Integration

This document explains how Weaviate semantic search has been integrated into the existing agentic search backend to enhance market discovery and provide richer context for user queries.

## Overview

The integration adds semantic search capabilities to the existing SQL-based market search system. When a user asks a question, the system now:

1. **Performs semantic search** using Weaviate to find relevant markets based on meaning
2. **Executes SQL queries** as before to find exact matches
3. **Combines both results** to provide comprehensive answers with enhanced context

## Architecture

```
User Query
    ↓
┌─────────────────────────────────────┐
│  Backend API (/chat endpoint)       │
├─────────────────────────────────────┤
│  1. Semantic Search (Weaviate)     │
│  2. SQL Query Planning (Gemini)    │
│  3. SQL Execution (SQLite)         │
│  4. Response Generation (Gemini)   │
└─────────────────────────────────────┘
    ↓
Enhanced Response with Market Context
```

## Key Components

### 1. Weaviate Service (`backend/service_weaviate.py`)

- **Purpose**: Handles all Weaviate operations and semantic search
- **Features**:
  - Market search with relevance scoring
  - Category filtering
  - Health monitoring
  - Error handling and graceful degradation

### 2. Backend Configuration (`backend/config.py`)

- **Added Settings**:
  - `weaviate_url`: Weaviate Cloud cluster URL
  - `weaviate_api_key`: Authentication key

### 3. Enhanced API (`backend/api.py`)

- **New Function**: `get_semantic_market_context()`
- **Integration Points**:
  - Semantic search runs before SQL planning
  - Results included in debug information
  - Context passed to Gemini for enhanced responses

### 4. Updated Gemini Service (`backend/service_gemini.py`)

- **Enhanced System Instructions**: Include guidance on using semantic search results
- **Updated Templates**: Include semantic search context in response generation
- **Smart Integration**: Combines SQL results with semantic insights

## How It Works

### 1. Query Processing Flow

```python
# 1. User sends query
POST /chat {"message": "What are the markets about Fed rate cuts?"}

# 2. Semantic search runs first
semantic_results = weaviate_service.search_markets(
    query="What are the markets about Fed rate cuts?",
    limit=5,
    active_only=True
)

# 3. SQL planning with semantic context
gemini_payload = gemini.run_chat(
    columns=available_columns,
    user_message=user_query,
    history=conversation_history
)

# 4. SQL execution
sql_results = crud.execute_sql(session, sql, params)

# 5. Enhanced response generation
context = {
    "sql_results": sql_results,
    "semantic_search_results": semantic_results,
    "semantic_search_count": len(semantic_results)
}
final_response = gemini.run_answer_with_results(
    user_message, sql, sql_results, context, history
)
```

### 2. Semantic Search Integration

The semantic search results are included in the context passed to Gemini:

```python
semantic_context = f"Found {len(semantic_results)} semantically relevant markets:\n"
for i, market in enumerate(semantic_results[:3], 1):
    semantic_context += f"{i}. {market.get('question', 'N/A')}\n"
    semantic_context += f"   Category: {market.get('market_category_name', 'N/A')}\n"
    semantic_context += f"   Relevance: {market.get('relevance_score', 'N/A'):.3f}\n"
```

### 3. Enhanced Response Generation

Gemini now receives both SQL results and semantic search context, allowing it to:

- **Combine insights** from both exact matches and semantic matches
- **Suggest related markets** that might not appear in SQL results
- **Provide broader context** about market trends and themes
- **Enhance explanations** with semantically relevant market information

## Configuration

### Environment Variables

Add to your `.env` file:

```bash
# Weaviate Configuration
WEAVIATE_URL=https://your-cluster-url.weaviate.network
WEAVIATE_API_KEY=your-weaviate-api-key
```

### Setup Steps

1. **Set up Weaviate Cloud**:
   ```bash
   # Create free sandbox at https://console.weaviate.cloud/
   # Note your cluster URL and API key
   ```

2. **Ingest market data**:
   ```bash
   python weaviate_ingestion.py --input polymarket_markets.jsonl
   ```

3. **Start the backend**:
   ```bash
   uvicorn backend.api:app --reload
   ```

4. **Test the integration**:
   ```bash
   python test_backend_integration.py
   ```

## API Endpoints

### Health Checks

- **`GET /health`**: Basic API health
- **`GET /health/weaviate`**: Weaviate connection health with stats

### Chat Endpoint

- **`POST /chat`**: Enhanced chat with semantic search integration
  - Automatically includes semantic search results
  - Provides debug information about semantic search
  - Returns enhanced responses with market context

## Example Usage

### Query: "What are the markets about Fed rate cuts?"

**Before Integration**:
- Only SQL results based on exact keyword matches
- Limited to markets with "Fed" or "rate" in text fields

**After Integration**:
- SQL results for exact matches
- Semantic search finds markets about:
  - Federal Reserve policy
  - Interest rate predictions
  - Economic policy markets
  - Related financial markets
- Combined response with broader context

### Response Enhancement

```json
{
  "assistant_message": "Based on the SQL results and semantic search, I found several markets related to Fed rate cuts...",
  "payload": {
    "debug": {
      "semantic_search_count": 5,
      "semantic_search_results": [
        {
          "question": "Will the Fed cut rates in 2025?",
          "market_category_name": "Economic Policy",
          "relevance_score": 0.95
        }
      ]
    }
  }
}
```

## Benefits

### 1. **Enhanced Market Discovery**
- Finds markets that don't match exact keywords but are semantically related
- Discovers markets using synonyms, related concepts, and contextual understanding

### 2. **Richer Context**
- Provides broader market trends and themes
- Suggests related markets users might not have considered
- Enhances explanations with additional market insights

### 3. **Improved User Experience**
- More comprehensive answers
- Better market recommendations
- Enhanced understanding of market landscape

### 4. **Graceful Degradation**
- System works even if Weaviate is unavailable
- Falls back to SQL-only search
- No breaking changes to existing functionality

## Monitoring and Debugging

### Debug Information

The API now includes semantic search debug information:

```json
{
  "debug": {
    "semantic_search_count": 5,
    "semantic_search_results": [...],
    "stage": "answering"
  }
}
```

### Health Monitoring

Check Weaviate status:
```bash
curl http://localhost:8000/health/weaviate
```

### Logging

Semantic search operations are logged with appropriate levels:
- `INFO`: Successful searches and results
- `WARNING`: Service disabled or unavailable
- `ERROR`: Search failures and connection issues

## Performance Considerations

### 1. **Search Latency**
- Semantic search adds ~100-200ms to response time
- Runs in parallel with SQL planning
- Cached results for repeated queries

### 2. **Resource Usage**
- Minimal additional memory usage
- Weaviate connection pooling
- Graceful handling of connection failures

### 3. **Scalability**
- Weaviate Cloud handles scaling automatically
- Backend remains stateless
- No additional database load

## Troubleshooting

### Common Issues

1. **Semantic search not working**:
   - Check Weaviate credentials in `.env`
   - Verify Weaviate collection exists and has data
   - Check `/health/weaviate` endpoint

2. **No semantic results**:
   - Ensure market data has been ingested
   - Check query relevance to available markets
   - Verify Weaviate collection is properly configured

3. **Performance issues**:
   - Check Weaviate Cloud status
   - Monitor connection health
   - Consider reducing semantic search limit

### Debug Steps

1. **Check health endpoints**:
   ```bash
   curl http://localhost:8000/health
   curl http://localhost:8000/health/weaviate
   ```

2. **Test semantic search directly**:
   ```bash
   python weaviate_search_client.py "test query"
   ```

3. **Review logs**:
   - Check backend logs for semantic search errors
   - Monitor Weaviate connection status

## Future Enhancements

### Potential Improvements

1. **Caching**: Cache semantic search results for common queries
2. **Hybrid Search**: Combine semantic and keyword search scores
3. **Personalization**: Use user history to improve semantic relevance
4. **Real-time Updates**: Sync market data changes with Weaviate
5. **Advanced Filtering**: Add more sophisticated filtering options

### Integration Opportunities

1. **RAG Enhancement**: Use semantic search for retrieval-augmented generation
2. **Market Recommendations**: Suggest related markets based on semantic similarity
3. **Trend Analysis**: Identify market trends using semantic clustering
4. **Alert System**: Notify users of semantically relevant new markets

## Conclusion

The Weaviate integration significantly enhances the agentic search system by adding semantic understanding to market discovery. Users now receive more comprehensive answers with broader market context, while the system maintains its existing SQL-based precision and adds graceful degradation for reliability.

The integration is designed to be:
- **Non-breaking**: Existing functionality remains unchanged
- **Performant**: Minimal impact on response times
- **Reliable**: Graceful handling of failures
- **Extensible**: Easy to add new features and enhancements
