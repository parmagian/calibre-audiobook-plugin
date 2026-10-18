import sys
import os
import asyncio
import json
import shutil
import subprocess
import tempfile
import traceback
import re
import unicodedata

EDGE_CHUNK_SIZE = 2500
KOKORO_CHUNK_SIZE = 400
RETRY_DELAYS = (1, 3, 9)
KOKORO_MODEL_DIR = os.path.expanduser('~/Library/Application Support/calibre-audiobook/kokoro')
TOOL_DIRS = ('~/.local/bin', '~/.cargo/bin', '/opt/homebrew/bin', '/usr/local/bin', '/usr/bin')


def main(epub_path, output_path, voice, engine, lang_code, vendor_path, book_id, output_format,
         meta, notifications, abort, log):
    """
    Worker function for audiobook generation.
    Returns (success, (book_id, output_format, output_path_or_error, warning)).
    """
    if vendor_path not in sys.path:
        sys.path.insert(0, vendor_path)

    workdir = tempfile.mkdtemp(prefix='audiobook_')
    try:
        log(f"Starting conversion for book ID: {book_id} ({engine}, {voice}, {output_format})")

        # 1. Extract text, one entry per chapter
        notifications.put((0.02, "Extracting text..."))
        chapters = extract_chapters(epub_path, lang_code, meta)
        if not chapters:
            return False, (book_id, output_format, "Could not extract text.", None)
        log(f"Chapters: {len(chapters)}, characters: {sum(len(t) for _, t in chapters)}")

        ffmpeg = find_tool('ffmpeg')
        if not ffmpeg and (engine == 'Kokoro' or output_format == 'M4B'):
            return False, (book_id, output_format,
                           "ffmpeg not found. Install it with: brew install ffmpeg", None)

        # 2. Generate one audio file per chapter
        if engine == 'Kokoro':
            parts, failed, first_error = run_kokoro(chapters, voice, lang_code, meta['helper_src'],
                                                    workdir, notifications, abort, log)
        else:
            parts, failed, first_error = run_online_tts(chapters, voice, engine, lang_code,
                                                        ffmpeg, workdir, notifications, abort, log)

        if abort.is_set():
            return False, (book_id, output_format, "Aborted.", None)
        if not parts:
            return False, (book_id, output_format, f"Audio generation failed: {first_error}", None)

        # 3. Join chapters into the final file
        notifications.put((0.95, "Assembling audio file..."))
        if os.path.exists(output_path):
            os.remove(output_path)
        if ffmpeg:
            assemble(ffmpeg, parts, output_path, output_format, meta, workdir)
        else:
            # No ffmpeg: plain MP3 byte concatenation, no chapters or cover
            with open(output_path, 'wb') as out:
                for part, _ in parts:
                    with open(part, 'rb') as f:
                        shutil.copyfileobj(f, out)

        warning = None
        if failed:
            warning = f"{failed} parts are missing ({first_error}). Run again to fill them."
            log(f"WARNING: {warning}")
        log("SUCCESS: Generation finished.")
        return True, (book_id, output_format, output_path, warning)

    except Exception as e:
        log(f"CRITICAL ERROR: {traceback.format_exc()}")
        return False, (book_id, output_format, str(e) or type(e).__name__, None)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def run_kokoro(chapters, voice, lang_code, helper_src, workdir, notifications, abort, log):
    """Runs kokoro_helper.py through uv. Returns ([(wav, title)], failed_count, error)."""
    uv = find_tool('uv')
    if not uv:
        return [], 0, "uv not found. Install it with: brew install uv"

    job = {'voice': voice, 'lang': lang_code, 'speed': 1.0, 'model_dir': KOKORO_MODEL_DIR,
           'chapters': [{'paragraphs': [split_into_chunks(p, KOKORO_CHUNK_SIZE) for p in text.split('\n\n')]}
                        for _, text in chapters]}
    job_path = os.path.join(workdir, 'job.json')
    helper_path = os.path.join(workdir, 'kokoro_helper.py')
    with open(job_path, 'w', encoding='utf-8') as f:
        json.dump(job, f)
    with open(helper_path, 'wb') as f:
        f.write(helper_src)

    # Calibre's own Python settings must not leak into uv's Python
    env = {k: v for k, v in os.environ.items() if not k.startswith('PYTHON')}
    stderr_path = os.path.join(workdir, 'stderr.txt')
    notifications.put((0.03, "Starting Kokoro (first run downloads ~350 MB)..."))
    with open(stderr_path, 'w') as stderr:
        proc = subprocess.Popen([uv, 'run', '--quiet', '--script', helper_path, job_path, workdir],
                                stdout=subprocess.PIPE, stderr=stderr, text=True, env=env, cwd=workdir)
        for line in proc.stdout:
            if abort.is_set():
                proc.terminate()
                break
            if line.startswith('PROGRESS'):
                done, total = map(int, line.split()[1:3])
                notifications.put((0.05 + 0.9 * done / total, f"Spoke {done} of {total} parts..."))
            elif line.startswith('STATUS'):
                notifications.put((0.04, line[7:].strip()))
        proc.wait()

    if proc.returncode != 0 and not abort.is_set():
        with open(stderr_path) as f:
            err = f.read().strip().splitlines()
        log("Kokoro helper error:\n" + "\n".join(err[-30:]))
        return [], 0, err[-1] if err else f"Kokoro exited with code {proc.returncode}"

    parts = [(os.path.join(workdir, f'chapter_{i:03d}.wav'), title) for i, (title, _) in enumerate(chapters)]
    return [p for p in parts if os.path.exists(p[0])], 0, None


