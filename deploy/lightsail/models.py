"""모델 버전 승격·되돌리기. 내 서버의 러너(Lightsail)가 부른다.

    python3 deploy/lightsail/models.py promote <파일 폴더>   버전 이름은 그 폴더의 model.json 에서
    python3 deploy/lightsail/models.py rollback <버전>

버킷 구조 (예: s3://<내 버킷 이름>/models/onnx/)
    m20261116-3/model_sklearn.onnx   모델 버전마다 폴더 하나 — 한 번 올리면 고치지 않는다
    m20261116-3/model.json           모델 카드 (training/model_card.py 가 쓴다)
    current.json                     포인터 — 지금 서비스 중인 버전

키는 없다. 서버는 버킷의 「리소스 액세스」로 aws 명령을 쓴다.
환경 변수: MODEL_BUCKET(저장소 변수), GITHUB_RUN_ID(Actions 가 넣는다).
Amazon Linux 2023 의 python3(3.9)과 aws CLI 만으로 돈다 — 따로 설치할 것이 없다.
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

SRV = "/srv/eta"  # 서버의 배포 폴더 (.env, compose.yml, server.sh, models/)
HERE = os.path.dirname(os.path.abspath(__file__))  # 체크아웃의 deploy/lightsail
S3 = f's3://{os.environ["MODEL_BUCKET"]}/models/onnx'  # 예: s3://<내 버킷 이름>/models/onnx
FILES = ("model_sklearn.onnx", "model.json")  # 모델 버전 하나에 든 파일
VERSION = re.compile(r"m[0-9]{8}-[0-9]+")  # 버전 이름의 모양 — m<날짜>-<실행 번호>, 예: m20261116-3
USAGE = """사용법:
    python3 deploy/lightsail/models.py promote <파일 폴더>
    python3 deploy/lightsail/models.py rollback <버전>"""


def aws(*args: str, stdin: str = "", check: bool = True) -> "subprocess.CompletedProcess[str]":
    """`aws s3 <args>` 를 실행한다.

    check=True 면 실패할 때 오류를 보이고 멈춘다(종료 코드 1).
    check=False 면 결과를 그대로 돌려준다 — 「없다」도 정상인 조회에 쓴다.
    """
    r = subprocess.run(["aws", "s3", *args], input=stdin, capture_output=True, text=True)
    if check and r.returncode:
        sys.exit(f"aws s3 {' '.join(args)} 실패\n{r.stderr}")
    return r


def check_version(ver: str) -> None:
    """버전 이름이 정해진 모양인지 본다. 아니면 멈춘다.

    입력이 버킷 경로·명령 인자에 들어가므로, 엉뚱한 글자(`../`, `;` 등)를 먼저 막는다.
    """
    if not VERSION.fullmatch(ver):
        sys.exit(f"모델 버전 형식이 아니다: {ver!r}")


def last_run() -> int:
    """포인터(current.json)를 마지막으로 바꾼 실행 번호. 포인터가 아직 없으면(첫 승격) 0."""
    r = aws("cp", f"{S3}/current.json", "-", check=False)  # `-` : 파일 대신 표준 출력으로 받는다
    if r.returncode:
        return 0
    return int(json.loads(r.stdout).get("run") or 0)


def go_live(ver: str) -> None:
    """버킷의 버전을 서버로 받아 띄우고, 뜬 것을 확인한 뒤에야 포인터를 바꾼다.

    순서가 중요하다. server.sh 가 실패하면(새 버전이 /health 에 안 나오면)
    서버는 이전 버전으로 돌아가고, 포인터는 바꾸지 않은 채 멈춘다.
    """
    # 배포 파일은 언제나 저장소의 것으로 — 서버에 놓인 옛 파일을 쓰지 않는다
    for f in ("compose.yml", "server.sh"):
        shutil.copy(os.path.join(HERE, f), SRV)

    # 예: s3://<내 버킷 이름>/models/onnx/m20261116-3/model.json → /srv/eta/models/m20261116-3/model.json
    for f in FILES:
        aws("cp", f"{S3}/{ver}/{f}", f"{SRV}/models/{ver}/{f}")

    # .env 의 MODEL_* 를 바꿔 띄우고 /health 의 model_version 을 확인한다
    if subprocess.run(["bash", f"{SRV}/server.sh", "model", ver]).returncode:
        sys.exit(f"{ver} 이 뜨지 않았다 — 서버는 이전 버전으로, current.json 은 그대로")

    # 마지막에 포인터 — 예: {"model_version": "m20261116-3", "set_at": "2026-11-16T08:44:02Z", "run": "44008258923"}
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    pointer = {"model_version": ver, "set_at": now, "run": os.environ.get("GITHUB_RUN_ID", "")}
    aws("cp", "-", f"{S3}/current.json", stdin=json.dumps(pointer))
    print(f"current.json → {ver}")


def promote(src: str) -> None:
    """학습 결과(src 폴더)를 새 버전으로 버킷에 올리고 서비스한다.

    두 경우에는 아무것도 바꾸지 않고 멈춘다.
    - 낡은 실행: 이 실행보다 나중에 시작한 실행(예: 학습 중의 rollback)이 이미 포인터를 바꿨다
    - 같은 버전: 그 버전 폴더가 버킷에 이미 있다 — 한 번 올린 버전은 고치지 않는다
    """
    with open(os.path.join(src, "model.json"), encoding="utf-8") as f:
        ver: str = json.load(f)["model_version"]  # 모델 카드에 적힌 버전 이름
    check_version(ver)

    # 실행 번호(run id)는 나중에 시작한 실행일수록 크다
    me = int(os.environ["GITHUB_RUN_ID"])
    if last_run() > me:
        sys.exit("이 실행보다 나중에 시작한 실행이 포인터를 바꿨다 — 낡은 실행이라 승격하지 않는다")

    # 폴더 안에 무엇이든 있으면 「있다」 — 반쯤 올라간 버전도 덮어쓰지 않는다
    if aws("ls", f"{S3}/{ver}/", check=False).returncode == 0:
        sys.exit(f"{ver} 은 이미 버킷에 있다 — 한 번 올린 버전은 고치지 않는다")

    for f in FILES:
        aws("cp", os.path.join(src, f), f"{S3}/{ver}/{f}")
    go_live(ver)


def rollback(ver: str) -> None:
    """버킷에 이미 있는 버전(ver)으로 서비스를 되돌린다. 학습·검사는 하지 않는다."""
    check_version(ver)
    go_live(ver)


def main(argv: "list[str]") -> None:
    """명령줄: promote <파일 폴더> | rollback <버전>"""
    if len(argv) != 2 or argv[0] not in ("promote", "rollback"):
        sys.exit(USAGE)  # 문자열을 주면 그 글을 stderr 에 찍고 종료 코드 1 로 끝난다
    cmd, arg = argv
    if cmd == "promote":
        promote(arg)
    else:
        rollback(arg)


if __name__ == "__main__":
    main(sys.argv[1:])
