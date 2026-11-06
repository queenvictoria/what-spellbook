#!/bin/bash
PORT=8000

uvicorn backend.api.main:get_app --factory --port $PORT
