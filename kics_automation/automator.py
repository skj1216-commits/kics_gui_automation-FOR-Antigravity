import json
import re
import threading
import time
from urllib.parse import urljoin

from playwright.sync_api import TimeoutError, sync_playwright

import database


class ExtractionError(Exception):
    pass


class KICSAutomator:
    STEP_CONNECT = 0
    STEP_EXTRACT = 1
    STEP_SEARCH = 2
    STEP_SELECT = 3
    STEP_ADMIN = 4
    STEP_APPROVE = 5

    def __init__(
        self,
        log_callback=None,
        error_callback=None,
        confirm_callback=None,
        update_data_callback=None,
        status_callback=None,
        progress_callback=None,
        step_callback=None,
    ):
        self.running = False
        self.should_quit = False
        self.log_callback = log_callback
        self.error_callback = error_callback
        self.confirm_callback = confirm_callback
        self.update_data_callback = update_data_callback
        self.status_callback = status_callback
        self.progress_callback = progress_callback
        self.step_callback = step_callback

        self.config = {}
        self.load_config()
        database.init_db()

        self._run_once_event = threading.Event()
        self._run_once_url = None

    def load_config(self):
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                self.config = json.load(f)
        except Exception as e:  # noqa: BLE001
            self.log(f"설정 파일 로드 실패: {e}")

    def log(self, message):
        if self.log_callback:
            self.log_callback(message)
        else:
            print(message)

    def _set_status(self, text):
        if self.status_callback:
            self.status_callback(text)

    def _set_progress(self, value):
        if self.progress_callback:
            self.progress_callback(value)

    def _set_step(self, step_idx, state):
        if self.step_callback:
            self.step_callback(step_idx, state)

    def _reset_all_steps(self):
        for i in range(6):
            self._set_step(i, "대기")
        self._set_progress(0)

    def stop(self):
        self.running = False
        self.log("감시 중지")

    def quit(self):
        self.running = False
        self.should_quit = True

    def start_monitoring(self):
        self.load_config()
        self.running = True
        suffix = " [DRY-RUN]" if self.config.get("dry_run") else ""
        self.log(f"감시 루프를 시작합니다.{suffix}")
        self._set_status("감시 중")

    def run_once(self, url: str = ""):
        self._run_once_url = url
        self._run_once_event.set()

    def browser_thread_worker(self):
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=False)
                context = browser.new_context()
                page = context.new_page()

                self.log("브라우저를 실행했습니다.")
                list_url = self.config.get("document_list_url", "").strip()
                if list_url:
                    try:
                        page.goto(list_url, wait_until="domcontentloaded")
                    except Exception as e:  # noqa: BLE001
                        self.log(f"목록 페이지 이동 실패: {e}")

                self.log("로그인이 필요하면 열린 브라우저에서 먼저 진행하세요.")

                while not self.should_quit:
                    if self._run_once_event.is_set():
                        self._run_once_event.clear()
                        url = (self._run_once_url or self.config.get("document_detail_url", "")).strip()
                        if url:
                            self._reset_all_steps()
                            self._process_single_url(url, context)
                        else:
                            self.log("공문 URL(수동 1건)이 비어 있습니다.")

                    if self.running:
                        try:
                            self._set_status("목록 스캔 중")
                            current_list_url = self.config.get("document_list_url", "").strip()
                            if current_list_url:
                                page.goto(current_list_url, wait_until="domcontentloaded")
                            self._reset_all_steps()
                            self.process_documents(page, context)
                        except Exception as e:  # noqa: BLE001
                            self.log(f"감시 루프 중 오류: {e}")

                        self.load_config()
                        interval = int(self.config.get("refresh_interval_seconds", 60))
                        self.log(f"다음 스캔까지 {interval}초 대기합니다.")
                        self._set_status(f"대기 중 (다음 스캔: {interval}초)")
                        for _ in range(interval):
                            if not self.running or self.should_quit or self._run_once_event.is_set():
                                break
                            time.sleep(1)
                    else:
                        time.sleep(0.5)

                browser.close()
            except Exception as e:  # noqa: BLE001
                self.log(f"브라우저 스레드 치명적 오류: {e}")
                self._set_status("오류 발생")

    def process_documents(self, page, context):
        anchors = page.locator("a")
        matched = []

        for index in range(anchors.count()):
            anchor = anchors.nth(index)
            try:
                text = anchor.inner_text(timeout=1000).strip()
            except Exception:  # noqa: BLE001
                continue
            if self._matches_target_title(text):
                matched.append(anchor)

        if not matched:
            self.log("처리할 새로운 공문이 없습니다.")
            self._set_status("감시 중 (신규 없음)")
            return

        for anchor in matched:
            if not self.running or self.should_quit:
                break

            doc_id = anchor.get_attribute("href") or anchor.inner_text()
            if database.is_processed(doc_id):
                continue

            self.log(f"신규 권한 요청 공문 발견: {doc_id}")
            self._process_with_retry(lambda: self._open_and_handle(anchor, doc_id, page, context), doc_id)

    def _matches_target_title(self, text: str) -> bool:
        text_norm = self._normalize_text(text)
        keywords = self.config.get("target_keywords", [])
        if keywords:
            return all(self._normalize_text(keyword) in text_norm for keyword in keywords)

        target_title = self.config.get("target_title", "")
        return self._normalize_text(target_title) in text_norm

    def _open_and_handle(self, anchor, doc_id, list_page, context):
        self._set_step(self.STEP_CONNECT, "진행중")
        self._set_progress(10)

        href = anchor.get_attribute("href")
        detail_url = urljoin(list_page.url, href) if href else ""
        doc_page = context.new_page()

        try:
            if detail_url:
                doc_page.goto(detail_url, wait_until="domcontentloaded")
            else:
                anchor.click()
                doc_page.wait_for_load_state("domcontentloaded")

            self._set_step(self.STEP_CONNECT, "완료")
            self._set_progress(20)
            self.handle_single_document(doc_page, doc_id, context)
        finally:
            if not doc_page.is_closed():
                doc_page.close()

    def _process_single_url(self, url, context):
        doc_id = url
        self.log(f"수동 실행: {url}")

        def _do():
            self._set_step(self.STEP_CONNECT, "진행중")
            self._set_progress(10)
            doc_page = context.new_page()
            try:
                doc_page.goto(url, wait_until="domcontentloaded")
                self._set_step(self.STEP_CONNECT, "완료")
                self._set_progress(20)
                self.handle_single_document(doc_page, doc_id, context)
            finally:
                if not doc_page.is_closed():
                    doc_page.close()

        self._process_with_retry(_do, doc_id)

    def _process_with_retry(self, fn, doc_id):
        auto_retry = bool(self.config.get("auto_retry", True))
        max_retries = int(self.config.get("max_retries", 3)) if auto_retry else 1
        retry_delays = [5, 10, 20]
        success = False

        for attempt in range(1, max_retries + 1):
            try:
                fn()
                success = True
                break
            except ExtractionError as e:
                self.log(f"[중단] {e}")
                self._set_status("중단됨")
                break
            except Exception as e:  # noqa: BLE001
                self.log(f"[오류] 문서 처리 실패 ({attempt}/{max_retries}): {e}")
                if attempt < max_retries:
                    delay = retry_delays[min(attempt - 1, len(retry_delays) - 1)]
                    self.log(f"{delay}초 후 재시도합니다.")
                    time.sleep(delay)

        if not success:
            database.mark_processed(doc_id, "UNKNOWN", "FAILED")
            self.log(f"문서 실패 기록: {doc_id}")
            self._set_status("처리 실패")
            if self.error_callback:
                self.error_callback(f"공문 처리 자동화 실패\nID: {doc_id}")

    def handle_single_document(self, doc_page, doc_id, context):
        self._set_step(self.STEP_EXTRACT, "진행중")
        self._set_status("공문 내용 분석 중")
        self.log("공문 내용을 분석합니다.")

        content_text = doc_page.locator("body").inner_text()
        user_id = self._extract_user_id(content_text)
        requested_permissions = self._extract_permissions(content_text)

        if not user_id or not requested_permissions:
            self._set_step(self.STEP_EXTRACT, "오류")
            raise ExtractionError("사용자 ID 또는 요청 권한을 추출하지 못했습니다.")

        self._set_step(self.STEP_EXTRACT, "완료")
        self._set_progress(40)
        self.log(f"추출 완료 -> ID: {user_id}, 요청권한: {requested_permissions}")

        if self.update_data_callback:
            self.update_data_callback(user_id, requested_permissions)

        result_status = self.grant_permissions(user_id, requested_permissions, context)
        database.mark_processed(doc_id, user_id, result_status)

        self.log(f"[{user_id}] 처리 완료. status={result_status}")
        self._set_step(self.STEP_APPROVE, "완료")
        self._set_progress(100)
        self._set_status("처리 완료")

        if self.update_data_callback:
            self.update_data_callback("(대기 중)", [])

    def _extract_user_id(self, content_text: str) -> str:
        patterns = [
            r"아이디\s*[:：]?\s*([a-zA-Z][a-zA-Z0-9_]{3,})",
            r"\bID\s*[:：]?\s*([a-zA-Z][a-zA-Z0-9_]{3,})",
            r"사용자\s*ID\s*[:：]?\s*([a-zA-Z][a-zA-Z0-9_]{3,})",
        ]
        for pattern in patterns:
            matched = re.search(pattern, content_text, re.IGNORECASE)
            if matched:
                return matched.group(1).strip()

        candidates = re.findall(r"\b[a-zA-Z][a-zA-Z0-9_]{4,}\b", content_text)
        if candidates:
            return max(candidates, key=len)
        return ""

    def _extract_permissions(self, content_text: str) -> list[str]:
        found = []
        normalized_text = self._normalize_text(content_text)

        for item in self.config.get("permission_catalog", []):
            keywords = item.get("keywords", [])
            if keywords and any(self._normalize_text(keyword) in normalized_text for keyword in keywords):
                found.append(item.get("name", ""))

        if found:
            return list(dict.fromkeys([name for name in found if name]))

        bullet_permissions = []
        for line in content_text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith(("-", "•", "·", "*")) and len(line) > 2:
                bullet_permissions.append(line[1:].strip())

        return list(dict.fromkeys(bullet_permissions))

    def grant_permissions(self, user_id, permissions, context):
        self._set_step(self.STEP_ADMIN, "진행중")
        self._set_status("관리자 페이지 이동 중")
        self.log("관리자 페이지로 이동합니다.")
        self._set_progress(50)

        admin_url = self.config.get("admin_url", "").strip()
        if not admin_url:
            raise ExtractionError("관리자 URL이 비어 있습니다.")

        admin_page = context.new_page()
        try:
            admin_page.goto(admin_url, wait_until="domcontentloaded")
            self._set_step(self.STEP_ADMIN, "완료")
            self._set_progress(60)

            if self.config.get("dry_run", False):
                self._set_step(self.STEP_SEARCH, "완료")
                self._set_step(self.STEP_SELECT, "완료")
                self._set_step(self.STEP_APPROVE, "진행중")
                self.log(f"[DRY-RUN] 사용자 검색 예정: {user_id}")
                self.log(f"[DRY-RUN] 권한 선택 예정: {permissions}")
                if self.config.get("require_confirmation", True) and self.confirm_callback:
                    message = (
                        f"다음 사용자에게 권한을 부여하시겠습니까?\n\n"
                        f"사용자 ID: {user_id}\n부여 권한:\n- " + "\n- ".join(permissions)
                    )
                    if not self.confirm_callback(message):
                        self._set_step(self.STEP_APPROVE, "오류")
                        raise ExtractionError("관리자가 최종 확인을 취소했습니다.")
                self.log("[DRY-RUN] 실제 승인 클릭은 수행하지 않았습니다.")
                return "DRY_RUN"

            search_selector = self.config.get("admin_user_search_selector", "").strip()
            search_button_selector = self.config.get("admin_user_search_button_selector", "").strip()
            approve_button_selector = self.config.get("admin_approve_button_selector", "").strip()

            if not search_selector or not approve_button_selector:
                raise ExtractionError("관리자 자동화 셀렉터가 아직 설정되지 않았습니다.")

            self._set_step(self.STEP_SEARCH, "진행중")
            self._set_status(f"사용자 검색 중: {user_id}")
            admin_page.fill(search_selector, user_id)
            if search_button_selector:
                admin_page.click(search_button_selector)
            self._set_step(self.STEP_SEARCH, "완료")
            self._set_progress(70)

            self._set_step(self.STEP_SELECT, "진행중")
            self._set_status("권한 선택 중")
            permission_map = self.config.get("admin_permission_selector_map", {})
            for permission in permissions:
                selector = permission_map.get(permission)
                if not selector:
                    raise ExtractionError(f"권한 셀렉터가 없습니다: {permission}")
                admin_page.click(selector)
            self._set_step(self.STEP_SELECT, "완료")
            self._set_progress(85)

            self._set_step(self.STEP_APPROVE, "진행중")
            if self.config.get("require_confirmation", True) and self.confirm_callback:
                message = (
                    f"다음 사용자에게 권한을 부여하시겠습니까?\n\n"
                    f"사용자 ID: {user_id}\n부여 권한:\n- " + "\n- ".join(permissions)
                )
                if not self.confirm_callback(message):
                    self._set_step(self.STEP_APPROVE, "오류")
                    raise ExtractionError("관리자가 최종 확인을 취소했습니다.")

            admin_page.click(approve_button_selector)
            self.log("최종 승인 버튼을 클릭했습니다.")
            return "SUCCESS"
        except TimeoutError as e:
            raise ExtractionError(f"페이지 대기 시간 초과: {e}") from e
        finally:
            if not admin_page.is_closed():
                admin_page.close()

    def _normalize_text(self, value: str) -> str:
        return re.sub(r"[^0-9a-z가-힣]+", "", value.lower())