def run_online_tts(chapters, voice, engine, lang_code, ffmpeg, workdir, notifications, abort, log):
    """Edge TTS / gTTS with retries. Returns ([(mp3, title)], failed_count, first_error)."""
    jobs = [(ci, chunk) for ci, (_, text) in enumerate(chapters)
            for chunk in split_into_chunks(text, EDGE_CHUNK_SIZE)]
    total = len(jobs)
    log(f"Total chunks: {total}")
    results = [None] * total
    errors = []
    completed = [0]

    async def synthesize(chunk_text):
        if engine == 'Edge TTS':
            import edge_tts
            data = b""
            async for message in edge_tts.Communicate(chunk_text, voice).stream():
                if message["type"] == "audio":
                    data += message["data"]
            return data

        from gtts import gTTS
        def run_gtts():
            fd, path = tempfile.mkstemp(suffix='.mp3')
            os.close(fd)
            try:
                gTTS(text=chunk_text, lang=lang_code).save(path)
                with open(path, "rb") as rf:
                    return rf.read()
            finally:
                os.unlink(path)
        data = await asyncio.get_event_loop().run_in_executor(None, run_gtts)
        await asyncio.sleep(0.5)  # Rate limit safety
        return data

    async def fetch_chunk(index, chunk_text, semaphore):
        async with semaphore:
            for attempt, delay in enumerate(RETRY_DELAYS + (None,)):
                if abort.is_set():
                    return
                try:
                    data = await synthesize(chunk_text)
                    if not data:
                        raise RuntimeError("no audio received")
                    results[index] = data
                    completed[0] += 1
                    notifications.put((0.05 + 0.9 * completed[0] / total,
                                       f"Downloaded {completed[0]} of {total} segments..."))
                    return
                except Exception as e:
                    msg = str(e) or type(e).__name__
                    if delay is None:
                        log(f"Error in chunk {index} (gave up): {msg}")
                        errors.append(msg)
                        return
                    log(f"Error in chunk {index} (attempt {attempt + 1}, retrying): {msg}")
                    await asyncio.sleep(delay)

    async def run_all():
        # Limit concurrency to avoid getting blocked
        semaphore = asyncio.Semaphore(3)
        await asyncio.gather(*[fetch_chunk(i, chunk, semaphore) for i, (_, chunk) in enumerate(jobs)])

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run_all())
    finally:
        loop.close()

    silence = make_silence_mp3(ffmpeg, workdir) if ffmpeg else b""
    parts = []
    for ci, (title, _) in enumerate(chapters):
        data = b"".join(results[i] for i, (c, _) in enumerate(jobs) if c == ci and results[i])
        if data:
            path = os.path.join(workdir, f'chapter_{ci:03d}.mp3')
            with open(path, 'wb') as f:
                f.write(data + silence)
            parts.append((path, title))
    return parts, len(errors), errors[0] if errors else None


