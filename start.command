#!/bin/bash

cd ~/emergency_contact
source venv/bin/activate

# 既存の8000番サーバを停止
lsof -ti:8000 | xargs kill 2>/dev/null

# サーバ起動
uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
SERVER_PID=$!

sleep 3

open http://127.0.0.1:8000

wait $SERVER_PID