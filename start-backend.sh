#!/bin/bash
cd /home/kwhittenberger/repos/ice_violent_confrontations
source .venv/bin/activate
set -a
source .env
set +a
cd backend
USE_DATABASE=true uvicorn main:app --host 127.0.0.1 --port 8000 --reload
