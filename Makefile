.PHONY: whisper gateway down logs

# Build and start the whisper.cpp server on its own.
# Override the model with: make whisper WHISPER_MODEL=ggml-large-v3-turbo-q5_0.bin
whisper:
	docker compose up -d --build whisper

# Build and start the G2 BLE gateway.
gateway:
	docker compose up -d --build gateway

# Stop and remove all containers.
down:
	docker compose down

# Follow logs. Limit to one service with: make logs S=whisper
logs:
	docker compose logs -f $(S)
