# 🏙️ Civic App Backend - Singapore Government Data Assistant

A FastAPI backend service that provides REST API endpoints for accessing Singapore government data through natural language queries. This backend processes user queries, matches them to appropriate government APIs, and returns structured, visualization-ready data.

## 🌟 Features

- **Natural Language API**: REST endpoint that accepts plain English queries
- **Smart Endpoint Matching**: AI-powered semantic search to find the right data endpoint
- **Structured Responses**: Returns data with visualization hints for frontend consumption
- **Real-time Data**: Access live data from Singapore government APIs
- **Auto-generated API Docs**: Interactive documentation at `/docs`
- **Frontend Agnostic**: Any frontend can consume the REST API

## 🏗️ Architecture

The backend follows a modular pipeline architecture:

1. **API Request Handling**: FastAPI endpoint receives natural language queries
2. **Endpoint Selection**: Semantic search + LLM parameter extraction (2-stage optimization)
3. **Query Building**: Parameter validation and payload construction
4. **API Trigger**: Async HTTP client for calling government APIs
5. **Data Processing**: Transform responses into visualization-ready formats
6. **Response Formation**: Return structured JSON with visualization hints

See [civic-app-architecture.md](design_docs/civic-app-architecture.md) for detailed architecture documentation.

## 🚀 Quick Start

### Prerequisites

