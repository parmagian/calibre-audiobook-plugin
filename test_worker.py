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


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
