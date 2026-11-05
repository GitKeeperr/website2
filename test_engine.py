"""Core unit tests. Run `python -m pytest tests` from the project folder."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import engine


def test_srt_style_time():
    assert engine.ass_time(61.23) == '0:01:01.23'


def test_word_mapping():
    words = [{'start': 10, 'end': 11, 'text': 'Hello'},
             {'start': 20, 'end': 21, 'text': 'Konzei'}]
    result = engine.map_words(words, [(9, 12), (19, 22)])
    assert result == [{'start': 1.0, 'end': 2.0, 'text': 'Hello'},
                      {'start': 4.0, 'end': 5.0, 'text': 'Konzei'}]


def test_caption_ass(tmp_path):
    f = tmp_path / 'sub.ass'
    assert engine.caption_ass(f, [], 2, 'karaoke', 'A title', '9:16', manual='Test speech here')
    value = f.read_text(encoding='utf-8-sig')
    assert 'Test' in value and 'A title' in value and 'Dialogue:' in value


def test_highlight_scoring():
    candidates = engine.identify_highlights({'duration':120}, [], [.5]*120, [8,40,80], 5, 25, '')
    assert 1 <= len(candidates) <= 5
    assert all(0 <= c['start'] < c['end'] <= 120 for c in candidates)