- Python 3.10 or higher
- OpenAI API key ([Get one here](https://platform.openai.com/api-keys))
- Access to Singapore government data trigger API

### Installation

**Option 1: Using the Quick Start Script (Recommended)**

1. **Clone the repository** (if not already done):
   ```bash
   cd civic-app
   ```

2. **Run the quick start script**:
   ```bash
   ./start_server.sh
   ```
   
   This script will:
   - Create a virtual environment
   - Install all dependencies
   - Check for .env configuration
   - Start the FastAPI server

3. **Configure your API keys** (if prompted):
   Edit the `.env` file with your OpenAI API key and API base URL

**Option 2: Manual Setup**

1. **Clone the repository**:
   ```bash
   cd civic-app
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**:
   ```bash
   cp .env.example .env
   ```
   
   Edit `.env` and add your API keys:
   ```env
   OPENAI_API_KEY=your-openai-api-key-here
   API_BASE_URL=https://your-api-base-url
   LOG_LEVEL=INFO
   ```

5. **Run the backend server**:
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

6. **Access the API**:
   - API Documentation (Swagger): `http://localhost:8000/docs`
   - Alternative Docs (ReDoc): `http://localhost:8000/redoc`
   - Health Check: `http://localhost:8000/health`

### Docker Deployment

**Build and run with Docker Compose**:

```bash
# Make sure .env file is configured
docker-compose up --build
```

The API will be available at `http://localhost:8000`

## 📡 API Usage

### Query Endpoint

**POST** `/api/query`

Process a natural language query and return structured data.

**Request Body**:
```json
{
  "query": "What's the temperature in Singapore today?",
  "session_id": "optional-session-uuid",
  "context": {}
}
```

**Response**:
```json
{
  "status": "success",
  "data": {
    "records": [...],
    "summary_stats": {...},
    "chart_configs": [...]
  },
  "visualization_type": "time_series",
  "metadata": {
    "timestamp": "2026-02-08T10:00:00",
    "endpoint_id": "uuid-123"
  },
  "error": null
}
```

### List Available Endpoints

**GET** `/api/endpoints`

Get a list of all available Singapore government data API endpoints.

**Response**:
```json
{
  "total": 10,
  "endpoints": [
    {
      "id": "uuid-123",
      "description": "Get air temperature readings",
      "parameters": [...]
    }
  ]
}
```

### Health Check

**GET** `/health`

Check if the backend service is running.

**Response**:
```json
{
  "status": "healthy",
  "service": "civic-app-backend",
  "version": "1.0.0"
}
```

## 💬 Example Queries

Try sending POST requests to `/api/query` with questions like:

- "What's the temperature today?"
- "Show me air temperature readings"
- "Get temperature data for yesterday"
- "Where are the buses right now?"

**Using curl**:
```bash
curl -X POST "http://localhost:8000/api/query" \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the temperature in Singapore today?"}'
```

**Using Python**:
```python
import requests

response = requests.post(
    "http://localhost:8000/api/query",
    json={"query": "What's the temperature today?"}
)

data = response.json()
print(data)
```

## 📁 Project Structure

```
civic-app/
├── app/
│   ├── main.py                    # FastAPI application
│   ├── models.py                  # Pydantic request/response models
│   ├── endpoint_matcher.py        # LLM-based endpoint matching
│   ├── api_client.py              # API trigger logic
│   ├── data_processor.py          # Data transformation
│   └── utils.py                   # Helper functions & response formatter
│
├── design_docs/
│   ├── civic-app-architecture.md  # Architecture documentation
│   ├── endpoint-schema-api-response.json  # API endpoint schemas
│   └── data-gov-apis-definations/ # API integration guides
│
├── tests/                         # Unit tests
├── notebooks/                     # Jupyter notebooks for exploration
├── requirements.txt               # Python dependencies
├── Dockerfile                     # Docker configuration
├── docker-compose.yml             # Docker Compose configuration
├── start_server.sh                # Quick start script
├── .env.example                   # Environment variables template
└── README.md                      # This file
```

## 🔧 Configuration

### Environment Variables

- `OPENAI_API_KEY`: Your OpenAI API key (required)
- `API_BASE_URL`: Base URL for the Singapore government data trigger API (required)
- `LOG_LEVEL`: Logging level (optional, default: INFO)

### CORS Configuration

For production, update the CORS settings in `app/main.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://your-frontend-domain.com"],  # Specify your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
secondaryBackgroundColor = "#F0F2F6"
textColor = "#262730"
font = "sans serif"
```

## 🧪 Development

### Running Tests

```bash
pytest tests/
```

### Code Structure

- **endpoint_matcher.py**: Implements semantic search using embeddings and LLM-based parameter extraction
- **api_client.py**: Handles HTTP communication with government APIs
- **data_processor.py**: Processes different data types (GeoJSON, time-series, tabular)
- **visualizers.py**: Renders appropriate visualizations using Plotly and Folium
- **utils.py**: Query building and validation utilities

## 📊 Supported Data Types

- **Time-Series Data**: Temperature, weather readings, etc.
  - Line charts, bar charts, statistics
  
- **Geospatial Data**: Bus locations, facility locations
  - Interactive maps with markers
  
- **Tabular Data**: Generic structured data
  - Data tables with search and filter

## 🚢 Deployment

### Docker (Recommended)

```bash
# Using Docker Compose
docker-compose up --build

# Or build and run manually
docker build -t civic-app-backend .
docker run -p 8000:8000 --env-file .env civic-app-backend
```

### Cloud Platforms

- **AWS**: ECS, EKS, or Lambda + API Gateway
- **Google Cloud**: Cloud Run, GKE
- **Azure**: Container Apps, AKS
- **Heroku/Railway**: Connect GitHub repo and deploy

### Manual Deployment

```bash
# Install dependencies
pip install -r requirements.txt

# Run with gunicorn (production)
gunicorn -w 4 -k uvicorn.workers.UvicornWorker app.main:app --bind 0.0.0.0:8000
```

## 🛠️ Technology Stack

- **Backend**: FastAPI
- **LLM Framework**: LangChain + OpenAI
- **Data Processing**: Pandas, NumPy
- **HTTP Client**: httpx (async)
- **Embeddings**: OpenAI Embeddings + scikit-learn

## 📈 Performance

The backend uses an optimized two-stage approach:
- **Stage 1**: Semantic search with embeddings (fast, no LLM)
- **Stage 2**: Parameter extraction with LLM (only for matched endpoints)

**Benefits**:
- 75-80% cost reduction
- 2-3x faster response time
- Scales to 100+ endpoints

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📝 License

[Add your license here]

## 📧 Contact

[Add your contact information here]

## 🙏 Acknowledgments

- Singapore Government Open Data APIs
- LangChain community
- FastAPI team

---

Built with ❤️ for Singapore
