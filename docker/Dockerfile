# O laboratorio inteiro dentro de um container, para que o que roda na sua maquina seja
# o mesmo que roda na VPS depois, e para que o modelo local fique isolado do resto do
# sistema. Uma imagem so atende CPU e GPU: os wheels de torch com CUDA funcionam sem
# placa, apenas sem enxerga-la. A diferenca entre os dois modos esta no compose.
#
# A imagem e grande (o torch traz as bibliotecas da NVIDIA). Para a VPS, o caminho certo
# e outro: o runtime ONNX do Laya dispensa torch inteiro. Ver docs/local.md.
FROM python:3.12-slim

# git: o resultado de cada execucao grava o commit do repositorio.
# libgomp1: runtime do OpenMP, que o torch usa em CPU.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /uvx /usr/local/bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYDANTIC_AI_NO_BANNER=1 \
    # Os pesos ficam num volume, fora da imagem: sao centenas de megabytes e nao
    # mudam entre builds. Sem isto, cada `docker compose up` baixaria de novo.
    HF_HOME=/cache/huggingface

WORKDIR /app

# As dependencias entram antes do codigo, para que editar um modulo nao invalide
# a camada que leva minutos para construir.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --extra painel --extra local

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra painel --extra local

# O diretorio de cache precisa existir e ser gravavel pelo usuario do compose.
RUN mkdir -p /cache/huggingface && chmod -R 777 /cache

EXPOSE 8501

# Sem argumento, abre o painel. Para a CLI:
#   docker compose run --rm lab lab rodar --modelo laya --limite 40
CMD ["lab", "painel", "--porta", "8501"]
