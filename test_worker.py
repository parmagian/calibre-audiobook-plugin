"""Plain-assert checks for worker.py's pure helpers. Run: python3 test_worker.py"""
import os
import tempfile

import worker


def sec(title, n=5000, toc=True, types=(), link_ratio=0):
    return {'title': title, 'text': 'x' * n, 'types': set(types), 'link_ratio': link_ratio,
            'toc': [title] if toc else []}


def test_split_into_chunks():
    text = ('Mister Smith went home. "Are you sure?" she asked! He nodded.\n\n'
            + ' '.join(f'Sentence number {i} is here.' for i in range(200)))
    chunks = worker.split_into_chunks(text, 400)
    assert all(len(c) <= 400 for c in chunks), max(map(len, chunks))
    # Nothing lost, nothing cut mid-word
    assert ' '.join(chunks).split() == text.split()
    assert all(c.rstrip().endswith(('.', '!', '?', '"')) for c in chunks)
    # A sentence longer than the limit is split at spaces
    long = worker.split_into_chunks('word ' * 300, 100)
    assert all(len(c) <= 100 for c in long) and ' '.join(long).split() == ['word'] * 300


def test_unique_path():
    with tempfile.TemporaryDirectory() as d:
        assert worker.unique_path(d, 'Book - Author', 'm4b').endswith('Book - Author.m4b')
        open(os.path.join(d, 'Book - Author.m4b'), 'w').close()
        assert worker.unique_path(d, 'Book - Author', 'm4b').endswith('Book - Author (2).m4b')
        open(os.path.join(d, 'Book - Author (2).m4b'), 'w').close()
        assert worker.unique_path(d, 'Book - Author', 'm4b').endswith('Book - Author (3).m4b')


def test_select_chapters():
    book = {'title': 'Gathering Blue', 'author': 'Lois Lowry'}
    sections = [
        sec('Gathering Blue', 60), sec('Table of Contents', 300, link_ratio=0.9),
        sec('Copyright', 900), sec('Dedication', 50, toc=False), sec('Lois Lowry', 2000),
        sec('Preface', 2000), sec('One', 1200), sec('The Marauder’s Map'),
        sec('Chapter Four: Index Funds'), sec('Appendix A'), sec('Notes'),
        sec('Acknowledgments'), sec('About the Author', 800), sec('Sample Chapter from MESSENGER'),
    ]
    titles = [t for t, _ in worker.select_chapters(sections, book)]
    assert titles == ['Preface', 'One', 'The Marauder’s Map', 'Chapter Four: Index Funds', 'Appendix A'], titles
    # A file holding several chapters isn't skipped just because the first one is "Title Page"
    multi = dict(sec('Title Page', 100000), toc=['Title Page', 'Chapter 1', 'Chapter 2'])
    assert worker.select_chapters([multi], book)[0][0] == 'Title Page'
    # Front matter that isn't in the table of contents is skipped until real text starts
    assert [t for t, _ in worker.select_chapters([sec('Blurb page', 900, toc=False), sec('1')])] == ['1']


def test_clean_text():
    assert worker.clean_text_for_tts('Mr. Smith met Dr. Who.\n\n12\n\nNext page.') == \
        'Mister Smith met Doctor Who.\n\nNext page.'
    assert 'Mr.' in worker.clean_text_for_tts('Mr. Smith', 'es')


def test_kokoro_cloud():
    import threading
    import wave

    class Q:
        def put(self, x): pass

    calls = []
    def fake_speech(text, voice, key):
        calls.append(text)
        return b'\x01\x00' * 2400, 24000  # 0.1 s of audio per chunk
    real = worker.openrouter_speech
    worker.openrouter_speech = fake_speech
    try:
        long_para = ' '.join(f'This is sentence number {i} of a long paragraph.' for i in range(50))  # > CLOUD_CHUNK_SIZE
        chapters = [('One', f'First para. Second sentence.\n\n{long_para}'), ('Two', 'Only para.')]
        with tempfile.TemporaryDirectory() as d:
            parts, failed, err = worker.run_online_tts(chapters, 'af_heart', 'Kokoro Cloud', 'en-us', None, d,
                                                       Q(), threading.Event(), lambda m: None, 'key')
            assert failed == 0 and [t for _, t in parts] == ['One', 'Two'], (failed, err)
            assert all(len(c) <= worker.CLOUD_CHUNK_SIZE for c in calls)
            with wave.open(parts[0][0]) as w:
                seconds = w.getnframes() / w.getframerate()
            # 2 big chunks; only the last one ends a paragraph, then the chapter pause
            assert len(calls) == 3, len(calls)
            assert abs(seconds - (0.2 + worker.PARAGRAPH_PAUSE + worker.CHAPTER_PAUSE)) < 0.01, seconds

        # A bad key stops the job instead of retrying every chunk
        def bad_key(*a):
            raise worker.FatalTTSError('401')
        worker.openrouter_speech = bad_key
        with tempfile.TemporaryDirectory() as d:
            parts, _, err = worker.run_online_tts(chapters, 'af_heart', 'Kokoro Cloud', 'en-us', None, d,
                                                  Q(), threading.Event(), lambda m: None, 'key')
            assert parts == [] and err == '401'
        assert worker.run_online_tts(chapters, 'v', 'Kokoro Cloud', 'en', None, '.', Q(), threading.Event(),
                                     lambda m: None, '')[2].startswith('No OpenRouter API key')
    finally:
        worker.openrouter_speech = real


def test_estimate():
    e = worker.estimate_job(1_000_000, 'Kokoro Cloud')
    assert abs(e['cost_low'] - 4.0) < 1e-9 and abs(e['cost_high'] - 4.4) < 1e-9
    assert worker.estimate_job(1_000_000, 'Kokoro')['cost_high'] == 0
    assert '$1.92 to $2.11' in worker.describe_estimate(480_000, 'Kokoro Cloud')
    assert 'Free' in worker.describe_estimate(480_000, 'Edge TTS')
    import datetime
    at_3pm = datetime.datetime(2026, 10, 18, 15, 0)
    text = worker.describe_estimate(266_345, 'Kokoro Cloud', now=at_3pm)
    assert '27 min (done around 3:27 PM)' in text, text
    late = worker.describe_estimate(266_345, 'Kokoro', now=datetime.datetime(2026, 10, 18, 23, 30))
    assert 'tomorrow' in late, late


def test_time_left():
    # 40 of 190 done in 10 minutes -> 150 left at 4 per minute = ~38 min
    assert worker.time_left(0, 40, 190, now=600) == ' - about 38 min left'
    assert worker.time_left(0, 0, 190, now=600) == '...'
    assert worker.time_left(0, 10, 1000, now=600) == ' - about 16.5 hours left'


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
