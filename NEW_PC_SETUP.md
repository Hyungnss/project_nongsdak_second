# 새 PC 에서 개발 환경 만들기

컴퓨터를 바꾸거나 초기화한 뒤, **아무것도 안 깔린 윈도우**에서 이 프로젝트를
다시 개발할 수 있는 상태까지 가는 순서다.

프로젝트 자체를 돌리는 방법(Oracle 적재·웹서비스 실행)은 [SETUP.md](SETUP.md) 에 있다.
이 문서는 그 **앞 단계** — 도구를 까는 부분만 다룬다.

| 순서 | 무엇 | 왜 필요한가 |
|---|---|---|
| 1 | Python 3.11 | 프로젝트가 파이썬으로 돼 있다 |
| 2 | Git | 저장소를 받고 이력을 남긴다 |
| 3 | Node.js | Claude Code 가 이걸 깔고 돈다 |
| 4 | Claude Code | 개발 보조 |
| 5 | 저장소 내려받기 | 코드를 가져온다 |
| 6 | Oracle | DB. 무겁고 오래 걸린다 |

> **터미널을 새로 열 것** — 뭔가를 설치한 뒤에는 열려 있던 터미널이 그걸 못 찾는다.
> `'python' is not recognized` 같은 오류가 나오면 대개 이것 때문이다.
> 창을 닫고 새로 열면 해결된다.

---

## 0. winget 확인

윈도우 10/11 에 기본으로 들어 있는 설치 도구다. 이걸로 깔면 다운로드 페이지를
찾아다닐 필요가 없다.

PowerShell 을 열고:

```powershell
winget --version
```

버전이 나오면 아래 명령들을 그대로 쓰면 된다.
`winget 을 찾을 수 없다` 고 나오면 Microsoft Store 에서 **앱 설치 관리자**를 설치한다.

---

## 1. Python 3.11

```powershell
winget install --id Python.Python.3.11 -e
```

**새 터미널을 열고** 확인:

```powershell
python --version
```

`Python 3.11.x` 가 나와야 한다.

> **왜 3.11 인가** — 이 프로젝트를 만든 환경이 3.11.7 이다. 3.12·3.13 에서도 대체로
> 돌지만, 패키지 설치에서 걸리면 3.11 로 맞추는 게 빠르다.

> **직접 설치 파일로 깔 경우** — python.org 에서 받는다면 설치 첫 화면의
> **`Add python.exe to PATH`** 를 반드시 체크해야 한다. 이걸 놓치면 터미널에서
> `python` 을 못 찾는다. 가장 흔한 실수다.

---

## 2. Git

```powershell
winget install --id Git.Git -e --source winget
```

**새 터미널**에서 확인하고, 이름과 이메일을 등록한다.

```powershell
git --version

git config --global user.name "Hyungnss"
git config --global user.email "323386612+Hyungnss@users.noreply.github.com"
git config --global init.defaultBranch main
```

이름·이메일은 커밋에 찍히는 **서명**이다. 컴퓨터마다 한 번씩 해주면 된다.

> **이메일이 왜 저 이상한 주소인가** — 깃허브가 주는 대체 주소다.
> 실제 이메일을 쓰면 커밋 이력에 그대로 남아 노출된다.
> 자기 주소는 깃허브 → Settings → Emails 에서 확인한다.

---

## 3. Node.js

Claude Code 를 설치하는 데 쓴다.

```powershell
winget install --id OpenJS.NodeJS.LTS -e
```

**새 터미널**에서 확인:

```powershell
node --version
npm --version
```

---

## 4. Claude Code

```powershell
npm install -g @anthropic-ai/claude-code
```

설치되면 프로젝트 폴더로 가서 실행한다.

```powershell
cd C:\경로\project_nongsdak
claude
```

처음 실행하면 로그인하라고 한다. 안내대로 브라우저에서 로그인하면 된다.
이후에는 바로 켜진다.

> 설치 방법은 바뀔 수 있다. 위 명령이 안 되면 공식 문서를 본다 —
> https://docs.claude.com/en/docs/claude-code/setup

---

## 5. 저장소 내려받기

작업할 폴더로 가서:

```powershell
git clone https://github.com/Hyungnss/project_nongsdak.git
cd project_nongsdak
```

**비공개 저장소라 로그인을 요구한다.** 브라우저 창이 뜨면 깃허브 계정으로
로그인하면 되고, 한 번 하면 그 컴퓨터에서는 다시 묻지 않는다.

이걸로 코드는 전부 돌아왔다. 다만 아래 두 개는 **따라오지 않는다.**

| 없는 것 | 어떻게 하나 |
|---|---|
| `.env` | `.env.example` 을 복사해 새로 만든다 ([SETUP.md](SETUP.md) 2단계) |
| `.venv/` | 새로 만든다 ([SETUP.md](SETUP.md) 1단계) |

일부러 제외한 것이다. `.env` 에는 비밀번호와 API 키가 들어 있어서 깃허브에
올리면 안 되고, `.venv/` 는 컴퓨터마다 새로 만드는 게 맞다.

> **KAMIS 인증키** — 예전 키를 그대로 쓸 수 있으면 쓰고, 잃어버렸거나 이전 PC 를
> 반납하면서 폐기했다면 KAMIS 에서 새로 발급받는다.

---

## 6. Oracle

여기가 제일 오래 걸린다. 두 개가 필요하다.

- **Oracle Database XE** — DB 본체
- **Oracle Instant Client** — 접속용 라이브러리. 이 프로젝트는 Oracle 11g 라서
  이게 없으면 `DPY-3010` 오류가 나며 접속이 안 된다

둘 다 oracle.com 에서 받는다 (무료, 계정 가입 필요).
Instant Client 는 압축을 풀기만 하면 되고, **푼 폴더 경로를 `.env` 의
`ORACLE_CLIENT_DIR` 에 적어야 한다.** 사람마다 다른 값이다.

설치 후 할 일은 [SETUP.md](SETUP.md) 3단계(테이블 만들기)부터 이어진다.

---

## 다 됐는지 확인

새 터미널에서 이 네 줄이 전부 버전을 뱉으면 도구 설치는 끝이다.

```powershell
python --version
git --version
node --version
claude --version
```

그다음은 [SETUP.md](SETUP.md) 로 넘어간다.

---

## 있으면 편한 것 (선택)

```powershell
winget install --id Microsoft.VisualStudioCode -e
```

코드 편집기. 없어도 개발은 되지만 있으면 편하다.
