# whisper.cpp HTTP server (CPU). Build context: ./whisper.cpp
FROM ubuntu:22.04 AS build
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential cmake git \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY . .
RUN cmake -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DWHISPER_BUILD_TESTS=OFF \
 && cmake --build build -j --target whisper-server

FROM ubuntu:22.04
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/build/bin/whisper-server /usr/local/bin/whisper-server
EXPOSE 8080
ENTRYPOINT ["whisper-server", "--host", "0.0.0.0", "--port", "8080"]
CMD ["-m", "/models/ggml-base.en.bin"]
