#!/bin/bash

# Civic App Backend - Quick Start Script
# This script helps you start the FastAPI backend server

echo "🏙️  Civic App Backend - Starting..."
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Install/upgrade dependencies
echo "📥 Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "⚠️  No .env file found. Copying from .env.example..."
    cp .env.example .env
    echo "✏️  Please edit .env file with your API keys before running the server."
    echo ""
    exit 1
fi

# Check if OPENAI_API_KEY is set
if grep -q "your-openai-api-key-here" .env; then
    echo "⚠️  Please set your OPENAI_API_KEY in the .env file"
    echo ""
    exit 1
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "🚀 Starting FastAPI server..."
echo "📖 API Documentation will be available at: http://localhost:8000/docs"
echo "📘 Alternative docs at: http://localhost:8000/redoc"
echo ""

# Start the server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
