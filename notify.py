"""수집 결과·경고를 슬랙으로 보낸다. 여러 스크립트(06 수집, 08 점검)가 함께 쓴다.

같은 전송 코드를 두 곳에 두면 한쪽만 고쳐져 어긋나므로 한 군데로 모은다.
config.SLACK_WEBHOOK_URL 이 비어 있으면 조용히 건너뛰고, 전송 실패가 부르는
쪽 작업을 막지 않도록 예외를 삼킨다. 이미 의존성인 requests 로 POST 한다.
"""

import config


def notify_slack(text):
    """슬랙 Incoming Webhook 으로 한 줄 보낸다. URL 미설정이면 아무것도 안 한다."""
    url = config.SLACK_WEBHOOK_URL
    if not url:
        return
    try:
        import requests

        requests.post(url, json={"text": text}, timeout=10)
    except Exception as e:
        print(f"  (슬랙 알림 실패: {e})")
