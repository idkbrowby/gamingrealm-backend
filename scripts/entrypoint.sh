#!/bin/bash
poetry run prisma migrate deploy
poetry run uvicorn src.backend.app:app --host 0.0.0.0 --reload --reload-dir ./src
