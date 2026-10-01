# whisper.cpp. One image for everything whisper-related:
#   whisper-server         HTTP transcription API              (service: whisper)
#   stream-entrypoint      live mic transcription and captions (service: stream)
#   download-ggml-model    model downloader                    (service: models)
# Build context: ./whisper.cpp   Extra context "support": ./docker
#
# CPU by default. docker/compose.gpu.yml (make ... GPU=1) builds the NVIDIA
# variant by swapping the base images for CUDA ones and setting GGML_CUDA=ON.
ARG BUILD_IMAGE=ubuntu:22.04
ARG RUNTIME_IMAGE=ubuntu:22.04

FROM ${BUILD_IMAGE} AS build
ARG GGML_CUDA=OFF
# Compute capabilities to compile for, e.g. "89" or "75;86;89" (GPU builds only).
ARG CUDA_ARCH=
# Parallel compile jobs; empty = one per core. nvcc needs a few GB per job, so
# GPU builds set a limit (docker/compose.gpu.yml) to stay inside Docker's memory.
ARG BUILD_JOBS=
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential cmake git libsdl2-dev \
 && rm -rf /var/lib/apt/lists/*
# GPU builds: there is no GPU or driver during `docker build`, so link against
# the CUDA forward-compat libcuda (as upstream's .devops/main-cuda.Dockerfile
# does). Build stage only; at runtime the real driver comes from the host.
ENV LD_LIBRARY_PATH=/usr/local/cuda/compat
WORKDIR /src
COPY . .
# WHISPER_SDL2 also enables the talk-llama example, whose configure step clones
# llama.cpp from GitHub. It is not needed here, so leave it out of this build.
RUN sed -i '/add_subdirectory(talk-llama)/d' examples/CMakeLists.txt \
 && cmake -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DWHISPER_BUILD_TESTS=OFF \
          -DWHISPER_SDL2=ON -DGGML_CUDA=${GGML_CUDA} ${CUDA_ARCH:+"-DCMAKE_CUDA_ARCHITECTURES=${CUDA_ARCH}"} \
 && cmake --build build -j ${BUILD_JOBS} --target whisper-server whisper-stream

FROM ${RUNTIME_IMAGE}
# libpulse0: SDL captures through PulseAudio (WSLg on Windows, the host's
# PulseAudio/PipeWire socket on Linux). pulseaudio-utils: pactl, for `make mic-check`.
# python3: g2_bridge.py (`make captions`). curl: model downloads (`make model`).
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 libsdl2-2.0-0 libpulse0 pulseaudio-utils \
                       python3 curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/build/bin/whisper-server /src/build/bin/whisper-stream /usr/local/bin/
COPY --from=support stream-entrypoint.sh /usr/local/bin/stream-entrypoint
COPY g2_bridge.py /usr/local/bin/g2_bridge.py
COPY models/download-ggml-model.sh /usr/local/bin/download-ggml-model
# Strip CRLF in case the scripts were checked out on Windows with autocrlf.
RUN sed -i 's/\r$//' /usr/local/bin/stream-entrypoint /usr/local/bin/g2_bridge.py /usr/local/bin/download-ggml-model \
 && chmod +x /usr/local/bin/stream-entrypoint /usr/local/bin/download-ggml-model
EXPOSE 8080
ENTRYPOINT ["whisper-server", "--host", "0.0.0.0", "--port", "8080"]
CMD ["-m", "/models/ggml-base.en.bin"]
