"""모델 카드(artifacts/model.json)를 쓴다 — 이 모델 버전이 무엇인지 적은 한 장.

    uv run python -m training.model_card

- 버전 이름은 m<날짜>-<실행 번호>  (예: 11월 16일 3번째 실행이면 m20261116-3)
- 서버의 /health 가 여기서 model_version 을 읽고,
  승격 스크립트(deploy/lightsail/models.py)도 이 카드에서 버전 이름을 읽는다.
- 학습(train_sklearn)이 남긴 artifacts/metrics_sklearn.json 이 있어야 한다.
"""
import datetime
import json
import os

METRICS = "artifacts/metrics_sklearn.json"  # 학습이 남긴 지표 — 데이터·성능
CARD = "artifacts/model.json"  # 이 스크립트가 쓰는 모델 카드


def version_name(now: datetime.datetime) -> str:
    """버전 이름 m<날짜>-<실행 번호>. Actions 밖(내 PC)에서는 실행 번호가 0이다."""
    run_number = os.getenv("GITHUB_RUN_NUMBER", "0")  # 이 워크플로의 몇 번째 실행인지
    return f"m{now:%Y%m%d}-{run_number}"  # 예: m20261116-3


def run_url() -> str:
    """이 모델을 만든 Actions 실행의 주소. 나중에 로그를 되짚을 때 쓴다."""
    server = os.getenv("GITHUB_SERVER_URL", "")  # 예: https://github.com
    repo = os.getenv("GITHUB_REPOSITORY", "")  # 예: allieus/eta-mini-aws
    run_id = os.getenv("GITHUB_RUN_ID", "")  # 예: 44008258923
    return f"{server}/{repo}/actions/runs/{run_id}"  # 예: https://github.com/allieus/eta-mini-aws/actions/runs/44008258923


def build_card(metrics: dict, now: datetime.datetime) -> dict:
    """모델 카드 내용 — 버전 이름, 어느 코드(git_sha)·데이터(data)에서 나왔는지, 성능(mae)."""
    return {
        "model_version": version_name(now),
        "git_sha": os.getenv("GITHUB_SHA", "local"),  # 학습한 코드의 커밋
        "run_url": run_url(),
        "data": metrics["data"],  # 데이터 건수·시드
        "mae": metrics["mae"],  # 평균 오차(분)
        "baseline_mae": metrics["baseline_mae"],  # 규칙 공식(api/predictors/rule.py) 기준선의 오차
        "created_at": now.isoformat(timespec="seconds"),
    }


def main() -> None:
    with open(METRICS, encoding="utf-8") as f:
        metrics = json.load(f)
    card = build_card(metrics, datetime.datetime.now(datetime.timezone.utc))
    with open(CARD, "w", encoding="utf-8") as f:
        json.dump(card, f, indent=2, ensure_ascii=False)
    print(json.dumps(card, indent=2, ensure_ascii=False))  # Actions 로그에서 바로 보이게


if __name__ == "__main__":
    main()
