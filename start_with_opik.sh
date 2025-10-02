#!/bin/bash

# Startup script for Polymarket app with Opik tracing enabled

echo "🚀 Starting Polymarket Prediction Market Discovery Engine with Opik tracing..."

# Set Opik environment variables
export OPIK_API_KEY="IhcWkQH6koIBliekV1uWcnzrf"
export OPIK_WORKSPACE="shahjaidev"
export OPIK_PROJECT="polymarket"

echo "✅ Opik configuration:"
echo "   Workspace: $OPIK_WORKSPACE"
echo "   Project: $OPIK_PROJECT"
echo "   API Key: Set"

# Check if backend is already running
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "✅ Backend is already running"
else
    echo "🔧 Starting backend..."
    # Start backend in background
    uvicorn backend.api:app --reload --host 0.0.0.0 --port 8000 &
    BACKEND_PID=$!
    echo "   Backend PID: $BACKEND_PID"
    
    # Wait for backend to start
    echo "   Waiting for backend to be ready..."
    for i in {1..30}; do
        if curl -s http://localhost:8000/health > /dev/null 2>&1; then
            echo "   ✅ Backend is ready!"
            break
        fi
        sleep 1
        echo -n "."
    done
fi

# Check if Streamlit is already running
if curl -s http://localhost:8501 > /dev/null 2>&1; then
    echo "✅ Streamlit is already running"
else
    echo "🔧 Starting Streamlit UI..."
    # Start Streamlit
    streamlit run ui/app.py --server.port 8501 &
    STREAMLIT_PID=$!
    echo "   Streamlit PID: $STREAMLIT_PID"
fi

echo ""
echo "🎉 Polymarket app is running with Opik tracing!"
echo "   📊 App: http://localhost:8501"
echo "   🔧 API: http://localhost:8000"
echo "   📈 Traces: https://www.comet.com/shahjaidev/polymarket"
echo ""
echo "💡 All your Gemini API calls will now be logged to your Comet polymarket project!"
echo "   Try asking: 'Show me markets about US politics'"
echo ""
echo "Press Ctrl+C to stop all services"

# Function to cleanup on exit
cleanup() {
    echo ""
    echo "🛑 Stopping services..."
    if [ ! -z "$BACKEND_PID" ]; then
        kill $BACKEND_PID 2>/dev/null
        echo "   Stopped backend"
    fi
    if [ ! -z "$STREAMLIT_PID" ]; then
        kill $STREAMLIT_PID 2>/dev/null
        echo "   Stopped Streamlit"
    fi
    echo "✅ Cleanup complete"
    exit 0
}

# Set trap to cleanup on script exit
trap cleanup SIGINT SIGTERM

# Keep script running
wait
