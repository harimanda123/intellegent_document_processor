# Intelligent Document Processing (IDP)

AI-powered document extraction platform that leverages Large Language Models (LLMs) to extract structured data from PDFs and images.

**🌐 Live Demo:** [GitHub Repository](https://github.com/harimanda123/intellegent_document_processor)

---

## 📋 Overview

IDP is a comprehensive document processing system that:
- **Uploads** PDFs and images (TIFF, JPG, PNG)
- **Extracts** text and tables using OCR
- **Structures** data according to user-defined schemas
- **Reviews** extraction quality with confidence scoring
- **Delivers** results via download or direct ERP system integration

The system is designed to be modular, with configurable LLM providers and flexible schema definitions.

---

## ✨ Key Features

### Document Processing
- **Multi-format Support**: PDF, TIFF, JPG, PNG (up to 50MB)
- **OCR & Text Extraction**: Accurate text extraction with spatial positioning
- **Table Detection**: Automatic detection and structured extraction of tables
- **Page-level Processing**: Handle multi-page documents with per-page analysis

### AI-Powered Extraction
- **Schema-based Extraction**: Define custom extraction schemas with field rules
- **LLM Flexibility**: Support for multiple LLM providers (Groq, OpenAI, Anthropic, Ollama)
- **Confidence Scoring**: Track extraction quality with confidence metrics
- **Field Validation**: Automatic validation against schema rules

### Review & Quality Control
- **Manual Review**: Built-in UI for reviewing and correcting extractions
- **Auto-Review**: Automatic routing based on confidence thresholds
- **Audit Logging**: Complete audit trail of all document processing and reviews
- **Feedback Loop**: Schema improvement through user feedback

### Integration
- **REST API**: Full REST API for programmatic access
- **ERP Integration**: Direct delivery to ERP systems with reference tracking
- **UI Dashboard**: Streamlit-based web interface
- **Async Processing**: Background task processing for scalability

---

## 🏗️ Architecture

```
┌─────────────────┐          ┌──────────────────────┐
│   UI (Streamlit)│──────────│  FastAPI Backend     │
│   - Dashboard   │          │  - API Endpoints     │
│   - Upload      │          │  - Schema Manager    │
│   - Review      │          │  - Pipeline Executor │
└─────────────────┘          └──────────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                 │                 │
                 ┌──▼──┐         ┌───▼────┐       ┌───▼────┐
                 │ OCR │         │ Tables │       │  LLM   │
                 │Srv  │         │ Srv    │       │ Srv    │
                 └──┬──┘         └───┬────┘       └───┬────┘
                    │                │                │
                    └────────────────┼────────────────┘
                                     │
                            ┌────────▼────────┐
                            │  SQLite DB      │
                            │  - Documents    │
                            │  - Extractions  │
                            │  - Schemas      │
                            │  - Audit Logs   │
                            └─────────────────┘
```

---

## 🛠️ Tech Stack

### Backend
- **Framework**: FastAPI (Python 3.11+)
- **ORM**: SQLAlchemy 2.0
- **Database**: SQLite (PostgreSQL compatible)
- **Document Processing**: PyMuPDF, Instructor
- **LLM Integration**: OpenAI, Groq, Anthropic SDKs

### Frontend
- **Framework**: Streamlit
- **State Management**: Streamlit session state
- **API Client**: Requests library

### Infrastructure
- **Server**: Uvicorn
- **Task Queue**: Background tasks (FastAPI)
- **File Storage**: Local filesystem

---

## 📦 Installation & Setup

### Prerequisites
- Python 3.11+
- pip or conda
- 50MB disk space for uploads
- API keys (if using cloud LLM providers)

### 1. Clone Repository
```bash
git clone https://github.com/harimanda123/intellegent_document_processor.git
cd intellegent_document_processor
```

### 2. Create Virtual Environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -e .
```

### 4. Configure Environment
Create `.env` file in project root:

```bash
# ── LLM Configuration ─────────────────────────────────────────────────
LLM_PROVIDER=groq              # Options: groq, openai, anthropic, ollama, openai_compatible
LLM_API_KEY=your-api-key-here
LLM_MODEL=llama-3.3-70b-versatile
LLM_BASE_URL=                  # Leave empty for default, required for ollama/custom endpoints

# ── Database ───────────────────────────────────────────────────────
DATABASE_URL=sqlite:///./idp.db    # Or: postgresql://user:pass@host/db

# ── App ────────────────────────────────────────────────────────────
APP_HOST=0.0.0.0
APP_PORT=8000
UPLOAD_DIR=./uploads
MAX_FILE_SIZE_MB=50

# ── Review ─────────────────────────────────────────────────────────
AUTO_REVIEW_THRESHOLD=0.80     # Confidence threshold for auto-review

# ── CORS ───────────────────────────────────────────────────────────
CORS_ORIGINS=http://localhost:5173
```

### 5. Initialize Database
```bash
python -c "from app.database import init_db; init_db()"
```

---

## 🚀 Usage

### Start Backend API
```bash
python main.py
```
API available at: `http://localhost:8000`
OpenAPI docs at: `http://localhost:8000/docs`

### Start Frontend UI
```bash
streamlit run ui/app.py
```
UI available at: `http://localhost:8501`

---

## 📚 API Endpoints

### Documents
- `POST /documents/upload` - Upload document for extraction
- `GET /documents/{doc_id}` - Get document details and status
- `GET /documents/{doc_id}/extractions` - Get extracted data
- `POST /documents/{doc_id}/review` - Submit review feedback
- `GET /documents/{doc_id}/json` - Download extraction as JSON
- `POST /documents/{doc_id}/retry` - Retry failed extraction

### Schemas
- `POST /schemas` - Create new extraction schema
- `GET /schemas` - List all schemas
- `GET /schemas/{schema_id}` - Get schema details
- `PATCH /schemas/{schema_id}` - Update schema
- `DELETE /schemas/{schema_id}` - Delete schema
- `POST /schemas/{schema_id}/feedback` - Submit schema feedback

### ERP Integration
- `POST /erp/documents` - Submit document via ERP
- `GET /erp/documents/{erp_ref_id}` - Get ERP document status
- `GET /erp/documents/{erp_ref_id}/result` - Deliver extraction result

### Dashboard
- `GET /dashboard/stats` - Get system statistics
- `GET /dashboard/queue` - Get processing queue status

---

## 🗄️ Database Schema

### Documents Table
- `id` - Unique document identifier (UUID)
- `filename` - Original filename
- `file_path` - Stored file location
- `file_size` - File size in bytes
- `schema_id` - Associated extraction schema
- `state` - Processing state (RECEIVED, PROCESSING, VERIFIED, PENDING_REVIEW, FAILED, ABANDONED, DOWNLOADED)
- `progress` - Current processing stage
- `source` - Upload source (ui, erp)
- `require_review` - Manual review required flag
- `require_review_mode` - Review mode (false, true, auto)
- `error_code`, `error_message` - Error information
- `created_at`, `updated_at` - Timestamps

### Extractions Table
- `id` - Extraction record ID
- `document_id` - Reference to document
- `page_number` - Page being extracted
- `extracted_data` - Structured JSON extraction
- `confidence` - Extraction confidence score
- `raw_text` - Full OCR text
- `created_at` - Extraction timestamp

### Schemas Table
- `id` - Schema identifier
- `name` - Schema name
- `version` - Schema version
- `field_definitions` - Schema field specifications
- `rules` - Extraction rules
- `created_by` - Creator information
- `created_at`, `updated_at` - Timestamps

### Audit Logs Table
- `id` - Log entry ID
- `document_id` - Related document
- `action` - Action performed
- `details` - Action details JSON
- `created_at` - Timestamp

---

## 🔧 Configuration

### LLM Providers

#### Groq (Recommended for free tier)
```env
LLM_PROVIDER=groq
LLM_API_KEY=gsk_xxxxxxxxxxxx
LLM_MODEL=llama-3.3-70b-versatile
```
[Get Groq API Key](https://console.groq.com)

#### OpenAI
```env
LLM_PROVIDER=openai
LLM_API_KEY=sk-xxxxxxxxxxxx
LLM_MODEL=gpt-4o
```

#### Anthropic
```env
LLM_PROVIDER=anthropic
LLM_API_KEY=sk-ant-xxxxxxxxxxxx
LLM_MODEL=claude-3-5-sonnet-20241022
```

#### Ollama (Local)
```env
LLM_PROVIDER=ollama
LLM_API_KEY=ollama
LLM_MODEL=llama3
LLM_BASE_URL=http://localhost:11434
```

### Review Threshold
The `AUTO_REVIEW_THRESHOLD` determines when documents are automatically flagged for review:
- Documents with avg_confidence < threshold → PENDING_REVIEW state
- Documents with avg_confidence ≥ threshold → VERIFIED state

---

## 📖 Project Structure

```
project-root/
├── app/
│   ├── main.py              # FastAPI app entry point
│   ├── config.py            # Configuration management
│   ├── database.py          # Database setup
│   ├── models/
│   │   ├── document.py      # Document & Extraction models
│   │   └── schema.py        # Schema & Feedback models
│   ├── routers/
│   │   ├── documents.py     # Document upload/retrieval
│   │   ├── schemas.py       # Schema management
│   │   ├── erp.py           # ERP integration
│   │   └── dashboard.py     # Statistics & monitoring
│   └── services/
│       ├── ocr_service.py   # OCR & text extraction
│       ├── llm_service.py   # LLM integration & field extraction
│       ├── table_service.py # Table detection
│       ├── pipeline.py      # Main processing pipeline
│       └── feedback_service.py # Schema feedback handling
├── ui/
│   ├── app.py               # Streamlit main page
│   ├── api_client.py        # API wrapper
│   ├── cached_api.py        # Response caching
│   ├── components.py        # UI components
│   └── pages/
│       ├── 1_Documents.py   # Upload & browse
│       ├── 2_Schema_Builder.py # Schema management
│       ├── 3_Dashboard.py   # Statistics
│       └── 4_Analytics.py   # Usage analytics
├── uploads/                 # Uploaded files (generated)
├── specs/                   # API specifications (OpenAPI)
├── pyproject.toml          # Project metadata & dependencies
├── .env                    # Environment variables
└── README.md               # This file
```

---

## 🔄 Processing Pipeline

1. **Upload** - Document uploaded via UI or ERP endpoint
2. **Validate** - File type and size validation
3. **OCR** - Extract text and positions using PyMuPDF
4. **Layout Analysis** - Strip headers/footers, identify sections
5. **Table Detection** - Identify and extract table structures
6. **Schema Loading** - Load relevant extraction schema
7. **LLM Extraction** - Extract fields using schema rules
8. **Validation** - Validate extracted data against schema
9. **Review Decision** - Route to manual review or auto-verify based on confidence
10. **Complete** - Document marked as VERIFIED or PENDING_REVIEW

---

## 🧪 Error Handling & Retry

The pipeline includes automatic retry logic for transient failures:

### Retryable Errors (Max 3 retries)
- `OCR_FAILED` - OCR service temporary failure
- `EXTRACTION_FAILED` - LLM service temporary failure
- `PIPELINE_ERROR` - Unexpected pipeline error

### Non-retryable Errors
- `INVALID_FILE` - Unsupported file format
- `FILE_CORRUPTED` - Corrupted file
- `SCHEMA_NOT_FOUND` - Referenced schema not found

---

## 📊 Dashboard & Monitoring

The Dashboard page provides:
- **Document Statistics**: Total, processed, pending, failed counts
- **Processing Queue**: Real-time view of documents being processed
- **Error Summary**: Common errors and failure patterns
- **Performance Metrics**: Average processing time, confidence scores
- **LLM Usage**: Provider and model information

---

## 🔐 Security Considerations

- **File Upload**: Size limit enforced (50MB default, configurable)
- **Sensitive Data**: API keys stored in `.env`, never committed to git
- **CORS**: Configurable origins to prevent unauthorized access
- **Database**: SQLAlchemy ORM prevents SQL injection
- **Audit Logging**: Complete audit trail of all operations

---

## 📝 Example: Complete Workflow

### 1. Create a Schema
```bash
curl -X POST http://localhost:8000/schemas \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Invoice",
    "fields": [
      {"name": "invoice_number", "type": "string", "required": true},
      {"name": "amount", "type": "float", "required": true},
      {"name": "date", "type": "date", "required": true}
    ]
  }'
```

### 2. Upload Document
```bash
curl -X POST http://localhost:8000/documents/upload \
  -F "file=@invoice.pdf" \
  -F "schema_id=<schema-id>"
```

### 3. Poll Status
```bash
curl http://localhost:8000/documents/<doc-id>
```

### 4. Download Results
```bash
curl http://localhost:8000/documents/<doc-id>/json -o result.json
```

---

## 🐛 Troubleshooting

### Backend won't start
- Check `.env` file exists and is properly formatted
- Verify LLM API keys are valid
- Check port 8000 is not in use: `netstat -tuln | grep 8000`

### Documents stuck in PROCESSING
- Check backend logs for errors
- Verify LLM provider connectivity
- Retry via `/documents/{id}/retry` endpoint

### UI can't connect to backend
- Ensure backend is running on port 8000
- Check CORS_ORIGINS in `.env` includes UI origin
- Verify firewall allows localhost connections

### File upload fails
- Check file size < MAX_FILE_SIZE_MB
- Verify file format is supported (PDF, TIFF, JPG, PNG)
- Check uploads directory has write permissions

---

## 🤝 Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📄 License

This project is open source and available under the MIT License.

---

## 📞 Support

For issues, questions, or suggestions:
- Open an [issue on GitHub](https://github.com/harimanda123/intellegent_document_processor/issues)
- Check existing documentation
- Review API documentation at `/docs`

---

## 🎯 Roadmap

- [ ] Webhook support for delivery notifications
- [ ] Batch processing API
- [ ] Advanced table extraction with merge cell handling
- [ ] Custom OCR model training
- [ ] Document version control
- [ ] Multi-language support
- [ ] Docker containerization
- [ ] Kubernetes deployment examples
- [ ] Performance monitoring dashboards
- [ ] GraphQL API support

---

**Built with ❤️ using FastAPI, Streamlit, and LLMs**