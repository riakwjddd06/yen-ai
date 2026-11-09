#!/bin/sh
# Vercel 빌드 때 실행: 환경변수 API_BASE_URL로 config.js를 만든다.
# 로컬에서는: API_BASE_URL=http://127.0.0.1:8000 sh build.sh
set -e
if [ -z "$API_BASE_URL" ]; then
  echo "API_BASE_URL 환경변수가 비어 있습니다." >&2
  exit 1
fi
echo "window.APP_CONFIG = { API_BASE_URL: \"$API_BASE_URL\" };" > config.js
echo "config.js 생성: $API_BASE_URL"
