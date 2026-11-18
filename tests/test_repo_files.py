"""파이썬 밖의 파일들 — 배치 파일과 화면 스크립트.

이 둘은 깨져도 파이썬 시험에는 안 걸리고, 실제로 돌려 봐야 드러난다.
  · 배치 파일에 한글이 들어가면 작업 스케줄러에서 통째로 깨진다 (docs/WORKLOG.md 2026-09-02).
  · index.html 의 스크립트에 문법 오류가 하나라도 있으면 화면 전체가 멈춘다.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BATCH_FILES = ["run_fetch.bat", "check_fetch.bat"]


@pytest.mark.parametrize("name", BATCH_FILES)
def test_batch_file_is_ascii_only(name):
    """cmd 는 .bat 을 그때그때의 코드페이지로 읽는다. 한글이 한 글자만 있어도 뒤가 깨진다."""
    data = (ROOT / name).read_bytes()
    bad = [i for i, b in enumerate(data) if b > 0x7F]
    assert not bad, f"{name} 에 ASCII 가 아닌 글자가 있다 (바이트 위치 {bad[:5]})"


@pytest.mark.parametrize("name", BATCH_FILES)
def test_batch_file_uses_crlf(name):
    """LF 만 있으면 cmd 가 마지막 줄을 흘린다 (.gitattributes 에서 CRLF 로 고정)."""
    data = (ROOT / name).read_bytes()
    assert b"\n" in data
    assert data.count(b"\r\n") == data.count(b"\n"), f"{name} 에 CRLF 가 아닌 줄바꿈이 있다"


# ── 화면 스크립트 문법 (node 가 있을 때만) ───────────────────────────────
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node 가 없어 JS 문법 검사를 건너뜀")


def _node_check(path):
    r = subprocess.run([NODE, "--check", str(path)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr


@needs_node
@pytest.mark.parametrize("name", ["auth.js", "cart.js"])
def test_frontend_js_syntax(name):
    _node_check(ROOT / "frontend" / name)


@needs_node
def test_index_inline_scripts_syntax(tmp_path):
    """index.html 안에 들어 있는 <script> 블록을 꺼내 하나씩 검사한다 (src= 로 부르는 것은 위에서 본다)."""
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
    assert scripts, "index.html 에서 스크립트를 못 찾았다"
    for i, code in enumerate(scripts):
        f = tmp_path / f"inline_{i}.js"
        f.write_text(code, encoding="utf-8")
        _node_check(f)
