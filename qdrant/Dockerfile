# syntax=docker/dockerfile:1
#
# Qdrant rebuilt for ARM64 kernels with 16KB page size (Raspberry Pi 5 + Ubuntu).
#
# Root cause:
#   The official qdrant/qdrant image ships jemalloc compiled for 4KB pages.
#   Raspberry Pi 5 running Ubuntu uses PAGE_SIZE=16384 (2^14 bytes), so jemalloc
#   aborts immediately: "<jemalloc>: Unsupported system page size".
#   This is a compile-time issue — no runtime flag can fix a pre-compiled binary.
#
# Fix:
#   Recompile the Qdrant binary with JEMALLOC_SYS_WITH_LG_PAGE=14.
#   All other files (entrypoint, config templates, directory layout) are kept
#   from the official image — only the binary is replaced.
#
# Build and push (run on your LAPTOP, not on the Pi — cross-builds via QEMU):
#
#   docker buildx build \
#     --platform linux/arm64 \
#     -t ghcr.io/<GHCR_USERNAME>/qdrant-pi5:latest \
#     --push \
#     ./qdrant
#
# To upgrade Qdrant: bump QDRANT_VERSION below, rebuild, and push.
# Keep both ARG and the runtime FROM tag in sync.
#
ARG QDRANT_VERSION=v1.17.1

# ── Stage 1: Compile ─────────────────────────────────────────────────────────
FROM --platform=linux/arm64 rust:slim-bookworm AS builder
ARG QDRANT_VERSION

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    make \
    git \
    clang \
    libclang-dev \
    llvm-dev \
    libssl-dev \
    pkg-config \
    protobuf-compiler \
    libprotobuf-dev \
    libunwind-dev \
    zlib1g-dev \
    libbz2-dev \
    liblz4-dev \
    libzstd-dev \
    libgomp1 \
    curl \
    unzip \
    python3 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

RUN git clone --depth 1 --branch ${QDRANT_VERSION} \
    https://github.com/qdrant/qdrant.git .

# 2^14 = 16384 = 16 KB  ← the page size on Raspberry Pi 5 + Ubuntu ARM64.
# This environment variable is read by the tikv-jemalloc-sys crate at build
# time and passed as --with-lg-page=14 to the jemalloc configure script.
ENV JEMALLOC_SYS_WITH_LG_PAGE=14
ENV RUST_BACKTRACE=1
ENV PROTOC=/usr/bin/protoc
ENV PROTOC_INCLUDE=/usr/include

RUN cargo build --release --bin qdrant

# ── Stage 2: Runtime ─────────────────────────────────────────────────────────
# Use the official image for its entrypoint.sh, directory structure, and config.
# Only the binary (the part that contains jemalloc) is swapped out.
FROM --platform=linux/arm64 qdrant/qdrant:v1.17

COPY --chmod=0755 --from=builder /build/target/release/qdrant /qdrant/qdrant
