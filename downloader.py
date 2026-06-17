"""
YouTube Downloader — 단일 파일 구현
설계 문서: _workspace/01_command_design.md
Python 3.x + tkinter + yt_dlp
"""

import sys
import os
import shutil
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import yt_dlp
    print("[DEBUG] yt_dlp import 성공:", yt_dlp.version.__version__)
except ImportError:
    messagebox.showerror(
        "모듈 누락",
        "yt_dlp가 설치되어 있지 않습니다.\n\npip install yt-dlp 를 실행 후 재시작하세요."
    )
    sys.exit(1)


# ─────────────────────────────────────────────
# 1. DownloadConfig (dataclass)
# ─────────────────────────────────────────────

@dataclass
class DownloadConfig:
    """다운로드 파라미터 보관 전용 — 로직 없음"""
    url: str
    format: str          # "mp3" | "mp4"
    quality: str         # "192" | "320" | "1080" | "2160"
    save_dir: Path
    no_playlist: bool = True


# ─────────────────────────────────────────────
# 2. YtdlpRunner (Thread 서브클래스)
# ─────────────────────────────────────────────

class YtdlpRunner(threading.Thread):
    """
    별도 Thread에서 yt_dlp 다운로드 실행.
    진행 상태를 queue로 MainWindow에 전달.
    """

    def __init__(self, config: DownloadConfig,
                 result_queue: queue.Queue,
                 cancel_event: threading.Event):
        super().__init__(daemon=True)
        self.config = config
        self.queue = result_queue
        self.cancel_event = cancel_event
        print(f"[DEBUG] YtdlpRunner 생성: format={config.format}, quality={config.quality}, url={config.url[:60]}")

    # ── FFmpeg 경로 탐색 ──────────────────────────────────────
    @staticmethod
    def _get_ffmpeg_path() -> Optional[str]:
        if getattr(sys, 'frozen', False):
            # 1순위: PyInstaller 번들 내부 (onefile 빌드 시)
            bundle_path = os.path.join(sys._MEIPASS, 'ffmpeg')
            if os.path.exists(os.path.join(bundle_path, 'ffmpeg.exe')):
                print(f"[DEBUG] 번들 FFmpeg 사용: {bundle_path}")
                return bundle_path
            # 2순위: EXE 파일 옆 ffmpeg.exe
            exe_dir = str(Path(sys.executable).parent)
            if os.path.exists(os.path.join(exe_dir, 'ffmpeg.exe')):
                print(f"[DEBUG] EXE 옆 FFmpeg 사용: {exe_dir}")
                return exe_dir
        # 개발 환경: PATH에서 탐색 (None → yt-dlp가 PATH에서 찾음)
        return None

    # ── yt-dlp 옵션 딕셔너리 생성 ─────────────────────────────
    def build_options(self) -> dict:
        cfg = self.config
        fmt = cfg.format
        qty = cfg.quality
        ffmpeg_loc = self._get_ffmpeg_path()

        # 포맷별 기본 옵션
        if fmt == "mp3":
            opts = {
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": qty,   # "192" or "320"
                }],
            }
        elif fmt == "mp4" and qty == "1080":
            opts = {
                "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best[height<=1080]",
                "merge_output_format": "mp4",
                "postprocessors": [{
                    "key": "FFmpegVideoConvertor",
                    "preferedformat": "mp4",
                }],
            }
        else:  # mp4 2160p
            opts = {
                "format": "bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/best[height<=2160][ext=mp4]/best[height<=2160]",
                "merge_output_format": "mp4",
                "postprocessors": [{
                    "key": "FFmpegVideoConvertor",
                    "preferedformat": "mp4",
                }],
            }

        # 공통 옵션 추가
        outtmpl = str(cfg.save_dir / "%(title)s.%(ext)s")
        opts.update({
            "outtmpl": outtmpl,
            "ffmpeg_location": ffmpeg_loc,
            "progress_hooks": [self._progress_hook],
            "noplaylist": cfg.no_playlist,
            "quiet": True,
            "no_warnings": False,
            "ignoreerrors": False,
        })

        print(f"[DEBUG] build_options: {opts}")
        return opts

    # ── 진행률 콜백 → Queue push ───────────────────────────────
    def _progress_hook(self, d: dict):
        # 취소 신호 확인
        if self.cancel_event.is_set():
            print("[DEBUG] 취소 이벤트 감지 — DownloadCancelled raise")
            raise yt_dlp.utils.DownloadCancelled("사용자 취소")

        status = d.get("status")

        if status == "downloading":
            raw = d.get("_percent_str", "0%").strip()
            # "  45.2%" 형태 파싱
            try:
                percent = float(raw.replace("%", "").strip())
            except ValueError:
                percent = 0.0

            speed = d.get("_speed_str", "").strip()
            eta = d.get("eta") or 0

            msg = {
                "type": "progress",
                "percent": percent,
                "speed": speed,
                "eta": eta,
                "status_text": f"다운로드 중... {percent:.1f}%  {speed}  남은 시간: {eta}초",
            }
            self.queue.put(msg)

        elif status == "finished":
            filename = d.get("filename", "")
            print(f"[DEBUG] 다운로드 finished: {filename}")
            # 후처리(FFmpeg) 진행 중 상태 표시
            self.queue.put({
                "type": "progress",
                "percent": 99.0,
                "speed": "",
                "eta": 0,
                "status_text": "후처리 중 (FFmpeg 변환)...",
            })

    # ── Thread 본체 ───────────────────────────────────────────
    def run(self):
        print(f"[DEBUG] YtdlpRunner.run() 시작 — URL: {self.config.url}")
        try:
            opts = self.build_options()
            with yt_dlp.YoutubeDL(opts) as ydl:
                # 파일명 추출용 info (다운로드 전)
                info = ydl.extract_info(self.config.url, download=True)

            if info is None:
                raise RuntimeError("영상 정보를 가져올 수 없습니다.")

            # 완료 파일명 추정
            title = info.get("title", "알 수 없음")
            ext = "mp3" if self.config.format == "mp3" else "mp4"
            filename = f"{title}.{ext}"
            filesize_bytes = info.get("filesize") or info.get("filesize_approx") or 0
            size_mb = filesize_bytes / (1024 * 1024) if filesize_bytes else 0.0

            print(f"[DEBUG] 다운로드 완료: {filename} ({size_mb:.1f} MB)")
            self.queue.put({
                "type": "done",
                "filename": filename,
                "size_mb": size_mb,
            })

        except yt_dlp.utils.DownloadCancelled:
            print("[DEBUG] DownloadCancelled — 취소 완료")
            self.queue.put({"type": "cancelled"})

        except yt_dlp.utils.DownloadError as e:
            msg = str(e)
            print(f"[DEBUG] DownloadError: {msg}")
            self.queue.put({"type": "error", "message": msg})

        except Exception as e:
            msg = str(e)
            print(f"[DEBUG] 예외 발생: {type(e).__name__}: {msg}")
            self.queue.put({"type": "error", "message": msg})


