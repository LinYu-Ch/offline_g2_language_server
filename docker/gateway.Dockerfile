# men-g2-ble-gateway, headless. Build context: ./men-g2-ble-gateway
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8765
CMD ["python", "gateway_server.py", "--no-gui", "--host", "0.0.0.0", "--port", "8765"]