def make_silence_mp3(ffmpeg, workdir, seconds=1.5):
    """Silence matching Edge's 24 kHz mono MP3 so chapters don't run together."""
    path = os.path.join(workdir, 'silence.mp3')
    subprocess.run([ffmpeg, '-y', '-loglevel', 'error', '-f', 'lavfi', '-i', 'anullsrc=r=24000:cl=mono',
                    '-t', str(seconds), '-c:a', 'libmp3lame', '-b:a', '48k', path], check=True)
    with open(path, 'rb') as f:
        return f.read()


def assemble(ffmpeg, parts, output_path, output_format, meta, workdir):
    """Joins [(chapter_file, title)] into one M4B/MP3 with chapter markers, cover and tags."""
    ffprobe = os.path.join(os.path.dirname(ffmpeg), 'ffprobe')
    list_path = os.path.join(workdir, 'parts.txt')
    meta_path = os.path.join(workdir, 'meta.txt')

    with open(list_path, 'w', encoding='utf-8') as f:
        for part, _ in parts:
            f.write("file '{}'\n".format(part.replace("'", "'\\''")))

    def esc(s):
        return re.sub(r'([=;#\\\n])', r'\\\1', s)

    lines = [';FFMETADATA1', f"title={esc(meta.get('title', ''))}", f"artist={esc(meta.get('author', ''))}",
             f"album={esc(meta.get('title', ''))}", 'genre=Audiobook']
    start = 0
    for part, title in parts:
        out = subprocess.run([ffprobe, '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', part],
                             capture_output=True, text=True, check=True)
        end = start + int(float(out.stdout.strip()) * 1000)
        lines += ['[CHAPTER]', 'TIMEBASE=1/1000', f'START={start}', f'END={end}', f'title={esc(title)}']
        start = end
    with open(meta_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')

    cover = meta.get('cover')
    cover = cover if cover and os.path.exists(cover) else None
    cmd = [ffmpeg, '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', list_path, '-i', meta_path]
    if cover:
        cmd += ['-i', cover]
    cmd += ['-map', '0:a', '-map_metadata', '1', '-map_chapters', '1']
    if cover:
        cmd += ['-map', '2:v', '-c:v', 'copy', '-disposition:v:0', 'attached_pic']
    if output_format == 'M4B':
        cmd += ['-c:a', 'aac', '-b:a', '64k', '-ac', '1', '-movflags', '+faststart', '-f', 'mp4']
    else:
        cmd += ['-c:a', 'libmp3lame', '-b:a', '64k', '-ac', '1', '-id3v2_version', '3', '-f', 'mp3']
    proc = subprocess.run(cmd + [output_path], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.strip()[-500:]}")


def find_tool(name):
    """Calibre on macOS starts with a bare PATH, so also look in the usual install spots."""
    found = shutil.which(name)
    if found:
        return found
    for d in TOOL_DIRS:
        path = os.path.join(os.path.expanduser(d), name)
        if os.access(path, os.X_OK):
            return path
    return None


def unique_path(folder, base, ext):
    """Title - Author.m4b, then Title - Author (2).m4b, ... so nothing gets overwritten."""
    path = os.path.join(folder, f"{base}.{ext}")
    n = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{base} ({n}).{ext}")
        n += 1
    return path


def split_into_chunks(text, limit):
    """Packs whole sentences into chunks of at most `limit` chars, never cutting mid-word."""
    chunks, current = [], ""
    for para in text.split('\n\n'):
        # A sentence ends at . ! ? plus any closing quote/bracket, followed by space or end
        for sentence in re.findall(r'.+?(?:[.!?]+["\')\]]*(?=\s|$)|$)', para.strip()):
            for piece in _split_long(sentence.strip(), limit):
                if current and len(current) + 1 + len(piece) > limit:
                    chunks.append(current.strip())
                    current = ""
                current = f"{current} {piece}" if current else piece
        if current:
            current += "\n\n"
    if current.strip():
        chunks.append(current.strip())
    return [c for c in chunks if c]


def _split_long(sentence, limit):
    """Splits a sentence longer than `limit` at commas/semicolons, then at spaces."""
    if len(sentence) <= limit:
        return [sentence]
    pieces, current = [], ""
    for word in re.split(r'(?<=[,;:])\s+|\s+', sentence):
        if current and len(current) + 1 + len(word) > limit:
            pieces.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        pieces.append(current)
    return pieces


ABBREVIATIONS = {'Mr.': 'Mister', 'Mrs.': 'Missus', 'Ms.': 'Miz', 'Dr.': 'Doctor', 'Prof.': 'Professor'}


def clean_text_for_tts(text, lang_code='en'):
    text = unicodedata.normalize('NFKC', text)
    replacements = {'\xad': '', '​': '', '﻿': '', '“': '"', '”': '"', '‘': "'", '’': "'", '…': '...', '—': ' - '}
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = "".join(c for c in text if unicodedata.category(c)[0] != 'C' or c in '\n\t')
    text = re.sub(r'<[^>]+>', '', text)
    if lang_code and lang_code.startswith('en'):
        # "Mr." would otherwise read as the end of a sentence
        for abbr, full in ABBREVIATIONS.items():
            text = re.sub(r'\b' + re.escape(abbr), full, text)
    text = re.sub(r'^\s*\d{1,4}\s*$', '', text, flags=re.M)  # stray page numbers
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n', '\n\n', text)
    return text.strip()


def extract_chapters(epub_path, lang_code='en', book=None):
    """Returns [(title, text)] for the parts of the book worth reading aloud."""
    return select_chapters(extract_sections(epub_path, lang_code), book)


def extract_sections(epub_path, lang_code='en'):
    """Returns one dict per spine item: title, text, types (epub:type/landmarks), link_ratio."""
    from calibre.ebooks.oeb.polish.container import get_container
    from calibre.ebooks.oeb.polish.cover import find_cover_page
    from calibre.ebooks.oeb.polish.toc import get_toc, get_landmarks
    from bs4 import BeautifulSoup

    container = get_container(epub_path)
    cover_page = None
    try: cover_page = find_cover_page(container)
    except: pass

    toc_titles = {}  # file -> every TOC title pointing into it
    try:
        for node in get_toc(container).iterdescendants():
            if node.dest and node.title:
                toc_titles.setdefault(node.dest, []).append(node.title.strip())
    except: pass

    landmark_types = {}
    try:
        for lm in get_landmarks(container):
            if lm['type'] != 'text':  # "start reading" landmarks are too often wrong
                landmark_types.setdefault(lm['dest'], set()).add(lm['type'])
    except: pass

    PARA = ''  # paragraph marker; must not count as whitespace for \s
    sections = []
    spine_names = [x[0] if isinstance(x, (list, tuple)) else x for x in container.spine_names]
    for name in spine_names:
        if cover_page and name == cover_page: continue
        if container.mime_map.get(name) not in {'text/html', 'application/xhtml+xml'}: continue
        try:
            soup = BeautifulSoup(container.raw_data(name), 'html.parser')
        except: continue
        types = set(landmark_types.get(name, ()))
        for tag in soup.find_all(['body', 'section', 'div', 'nav'], limit=4):
            types.update(tag.get('epub:type', '').split())
        # Table-of-contents pages are mostly real links (anchors without href don't count)
        all_text = soup.get_text(' ', strip=True)
        links = soup.find_all('a', href=True)
        link_text = ' '.join(a.get_text(' ', strip=True) for a in links)
        link_ratio = len(link_text) / len(all_text) if all_text and len(links) >= 5 else 0
        for tag in soup(["script", "style", "img", "image", "svg", "video", "audio", "iframe", "meta", "link"]):
            tag.decompose()
        # Footnote markers and page-break anchors shouldn't be read aloud
        for tag in soup.find_all(attrs={'epub:type': re.compile(r'noteref|pagebreak')}):
            tag.decompose()
        for tag in soup.find_all('sup'):
            if re.fullmatch(r'[\d*†‡,\[\]\s]*', tag.get_text()):
                tag.decompose()
        heading = soup.find(['h1', 'h2', 'h3'])
        heading_text = heading.get_text(' ', strip=True) if heading else ""
        for tag in soup.find_all(['p', 'div', 'li', 'blockquote', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'tr']):
            tag.append(PARA)
        body = soup.body or soup
        text = re.sub(r'\s+', ' ', body.get_text())
        text = re.sub(r'\s*' + PARA + r'[\s' + PARA + r']*', '\n\n', text)
        text = clean_text_for_tts(text, lang_code)
        if not text:
            continue
        first_line = text.split('\n\n', 1)[0]
        toc = toc_titles.get(name, [])
        title = ((toc and toc[0]) or heading_text or (first_line if len(first_line) <= 80 else '')
                 or f"Section {len(sections) + 1}")
        sections.append({'title': title, 'text': text, 'types': types, 'link_ratio': link_ratio, 'toc': toc})
    return sections


# Front/back matter nobody wants read aloud. Intros, prefaces, forewords and prologues are kept.
KEEP_TITLE = re.compile(r'\b(introduction|intro|preface|foreword|prologue|prelude)\b', re.I)
# The whole title must be one of these ("Index", "Notes 3") so "Index Funds" or "The Marauder's Map" survive
SKIP_EXACT = re.compile(
    r'^\W*(?:(?:table of )?contents|(?:master |general |subject )?index(?: (?:of|to) .*)?|'
    r'(?:end)?notes(?: \d+|:.*)?|references|(?:\w+ )?glossary\b.*|bibliography|'
    r'credits|permissions|colophon|imprint|cover|maps?|epigraph|dedication|title ?page|half ?title|'
    r'praise|copyright(?: page| notice)?|acknowledge?ments?|preview|excerpt|frontispiece|title|jacket|'
    r'description|endorsements|blurbs?|dramatis person\w+|(?:cast of )?characters|timeline\b.*|chronology|'
    r'(?:a )?note on the (?:text|translation|type)|penguin (?:books|classics)|half[- ]?title(?: page)?|'
    r'other titles|the world of .*|author bio\w*)(?:\s+[\divxlc]+)?\W*$', re.I)
# These can appear anywhere in the title
SKIP_PHRASE = re.compile(
    r'\b(about the (authors?|publisher|illustrator|translator|e-?book|type)|also by|other (books|titles) by|'
    r'books by|by the same author|praise for|reading group|discussion questions|book club|sneak peek|'
    r'excerpt from|preview of|newsletters?|sign up|discover more|more from|coming soon|sample chapter|'
    r'buy the book|read more|bonus (content|material)|thank you for (purchasing|buying|downloading)|'
    r'download more|from the pages of|review team)\b', re.I)
SKIP_TYPES = {'cover', 'title-page', 'titlepage', 'halftitlepage', 'copyright-page', 'colophon',
              'imprint', 'dedication', 'epigraph', 'acknowledgments', 'acknowledgements', 'contributors',
              'other-credits', 'index', 'bibliography', 'loi', 'lot', 'endnotes', 'rearnotes', 'footnotes',
              'note', 'seriespage', 'adcard', 'landmarks', 'page-list', 'glossary', 'errata', 'teaser'}
MIN_BODY_CHARS = 3000  # an unlisted section this long starts the book
MIN_LISTED_CHARS = 500  # a section in the table of contents this long starts the book
MAX_PHRASE_SKIP_CHARS = 30000  # a huge section titled "Praise for..." is a mislabeled book, not a blurb


def is_skip_title(title, text_len, book):
    if KEEP_TITLE.search(title):
        return False
    t = title.strip().lower()
    if book.get('author') and t == book['author'].strip().lower():
        return True  # "Jane Austen": an author bio page
    if book.get('title') and t == book['title'].strip().lower() and text_len < MIN_BODY_CHARS:
        return True  # title page
    return bool(SKIP_EXACT.match(title) or (SKIP_PHRASE.search(title) and text_len < MAX_PHRASE_SKIP_CHARS))


def is_skippable(section, book):
    if KEEP_TITLE.search(section['title']):
        return False
    if section['types'] & SKIP_TYPES or section['link_ratio'] > 0.5:
        return True
    # A file holding several chapters is only skipped if every chapter in it is skippable
    titles = section['toc'] if len(section['toc']) > 1 else [section['title']]
    return all(is_skip_title(t, len(section['text']), book) for t in titles)


def select_chapters(sections, book=None):
    """Drops front/back matter. The book starts at the first section that is listed in the
    table of contents and not tiny, or is long, or is an intro/preface; title pages, blurbs
    and dedications before that go. `book` is {'title', 'author'}."""
    book = book or {}
    started = False
    chapters = []
    for s in sections:
        if is_skippable(s, book):
            continue
        if not started:
            n = len(s['text'])
            if (s['toc'] and n >= MIN_LISTED_CHARS) or n >= MIN_BODY_CHARS or KEEP_TITLE.search(s['title']):
                started = True
            else:
                continue
        chapters.append((s['title'], s['text']))
    return chapters or [(s['title'], s['text']) for s in sections]
