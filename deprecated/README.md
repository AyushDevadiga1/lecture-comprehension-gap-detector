# 📦 Deprecated: Legacy Streamlit Frontend

This folder contains the original Streamlit prototype frontend (`frontend/`) and its configuration (`.streamlit/`).

## Status: Deprecated & Archived
As of Engine 2, the primary user interface is the **React + Vite single-page application** located in [`/frontend-react`](../frontend-react).

## Contents
- **`frontend/student_app.py`**: Legacy student dashboard
- **`frontend/faculty_app.py`**: Legacy faculty dashboard
- **`frontend/client.py`**: Python HTTP client wrapper for FastAPI backend
- **`frontend/panels/`**: Legacy Streamlit UI components
- **`frontend/render.py`**: Dependency-free SVG DAG renderer
- **`.streamlit/config.toml`**: Streamlit theme and server configuration

This code is retained for historical reference and to support existing backend integration test fixtures.
