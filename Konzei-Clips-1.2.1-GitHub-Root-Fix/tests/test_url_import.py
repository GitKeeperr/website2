from app import ImportURL, build_ytdlp_options


def test_youtube_cookie_options_none():
    opts = build_ytdlp_options('0123456789abcdef0123456789abcdef')
    assert 'cookiesfrombrowser' not in opts


def test_youtube_cookie_options_chrome():
    opts = build_ytdlp_options('0123456789abcdef0123456789abcdef', 'chrome', 'Profile 1')
    assert opts['cookiesfrombrowser'] == ('chrome', 'Profile 1', None, None)


def test_reject_invalid_browser():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ImportURL(url='https://youtube.com', cookie_browser='other')


def test_browser_choices():
    for browser in ['none', 'chrome', 'edge', 'firefox', 'brave', 'vivaldi']:
        assert ImportURL(url='https://youtube.com', cookie_browser=browser).cookie_browser == browser
