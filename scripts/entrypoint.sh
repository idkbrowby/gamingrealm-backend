#!/bin/bash
extra_options=""
if [[ $DEBUG != "false" ]]; then
    extra_options="--reload --reload-dir ./src"
fi

poetry run prisma migrate deploy
poetry run uvicorn src.backend.app:app --host 0.0.0.0 $extra_options
