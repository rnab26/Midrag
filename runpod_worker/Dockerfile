FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip git ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*
RUN ln -s /usr/bin/python3 /usr/bin/python

WORKDIR /opt

# FaceFusion does the actual swapping — this is the same open-source engine most
# commercial face-swap SaaS sites wrap. Pin to a known-good tag; bump deliberately.
RUN git clone --branch 3.0.0 --depth 1 https://github.com/facefusion/facefusion.git
WORKDIR /opt/facefusion
RUN python -m pip install --no-cache-dir -r requirements.txt

# Pre-download the default models so cold starts aren't spent fetching multi-GB
# weights. If this step fails or times out during build, it's safe to skip it
# and let facefusion download models on first real run instead.
RUN python facefusion.py force-download || true

WORKDIR /opt/worker
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY handler.py .

CMD ["python", "-u", "handler.py"]
