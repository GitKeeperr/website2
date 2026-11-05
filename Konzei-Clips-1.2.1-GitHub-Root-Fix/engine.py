"""Local video analysis and rendering engine for Konzei Clips.
All clip processing happens through local FFmpeg; no subscription service is used.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

FFMPEG = shutil.which('ffmpeg') or 'ffmpeg'
FFPROBE = shutil.which('ffprobe') or 'ffprobe'
RATIOS = {'9:16': (720, 1280), '1:1': (1080, 1080), '4:5': (864, 1080), '16:9': (1280, 720)}
STOPWORDS = set('a an and are as at be but by for from had has have he her his i in is it its me my of on or our she so that the their them there they this to was we were what when where who why will with you your'.split())
TRIGGERS = set('amazing amazingly best biggest secret actually important incredible never always how why wait mistake truth surprising crazy reveal shocking finally learn watch discover viral'.split())


def run_cmd(cmd: list[str], timeout: int = 3600) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding='utf-8', errors='replace', stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f'Processing timed out after {timeout}s') from exc
    if proc.returncode:
        raise RuntimeError((proc.stderr or proc.stdout or 'FFmpeg failed')[-2200:])
    return proc.stderr or proc.stdout


def probe(path: Path) -> dict:
    cmd = [FFPROBE, '-v', 'error', '-show_entries', 'format=duration,size:stream=codec_type,width,height', '-of', 'json', str(path)]
    data = json.loads(run_cmd(cmd, timeout=45))
    video = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'), None)
    if video is None:
        raise ValueError('No video stream found in this file.')
    return {'duration': round(float(data.get('format', {}).get('duration') or 0), 2), 'width': video.get('width', 0),
            'height': video.get('height', 0), 'size': int(data.get('format', {}).get('size') or path.stat().st_size),
            'has_audio': any(s.get('codec_type') == 'audio' for s in data.get('streams', []))}


def thumbnail(video: Path, destination: Path) -> None:
    info = probe(video)
    run_cmd([FFMPEG, '-hide_banner', '-loglevel', 'error', '-y', '-ss', str(min(1.0, max(0, info['duration'] / 4))),
             '-i', str(video), '-frames:v', '1', '-vf', 'scale=560:-2', str(destination)], timeout=90)


def audio_activity(path: Path, duration: float) -> list[float]:
    """Energy per second in the first hour; normalized to [0,1]."""
    try:
        import numpy as np
        max_duration = min(duration, 3600)
        proc = subprocess.run([FFMPEG, '-hide_banner', '-loglevel', 'error', '-nostdin', '-i', str(path),
                               '-t', str(max_duration), '-vn', '-ac', '1', '-ar', '2000', '-f', 's16le', 'pipe:1'],
                              capture_output=True, timeout=250)
        if proc.returncode:
            return []
        arr = np.frombuffer(proc.stdout, dtype='<i2').astype(np.float32)
        levels = []
        for s in range(math.ceil(len(arr) / 2000)):
            section = arr[s * 2000: (s + 1) * 2000]
            levels.append(float(np.sqrt(np.mean(section**2))) if len(section) else 0.0)
        p90 = float(np.percentile(levels, 90)) if levels else 1
        return [min(1.0, x / max(1, p90)) for x in levels]
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def scene_changes(path: Path, duration: float) -> list[float]:
    """Find meaningful visual cuts using one sampled frame per second."""
    try:
        command = [FFMPEG, '-hide_banner', '-nostdin', '-i', str(path), '-vf',
                   "fps=1,scale=320:-2,select='gt(scene,0.22)',showinfo", '-an', '-f', 'null', '-']
        output = subprocess.run(command, capture_output=True, text=True, timeout=240, errors='replace')
        moments = [float(t) for t in re.findall(r'pts_time:([\d.]+)', output.stderr)]
        return [v for v in moments if 0 < v < duration]
    except (OSError, subprocess.SubprocessError):
        return []


def transcribe(path: Path) -> tuple[list[dict], str | None]:
    """Optional local Whisper. Initial run downloads the selected model once."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return [], 'Install the optional faster-whisper package to enable automatic captions and speech-aware selection.'
    model_name = os.getenv('KONZEI_WHISPER_MODEL', 'base')
    model = WhisperModel(model_name, device='cpu', compute_type='int8', cpu_threads=min(8, os.cpu_count() or 4))
    segments, info = model.transcribe(str(path), beam_size=3, vad_filter=True, word_timestamps=True)
    words: list[dict] = []
    for seg in segments:
        if seg.words:
            for word in seg.words:
                words.append({'start': round(max(0, word.start), 2), 'end': round(word.end, 2), 'text': word.word.strip()})
        elif seg.text.strip():
            words.append({'start': round(seg.start, 2), 'end': round(seg.end, 2), 'text': seg.text.strip()})
    return words, None