# ─────────────────────────────────────────────
# 3. MainWindow
# ─────────────────────────────────────────────

class MainWindow:
    """
    tkinter 메인 윈도우.
    상태 머신: IDLE → READY → DOWNLOADING → DONE/ERROR/CANCELLED
    Thread ↔ UI 통신: queue.Queue + after(100ms) poll
    """

    # 상태 상수
    STATE_IDLE        = "IDLE"
    STATE_READY       = "READY"
    STATE_DOWNLOADING = "DOWNLOADING"
    STATE_CANCELLING  = "CANCELLING"
    STATE_DONE        = "DONE"
    STATE_ERROR       = "ERROR"

    # 품질 옵션 맵
    QUALITY_MAP = {
        "mp3": ["192kbps", "320kbps"],
        "mp4": ["1080p", "2160p (4K)"],
    }
    QUALITY_VALUE_MAP = {
        "192kbps": "192",
        "320kbps": "320",
        "1080p": "1080",
        "2160p (4K)": "2160",
    }

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("YouTube Downloader")
        self.root.resizable(False, False)
        self.root.geometry("600x430")

        # 내부 상태
        self._state = self.STATE_IDLE
        self._queue: queue.Queue = queue.Queue()
        self._cancel_event = threading.Event()
        self._runner: Optional[YtdlpRunner] = None

        # FFmpeg 체크
        self._ffmpeg_ok = self._check_ffmpeg()

        # UI 구성
        self._build_ui()

        # 큐 폴링 시작
        self._poll_queue()

        # 초기 상태 적용
        self._set_state(self.STATE_IDLE)

        print("[DEBUG] MainWindow 초기화 완료")

    GITHUB_URL = "https://github.com/nokelan/yt-downloader"

    def _open_github(self):
        import webbrowser
        webbrowser.open(self.GITHUB_URL)
        print(f"[DEBUG] GitHub 열기: {self.GITHUB_URL}")

    # ── FFmpeg 감지 ────────────────────────────────────────────
    def _check_ffmpeg(self) -> bool:
        # PATH 확인
        if shutil.which("ffmpeg") is not None:
            print("[DEBUG] FFmpeg 감지: PATH에 있음")
            return True
        # 번들/EXE 옆 확인
        ffmpeg_loc = self._get_ffmpeg_path()
        if ffmpeg_loc and os.path.exists(os.path.join(ffmpeg_loc, 'ffmpeg.exe')):
            print(f"[DEBUG] FFmpeg 감지: {ffmpeg_loc}")
            return True
        # EXE 옆 직접 확인 (frozen 여부 무관)
        if getattr(sys, 'frozen', False):
            exe_dir = Path(sys.executable).parent
        else:
            exe_dir = Path(__file__).parent
        if (exe_dir / 'ffmpeg.exe').exists():
            print(f"[DEBUG] FFmpeg 감지: EXE 옆 {exe_dir}")
            return True

        print("[DEBUG] FFmpeg 없음")
        messagebox.showwarning(
            "FFmpeg 미설치",
            "FFmpeg가 설치되어 있지 않습니다.\n\n"
            "MP3 변환 및 MP4 병합에 FFmpeg가 필요합니다.\n\n"
            "해결 방법 (택 1):\n"
            "① YTDownloader.exe 와 같은 폴더에 ffmpeg.exe 를 복사\n"
            "② https://github.com/BtbN/FFmpeg-Builds/releases 에서\n"
            "   ffmpeg-master-latest-win64-gpl.zip 다운로드 후 bin\\ffmpeg.exe 복사\n\n"
            "복사 후 재시작하세요."
        )
        return False

    # ── UI 구성 ────────────────────────────────────────────────
    def _build_ui(self):
        PAD = {"padx": 10, "pady": 5}

        # ── 상단 헤더 ──
        header = tk.Frame(self.root, bg="#2d2d2d", height=40)
        header.pack(fill="x")
        tk.Label(
            header, text="YouTube Downloader",
            bg="#2d2d2d", fg="white",
            font=("Segoe UI", 13, "bold")
        ).pack(side="left", padx=12, pady=8)
        github_lbl = tk.Label(
            header, text="GitHub / 피드백",
            bg="#2d2d2d", fg="#aaaaaa",
            font=("Segoe UI", 9, "underline"),
            cursor="hand2"
        )
        github_lbl.pack(side="right", padx=12, pady=10)
        github_lbl.bind("<Button-1>", lambda e: self._open_github())

        # ── 메인 컨텐츠 프레임 ──
        content = tk.Frame(self.root, bg="white", padx=12, pady=8)
        content.pack(fill="both", expand=True)

        # ── URL 행 ──
        url_frame = tk.Frame(content, bg="white")
        url_frame.pack(fill="x", pady=(8, 4))
        tk.Label(url_frame, text="URL", width=8, anchor="w", bg="white",
                 font=("Segoe UI", 9)).pack(side="left")
        self.url_var = tk.StringVar()
        self.url_var.trace_add("write", self._on_url_change)
        url_entry = tk.Entry(url_frame, textvariable=self.url_var,
                             font=("Segoe UI", 9), relief="solid", bd=1)
        url_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.btn_paste = ttk.Button(url_frame, text="붙여넣기", width=9,
                                    command=self._on_paste)
        self.btn_paste.pack(side="left")

        # ── 포맷 & 품질 행 ──
        fq_frame = tk.Frame(content, bg="white")
        fq_frame.pack(fill="x", pady=4)

        tk.Label(fq_frame, text="포맷", width=8, anchor="w", bg="white",
                 font=("Segoe UI", 9)).pack(side="left")
        self.format_var = tk.StringVar(value="mp3")
        for fmt_val, fmt_lbl in [("mp3", "MP3"), ("mp4", "MP4")]:
            rb = ttk.Radiobutton(fq_frame, text=fmt_lbl,
                                 variable=self.format_var, value=fmt_val,
                                 command=self._on_format_change)
            rb.pack(side="left", padx=6)

        tk.Label(fq_frame, text="품질", bg="white",
                 font=("Segoe UI", 9)).pack(side="left", padx=(20, 4))
        self.quality_var = tk.StringVar()
        self.quality_combo = ttk.Combobox(fq_frame, textvariable=self.quality_var,
                                          state="readonly", width=14,
                                          font=("Segoe UI", 9))
        self.quality_combo.pack(side="left")
        self._on_format_change()  # 초기 품질 목록 설정

        # ── 재생목록 체크박스 ──
        pl_frame = tk.Frame(content, bg="white")
        pl_frame.pack(fill="x", pady=2)
        tk.Label(pl_frame, text="", width=8, bg="white").pack(side="left")
        self.playlist_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(pl_frame, text="재생목록 전체 받기",
                        variable=self.playlist_var).pack(side="left")

        # ── 저장 경로 행 ──
        dir_frame = tk.Frame(content, bg="white")
        dir_frame.pack(fill="x", pady=4)
        tk.Label(dir_frame, text="저장 경로", width=8, anchor="w", bg="white",
                 font=("Segoe UI", 9)).pack(side="left")
        default_dir = str(Path.home() / "Downloads")
        self.save_dir_var = tk.StringVar(value=default_dir)
        dir_entry = tk.Entry(dir_frame, textvariable=self.save_dir_var,
                             font=("Segoe UI", 9), relief="solid", bd=1,
                             state="readonly")
        dir_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.btn_browse = ttk.Button(dir_frame, text="찾아보기", width=9,
                                     command=self._on_browse)
        self.btn_browse.pack(side="left")

        # ── 버튼 행 ──
        btn_frame = tk.Frame(content, bg="white")
        btn_frame.pack(pady=8)
        self.btn_start = ttk.Button(btn_frame, text="다운로드 시작", width=16,
                                    command=self._on_start)
        self.btn_start.pack(side="left", padx=8)
        self.btn_cancel = ttk.Button(btn_frame, text="취소", width=10,
                                     command=self._on_cancel)
        self.btn_cancel.pack(side="left", padx=8)

        # ── 진행률 바 ──
        prog_frame = tk.Frame(content, bg="white")
        prog_frame.pack(fill="x", pady=(4, 2))
        self.pct_label = tk.Label(prog_frame, text="  0%", width=6, bg="white",
                                  font=("Segoe UI", 9), anchor="e")
        self.pct_label.pack(side="right")
        self.progress_bar = ttk.Progressbar(prog_frame, mode="determinate",
                                            maximum=100)
        self.progress_bar.pack(side="left", fill="x", expand=True)

        # ── 상태 레이블 ──
        self.status_label = tk.Label(content, text="URL을 입력하거나 붙여넣기 하세요.",
                                     bg="white", fg="#555555",
                                     font=("Segoe UI", 9), anchor="w")
        self.status_label.pack(fill="x", pady=(0, 4))

        # ── 구분선 ──
        ttk.Separator(content, orient="horizontal").pack(fill="x", pady=4)

        # ── 완료 목록 ──
        tk.Label(content, text="완료 목록", bg="white", fg="#333333",
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x")
        list_frame = tk.Frame(content, bg="white")
        list_frame.pack(fill="both", expand=True, pady=(2, 0))
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        self.result_listbox = tk.Listbox(list_frame, font=("Segoe UI", 9),
                                         relief="flat", bd=0,
                                         selectbackground="#e8e8e8",
                                         yscrollcommand=scrollbar.set,
                                         height=5)
        self.result_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.result_listbox.yview)

    # ── 이벤트 핸들러 ─────────────────────────────────────────

    def _on_url_change(self, *_):
        url = self.url_var.get().strip()
        if url.startswith("http") and len(url) > 10:
            if self._state == self.STATE_IDLE:
                self._set_state(self.STATE_READY)
        else:
            if self._state == self.STATE_READY:
                self._set_state(self.STATE_IDLE)

    def _on_paste(self):
        try:
            text = self.root.clipboard_get().strip()
            self.url_var.set(text)
            print(f"[DEBUG] 붙여넣기: {text[:80]}")
        except tk.TclError:
            messagebox.showinfo("클립보드", "클립보드에 내용이 없습니다.")

    def _on_format_change(self, *_):
        fmt = self.format_var.get()
        options = self.QUALITY_MAP.get(fmt, [])
        self.quality_combo["values"] = options
        if options:
            self.quality_var.set(options[0])
        print(f"[DEBUG] 포맷 변경: {fmt} → 품질 목록: {options}")

    def _on_browse(self):
        chosen = filedialog.askdirectory(
            title="다운로드 폴더 선택",
            initialdir=self.save_dir_var.get()
        )
        if chosen:
            self.save_dir_var.set(chosen)
            print(f"[DEBUG] 저장 경로 변경: {chosen}")

    def _on_start(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("URL 없음", "YouTube URL을 입력하세요.")
            return

        # FFmpeg 필요 포맷인데 없는 경우
        if not self._ffmpeg_ok:
            ans = messagebox.askyesno(
                "FFmpeg 미설치",
                "FFmpeg가 없으면 MP3 변환/MP4 병합이 실패할 수 있습니다.\n"
                "그래도 계속 진행하시겠습니까?"
            )
            if not ans:
                return

        fmt = self.format_var.get()
        quality_label = self.quality_var.get()
        quality = self.QUALITY_VALUE_MAP.get(quality_label, "192")
        save_dir = Path(self.save_dir_var.get())
        no_playlist = not self.playlist_var.get()

        if not save_dir.exists():
            messagebox.showerror("경로 오류", f"저장 경로가 존재하지 않습니다:\n{save_dir}")
            return

        config = DownloadConfig(
            url=url,
            format=fmt,
            quality=quality,
            save_dir=save_dir,
            no_playlist=no_playlist,
        )
        print(f"[DEBUG] 다운로드 시작 요청: {config}")

        # 취소 이벤트 초기화
        self._cancel_event.clear()

        # Runner 생성 및 시작
        self._runner = YtdlpRunner(config, self._queue, self._cancel_event)
        self._runner.start()

        self._set_state(self.STATE_DOWNLOADING)

    def _on_cancel(self):
        print("[DEBUG] 취소 버튼 클릭")
        self._cancel_event.set()
        self._set_state(self.STATE_CANCELLING)
        self.status_label.config(text="취소 중... 잠시 기다려 주세요.")

    # ── 큐 폴링 (Thread-safe UI 갱신) ────────────────────────
    def _poll_queue(self):
        try:
            while True:
                msg = self._queue.get_nowait()
                print(f"[DEBUG] Queue 수신: {msg}")
                self._handle_queue_msg(msg)
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._poll_queue)

    def _handle_queue_msg(self, msg: dict):
        mtype = msg.get("type")

        if mtype == "progress":
            pct = msg.get("percent", 0.0)
            self.progress_bar["value"] = pct
            self.pct_label.config(text=f"{pct:3.0f}%")
            self.status_label.config(text=msg.get("status_text", ""))

        elif mtype == "done":
            filename = msg.get("filename", "")
            size_mb = msg.get("size_mb", 0.0)
            self.progress_bar["value"] = 100
            self.pct_label.config(text="100%")
            self.status_label.config(text=f"완료: {filename}")
            entry = f"✓  {filename}"
            if size_mb > 0:
                entry += f"  ({size_mb:.1f} MB)"
            self.result_listbox.insert(tk.END, entry)
            self.result_listbox.see(tk.END)
            self._set_state(self.STATE_DONE)

        elif mtype == "error":
            error_msg = msg.get("message", "알 수 없는 오류")
            self.status_label.config(text=f"오류: {error_msg}", fg="red")
            self.result_listbox.insert(tk.END, f"✗  오류: {error_msg}")
            self.result_listbox.see(tk.END)
            self._set_state(self.STATE_ERROR)
            messagebox.showerror("다운로드 오류", error_msg)

        elif mtype == "cancelled":
            self.status_label.config(text="다운로드가 취소되었습니다.")
            self.progress_bar["value"] = 0
            self.pct_label.config(text="0%")
            self._set_state(self.STATE_READY)

    # ── 상태 머신 ─────────────────────────────────────────────
    def _set_state(self, state: str):
        self._state = state
        print(f"[DEBUG] 상태 전이 → {state}")

        url_has_value = len(self.url_var.get().strip()) > 10

        if state == self.STATE_IDLE:
            self.btn_start.config(state="disabled")
            self.btn_cancel.config(state="disabled")
            self.status_label.config(text="URL을 입력하거나 붙여넣기 하세요.", fg="#555555")

        elif state == self.STATE_READY:
            self.btn_start.config(state="normal")
            self.btn_cancel.config(state="disabled")
            self.status_label.config(text="다운로드 준비 완료.", fg="#555555")

        elif state == self.STATE_DOWNLOADING:
            self.btn_start.config(state="disabled")
            self.btn_cancel.config(state="normal")
            self.progress_bar["value"] = 0
            self.pct_label.config(text="0%")
            self.status_label.config(text="연결 중...", fg="#555555")

        elif state == self.STATE_CANCELLING:
            self.btn_start.config(state="disabled")
            self.btn_cancel.config(state="disabled")

        elif state == self.STATE_DONE:
            self.btn_start.config(state="normal")
            self.btn_cancel.config(state="disabled")

        elif state == self.STATE_ERROR:
            self.btn_start.config(state="normal" if url_has_value else "disabled")
            self.btn_cancel.config(state="disabled")
            self.status_label.config(fg="red")


# ─────────────────────────────────────────────
# 진입점
# ─────────────────────────────────────────────

def main():
    print("[DEBUG] 앱 시작")
    root = tk.Tk()

    # 기본 스타일
    style = ttk.Style()
    try:
        style.theme_use("vista")
    except tk.TclError:
        style.theme_use("default")

    app = MainWindow(root)
    root.mainloop()
    print("[DEBUG] 앱 종료")


if __name__ == "__main__":
    main()
