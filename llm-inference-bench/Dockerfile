FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        docker-cli \
        docker-compose \
        git \
        openssh-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY llm_decode_bench.py /app/llm_decode_bench.py
COPY app/ /app/app/

# Bakes the exact commit this image was built from into every benchmark
# result's "bench_tool_commit" field (see llm_decode_bench.py's
# save_results) - the image has no .git dir of its own to self-report from,
# so CI passes it as a build-arg (--build-arg GIT_SHA=${{ github.sha }},
# see .github/workflows/build.yml).
ARG GIT_SHA=unknown
ENV BENCH_GIT_SHA=${GIT_SHA}

RUN useradd --uid 1000 --create-home bench

RUN mkdir -p /bench-key

EXPOSE 8092

CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8092"]
