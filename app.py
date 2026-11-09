import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import yt_dlp
from faster_whisper import WhisperModel
from google import genai
from google.genai import types

APP_TITLE = "Arabic Subtitle Maker"
DEFAULT_WHISPER_MODEL = "small"
GEMINI_MODEL = "gemini-3.8-flash"


def srt_timestamp(seconds):
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def ass_timestamp(seconds):
    centiseconds = max(0, int(round(seconds * 100)))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, cs = divmod(remainder, 100)
    return f"{hours}:{minutes:02}:{secs:02}.{cs:02}"


def download_youtube_video(url, work_dir, log):
    log("Downloading the YouTube video (this may take a while)…")
    options = {
        "format": "bestvideo*+bestaudio/best",
        "outtmpl": str(work_dir / "source_video.%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        ydl.extract_info(url, download=True)

    candidates = [
        p for p in work_dir.glob("source_video.*")
        if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
    ]
    if not candidates:
        raise RuntimeError(
            "YouTube download completed, but the video file was not found. "
            "Check FFmpeg installation and try updating yt-dlp."
        )
    candidates.sort(key=lambda p: (p.suffix.lower() != ".mp4", -p.stat().st_size))
    return candidates[0]


def transcribe_video(video_path, model_size, log):
    log(f"Loading Whisper model: {model_size} (first run downloads model files)…")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    log("Transcribing speech locally…")
    segments, info = model.transcribe(
        str(video_path), task="transcribe", vad_filter=True, beam_size=5
    )
    result = []
    for segment in segments:
        text = (segment.text or "").strip()
        if text:
            result.append({
                "start": float(segment.start),
                "end": float(segment.end),
                "text": text,
            })
    if not result:
        raise RuntimeError("Whisper did not detect any speech in this video.")
    return result, getattr(info, "language", "unknown")


def translate_segments_with_gemini(segments, api_key, log):
    if not api_key.strip():
        raise RuntimeError("Enter a Gemini API key from Google AI Studio.")

    client = genai.Client(api_key=api_key.strip())
    translated = []
    batch_size = 20
    schema = {
        "type": "OBJECT",
        "properties": {
            "translations": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "id": {"type": "INTEGER"},
                        "text": {"type": "STRING"},
                    },
                    "required": ["id", "text"],
                },
            }
        },
        "required": ["translations"],
    }

    for start in range(0, len(segments), batch_size):
        batch = segments[start:start + batch_size]
        payload = [{"id": i, "text": item["text"]} for i, item in enumerate(batch)]
        log(f"Translating subtitles {start + 1}–{start + len(batch)} of {len(segments)} with Gemini…")
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=(
                "Translate each subtitle segment into natural, clear Modern Standard Arabic "
                "(العربية الفصحى). Keep each segment separate and preserve its meaning and order. "
                "Do not merge, split, summarize, or omit segments. Keep names and technical terms "
                "accurate. Use concise, movie-style subtitle wording. Return the translations "
                "using the requested JSON schema.\n\n"
                + json.dumps(payload, ensure_ascii=False)
            ),
            config=types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",
                response_json_schema=schema,
            ),
        )
        if not response.text:
            raise RuntimeError("Gemini returned an empty translation. Please retry.")
        data = json.loads(response.text)
        rows = data.get("translations", [])
        by_id = {
            int(row["id"]): str(row["text"]).strip()
            for row in rows if "id" in row and "text" in row
        }
        for i, item in enumerate(batch):
            arabic = by_id.get(i, "").strip()
            if not arabic:
                raise RuntimeError(
                    f"Gemini did not return subtitle {start + i + 1}. Please retry."
                )
            translated.append({**item, "text": arabic})
    return translated


def write_srt(segments, output_path):
    with output_path.open("w", encoding="utf-8-sig", newline="\n") as handle:
        for index, segment in enumerate(segments, 1):
            start = srt_timestamp(segment["start"])
            end = srt_timestamp(max(segment["end"], segment["start"] + 0.15))
            text = re.sub(r"\s+", " ", segment["text"]).strip()
            handle.write(f"{index}\n{start} --> {end}\n{text}\n\n")


