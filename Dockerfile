FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY cybers.py .
COPY players/ players/
COPY scenarios/ scenarios/
COPY static/ static/

# Expose port (Railway overrides with $PORT at runtime)
EXPOSE 8021

# Use $PORT if set (Railway), fall back to 8021 (local)
CMD ["sh", "-c", "uvicorn cybers:app --host 0.0.0.0 --port ${PORT:-8021}"]
