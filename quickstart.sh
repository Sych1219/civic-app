#!/bin/bash

# Quick Start Script for Civic App
# This script helps you set up and run the application

set -e

echo "=================================================="
echo "  Civic App - Quick Start Setup"
echo "=================================================="
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.10 or higher."
    exit 1
fi

echo "✅ Python found: $(python3 --version)"
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
    echo "✅ Virtual environment created"
else
    echo "✅ Virtual environment already exists"
fi
echo ""

# Activate virtual environment
echo "🔌 Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "📥 Installing dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "✅ Dependencies installed"
echo ""

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "⚙️  Creating .env file..."
    cp .env.example .env
    echo "✅ .env file created"
    echo ""
    echo "⚠️  IMPORTANT: Edit .env and add your API keys:"
    echo "   - OPENAI_API_KEY"
    echo "   - API_BASE_URL"
    echo ""
    read -p "Press Enter after you've configured .env..."
else
    echo "✅ .env file already exists"
fi
echo ""

# Verify setup
echo "🔍 Verifying setup..."
python verify_setup.py
echo ""

# Ask to run the app
echo "=================================================="
echo ""
read -p "🚀 Ready to launch the app? (y/n) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo "🎉 Starting Civic App..."
    echo "   The app will open in your browser at http://localhost:8501"
    echo ""
    streamlit run app/main.py
else
    echo ""
    echo "To start the app later, run:"
    echo "  source venv/bin/activate"
    echo "  streamlit run app/main.py"
    echo ""
fi
