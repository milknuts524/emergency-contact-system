#!/bin/bash

cd ~/emergency_contact
source venv/bin/activate

if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

# 既存の8000番サーバを停止
lsof -ti:8000 | xargs kill 2>/dev/null

# サーバ起動
uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
SERVER_PID=$!

sleep 3

# ローカル画面を開く
open http://127.0.0.1:8000

# Cloudflare Tunnel 起動
rm -f current_url.txt cloudflared.log
cloudflared tunnel --url http://localhost:8000 > cloudflared.log 2>&1 &
CLOUDFLARED_PID=$!

for i in {1..30}; do
  CURRENT_URL=$(grep -Eo 'https://[A-Za-z0-9.-]+\.trycloudflare\.com' cloudflared.log | tail -n 1)
  if [ -n "$CURRENT_URL" ]; then
    echo "$CURRENT_URL" > current_url.txt
    echo "Cloudflare URL: $CURRENT_URL"
    break
  fi
  sleep 1
done

echo ""
echo "FastAPI PID: $SERVER_PID"
echo "Cloudflared PID: $CLOUDFLARED_PID"
echo ""
echo "Cloudflare URL は current_url.txt に保存されます。"
echo "Cloudflared のログは cloudflared.log に保存されます。"
echo "終了するときは、このターミナルで control + C を押してください。"
echo ""

wait
