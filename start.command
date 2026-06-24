#!/bin/bash

cd ~/emergency_contact
source venv/bin/activate

if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

PUBLIC_URL_MODE=${PUBLIC_URL_MODE:-dynamic}
CLOUDFLARED_TUNNEL_NAME=${CLOUDFLARED_TUNNEL_NAME:-emergency}

echo "Emergency Contact System starting..."
echo ""

# 既存の8000番サーバを停止
lsof -ti:8000 | xargs kill 2>/dev/null

# 既存のcloudflaredプロセスを停止
pkill -f "cloudflared tunnel --url http://localhost:8000" 2>/dev/null
pkill -f "cloudflared tunnel run $CLOUDFLARED_TUNNEL_NAME" 2>/dev/null

# サーバ起動
uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
SERVER_PID=$!

sleep 3
echo "FastAPI起動完了"

rm -f cloudflared.log
if [ "$PUBLIC_URL_MODE" = "fixed" ]; then
  echo "Mode: fixed"
  echo "Cloudflare: Named Tunnel $CLOUDFLARED_TUNNEL_NAME"
  cloudflared tunnel run "$CLOUDFLARED_TUNNEL_NAME" > cloudflared.log 2>&1 &
  CLOUDFLARED_PID=$!
  echo "Cloudflare Named Tunnel起動完了"
  echo "固定URL運用中"
else
  PUBLIC_URL_MODE="dynamic"
  echo "Mode: dynamic"
  echo "Cloudflare: TryCloudflare temporary URL"
  rm -f current_url.txt
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
fi

# ローカル画面を開く
open http://127.0.0.1:8000

echo ""
echo "FastAPI PID: $SERVER_PID"
echo "Cloudflared PID: $CLOUDFLARED_PID"
if [ "$PUBLIC_URL_MODE" = "fixed" ]; then
  echo "Cloudflare Named Tunnel: $CLOUDFLARED_TUNNEL_NAME"
else
  echo "Cloudflare URL は current_url.txt に保存されます。"
fi
echo ""
echo "固定URLは ~/.cloudflared/config.yml で管理されます。"
echo "Cloudflared のログは cloudflared.log に保存されます。"
echo "終了するときは、このターミナルで control + C を押してください。"
echo ""

wait
