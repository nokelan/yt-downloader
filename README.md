# YouTube Downloader

> AI로 30분 만에 만든 유튜브 다운로더

Python + yt-dlp + tkinter로 만든 심플한 유튜브 다운로드 앱입니다.
설치 없이 exe 파일 하나만 받으면 바로 쓸 수 있습니다.

---

## 다운로드

[Releases 페이지](https://github.com/nokelan/yt-downloader/releases/latest)에서 `YTDownloader.exe` 다운로드

> **필수**: [FFmpeg](https://ffmpeg.org/download.html) 설치 후 시스템 PATH에 등록 필요
> MP3 변환, MP4 병합에 사용됩니다.

---

## 기능

- YouTube URL 붙여넣기 → 자동 다운로드
- **MP3**: 192kbps / 320kbps
- **MP4**: 1080p / 4K(2160p)
- 재생목록 / Shorts 일괄 다운로드
- 다운로드 진행률 + 취소 버튼
- 저장 폴더 선택

---

## 사용법

1. `YTDownloader.exe` 실행
2. YouTube URL 붙여넣기
3. 포맷(MP3/MP4)과 품질 선택
4. "다운로드 시작" 클릭

---

## 개발 환경에서 실행

```bash
pip install yt-dlp
python downloader.py
```

---

## 기술 스택

| 항목 | 내용 |
|------|------|
| 언어 | Python 3.8+ |
| 다운로드 | yt-dlp |
| GUI | tkinter (기본 내장) |
| 패키징 | PyInstaller |

---

## 문제 신고 / 피드백

[Issues](https://github.com/nokelan/yt-downloader/issues)에 남겨주세요.
