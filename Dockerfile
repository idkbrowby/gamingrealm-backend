FROM python:3.11-slim

ENV POETRY_VERSION=1.5.0 \
    PIP_NO_CACHE_DIR=1

WORKDIR /GR-backend/

RUN pip install -U poetry

COPY ./pyproject.toml ./poetry.lock* ./

RUN poetry install --no-root --without dev

RUN mkdir ./prisma/

COPY prisma/schema.prisma  ./prisma/

COPY prisma/prisma_partial_types.py ./prisma/

RUN poetry run prisma generate

COPY . .

ENTRYPOINT ["./scripts/entrypoint.sh"]
