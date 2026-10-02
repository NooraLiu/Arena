# Arena web app: humans play from any browser, the app plays the AI seats (Claude API or rule bots).
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir openpyxl "anthropic>=1.0"
COPY . .
ENV ARENA_HOST=0.0.0.0 \
    PORT=8000 \
    ARENA_STATE=/app/play/game.pkl \
    PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python3", "app/server.py"]
