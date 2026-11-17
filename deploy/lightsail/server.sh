#!/bin/bash
# 서버에서 도는 배포 스크립트.
#   server.sh image <태그> <이미지 경로>   stdin 으로 GHCR 토큰 한 줄
#   server.sh model <모델 판>   /srv/eta/models/<판>/ 에 놓인 모델로 바꾼다 (승격·되돌리기 공통)
#   server.sh status
set -euo pipefail
cd /srv/eta
touch .env
# setenv 키 값 : .env 에서 그 키 줄을 새 값으로 바꾼다 (바라는 상태 기록)
setenv() { grep -v "^$1=" .env > .env.new || true; echo "$1=$2" >> .env.new; mv .env.new .env; }
# health [판] : /health 가 응답할 때까지 30초 기다린다. 판을 주면 model_version 이 그 판일 때만 성공
health() {
  for i in $(seq 1 30); do
    H=$(curl -fsS localhost/health 2>/dev/null) && { [ -z "${1:-}" ] || echo "$H" | grep -q "\"model_version\":\"$1\""; } \
      && echo "$H" && return 0
    sleep 1
  done
  echo "health 실패" >&2; return 1
}
case "$1" in
  image) # 코드 배포 : 새 이미지 받기 → .env 의 TAG 바꿔 띄우기 → health 실패면 이전 TAG 로
    TAG=$2 IMAGE=$3
    [[ $TAG =~ ^v[0-9]+(\.[0-9]+)*$ ]] || { echo "태그 형식이 아니다: $TAG" >&2; exit 1; }
    read -r TOKEN # 토큰은 stdin 으로만 받는다 (명령 인자에 남지 않게)
    export DOCKER_CONFIG=$(mktemp -d)
    trap 'rm -rf "$DOCKER_CONFIG"' EXIT
    printf %s "$TOKEN" | docker login ghcr.io -u token --password-stdin >/dev/null
    PREV=$(grep '^TAG=' .env | cut -d= -f2 || true)
    docker pull -q "$IMAGE/eta-go:$TAG"
    setenv IMAGE "$IMAGE"; setenv TAG "$TAG"
    docker compose up -d
    if ! health; then
      [ -n "$PREV" ] && { setenv TAG "$PREV"; docker compose up -d; }
      exit 1
    fi
    ;;
  model) # 모델 배포·되돌리기 : .env 의 MODEL_* 바꿔 띄우기 → 그 판이 안 뜨면 이전 판으로
    VER=$2
    [[ $VER =~ ^m[0-9]{8}-[0-9]+$ ]] || { echo "모델 판 형식이 아니다: $VER" >&2; exit 1; }
    [ -f "models/$VER/model_sklearn.onnx" ] && [ -f "models/$VER/model.json" ] || { echo "models/$VER 가 없다" >&2; exit 1; }
    PREV=$(grep '^MODEL_VERSION=' .env | cut -d= -f2 || true)
    setenv MODEL_VERSION "$VER"; setenv MODEL_DIR "/models/$VER"
    docker compose up -d
    if ! health "$VER"; then
      if [ -n "$PREV" ]; then setenv MODEL_VERSION "$PREV"; setenv MODEL_DIR "/models/$PREV"
      else sed -i '/^MODEL_VERSION=/d; /^MODEL_DIR=/d' .env; fi
      docker compose up -d; exit 1
    fi
    ;;
  status) # 지금 상태 : .env, 컨테이너, /health
    cat .env; docker compose ps --format '{{.Service}} {{.Image}} {{.Status}}'; health ;;
  *) echo "사용: server.sh image|model|status" >&2; exit 2 ;;
esac
