FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV HOST=0.0.0.0
ENV PORT=8080
ENV OPS_DB_PATH=data/ops_bot.sqlite3
EXPOSE 8080
CMD ["python", "-m", "app.server"]