def identify_highlights(info: dict, words: list[dict], energy: list[float], cuts: list[float],
                        count: int, clip_duration: float, prompt: str = '') -> list[dict]:
    duration = float(info['duration'])
    if duration <= 0:
        return []
    length = max(3, min(900, clip_duration, duration))
    count = max(1, min(20, count))
    prompt_terms = [v.lower() for v in re.findall(r'\w+', prompt) if len(v) >= 3 and v.lower() not in STOPWORDS]
    step = max(2.0, min(12.0, length / 3))
    starts = [i * step for i in range(max(1, math.ceil(max(0, duration - length) / step) + 1))]
    starts += [max(0, duration - length)]
    candidates = []
    for start in starts:
        end = min(duration, start + length)
        selected = [w for w in words if w['end'] > start and w['start'] < end]
        speech = ' '.join(w['text'] for w in selected)
        term_list = re.findall(r'\w+', speech.lower())
        activity = energy[int(start):int(math.ceil(end))] if energy else []
        avg_energy = (sum(activity) / len(activity)) if activity else 0.38
        dynamic = (max(activity) - min(activity)) if activity else 0.15
        scene_density = sum(1 for v in cuts if start <= v < end) / max(1, length / 15)
        speech_density = min(1, len(selected) / max(1, length * 1.8)) if words else 0.35
        match = min(1, sum(term_list.count(term) for term in prompt_terms) / max(1, len(prompt_terms))) if prompt_terms else 0
        trigger = sum(1 for t in term_list if t in TRIGGERS) / max(1, len(term_list))
        raw = 20 + 26 * avg_energy + 13 * dynamic + 12 * min(1, scene_density) + 13 * speech_density + 12 * match + 8 * min(1, trigger * 15)
        score = int(min(99, max(10, round(raw))))
        cleaned = re.sub(r'\s+', ' ', speech).strip()
        title = ' '.join(cleaned.split()[:9]) + ('…' if len(cleaned.split()) > 9 else '') if cleaned else f'Highlight at {int(start // 60):02d}:{int(start % 60):02d}'
        candidates.append({'start': round(start, 2), 'end': round(end, 2), 'title': title,
                           'score': score, 'reason': 'Topic match + activity' if match else 'Speech and visual activity' if words else 'Audio and scene activity'})
    candidates.sort(key=lambda c: c['score'], reverse=True)
    picked = []
    for cand in candidates:
        if any(max(0, min(cand['end'], old['end']) - max(cand['start'], old['start'])) > length * .35 for old in picked):
            continue
        picked.append(cand)
        if len(picked) >= count:
            break
    return sorted(picked, key=lambda c: c['start'])


def detect_silence(path: Path, start: float, end: float, noise: str = '-35dB', min_silence: float = 0.55) -> list[tuple[float, float]]:
    """Return non-silent intervals in seconds relative to the requested selection."""
    duration = end - start
    if duration < 1:
        return [(0, duration)]
    cmd = [FFMPEG, '-hide_banner', '-nostdin', '-ss', str(start), '-t', str(duration), '-i', str(path), '-vn',
           '-af', f'silencedetect=noise={noise}:d={min_silence}', '-f', 'null', '-']
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, errors='replace')
        begins = [float(x) for x in re.findall(r'silence_start: ([-\d.]+)', result.stderr)]
        ends = [float(x) for x in re.findall(r'silence_end: ([-\d.]+)', result.stderr)]
        silences = []
        for idx, begin in enumerate(begins):
            following = next((finish for finish in ends if finish > begin), duration)
            silences.append((max(0, begin + .12), min(duration, following - .12)))
        keeps = []
        pos = 0.0
        for begin, finish in silences:
            if begin > pos + .18:
                keeps.append((pos, begin))
            pos = max(pos, finish)
        if pos < duration - .18:
            keeps.append((pos, duration))
        return keeps or [(0, duration)]
    except (OSError, subprocess.SubprocessError):
        return [(0, duration)]


def cut_silences(source: Path, destination: Path, start: float, end: float, has_audio: bool) -> list[tuple[float, float]]:
    intervals = detect_silence(source, start, end) if has_audio else [(0, end - start)]
    if len(intervals) < 2:
        return [(start, end)]
    clips = []
    parts = []
    for idx, (a, b) in enumerate(intervals):
        if b <= a + .10:
            continue
        parts += [f'[0:v]trim=start={start + a}:end={start + b},setpts=PTS-STARTPTS[v{idx}]',
                  f'[0:a]atrim=start={start + a}:end={start + b},asetpts=PTS-STARTPTS[a{idx}]']
        clips.append(idx)
    if len(clips) < 2:
        return [(start, end)]
    inputs = ''.join(f'[v{i}][a{i}]' for i in clips)
    parts.append(f'{inputs}concat=n={len(clips)}:v=1:a=1[vout][aout]')
    run_cmd([FFMPEG, '-hide_banner', '-loglevel', 'error', '-y', '-i', str(source), '-filter_complex', ';'.join(parts),
             '-map', '[vout]', '-map', '[aout]', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p',
             '-c:a', 'aac', '-b:a', '160k', str(destination)], timeout=3600)
    return [(start + a, start + b) for a, b in intervals]


