import tkinter as tk
from tkinter import scrolledtext, messagebox, ttk
import threading
import json
import datetime
from automator import KICSAutomator

# 처리 단계 정의 (index, 표시명)
STEPS = [
    "공문 접속",
    "데이터 추출",
    "사용자 검색",
    "권한 선택",
    "관리자 이동",
    "최종 승인/종료",
]

# 단계 상태별 색상
STEP_COLORS = {
    "대기":   {"fg": "gray",    "symbol": "○"},
    "진행중": {"fg": "#1565C0", "symbol": "●"},
    "완료":   {"fg": "#2E7D32", "symbol": "●"},
    "오류":   {"fg": "#C62828", "symbol": "●"},
}


class Application(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("KICS 권한 요청 처리 자동화")
        self.geometry("820x700")
        self.resizable(True, True)

        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.automator = KICSAutomator(
            log_callback=self.append_log,
            error_callback=self.show_error_popup,
            confirm_callback=self.show_confirm_popup,
            update_data_callback=self.update_parsed_data_display,
            status_callback=self.update_status,
            progress_callback=self.update_progress,
            step_callback=self.update_step,
        )

        self.browser_thread = threading.Thread(
            target=self.automator.browser_thread_worker, daemon=True
        )
        self.browser_thread.start()

        self.create_widgets()

    # ──────────────────────────────────────────
    # UI 구성
    # ──────────────────────────────────────────
    def create_widgets(self):
        # ── 1. URL 입력 ──────────────────────────
        url_frame = tk.Frame(self)
        url_frame.pack(fill=tk.X, padx=10, pady=(10, 4))

        tk.Label(url_frame, text="공문 URL (수동 1건)", width=16, anchor="w").grid(row=0, column=0, pady=3)
        self.doc_single_var = tk.StringVar(value=self.automator.config.get('document_detail_url', ''))
        tk.Entry(url_frame, textvariable=self.doc_single_var, width=80).grid(row=0, column=1, pady=3, sticky="we")

        tk.Label(url_frame, text="공문 목록 URL (감시)", width=16, anchor="w").grid(row=1, column=0, pady=3)
        self.doc_url_var = tk.StringVar(value=self.automator.config.get('document_list_url', ''))
        tk.Entry(url_frame, textvariable=self.doc_url_var, width=80).grid(row=1, column=1, pady=3, sticky="we")

        tk.Label(url_frame, text="관리자 URL", width=16, anchor="w").grid(row=2, column=0, pady=3)
        self.admin_url_var = tk.StringVar(value=self.automator.config.get('admin_url', ''))
        tk.Entry(url_frame, textvariable=self.admin_url_var, width=80).grid(row=2, column=1, pady=3, sticky="we")

        # ── 2. 실행 옵션 ─────────────────────────
        option_frame = tk.LabelFrame(self, text="실행 옵션")
        option_frame.pack(fill=tk.X, padx=10, pady=4)

        ctrl_row = tk.Frame(option_frame)
        ctrl_row.pack(fill=tk.X, padx=6, pady=(5, 2))

        self.dry_run_var = tk.BooleanVar(value=self.automator.config.get('dry_run', False))
        tk.Checkbutton(ctrl_row, text="Dry-run: 최종 승인/저장 안 함", variable=self.dry_run_var).pack(side=tk.LEFT)

        self.confirm_var = tk.BooleanVar(value=self.automator.config.get('require_confirmation', True))
        tk.Checkbutton(ctrl_row, text="최종 승인 전 확인창 표시", variable=self.confirm_var).pack(side=tk.LEFT, padx=30)

        self.auto_retry_var = tk.BooleanVar(value=self.automator.config.get('auto_retry', True))
        tk.Checkbutton(ctrl_row, text="자동 재시도", variable=self.auto_retry_var).pack(side=tk.LEFT)

        spin_row = tk.Frame(option_frame)
        spin_row.pack(fill=tk.X, padx=6, pady=(2, 8))

        tk.Label(spin_row, text="스캔 주기(초)").pack(side=tk.LEFT)
        self.scan_interval_var = tk.StringVar(
            value=str(self.automator.config.get('refresh_interval_seconds', 30))
        )
        tk.Spinbox(
            spin_row, from_=1, to=3600, increment=1,
            textvariable=self.scan_interval_var, width=7, justify=tk.CENTER
        ).pack(side=tk.LEFT, padx=(4, 30))

        tk.Label(spin_row, text="최대 시도 횟수").pack(side=tk.LEFT)
        self.max_retry_var = tk.StringVar(
            value=str(self.automator.config.get('max_retries', 3))
        )
        tk.Spinbox(
            spin_row, from_=1, to=10, increment=1,
            textvariable=self.max_retry_var, width=5, justify=tk.CENTER
        ).pack(side=tk.LEFT, padx=(4, 0))

        # ── 3. 실행 버튼 4개 ─────────────────────
        exec_frame = tk.LabelFrame(self, text="실행")
        exec_frame.pack(fill=tk.X, padx=10, pady=4)

        btn_row = tk.Frame(exec_frame)
        btn_row.pack(fill=tk.X, padx=6, pady=6)

        self.save_btn = tk.Button(btn_row, text="로그인 저장", command=self.save_config, height=2)
        self.save_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 3))

        self.job_btn = tk.Button(btn_row, text="작업 시작", command=self.run_once, height=2)
        self.job_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=3)

        self.monitor_btn = tk.Button(btn_row, text="감시 시작", command=self.start_monitoring, height=2)
        self.monitor_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=3)

        self.stop_btn = tk.Button(
            btn_row, text="감시 중지", command=self.stop_monitoring,
            height=2, state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(3, 0))

        # ── 4. 실행 상태 ─────────────────────────
        status_frame = tk.LabelFrame(self, text="실행 상태")
        status_frame.pack(fill=tk.X, padx=10, pady=4)

        self.status_label = tk.Label(status_frame, text="상태: 대기중", anchor="w")
        self.status_label.pack(fill=tk.X, padx=8, pady=(4, 2))

        pb_row = tk.Frame(status_frame)
        pb_row.pack(fill=tk.X, padx=8, pady=(0, 6))

        self.progress_bar = ttk.Progressbar(pb_row, orient=tk.HORIZONTAL, mode="determinate", maximum=100)
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.progress_pct_label = tk.Label(pb_row, text="  0%", width=5, anchor="e")
        self.progress_pct_label.pack(side=tk.LEFT)

        # ── 5. 처리 단계 ─────────────────────────
        step_outer = tk.LabelFrame(self, text="처리 단계")
        step_outer.pack(fill=tk.X, padx=10, pady=4)

        step_grid = tk.Frame(step_outer)
        step_grid.pack(fill=tk.X, padx=8, pady=6)

        # 6단계를 3열 × 2행으로 배치
        # 열 순서: [0]공문접속 [1]데이터추출 [2]관리자이동
        #          [3]사용자검색 [4]권한선택  [5]최종승인/종료
        display_order = [0, 1, 4,   # row0: 공문접속 | 데이터추출 | 관리자이동
                         2, 3, 5]   # row1: 사용자검색 | 권한선택 | 최종승인/종료
        self.step_labels = {}
        for grid_pos, step_idx in enumerate(display_order):
            row = grid_pos // 3
            col = grid_pos % 3
            lbl = tk.Label(
                step_grid,
                text=f"○ {STEPS[step_idx]}: 대기",
                fg="gray", anchor="w", width=22
            )
            lbl.grid(row=row, column=col, sticky="w", padx=10, pady=3)
            self.step_labels[step_idx] = lbl

        # ── 6. 현재 파싱된 데이터 확인 ────────────
        data_frame = tk.LabelFrame(
            self, text="현재 파싱된 데이터 확인 (화면 표출)",
            fg="#1565C0", font=("맑은 고딕", 9, "bold")
        )
        data_frame.pack(fill=tk.X, padx=10, pady=4)

        self.parsed_id_label = tk.Label(
            data_frame, text="대상 ID : (대기 중)",
            font=("맑은 고딕", 11, "bold"), fg="#333333", anchor="w"
        )
        self.parsed_id_label.pack(fill=tk.X, padx=10, pady=(6, 2))

        self.parsed_perm_label = tk.Label(
            data_frame, text="요청 권한 : (대기 중)",
            font=("맑은 고딕", 10), fg="#555555", anchor="w"
        )
        self.parsed_perm_label.pack(fill=tk.X, padx=10, pady=(2, 6))

        # ── 7. 로그 ──────────────────────────────
        log_frame = tk.Frame(self)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(4, 8))

        tk.Label(log_frame, text="처리 로그").pack(anchor="w")
        self.log_area = scrolledtext.ScrolledText(
            log_frame, wrap=tk.WORD, font=("Consolas", 9), bg="#F5F5F5"
        )
        self.log_area.pack(fill=tk.BOTH, expand=True)

        self.append_log("프로그램이 시작되었습니다. URL을 설정하고 버튼을 누르세요.")

    # ──────────────────────────────────────────
    # 상태 콜백 (automator → UI)
    # ──────────────────────────────────────────
    def update_status(self, text):
        """실행 상태 텍스트 업데이트"""
        self.after(0, lambda: self.status_label.config(text=f"상태: {text}"))

    def update_progress(self, value: int):
        """프로그레스바 업데이트 (0~100)"""
        def _do():
            self.progress_bar["value"] = value
            self.progress_pct_label.config(text=f"{value:3d}%")
        self.after(0, _do)

    def update_step(self, step_idx: int, state: str):
        """처리 단계 인디케이터 업데이트
        state: '대기' | '진행중' | '완료' | '오류'
        """
        def _do():
            if step_idx not in self.step_labels:
                return
            cfg = STEP_COLORS.get(state, STEP_COLORS["대기"])
            self.step_labels[step_idx].config(
                text=f"{cfg['symbol']} {STEPS[step_idx]}: {state}",
                fg=cfg["fg"]
            )
        self.after(0, _do)

    def reset_steps(self):
        """모든 처리 단계를 '대기'로 초기화"""
        for idx in range(len(STEPS)):
            self.update_step(idx, "대기")
        self.update_progress(0)
        self.update_status("대기중")

    def update_parsed_data_display(self, user_id, permissions):
        """automator에서 파싱 결과를 받아 UI 라벨을 갱신"""
        def _update():
            if not user_id or user_id == "(대기 중)":
                self.parsed_id_label.config(text="대상 ID : (대기 중)", fg="#333333")
                self.parsed_perm_label.config(text="요청 권한 : (대기 중)", fg="#555555")
            else:
                perm_text = ", ".join(permissions) if permissions else "(없음)"
                self.parsed_id_label.config(
                    text=f"대상 ID : {user_id}", fg="#1565C0"
                )
                self.parsed_perm_label.config(
                    text=f"요청 권한 : {perm_text}", fg="#2E7D32"
                )
        self.after(0, _update)

    # ──────────────────────────────────────────
    # 버튼 액션
    # ──────────────────────────────────────────
    def run_once(self):
        """수동 1회 실행 (공문 URL 1건)"""
        self.save_config()
        self.reset_steps()
        self.update_status("수동 작업 실행 중...")
        self.automator.run_once(url=self.doc_single_var.get())

    def start_monitoring(self):
        """감시 루프 시작"""
        self.save_config()
        self.reset_steps()
        self.monitor_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.automator.start_monitoring()

    def stop_monitoring(self):
        """감시 루프 중지"""
        self.automator.stop()
        self.stop_btn.config(state=tk.DISABLED)
        self.monitor_btn.config(state=tk.NORMAL)
        self.update_status("중지됨")

    def on_closing(self):
        self.automator.quit()
        self.destroy()

    # ──────────────────────────────────────────
    # 설정 저장
    # ──────────────────────────────────────────
    def save_config(self):
        try:
            try:
                interval_val = int(self.scan_interval_var.get())
                if interval_val < 1:
                    interval_val = 1
                    self.scan_interval_var.set("1")
            except ValueError:
                interval_val = 30
                self.scan_interval_var.set("30")
                self.append_log("스캔 주기 값이 잘못되어 기본값(30초)으로 설정합니다.")

            try:
                retry_val = int(self.max_retry_var.get())
                if retry_val < 1:
                    retry_val = 1
                    self.max_retry_var.set("1")
            except ValueError:
                retry_val = 3
                self.max_retry_var.set("3")

            with open('config.json', 'r', encoding='utf-8') as f:
                config = json.load(f)

            config['document_detail_url'] = self.doc_single_var.get()
            config['document_list_url']   = self.doc_url_var.get()
            config['admin_url']           = self.admin_url_var.get()
            config['dry_run']             = self.dry_run_var.get()
            config['require_confirmation']= self.confirm_var.get()
            config['auto_retry']          = self.auto_retry_var.get()
            config['refresh_interval_seconds'] = interval_val
            config['max_retries']         = retry_val

            with open('config.json', 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)

            self.automator.load_config()
            self.append_log(f"설정이 저장되었습니다. (스캔 주기: {interval_val}초, 최대 재시도: {retry_val}회)")
        except Exception as e:
            self.append_log(f"설정 저장 오류: {e}")

    # ──────────────────────────────────────────
    # 로그 / 팝업
    # ──────────────────────────────────────────
    def append_log(self, msg):
        now = datetime.datetime.now().strftime("[%H:%M:%S]")
        self.after(0, self._insert_log, f"{now} {msg}")

    def _insert_log(self, msg):
        self.log_area.insert(tk.END, msg + "\n")
        self.log_area.see(tk.END)

    def show_error_popup(self, msg):
        self.after(0, lambda: messagebox.showwarning("자동화 경고", msg))

    def show_confirm_popup(self, msg):
        event = threading.Event()
        result = [False]
        def _ask():
            result[0] = messagebox.askyesno("권한 부여 최종 승인 대기", msg)
            event.set()
        self.after(0, _ask)
        event.wait()
        return result[0]

    # ──────────────────────────────────────────
    # 작업 이력
    # ──────────────────────────────────────────
    def show_history(self):
        import database
        records = database.get_all_processed_docs()

        hist_win = tk.Toplevel(self)
        hist_win.title("작업 완료/실패 이력")
        hist_win.geometry("700x400")

        columns = ("time", "doc_id", "user_id", "status")
        tree = ttk.Treeview(hist_win, columns=columns, show="headings")
        tree.heading("time",    text="처리 시간")
        tree.heading("doc_id",  text="공문 ID (또는 텍스트)")
        tree.heading("user_id", text="대상자 ID")
        tree.heading("status",  text="결과 상태")

        tree.column("time",    width=150, anchor="center")
        tree.column("doc_id",  width=300, anchor="w")
        tree.column("user_id", width=120, anchor="center")
        tree.column("status",  width=100, anchor="center")

        scrollbar = ttk.Scrollbar(hist_win, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        for r in records:
            tree.insert("", tk.END, values=(r[2], r[0], r[1], r[3]))


if __name__ == "__main__":
    app = Application()
    app.mainloop()
