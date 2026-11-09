# Arabic Subtitle Maker

A desktop Python app for local videos and public YouTube URLs. It transcribes speech locally with Faster-Whisper, translates it into Modern Standard Arabic with Gemini, and creates:
- A separate `.ar.srt` subtitle file
- A new MP4 with Arabic subtitles permanently burned into the picture
- Or both outputs

## Requirements

- Python 3.10–3.12 (64-bit recommended).
- FFmpeg on PATH (required only when burning subtitles into the video; SRT-only output does not require it).
- A Gemini API key from https://aistudio.google.com/apikey

Gemini's API has a free tier for selected models. Limits and model availability can change; see https://ai.google.dev/gemini-api/docs/pricing. This app uses the stable `gemini-3.8-flash` model. Older Gemini models may not be available to new API users; the model ID is defined near the top of `app.py`.

**Privacy:** Whisper transcription runs locally. The transcript text is sent to Google's Gemini API for translation. Google states that free-tier content may be used to improve its products. Avoid using this with sensitive/private videos if that is a concern.

## Install on Windows

1. Install Python 3.12 (64-bit): https://www.python.org/downloads/
2. (Optional, required only for burned-in MP4 output) Install FFmpeg:
   ```powershell
   winget install Gyan.FFmpeg
   ```
3. If CTranslate2 reports that a DLL cannot be loaded, install Microsoft Visual C++ Redistributable x64:
   https://aka.ms/vc14/vc_redist.x64.exe
4. Extract this folder and open PowerShell inside it:
   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   python app.py
   ```

If PowerShell blocks activation, use Command Prompt:
```bat
.venv\Scripts\activate.bat
```

After installing FFmpeg, close and reopen PowerShell so PATH refreshes.

## Quick setup on Windows

You can also double-click `setup_windows.bat` to create the virtual environment and install Python dependencies. Then double-click `run_windows.bat` to launch the app. Install FFmpeg separately if you want burned-in MP4 output.

## Install on Debian/Ubuntu

```bash
sudo apt install ffmpeg python3-tk python3-venv
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

## Use

1. Choose YouTube URL or Local video file.
2. Paste a public YouTube URL or browse to a local video.
3. Choose an output folder.
4. Paste your Gemini API key.
5. Select a Whisper model (`small` is a good starting point).
6. Select SRT, burn-in MP4, or both.
7. Click Generate Arabic subtitles.

Output examples:
- `video_name.ar.srt`
- `video_name.ar.subtitled.mp4`

## Burned subtitle appearance

The burned MP4 uses white Arabic text with a black outline near the bottom, like movie subtitles. FFmpeg's libass renderer needs FriBidi support for correct Arabic shaping and right-to-left text. If Arabic letters appear disconnected or reversed, install a full FFmpeg build with libass/FriBidi support.

Burning captions re-encodes the video and can take a while. The original video is not changed. The output uses H.264 video (CRF 20) and AAC audio.

## Notes

- First use downloads the Whisper model; larger models may take several GB.
- YouTube downloading uses yt-dlp and may need updates if YouTube changes.
- Only download videos you own or have permission to download. Respect copyright and YouTube's terms.
- Review names, technical terms, translation quality, and timing before publishing.
- This app does not upload anything to YouTube.


## Troubleshooting

- **Gemini 404 / model not found:** make sure you are using a current app version. This release calls `gemini-3.8-flash`. Check that your API key was created in Google AI Studio and that the Gemini API is available to your account/region.
- **`metadata_errors` error:** keep PyAV below version 19. The requirements file already constrains it to `av<19`.
- **CTranslate2 DLL error on Windows:** install the Microsoft Visual C++ Redistributable x64 and restart Windows.
- **FFmpeg not found:** install FFmpeg and reopen the terminal/app so PATH refreshes. This is only needed for burning subtitles into the video.
