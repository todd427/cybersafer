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

# Expose port
EXPOSE 8021

# Run
CMD ["uvicorn", "cybers:app", "--host", "0.0.0.0", "--port", "8021"]
