#!/bin/bash
PORT=8000

uvicorn backend.api.main:get_app \
  --factory \
  --reload \
  --reload-dir backend \
  --reload-dir context \
  --port $PORT