def write_ass(segments, output_path):
    # libass handles Arabic shaping and RTL when FFmpeg is built with FriBidi support.
    lines = [
        "[Script Info]", "Title: Arabic subtitles", "ScriptType: v4.00+",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes",
        "PlayResX: 1920", "PlayResY: 1080", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Arabic,Arial,46,&H00FFFFFF,&H000000FF,&H00000000,&H78000000,0,0,1,2.5,1.2,2,70,70,48,1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for segment in segments:
        start = ass_timestamp(segment["start"])
        end = ass_timestamp(max(segment["end"], segment["start"] + 0.15))
        text = segment["text"].replace("{", "［").replace("}", "］")
        text = text.replace("\r", " ").replace("\n", r"\N").strip()
        lines.append(f"Dialogue: 0,{start},{end},Arabic,,0,0,0,,{text}")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def ffmpeg_filter_path(path):
    value = path.resolve().as_posix()
    return value.replace(":", r"\:").replace("'", r"\'").replace(",", r"\,")


def burn_subtitles(video_path, ass_path, output_path, log):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            "FFmpeg was not found. Install it and add ffmpeg.exe to PATH. "
            "PowerShell: winget install Gyan.FFmpeg"
        )
    subtitle_filter = (
        f"subtitles=filename='{ffmpeg_filter_path(ass_path)}':"
        "force_style='FontName=Arial,FontSize=46,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,BorderStyle=1,Outline=2.5,Shadow=1.2,"
        "Alignment=2,MarginV=48'"
    )
    command = [
        ffmpeg, "-y", "-i", str(video_path),
        "-map", "0:v:0", "-map", "0:a?",
        "-vf", subtitle_filter,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", str(output_path),
    ]
    log("Burning Arabic subtitles into the video… This re-encodes the video and can take time.")
    process = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if process.returncode != 0:
        details = (process.stderr or process.stdout or "Unknown FFmpeg error")[-3500:]
        raise RuntimeError("FFmpeg could not burn the subtitles:\n\n" + details)


class SubtitleApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("760x650")
        self.root.minsize(660, 570)
        self.source_type = tk.StringVar(value="youtube")
        self.source_path = tk.StringVar()
        self.output_dir = tk.StringVar(value=str(Path.home() / "Downloads"))
        self.api_key = tk.StringVar(value=os.getenv("GEMINI_API_KEY", ""))
        self.model_size = tk.StringVar(value=DEFAULT_WHISPER_MODEL)
        self.save_srt = tk.BooleanVar(value=True)
        self.burn_video = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Ready")
        self._build_ui()

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Arabic Subtitle Maker", font=("Segoe UI", 19, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="Transcribe a video, translate it into Arabic, then save an SRT and/or bake captions into the video.",
            wraplength=700,
        ).pack(anchor="w", pady=(4, 14))

        source_box = ttk.LabelFrame(outer, text="Video source", padding=12)
        source_box.pack(fill="x", pady=5)
        choices = ttk.Frame(source_box)
        choices.pack(fill="x")
        ttk.Radiobutton(
            choices, text="YouTube URL", variable=self.source_type,
            value="youtube", command=self._update_source_hint
        ).pack(side="left")
        ttk.Radiobutton(
            choices, text="Local video file", variable=self.source_type,
            value="local", command=self._update_source_hint
        ).pack(side="left", padx=18)
        row = ttk.Frame(source_box)
        row.pack(fill="x", pady=(10, 3))
        ttk.Entry(row, textvariable=self.source_path).pack(side="left", fill="x", expand=True)
        self.browse_button = ttk.Button(row, text="Browse…", command=self._browse_source)
        self.browse_button.pack(side="left", padx=(8, 0))
        self.source_hint = ttk.Label(source_box, text="Paste a public YouTube video URL.")
        self.source_hint.pack(anchor="w", pady=(4, 0))

        output_box = ttk.LabelFrame(outer, text="Output", padding=12)
        output_box.pack(fill="x", pady=8)
        out_row = ttk.Frame(output_box)
        out_row.pack(fill="x")
        ttk.Entry(out_row, textvariable=self.output_dir).pack(side="left", fill="x", expand=True)
        ttk.Button(out_row, text="Choose folder…", command=self._browse_output).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(
            output_box, text="Save a separate Arabic .SRT subtitle file",
            variable=self.save_srt
        ).pack(anchor="w", pady=(9, 2))
        ttk.Checkbutton(
            output_box, text="Burn subtitles into the video (permanent movie-style captions)",
            variable=self.burn_video
        ).pack(anchor="w", pady=2)
        ttk.Label(
            output_box,
            text="Burned output: MP4 with white Arabic text, black outline, centered near the bottom.",
            wraplength=680,
        ).pack(anchor="w", pady=(5, 0))

        settings = ttk.LabelFrame(outer, text="AI settings", padding=12)
        settings.pack(fill="x", pady=5)
        key_row = ttk.Frame(settings)
        key_row.pack(fill="x")
        ttk.Label(key_row, text="Gemini API key:").pack(side="left")
        ttk.Entry(key_row, textvariable=self.api_key, show="•").pack(
            side="left", fill="x", expand=True, padx=(10, 0)
        )
        ttk.Label(
            settings, text="Get a key at aistudio.google.com. The key is not saved by this app."
        ).pack(anchor="w", pady=(4, 8))
        model_row = ttk.Frame(settings)
        model_row.pack(fill="x")
        ttk.Label(model_row, text="Whisper model:").pack(side="left")
        ttk.Combobox(
            model_row, textvariable=self.model_size, state="readonly",
            values=["tiny", "base", "small", "medium", "large-v3"], width=14
        ).pack(side="left", padx=10)
        ttk.Label(
            model_row, text="Larger models are more accurate but slower and use more RAM."
        ).pack(side="left")

        self.run_button = ttk.Button(
            outer, text="Generate Arabic subtitles", command=self._start
        )
        self.run_button.pack(fill="x", pady=(13, 8))
        ttk.Label(outer, textvariable=self.status).pack(anchor="w")
        self.log = tk.Text(outer, height=8, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, pady=(6, 0))

    def _update_source_hint(self):
        is_local = self.source_type.get() == "local"
        self.browse_button.configure(state="normal" if is_local else "disabled")
        self.source_hint.configure(
            text="Choose a video file from your computer." if is_local
            else "Paste a public YouTube video URL."
        )

    def _browse_source(self):
        path = filedialog.askopenfilename(
            title="Choose a video",
            filetypes=[
                ("Video files", "*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.mpeg *.mpg"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.source_path.set(path)

    def _browse_output(self):
        path = filedialog.askdirectory(title="Choose output folder")
        if path:
            self.output_dir.set(path)

    def _log(self, message):
        self.root.after(0, self._append_log, message)

    def _append_log(self, message):
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")
        self.status.set(message)

    def _start(self):
        source = self.source_path.get().strip()
        output = self.output_dir.get().strip()
        if not source:
            messagebox.showerror("Missing video", "Choose a video file or paste a YouTube URL.")
            return
        if not output or not Path(output).is_dir():
            messagebox.showerror("Output folder", "Choose an existing output folder.")
            return
        if self.source_type.get() == "local" and not Path(source).is_file():
            messagebox.showerror("Video file", "The selected video file does not exist.")
            return
        if self.source_type.get() == "youtube" and not re.match(r"^https?://", source, re.I):
            messagebox.showerror("YouTube URL", "Paste a valid URL beginning with http:// or https://.")
            return
        if not self.api_key.get().strip():
            messagebox.showerror("Gemini API key required", "Enter your Gemini API key.")
            return
        if not self.save_srt.get() and not self.burn_video.get():
            messagebox.showerror("Choose an output", "Select SRT, burn into video, or both.")
            return
        if self.burn_video.get() and not shutil.which("ffmpeg"):
            messagebox.showerror(
                "FFmpeg required",
                "To burn subtitles into the video, install FFmpeg and add it to PATH.\n\n"
                "PowerShell: winget install Gyan.FFmpeg\n"
                "Then reopen PowerShell and this app.",
            )
            return

        options = {
            "source": source,
            "source_type": self.source_type.get(),
            "output_dir": output,
            "api_key": self.api_key.get().strip(),
            "model_size": self.model_size.get(),
            "save_srt": self.save_srt.get(),
            "burn_video": self.burn_video.get(),
        }
        self.run_button.configure(state="disabled")
        self._append_log("Starting…")
        threading.Thread(target=self._worker, args=(options,), daemon=True).start()

    def _worker(self, options):
        try:
            output_dir = Path(options["output_dir"]).expanduser()
            output_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="arabic_subtitles_") as temp:
                work_dir = Path(temp)
                if options["source_type"] == "youtube":
                    video_path = download_youtube_video(options["source"], work_dir, self._log)
                    base_name = "youtube_video"
                else:
                    video_path = Path(options["source"])
                    base_name = video_path.stem

                segments, language = transcribe_video(
                    video_path, options["model_size"], self._log
                )
                self._log(f"Detected spoken language: {language}")
                arabic_segments = translate_segments_with_gemini(
                    segments, options["api_key"], self._log
                )

                saved_files = []
                if options["save_srt"]:
                    srt_path = output_dir / f"{base_name}.ar.srt"
                    counter = 2
                    while srt_path.exists():
                        srt_path = output_dir / f"{base_name}.ar ({counter}).srt"
                        counter += 1
                    write_srt(arabic_segments, srt_path)
                    saved_files.append(str(srt_path))
                    self._log(f"SRT saved: {srt_path}")

                if options["burn_video"]:
                    ass_path = work_dir / "arabic_subtitles.ass"
                    write_ass(arabic_segments, ass_path)
                    mp4_path = output_dir / f"{base_name}.ar.subtitled.mp4"
                    counter = 2
                    while mp4_path.exists():
                        mp4_path = output_dir / f"{base_name}.ar.subtitled ({counter}).mp4"
                        counter += 1
                    burn_subtitles(video_path, ass_path, mp4_path, self._log)
                    saved_files.append(str(mp4_path))
                    self._log(f"Subtitled video saved: {mp4_path}")

            summary = "Finished successfully:\n\n" + "\n".join(saved_files)
            self._log("Done!")
            self.root.after(0, lambda msg=summary: messagebox.showinfo("Subtitles ready", msg))
        except Exception as exc:
            error_text = str(exc)
            self._log(f"ERROR: {error_text}")
            self.root.after(
                0, lambda err=error_text: messagebox.showerror("Could not generate subtitles", err)
            )
        finally:
            self.root.after(0, lambda: self.run_button.configure(state="normal"))


def main():
    root = tk.Tk()
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    SubtitleApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
