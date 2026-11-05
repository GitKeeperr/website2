"""Konzei Clips: locally hosted video repurposing studio.
Run: python app.py, then visit http://127.0.0.1:8765
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from typing import Literal

from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import engine
import auth

ROOT = Path(__file__).parent.resolve()
DATA = Path(os.getenv('KONZEI_DATA_DIR', str(ROOT / 'data'))).resolve()
PROJECTS = DATA / 'projects'
UPLOADS = DATA / 'uploads'
EXPORTS = DATA / 'exports'
PRESETS = DATA / 'presets.json'
for folder in (DATA, PROJECTS, UPLOADS, EXPORTS):
    folder.mkdir(parents=True, exist_ok=True)

app = FastAPI(title='Konzei Clips', version='1.2.1')
app.mount('/static', StaticFiles(directory=str(ROOT / 'static')), name='static')
LOCK = threading.RLock()
JOBS: dict[str, dict] = {}
VALID_EXT = {'.mp4', '.mov', '.mkv', '.webm', '.m4v', '.avi', '.mpeg', '.mpg'}
MAX_BYTES = int(os.getenv('KONZEI_MAX_UPLOAD_GB', '8')) * 1024**3
USER_PRESETS = DATA / 'user-presets'
USER_PRESETS.mkdir(exist_ok=True)



def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def valid_id(project_id: str):
    if not re.fullmatch(r'[0-9a-f]{32}', project_id):
        raise HTTPException(404, 'Project not found')
    return project_id


def load_project(project_id: str, user: dict) -> dict:
    path = PROJECTS / f'{valid_id(project_id)}.json'
    if not path.is_file():
        raise HTTPException(404, 'Project not found')
    with LOCK:
        project = json.loads(path.read_text(encoding='utf-8'))
        belongs_to = project.get('owner_sub')
        if belongs_to != user['google_sub'] and not (belongs_to is None and user['role'] == 'owner'):
            raise HTTPException(404, 'Project not found')
        return project


def save_project(data: dict) -> None:
    with LOCK:
        path = PROJECTS / f'{data["id"]}.json'
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
        temp.replace(path)


def project_data(pid: str, path: Path, title: str, user: dict) -> dict:
    info = engine.probe(path)
    obj = {'id': pid, 'owner_sub': user['google_sub'], 'title': title[:140], 'file': path.name, 'created': stamp(),
           'info': info, 'status': 'ready', 'highlights': [], 'transcript': [], 'exports': [],
           'analysis_note': '', 'source_url': None}
    save_project(obj)
    try:
        engine.thumbnail(path, UPLOADS / f'{pid}.jpg')
    except Exception:
        pass
    return obj


def job_worker(job_id: str, fn):
    def progress(fraction, message):
        with LOCK:
            JOBS[job_id].update(progress=round(fraction, 2), message=message)
    try:
        result = fn(progress)
        with LOCK:
            JOBS[job_id].update(status='done', progress=1, message='Complete', result=result)
    except Exception as exc:
        with LOCK:
            JOBS[job_id].update(status='error', message=str(exc)[-1200:])


def start_job(kind: str, fn, user: dict) -> dict:
    jid = uuid.uuid4().hex
    with LOCK:
        if auth.PUBLIC_MODE and sum(j['status'] == 'working' for j in JOBS.values()) >= int(os.getenv('KONZEI_MAX_ACTIVE_JOBS', '2')):
            raise HTTPException(429, 'Konzei is busy processing videos. Please retry shortly.')
        JOBS[jid] = {'id': jid, 'owner_sub': user['google_sub'], 'kind': kind, 'status': 'working', 'progress': .04, 'message': 'Starting…', 'result': None}
    threading.Thread(target=job_worker, args=(jid, fn), daemon=True).start()
    return JOBS[jid]


@app.middleware('http')
async def auth_guard(request: Request, call_next):
    path = request.url.path
    if path.startswith('/api/') or path.startswith('/media/'):
        public = {'/api/auth/config', '/api/auth/me', '/api/auth/google', '/api/auth/logout'}
        if path not in public:
            user = auth.current_user(request)
            if user is None:
                return JSONResponse({'detail': 'Sign in with Google to use Konzei Clips.'}, status_code=401)
            request.state.user = user
            if path.startswith('/api/owner/') and user['role'] != 'owner':
                return JSONResponse({'detail': 'Owner-only feature.'}, status_code=403)
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            try:
                auth.check_csrf(request)
            except HTTPException as exc:
                return JSONResponse({'detail': exc.detail}, status_code=exc.status_code)
    response = await call_next(request)
    if path.startswith('/api/') or path.startswith('/media/'):
        response.headers['Cache-Control'] = 'private, no-store'
    return response


@app.middleware('http')
async def basic_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    if auth.PUBLIC_MODE:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    return response


app.include_router(auth.router)
app.include_router(auth.owner_router)


def preset_path(user: dict) -> Path:
    if user['role'] == 'owner':
        return PRESETS  # Carry forward the owner's pre-auth local recipes.
    import hashlib
    return USER_PRESETS / (hashlib.sha256(user['google_sub'].encode()).hexdigest() + '.json')


class ImportURL(BaseModel):
    url: str
    cookie_browser: Literal['none', 'chrome', 'edge', 'firefox', 'brave', 'vivaldi'] = 'none'
    cookie_profile: str = Field('', max_length=120)


class AnalyzeOptions(BaseModel):
    count: int = Field(6, ge=1, le=20)
    length: float = Field(45, ge=3, le=900)
    prompt: str = Field('', max_length=800)
    transcribe: bool = True


class ExportOptions(BaseModel):
    start: float = Field(0, ge=0)
    end: float = Field(45, ge=0)
    ratio: Literal['9:16', '1:1', '4:5', '16:9'] = '9:16'
    crop_mode: Literal['crop', 'blur', 'fit'] = 'crop'
    focus_x: float = Field(.5, ge=0, le=1)
    focus_y: float = Field(.5, ge=0, le=1)
    smart_crop: bool = True
    captions: bool = True
    manual_captions: str = Field('', max_length=18000)
    caption_style: Literal['classic', 'bold', 'karaoke', 'neon', 'minimal'] = 'bold'
    overlay_title: str = Field('', max_length=110)
    censor_captions: bool = False
    enhance_audio: bool = False
    remove_silence: bool = False
    fade: bool = False
    crf: int = Field(23, ge=18, le=32)
    label: str = Field('', max_length=90)


class Preset(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    options: ExportOptions


@app.get('/healthz', include_in_schema=False)
def healthz():
    return {'status': 'ok'}


@app.get('/', response_class=HTMLResponse)
def home():
    return (ROOT / 'static' / 'index.html').read_text(encoding='utf-8')


@app.get('/api/system')
def system():
    try:
        import faster_whisper  # noqa
        transcriber = True
    except ImportError:
        transcriber = False
    try:
        import yt_dlp  # noqa
        downloader = True
    except ImportError:
        downloader = False
    return {'app': 'Konzei Clips', 'version': '1.1.0', 'ffmpeg': bool(shutil.which('ffmpeg')),
            'whisper': transcriber, 'yt_dlp': downloader, 'max_upload_gb': MAX_BYTES // (1024**3),
            'local_only': not auth.PUBLIC_MODE, 'browser_cookie_import': not auth.PUBLIC_MODE}


@app.get('/api/projects')
def list_projects(request: Request):
    projects = []
    for path in PROJECTS.glob('*.json'):
        try:
            p = json.loads(path.read_text(encoding='utf-8'))
            if p.get('owner_sub') != request.state.user['google_sub'] and not (p.get('owner_sub') is None and request.state.user['role'] == 'owner'):
                continue
            projects.append({'id': p['id'], 'title': p['title'], 'created': p['created'],
                             'info': p['info'], 'exports': len(p.get('exports', [])),
                             'highlights': len(p.get('highlights', []))})
        except (ValueError, KeyError):
            continue
    return sorted(projects, key=lambda p: p['created'], reverse=True)


@app.get('/api/projects/{pid}')
def get_project(pid: str, request: Request):
    return load_project(pid, request.state.user)


@app.post('/api/projects/upload')
async def upload_project(request: Request, file: UploadFile = File(...)):
    name = (file.filename or 'video.mp4').replace('\\', '/').split('/')[-1]
    ext = Path(name).suffix.lower()
    if ext not in VALID_EXT:
        raise HTTPException(400, f'Unsupported video format: {ext or "unknown"}. Try MP4, MOV, MKV or WebM.')
    pid = uuid.uuid4().hex
    target = UPLOADS / (pid + ext)
    count = 0
    try:
        with target.open('wb') as dest:
            while chunk := await file.read(2 * 1024 * 1024):
                count += len(chunk)
                if count > MAX_BYTES:
                    raise HTTPException(413, f'Maximum upload size is {MAX_BYTES // 1024**3} GB')
                dest.write(chunk)
        obj = project_data(pid, target, Path(name).stem, request.state.user)
    except Exception as exc:
        target.unlink(missing_ok=True)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(400, f'Video import failed: {exc}') from exc
    finally:
        await file.close()
    return obj


def build_ytdlp_options(pid: str, browser: str = 'none', profile: str = '') -> dict:
    # Cookies are read from the chosen LOCAL browser only on explicit user opt-in.
    # No cookies are exported to a file or stored by Konzei.
    opts = {
        'outtmpl': str(UPLOADS / f'{pid}.%(ext)s'),
        'format': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
        'merge_output_format': 'mp4', 'noplaylist': True, 'quiet': True,
        'max_filesize': MAX_BYTES, 'socket_timeout': 30,
    }
    if browser != 'none':
        # The yt-dlp Python API expects (browser, profile, keyring, container).
        opts['cookiesfrombrowser'] = (browser, profile.strip() or None, None, None)
    return opts


@app.post('/api/projects/import-url')
def import_url(data: ImportURL, request: Request):
    parsed = urlparse(data.url)
    host = (parsed.hostname or '').lower().removeprefix('www.').removeprefix('m.')
    # Explicit allowlist prevents arbitrary local addresses or metadata service requests.
    allow = {'youtube.com', 'youtu.be', 'vimeo.com', 'twitch.tv', 'clips.twitch.tv', 'rumble.com', 'dailymotion.com'}
    if parsed.scheme != 'https' or host not in allow:
        raise HTTPException(400, 'Use an HTTPS video link from YouTube, Vimeo, Twitch, Rumble, or Dailymotion.')
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        raise HTTPException(400, 'Link importer needs yt-dlp in Konzei\'s Python environment. Run: .\\.venv\\Scripts\\python.exe -m pip install yt-dlp, then restart the app.')
    if auth.PUBLIC_MODE and data.cookie_browser != 'none':
        raise HTTPException(400, 'Browser cookie imports are local-only. Upload a file instead on hosted Konzei.')
    pid = uuid.uuid4().hex
    user = request.state.user

    def work(progress):
        progress(.10, 'Downloading from video provider…')
        opts = build_ytdlp_options(pid, data.cookie_browser, data.cookie_profile)
        try:
            with YoutubeDL(opts) as ydl:
                details = ydl.extract_info(data.url, download=True)
        except Exception as exc:
            if 'Sign in to confirm you' in str(exc) or 'not a bot' in str(exc):
                raise ValueError('YouTube requires sign-in verification. In the link importer, select the browser where you are logged into YouTube and try again. If browser cookies cannot be read, close your browser or try Firefox. YouTube may still reject a valid session.') from exc
            raise
        outputs = [p for p in UPLOADS.glob(f'{pid}.*') if p.suffix.lower() in VALID_EXT]
        if not outputs:
            raise ValueError('Download completed but no playable video was found.')
        source = sorted(outputs, key=lambda p: p.stat().st_size, reverse=True)[0]
        progress(.8, 'Creating project…')
        obj = project_data(pid, source, details.get('title') or 'Imported video', user)
        obj['source_url'] = data.url
        save_project(obj)
        return {'project_id': pid}
    return start_job('import', work, user)


@app.post('/api/projects/{pid}/analyze')
def analyze(pid: str, opts: AnalyzeOptions, request: Request):
    user = request.state.user
    p = load_project(pid, user)
    path = UPLOADS / p['file']

    def work(progress):
        progress(.10, 'Reading audio and visual activity…')
        audio = engine.audio_activity(path, p['info']['duration']) if p['info']['has_audio'] else []
        progress(.28, 'Finding scene changes…')
        cuts = engine.scene_changes(path, p['info']['duration'])
        words = p.get('transcript', [])
        note = ''
        if opts.transcribe and not words:
            progress(.48, 'Transcribing speech with local Whisper (if installed)…')
            words, note = engine.transcribe(path)
        progress(.82, 'Ranking candidate highlights…')
        suggestions = engine.identify_highlights(p['info'], words, audio, cuts, opts.count, opts.length, opts.prompt)
        with LOCK:
            current = load_project(pid, user)
            current['transcript'] = words
            current['highlights'] = suggestions
            current['analysis_note'] = note or ('Local activity-based highlight ranking. Scores are estimates, not predicted views.')
            current['last_analyzed'] = stamp()
            save_project(current)
        return {'project_id': pid, 'highlights': len(suggestions), 'words': len(words), 'note': current['analysis_note']}

    return start_job('analysis', work, user)


@app.post('/api/projects/{pid}/export')
def export(pid: str, opts: ExportOptions, request: Request):
    user = request.state.user
    p = load_project(pid, user)
    options = opts.model_dump()
    if opts.end > p['info']['duration'] + .2:
        raise HTTPException(400, 'End time is beyond the video duration.')
    if opts.end - opts.start < .5:
        raise HTTPException(400, 'Clip must be at least half a second.')
    if opts.captions and not p.get('transcript') and not opts.manual_captions.strip():
        raise HTTPException(400, 'No speech transcript yet. Analyze with Whisper or enter manual captions, or disable captions.')
    original = UPLOADS / p['file']
    clip_id = uuid.uuid4().hex
    destination = EXPORTS / f'{pid}_{clip_id}.mp4'

    def work(progress):
        progress(.12, 'Preparing crop, captions, and audio settings…')
        result = engine.export_video(original, destination, p['info'], options, p.get('transcript', []), progress)
        entry = {'id': clip_id, 'file': destination.name, 'created': stamp(), 'label': opts.label.strip() or f'Clip {len(p.get("exports", [])) + 1}',
                 'start': opts.start, 'end': opts.end, 'ratio': opts.ratio, 'info': result, 'options': options}
        with LOCK:
            current = load_project(pid, user)
            current.setdefault('exports', []).insert(0, entry)
            save_project(current)
        return {'project_id': pid, 'clip': entry}

    return start_job('export', work, user)


@app.post('/api/projects/{pid}/export-all')
def export_all(pid: str, opts: ExportOptions, request: Request):
    user = request.state.user
    p = load_project(pid, user)
    moments = p.get('highlights', [])
    if not moments:
        raise HTTPException(400, 'Analyze the video to create highlight suggestions first.')
    if opts.captions and not p.get('transcript') and not opts.manual_captions.strip():
        raise HTTPException(400, 'Add manual captions, run Whisper transcription, or turn captions off.')
    original = UPLOADS / p['file']
    shared = opts.model_dump()

    def work(progress):
        entries = []
        for index, moment in enumerate(moments):
            clip_id = uuid.uuid4().hex
            target = EXPORTS / f'{pid}_{clip_id}.mp4'
            options = {**shared, 'start': moment['start'], 'end': moment['end'],
                       'label': moment['title'][:90]}
            progress(index / len(moments), f'Exporting clip {index + 1} of {len(moments)}…')
            try:
                result = engine.export_video(original, target, p['info'], options, p.get('transcript', []))
                entry = {'id': clip_id, 'file': target.name, 'created': stamp(),
                         'label': options['label'], 'start': options['start'], 'end': options['end'],
                         'ratio': options['ratio'], 'info': result, 'options': options}
                with LOCK:
                    current = load_project(pid, user)
                    current.setdefault('exports', []).insert(0, entry)
                    save_project(current)
                entries.append(entry)
            except Exception:
                target.unlink(missing_ok=True)
                raise
            progress((index + 1) / len(moments), f'Finished clip {index + 1} of {len(moments)}')
        return {'project_id': pid, 'clips': entries}

    return start_job('bulk-export', work, user)


def format_srt_time(seconds: float) -> str:
    ms = max(0, round(float(seconds) * 1000))
    return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}'


@app.get('/api/projects/{pid}/subtitles.srt')
def subtitles(pid: str, request: Request):
    from fastapi.responses import PlainTextResponse
    p = load_project(pid, request.state.user)
    words = p.get('transcript', [])
    if not words:
        raise HTTPException(404, 'No transcription yet. Install faster-whisper and analyze the video.')
    blocks = []
    for i in range(0, len(words), 7):
        group = words[i:i+7]
        a, b = group[0]['start'], group[-1]['end']
        sentence = ' '.join(w['text'] for w in group)
        blocks.append(f'{len(blocks)+1}\n{format_srt_time(a)} --> {format_srt_time(b)}\n{sentence}\n')
    return PlainTextResponse('\n'.join(blocks), headers={'Content-Disposition': f'attachment; filename="konzei_{pid[:8]}.srt"'}, media_type='text/plain; charset=utf-8')


@app.get('/api/jobs/{job_id}')
def job_status(job_id: str, request: Request):
    with LOCK:
        if job_id not in JOBS:
            raise HTTPException(404, 'Job not found or app restarted')
        if JOBS[job_id]['owner_sub'] != request.state.user['google_sub']:
            raise HTTPException(404, 'Job not found')
        return {key: value for key, value in JOBS[job_id].items() if key != 'owner_sub'}


@app.get('/media/{pid}/original')
def original_media(pid: str, request: Request):
    p = load_project(pid, request.state.user)
    path = UPLOADS / p['file']
    if not path.exists():
        raise HTTPException(404, 'Video not found')
    return FileResponse(path, media_type={'.mp4': 'video/mp4', '.mov': 'video/quicktime', '.webm': 'video/webm', '.mkv': 'video/x-matroska'}.get(path.suffix.lower(), 'application/octet-stream'))


@app.get('/media/{pid}/thumbnail')
def thumb_media(pid: str, request: Request):
    load_project(pid, request.state.user)
    image = UPLOADS / f'{pid}.jpg'
    if not image.exists():
        raise HTTPException(404, 'Thumbnail not found')
    return FileResponse(image, media_type='image/jpeg')


@app.get('/media/{pid}/exports/{clip_id}')
def exported_media(pid: str, clip_id: str, request: Request, download: bool = False):
    p = load_project(pid, request.state.user)
    match = next((x for x in p.get('exports', []) if x['id'] == clip_id), None)
    if not match:
        raise HTTPException(404, 'Export not found')
    file = EXPORTS / match['file']
    if not file.exists():
        raise HTTPException(404, 'Export file is missing')
    return FileResponse(file, media_type='video/mp4', filename=f'Konzei_{clip_id[:8]}.mp4' if download else None)


@app.delete('/api/projects/{pid}')
def delete_project(pid: str, request: Request):
    p = load_project(pid, request.state.user)
    (UPLOADS / p['file']).unlink(missing_ok=True)
    (UPLOADS / f'{pid}.jpg').unlink(missing_ok=True)
    for entry in p.get('exports', []):
        (EXPORTS / entry['file']).unlink(missing_ok=True)
    (PROJECTS / f'{pid}.json').unlink(missing_ok=True)
    return {'deleted': pid}


@app.get('/api/presets')
def presets(request: Request):
    path = preset_path(request.state.user)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except ValueError:
        return []


@app.post('/api/presets')
def add_preset(preset: Preset, request: Request):
    with LOCK:
        existing = presets(request)
        entry = {'id': uuid.uuid4().hex, 'name': preset.name, 'options': preset.options.model_dump(), 'created': stamp()}
        existing.insert(0, entry)
        preset_path(request.state.user).write_text(json.dumps(existing, indent=2), encoding='utf-8')
    return entry


@app.delete('/api/presets/{preset_id}')
def delete_preset(preset_id: str, request: Request):
    with LOCK:
        original = presets(request)
        remaining = [x for x in original if x['id'] != preset_id]
        if len(original) == len(remaining):
            raise HTTPException(404, 'Recipe not found')
        preset_path(request.state.user).write_text(json.dumps(remaining, indent=2), encoding='utf-8')
    return {'deleted': preset_id}


if __name__ == '__main__':
    import uvicorn
    print('\n  KONZEI CLIPS  |  http://127.0.0.1:8765\n')
    uvicorn.run(app, host=os.getenv('KONZEI_HOST', '127.0.0.1'), port=int(os.getenv('PORT', '8765')))
