# llama.cpp server for NVIDIA Jetson Thor (JetPack 7 / L4T r38.x, sm_110)
#
# IMPORTANT: NVIDIA never published an l4t-jetpack or l4t-base container for
# JetPack 7 / r38 and has stated there is no plan to. The supported path for
# containerized CUDA on Thor is the generic nvcr.io/nvidia/cuda Ubuntu 24.04
# images, which are published for arm64.
#
# CUDA 13.0 is chosen deliberately: the Thor driver reports CUDA 13.0 support.
# Building with a newer toolkit (e.g. 13.3) against a 13.0 driver produces:
#   "the provided PTX was compiled with an unsupported toolchain"
# Keep the toolkit at or below the driver's reported CUDA version.

ARG CUDA_TAG=13.0.0
ARG CUDA_ARCH=110

########################  BUILDER  ########################
FROM nvcr.io/nvidia/cuda:${CUDA_TAG}-devel-ubuntu24.04 AS builder

ARG CUDA_ARCH
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        git cmake build-essential ccache \
        libcurl4-openssl-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
ARG LLAMA_REF=master
RUN git clone --depth 1 --branch ${LLAMA_REF} https://github.com/ggml-org/llama.cpp.git

WORKDIR /src/llama.cpp
RUN cmake -B build \
        -DGGML_CUDA=ON \
        -DCMAKE_CUDA_ARCHITECTURES=${CUDA_ARCH} \
        -DCMAKE_BUILD_TYPE=Release \
        -DLLAMA_CURL=ON \
        -DLLAMA_BUILD_TESTS=OFF \
        -DLLAMA_BUILD_EXAMPLES=OFF \
        -DLLAMA_BUILD_SERVER=ON \
    && cmake --build build --config Release -j"$(nproc)" --target llama-server

RUN mkdir -p /opt/llama/bin /opt/llama/lib \
    && cp build/bin/llama-server /opt/llama/bin/ \
    && (cp build/bin/*.so /opt/llama/lib/ 2>/dev/null || true)

########################  RUNTIME  ########################
FROM nvcr.io/nvidia/cuda:${CUDA_TAG}-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 libcurl4 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/llama/bin/llama-server /usr/local/bin/llama-server
COPY --from=builder /opt/llama/lib/ /usr/local/lib/

ENV LD_LIBRARY_PATH=/usr/local/lib:/usr/local/cuda/targets/sbsa-linux/lib:/usr/local/cuda/lib64
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=all

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=180s --retries=20 \
    CMD curl -fsS http://127.0.0.1:8080/health || exit 1

ENTRYPOINT ["/usr/local/bin/llama-server"]
CMD ["--help"]