def map_words(words: list[dict], ranges: list[tuple[float, float]]) -> list[dict]:
    mapped = []
    offset = 0
    for a, b in ranges:
        for word in words:
            if word['end'] <= a or word['start'] >= b:
                continue
            mapped.append({'start': round(offset + max(a, word['start']) - a, 3),
                           'end': round(offset + min(b, word['end']) - a, 3), 'text': word['text']})
        offset += b - a
    return mapped


def ass_time(seconds: float) -> str:
    centis = max(0, round(seconds * 100))
    return f'{centis // 360000}:{centis // 6000 % 60:02d}:{centis // 100 % 60:02d}.{centis % 100:02d}'


def ass_escape(value: str) -> str:
    return value.replace('\\', '／').replace('{', '(').replace('}', ')').replace('\n', r'\N')


def caption_ass(path: Path, words: list[dict], duration: float, style: str, title: str, ratio: str,
                manual: str = '', censor: bool = False) -> bool:
    if not words and manual.strip():
        toks = manual.strip().split()
        per_word = duration / max(1, len(toks))
        words = [{'start': i * per_word, 'end': (i + 1) * per_word, 'text': w} for i, w in enumerate(toks)]
    if not words and not title:
        return False
    sizes = {'classic': 76, 'bold': 92, 'karaoke': 85, 'neon': 84, 'minimal': 60}
    size = sizes.get(style, 78)
    primary = '&H00FFFFFF'
    outline = '&H00000000'
    if style == 'neon':
        primary = '&H0000F5FF'
    if style == 'minimal':
        outline = '&H90000000'
    margin = 195 if ratio == '9:16' else 115
    header = f'''[Script Info]
Title: Konzei Clips Captions
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Arial,{size},{primary},&H0000CCFF,{outline},&H99000000,{'-1' if style in ('bold','karaoke') else '0'},0,0,0,100,100,0,0,1,5,2,2,65,65,{margin},1
Style: Title,Arial,71,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,8,80,80,135,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    # Break into short, readable groups with word-aware timings.
    rows = []
    group = []
    for index, word in enumerate(words):
        t = word.get('text', '').strip()
        if not t:
            continue
        if censor and re.sub(r'\W', '', t.lower()) in {'fuck','fucking','shit','bitch','asshole','damn'}:
            t = t[:1] + '*' * max(1, len(t) - 1)
        group.append((word, t))
        if len(group) >= (4 if style in ('karaoke', 'bold') else 6) or t.endswith(('.', '?', '!')) or index == len(words) - 1:
            a = max(0, group[0][0]['start'])
            b = min(duration, max(group[-1][0]['end'], a + .18))
            if b > a:
                if style == 'karaoke':
                    pieces = []
                    for w, token in group:
                        cs = max(1, int(max(.08, w['end'] - w['start']) * 100))
                        pieces.append(r'{\kf' + str(cs) + '}' + ass_escape(token))
                    msg = ' '.join(pieces)
                else:
                    msg = ass_escape(' '.join(v for _, v in group))
                rows.append(f'Dialogue: 0,{ass_time(a)},{ass_time(b)},Caption,,0,0,0,,{msg}')
            group = []
    if title.strip():
        rows.append(f'Dialogue: 1,{ass_time(0)},{ass_time(min(3.5,duration))},Title,,0,0,0,,{ass_escape(title[:110])}')
    path.write_text(header + '\n'.join(rows) + '\n', encoding='utf-8-sig')
    return bool(rows)


def calculate_focus(video: Path, start: float, end: float) -> float | None:
    """Detect dominant faces over a few sampled frames. Missing faces => normal center crop."""
    try:
        import cv2
        cap = cv2.VideoCapture(str(video))
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        positions = []
        for k in range(9):
            position = start + (end - start) * (k + 1) / 10
            cap.set(cv2.CAP_PROP_POS_MSEC, position * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.18, minNeighbors=4, minSize=(36, 36))
            if len(faces):
                x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                positions.append((x + w / 2) / frame.shape[1])
        cap.release()
        if positions:
            return sorted(positions)[len(positions)//2]
    except (ImportError, OSError):
        return None
    return None


def filter_escape_path(path: Path) -> str:
    """Escaping for an FFmpeg filter option, not shell escaping."""
    p = path.resolve().as_posix()
    return p.replace('\\', '\\\\').replace(':', '\\:').replace("'", "\\'").replace('[', '\\[').replace(']', '\\]')


def export_video(source: Path, output: Path, info: dict, options: dict, words: list[dict], progress=None) -> dict:
    start = max(0, float(options.get('start', 0)))
    end = min(float(info['duration']), float(options.get('end') or info['duration']))
    if end - start < .5:
        raise ValueError('Clip must be at least 0.5 seconds long.')
    if end - start > 900:
        raise ValueError('This editor supports clips up to 15 minutes each.')
    ratio = options.get('ratio', '9:16')
    if ratio not in RATIOS:
        raise ValueError('Unsupported aspect ratio.')
    width, height = RATIOS[ratio]
    focus_x = float(options.get('focus_x', 0.5))
    focus_y = float(options.get('focus_y', 0.5))
    focus_x, focus_y = max(0, min(1, focus_x)), max(0, min(1, focus_y))
    if options.get('smart_crop') and options.get('crop_mode', 'crop') == 'crop':
        focus = calculate_focus(source, start, end)
        if focus is not None:
            focus_x = focus
    with tempfile.TemporaryDirectory(prefix='konzei_') as temp:
        folder = Path(temp)
        rendered_from = source
        input_start = start
        length = end - start
        ranges = [(start, end)]
        if options.get('remove_silence') and info['has_audio']:
            intermediate = folder / 'tight.mp4'
            ranges = cut_silences(source, intermediate, start, end, True)
            if intermediate.exists():
                rendered_from = intermediate
                input_start = 0
                length = probe(intermediate)['duration']
        mapped = map_words(words, ranges)
        caption_text = str(options.get('manual_captions', '') or '').strip()
        caption_file = folder / 'captions.ass'
        use_subs = bool(options.get('captions', True) or options.get('overlay_title'))
        ass_written = caption_ass(caption_file, mapped if options.get('captions', True) else [], length,
                                  options.get('caption_style', 'bold'), options.get('overlay_title', ''),
                                  ratio, manual=caption_text if options.get('captions', True) else '',
                                  censor=bool(options.get('censor_captions', False))) if use_subs else False
        mode = options.get('crop_mode', 'crop')
        if mode == 'blur':
            vf = (f'split=2[bg][fg];[bg]scale={width}:{height}:force_original_aspect_ratio=increase,'
                  f'crop={width}:{height},boxblur=20:2[back];'
                  f'[fg]scale={width}:{height}:force_original_aspect_ratio=decrease[front];'
                  f'[back][front]overlay=(W-w)/2:(H-h)/2')
            # Complex filtergraph; append labels only if necessary.
            if ass_written:
                vf += f",ass='{filter_escape_path(caption_file)}'"
            filter_flag = '-filter_complex'
        elif mode == 'fit':
            vf = (f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
                  f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black')
            if ass_written:
                vf += f",ass='{filter_escape_path(caption_file)}'"
            filter_flag = '-vf'
        else:
            vf = (f'scale={width}:{height}:force_original_aspect_ratio=increase,'
                  f'crop={width}:{height}:(in_w-out_w)*{focus_x:.4f}:(in_h-out_h)*{focus_y:.4f}')
            if ass_written:
                vf += f",ass='{filter_escape_path(caption_file)}'"
            filter_flag = '-vf'
        if options.get('fade'):
            out_start = max(0, length - .24)
            vf += f',fade=t=in:st=0:d=0.2,fade=t=out:st={out_start:.2f}:d=0.2'
        command = [FFMPEG, '-hide_banner', '-loglevel', 'error', '-y', '-ss', str(input_start), '-t', str(length), '-i', str(rendered_from)]
        command += [filter_flag, vf]
        command += ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', str(int(options.get('crf', 23))), '-pix_fmt', 'yuv420p']
        if info['has_audio']:
            filters = []
            if options.get('enhance_audio'):
                filters += ['afftdn=nf=-25', 'acompressor=threshold=0.12:ratio=2.3', 'loudnorm=I=-16:TP=-1.5:LRA=11']
            if options.get('fade'):
                filters += ['afade=t=in:st=0:d=0.2', f'afade=t=out:st={max(0,length-.25):.2f}:d=0.2']
            if filters:
                command += ['-af', ','.join(filters)]
            command += ['-c:a', 'aac', '-b:a', '160k']
        else:
            command += ['-an']
        command += ['-movflags', '+faststart', str(output)]
        if progress:
            progress(0.40, 'Rendering video locally…')
        run_cmd(command, timeout=7200)
        if progress:
            progress(0.98, 'Finishing export…')
    result = probe(output)
    return result
