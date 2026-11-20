"""파이썬 밖의 파일들 — 배치 파일 · 화면 스크립트 · 서버 설정(Caddyfile · 모니터링).

이것들은 깨져도 파이썬 시험에는 안 걸리고, 실제로 돌려 봐야 드러난다.
  · 배치 파일에 한글이 들어가면 작업 스케줄러에서 통째로 깨진다 (docs/WORKLOG.md 2026-09-02).
  · index.html 의 스크립트에 문법 오류가 하나라도 있으면 화면 전체가 멈춘다.
"""

import json
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
@pytest.mark.parametrize("name", ["auth.js", "cart.js", "developers.js"])
def test_frontend_js_syntax(name):
    _node_check(ROOT / "frontend" / name)


@needs_node
@pytest.mark.parametrize("page", ["index.html", "developers.html"])
def test_inline_scripts_syntax(tmp_path, page):
    """HTML 안에 들어 있는 <script> 블록을 꺼내 하나씩 검사한다 (src= 로 부르는 것은 위에서 본다)."""
    html = (ROOT / "frontend" / page).read_text(encoding="utf-8")
    scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
    assert scripts, f"{page} 에서 스크립트를 못 찾았다"
    for i, code in enumerate(scripts):
        f = tmp_path / f"inline_{i}.js"
        f.write_text(code, encoding="utf-8")
        _node_check(f)


# ── 서버 설정 — Caddyfile · 모니터링 (docs/MONITORING.md) ──────────────────
# 서버에서만 쓰여서 로컬 시험으로는 돌려 볼 수 없다. 깨지면 배포 뒤에야 드러나므로 글자로 확인한다.

def _caddy_site_block():
    text = (ROOT / "Caddyfile").read_text(encoding="utf-8")
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())   # 주석은 빼고 본다


def test_caddy_hides_metrics_before_proxying_to_web():
    """/metrics 는 인터넷에 내놓지 않는다 — web 으로 넘기는 handle 보다 먼저 404 로 끊어야 한다."""
    c = _caddy_site_block()
    m = re.search(r"@metrics\s+path\s+/metrics\s+/metrics/\*", c)
    assert m, "Caddyfile 에 @metrics 매처가 없다"
    block = re.search(r"handle\s+@metrics\s*\{([^}]*)\}", c)
    assert block and "respond 404" in block.group(1), "/metrics 를 404 로 막지 않는다"
    assert c.index("handle @metrics") < c.index("reverse_proxy web:8000")


def test_caddy_routes_grafana_subpath():
    c = _caddy_site_block()
    assert re.search(r"handle\s+/grafana/\*\s*\{\s*reverse_proxy\s+grafana:3000", c)
    assert "uri strip_prefix" not in c      # grafana 가 /grafana 를 직접 받는다 (serve_from_sub_path)


def _prod_compose():
    return (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")


def test_prod_images_are_pinned():
    """이미지는 정확한 버전으로 고정한다 (latest · 큰 버전 태그 금지)."""
    images = re.findall(r"^\s+image:\s*(\S+)", _prod_compose(), re.M)
    assert images
    for img in images:
        name, _, tag = img.partition(":")
        assert re.fullmatch(r"v?\d+\.\d+\.\d+", tag), f"{img} 는 정확한 버전이 아니다"


def test_monitoring_services_are_limited_and_private():
    text = _prod_compose()
    for svc in ["prometheus", "grafana", "node-exporter"]:
        m = re.search(rf"^  {svc}:\n(.*?)(?=^  \S|^\S)", text, re.M | re.S)
        assert m, f"{svc} 서비스가 없다"
        body = m.group(1)
        assert re.search(r"^    mem_limit:\s*\d+m$", body, re.M), f"{svc} 에 mem_limit 이 없다"
        assert not re.search(r"^    ports:", body, re.M), f"{svc} 는 포트를 열지 않는다 (caddy 로만)"
    assert "--storage.tsdb.retention.time=15d" in text
    assert 'GF_AUTH_ANONYMOUS_ENABLED: "false"' in text
    assert 'GF_SERVER_SERVE_FROM_SUB_PATH: "true"' in text
    assert "GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:?" in text


def test_deploy_writes_grafana_password_and_copies_monitoring():
    text = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    assert "secrets.GRAFANA_ADMIN_PASSWORD" in text
    assert 'echo "GRAFANA_ADMIN_PASSWORD=$GRAFANA_ADMIN_PASSWORD"' in text
    assert re.search(r"^\s+monitoring/$", text, re.M), "sparse-checkout 에 monitoring/ 이 없다"


def test_prometheus_targets_match_services():
    text = (ROOT / "monitoring" / "prometheus.yml").read_text(encoding="utf-8")
    assert '"web:8000"' in text and '"node-exporter:9100"' in text


def test_grafana_dashboard_uses_provisioned_datasource():
    """대시보드 JSON 이 깨지지 않았고, 모든 패널이 프로비저닝된 데이터 원본(uid)을 가리키는지."""
    ds = (ROOT / "monitoring" / "grafana" / "provisioning" / "datasources" / "prometheus.yml").read_text(encoding="utf-8")
    uid = re.search(r"^\s+uid:\s*(\S+)", ds, re.M).group(1)
    dash = json.loads((ROOT / "monitoring" / "grafana" / "dashboards" / "nongsdak.json").read_text(encoding="utf-8"))
    panels = [p for p in dash["panels"] if p["type"] != "row"]
    assert panels
    for p in panels:
        assert p["datasource"]["uid"] == uid, p["title"]
        assert p["targets"] and all(t["expr"] for t in p["targets"]), p["title"]
    exprs = " ".join(t["expr"] for p in panels for t in p["targets"])
    for metric in ["http_requests_total", "http_request_duration_highr_seconds_bucket",
                   "node_cpu_seconds_total", "node_memory_MemAvailable_bytes", "node_filesystem_avail_bytes"]:
        assert metric in exprs, f"대시보드에 {metric} 이 없다"
    ids = [p["id"] for p in dash["panels"]]
    assert len(ids) == len(set(ids)), "패널 id 가 겹친다"
