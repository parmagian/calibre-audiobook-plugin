import sys
import os
import time

# Add vendor directory to sys.path
plugin_path = os.path.dirname(__file__)
vendor_path = os.path.join(plugin_path, 'vendor')
if vendor_path not in sys.path:
    sys.path.insert(0, vendor_path)

from calibre.gui2.actions import InterfaceAction
from calibre.gui2 import error_dialog, info_dialog, warning_dialog, Dispatcher
from calibre.gui2.threaded_jobs import ThreadedJob
from calibre_plugins.audiobook_generator.config import prefs

from qt.core import QImage, QPainter, QBuffer, QIODevice, Qt, QMenu
from calibre.utils.config import config_dir

# One row per audiobook job; opens in Numbers/Excel
STATS_PATH = os.path.join(config_dir, 'plugins', 'audiobook_generator_stats.csv')

# Gemini voices speak every language; Sulafat is described as warm, Achird as friendly
GEMINI_VOICES = {'Female': 'Sulafat', 'Male': 'Achird'}

# Kokoro has only one French voice and Brazilian Portuguese
VOICE_MAPPING = {
    'English': {'Male': 'en-US-AndrewMultilingualNeural', 'Female': 'en-US-AvaMultilingualNeural', 'lang': 'en',
                'kokoro': {'Male': 'am_michael', 'Female': 'af_heart'}, 'kokoro_lang': 'en-us'},
    'Spanish (Latam)': {'Male': 'es-MX-JorgeNeural', 'Female': 'es-MX-DaliaNeural', 'lang': 'es',
                        'kokoro': {'Male': 'em_alex', 'Female': 'ef_dora'}, 'kokoro_lang': 'es'},
    'Spanish (Spain)': {'Male': 'es-ES-AlvaroNeural', 'Female': 'es-ES-ElviraNeural', 'lang': 'es',
                        'kokoro': {'Male': 'em_alex', 'Female': 'ef_dora'}, 'kokoro_lang': 'es'},
    'Portuguese': {'Male': 'pt-PT-DuarteNeural', 'Female': 'pt-PT-RaquelNeural', 'lang': 'pt',
                   'kokoro': {'Male': 'pm_alex', 'Female': 'pf_dora'}, 'kokoro_lang': 'pt-br'},
    'French': {'Male': 'fr-FR-HenriNeural', 'Female': 'fr-FR-DeniseNeural', 'lang': 'fr',
               'kokoro': {'Male': 'ff_siwis', 'Female': 'ff_siwis'}, 'kokoro_lang': 'fr-fr'},
    'Italian': {'Male': 'it-IT-DiegoNeural', 'Female': 'it-IT-ElsaNeural', 'lang': 'it',
                'kokoro': {'Male': 'im_nicola', 'Female': 'if_sara'}, 'kokoro_lang': 'it'},
}

# Global reference to the plugin instance for the config dialog
_plugin_instance = None

def get_plugin_instance():
    return _plugin_instance

class InterfacePlugin(InterfaceAction):
    name = 'Audiobook Generator'
    
    # List of formats that this plugin can "process". 
    # Adding MP3 here helps Calibre understand that this plugin 
    # is interested in these formats for actions like "Send to device".
    supported_formats = ['mp3', 'm4b']
    
    action_spec = ('Audiobook Generator', None, 
                   'Generate audiobooks from ebooks using TTS', None)

    def genesis(self):
        global _plugin_instance
        _plugin_instance = self
        
        if hasattr(self, 'interface_action_base_plugin'):
            self.interface_action_base_plugin.actual_plugin_object = self
        
        icon = get_icons('images/icon.png')
        if icon:
            self.qaction.setIcon(icon)
        self.qaction.triggered.connect(self.show_dialog)
        
        # 1. Configure Action in toolbar menu
        self.config_action = self.create_action(
            spec=('Configure Plugin', 'config.png', 'Change plugin settings', None),
            attr='configure_plugin'
        )
        self.config_action.triggered.connect(self.do_config)
        
        # attr is where Calibre stores the action on self, so it must not be a method name
        self.stats_action = self.create_action(
            spec=('Open audiobook statistics', None, 'Open the log of every audiobook made', None),
            attr='stats_menu_action'
        )
        self.stats_action.triggered.connect(self.open_stats)

        self.menu = QMenu(self.gui)
        self.menu.addAction(self.config_action)
        self.menu.addAction(self.stats_action)
        self.qaction.setMenu(self.menu)

    def open_stats(self):
        if not os.path.exists(STATS_PATH):
            return info_dialog(self.gui, 'No statistics yet',
                               'Statistics are recorded after your first audiobook finishes.', show=True)
        from calibre.gui2 import open_local_file
        open_local_file(STATS_PATH)

    def do_config(self):
        if hasattr(self, 'interface_action_base_plugin'):
            self.interface_action_base_plugin.do_user_config(self.gui)
        else:
            self.gui.iactions['Preferences'].do_config('plugins', self.name)

    def show_dialog(self):
        ids = self.gui.library_view.get_selected_ids()
        if not ids:
            return error_dialog(self.gui, 'No book selected', 
                                'Please select a book first.', show=True)
        
        if len(ids) > 1:
            return error_dialog(self.gui, 'Multiple books selected', 
                                'Please select only one book at a time.', show=True)

        db = self.gui.current_db
        book_id = ids[0]
        mi = db.get_metadata(book_id, index_is_id=True)
        title = mi.title

        # The book text doesn't change with the settings, so read it once
        chars = chapter_count = None
        epub_path = db.new_api.format_abspath(book_id, 'EPUB')
        if epub_path and os.path.exists(epub_path):
            try:
                from calibre_plugins.audiobook_generator.worker import extract_chapters
                author = mi.authors[0] if mi.authors else ''
                chapters = extract_chapters(epub_path, 'en', {'title': title, 'author': author})
                chars, chapter_count = sum(len(t) for _, t in chapters), len(chapters)
            except Exception:
                pass

        from qt.core import QDialog, QDialogButtonBox, QLabel, QVBoxLayout
        from calibre_plugins.audiobook_generator.config import ConfigWidget
        from calibre_plugins.audiobook_generator.worker import describe_estimate, learned_speed
        from html import escape

        d = QDialog(self.gui)
        d.setWindowTitle('Generate Audiobook')
        layout = QVBoxLayout(d)
        heading = QLabel(title, d)
        heading.setTextFormat(Qt.TextFormat.PlainText)
        font = heading.font()
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)
        w = ConfigWidget(self)
        layout.addWidget(w)
        est = QLabel(d)
        est.setTextFormat(Qt.TextFormat.RichText)
        est.setWordWrap(True)
        layout.addWidget(est)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, d)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Generate')
        buttons.accepted.connect(d.accept)
        buttons.rejected.connect(d.reject)
        layout.addWidget(buttons)

        def pick_language():
            detected = self.book_language(mi) if w.detect_language_checkbox.isChecked() else None
            return detected or w.language_combo.currentText()

        def refresh(*args):
            engine = w.engine_combo.currentText()
            gender = w.gender_combo.currentText() if engine != 'gTTS' else 'default voice'
            # (label, value, value color); mid-tone colors read on light and dark themes
            rows = []
            if chars is None:
                rows.append(('Estimate', 'unavailable', None))
            else:
                # "Estimated cost: $1.07 to ..." -> {'Cost': '$1.07 to ...'}
                est_rows = dict((label.replace('Estimated ', '').capitalize(), value.rstrip('.'))
                                for label, value in (line.split(': ', 1)
                                                     for line in describe_estimate(chars, engine, speed=learned_speed(STATS_PATH, engine)).splitlines()))
                length, audio = est_rows['Book text'].split(', ', 1)
                rows += [('Cost', est_rows['Cost'], '#2e9e5b'),
                         ('Time to make', est_rows['Time to make'], '#e08a1e'),
                         ('Book text', f'{audio[0].upper()}{audio[1:]}, {length}', None)]
            rows.append(('Audiobook', f'{w.format_combo.currentText()} with {engine} ({pick_language()}, {gender})', None))
            if chars is not None:
                rows.append(('Chapters', f'{chapter_count} (front and back matter skipped)', None))
            table = ''.join(f'<tr><td style="padding:2px 14px 2px 0; color:#4a8fe7"><b>{escape(k)}</b></td>'
                            f'<td style="padding:2px 0{"; color:" + c + "; font-weight:bold" if c else ""}">'
                            f'{escape(v)}</td></tr>' for k, v, c in rows)
            est.setText(f'<hr><table>{table}</table>'
                        '<p style="color:gray">It runs in the background. '
                        'Watch progress in the "Jobs" spinner.</p>')

        for combo in (w.format_combo, w.engine_combo, w.gender_combo, w.language_combo, w.storage_combo):
            combo.currentIndexChanged.connect(refresh)
        w.detect_language_checkbox.toggled.connect(refresh)
        refresh()

        if d.exec() != QDialog.DialogCode.Accepted:
            return
        w.save_settings()
        self.start_background_job(book_id, title, pick_language(), prefs['tts_engine'],
                                  prefs['voice_gender'], prefs['output_format'])

    def book_language(self, mi):
        if not mi.languages:
            return None
        l = mi.languages[0].lower()
        if l.startswith('en') or l == 'eng':
            return 'English'
        if l.startswith('es') or l == 'spa':
            # Map to Spain if specifically es-es or spa-es, else Latam
            return 'Spanish (Spain)' if l in ('es-es', 'spa-es') else 'Spanish (Latam)'
        if l.startswith('pt') or l == 'por':
            return 'Portuguese'
        if l.startswith('fr') or l in ('fra', 'fre'):
            return 'French'
        if l.startswith('it') or l == 'ita':
            return 'Italian'
        return None

    def start_background_job(self, book_id, title, language, engine, gender, output_format):
        from calibre_plugins.audiobook_generator.worker import main as worker_main, learned_speed
        db = self.gui.current_db.new_api
        epub_path = db.format_abspath(book_id, 'EPUB')
        if not epub_path:
            return error_dialog(self.gui, 'No EPUB found', 'This book does not have an EPUB format.', show=True)

        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.' + output_format.lower(), delete=False) as tf:
            temp_out = tf.name

        mapping = VOICE_MAPPING.get(language, VOICE_MAPPING['English'])
        if engine.startswith('Kokoro'):
            voice, lang_code = mapping['kokoro'][gender], mapping['kokoro_lang']
        elif engine.startswith('Gemini'):
            voice, lang_code = GEMINI_VOICES[gender], mapping['lang']  # Gemini picks up the language itself
        else:
            voice, lang_code = mapping[gender], mapping['lang']

        mi = db.get_metadata(book_id)
        meta = {'title': mi.title, 'author': mi.authors[0] if mi.authors else '',
                'cover': db.cover(book_id, as_path=True), 'helper_src': get_resources('kokoro_helper.py'),
                'api_key': prefs.get('openrouter_key', '').strip() or os.environ.get('OPENROUTER_API_KEY', ''),
                'stats': {}, 'speed': learned_speed(STATS_PATH, engine)}

        callback = Dispatcher(self.on_job_finished)
        job = ThreadedJob('audiobook_gen', f'Generating audiobook for "{title}"', worker_main,
                          [epub_path, temp_out, voice, engine, lang_code, vendor_path, book_id, output_format, meta], {},
                          callback)
        job.temp_files = [temp_out, meta['cover']]
        job.stats = meta['stats']  # the worker fills this in as it runs
        self.gui.job_manager.run_threaded_job(job)
        self.gui.status_bar.show_message(f'Audiobook Generator: Background job started for "{title}"', 3000)

    def on_job_finished(self, job):
        temp_files = [p for p in getattr(job, 'temp_files', []) if p]
        stats = getattr(job, 'stats', {})
        try:
            self.save_job_result(job, stats)
        except Exception as e:
            stats.update(status='failed', error=f'Saving failed: {e}')
            raise
        finally:
            self.record_stats(stats)
            for path in temp_files:
                if os.path.exists(path):
                    os.remove(path)

    def record_stats(self, stats):
        from calibre_plugins.audiobook_generator.worker import append_stats
        try:
            append_stats(STATS_PATH, stats)
        except Exception as e:  # never let bookkeeping break the job
            print('Audiobook Generator: could not write statistics:', e)

    def save_job_result(self, job, stats):
        if job.failed:
            stats.update(status='crashed', error=str(job.exception))
            return error_dialog(self.gui, 'Audiobook Generator failed',
                                f'The job crashed: {job.exception}', det_msg=job.details, show=True)

        success, (book_id, output_format, result_val, warning) = job.result
        if not success:
            stats.update(status='stopped' if result_val == 'Aborted.' else 'failed', error=result_val)
            return error_dialog(self.gui, 'Audiobook Generator failed', result_val,
                                det_msg=job.details, show=True)

        temp_out = result_val
        stats.update(status='saved with gaps' if warning else 'success', error=warning or '',
                     file_mb=round(os.path.getsize(temp_out) / 1e6, 1))
        db = self.gui.current_db.new_api
        storage_mode = prefs.get('storage_mode', 'Internal')
        unified_path = prefs.get('unified_folder_path', '')

        if storage_mode == 'External' and unified_path and os.path.exists(unified_path):
            import shutil
            from calibre_plugins.audiobook_generator.worker import unique_path
            mi = db.get_metadata(book_id)
            safe_title = "".join([c for c in mi.title if c.isalnum() or c in (' ', '-', '_')]).strip()
            safe_author = "".join([c for c in mi.authors[0] if c.isalnum() or c in (' ', '-', '_')]).strip()
            dest_path = unique_path(unified_path, f"{safe_title} - {safe_author}", output_format.lower())
            shutil.move(temp_out, dest_path)
            saved_to = dest_path
        else:
            with open(temp_out, 'rb') as f:
                db.add_format(book_id, output_format, f, replace=True)
            saved_to = 'your Calibre library'
        stats['saved_to'] = saved_to

        self.apply_emblem_to_book(book_id)
        if warning:
            warning_dialog(self.gui, 'Audiobook saved with gaps', f'Saved to {saved_to}, but {warning}',
                           det_msg=job.details, show=True)
        else:
            self.gui.status_bar.show_message(f'Audiobook Generator: SUCCESS - saved to {saved_to}', 10000)

    def has_audio_format(self, book_id):
        db = self.gui.current_db.new_api
        formats = db.formats(book_id)
        if 'MP3' in formats or 'M4B' in formats:
            return True
        
        # Check external folder if configured
        storage_mode = prefs.get('storage_mode', 'Internal')
        unified_path = prefs.get('unified_folder_path', '')
        if storage_mode == 'External' and unified_path and os.path.exists(unified_path):
            mi = db.get_metadata(book_id)
            safe_title = "".join([c for c in mi.title if c.isalnum() or c in (' ', '-', '_')]).strip()
            safe_author = "".join([c for c in mi.authors[0] if c.isalnum() or c in (' ', '-', '_')]).strip()
            for ext in ('mp3', 'm4b'):
                filename = f"{safe_title} - {safe_author}.{ext}"
                if os.path.exists(os.path.join(unified_path, filename)):
                    return True
        return False

    def remove_emblem_from_book(self, book_id):
        """Attempts to restore original cover from ebook file if audio is missing."""
        if self.has_audio_format(book_id):
            return

        db = self.gui.current_db.new_api
        formats = db.formats(book_id)
        
        from calibre.ebooks.metadata.meta import get_metadata
        for fmt in formats:
            path = db.format_abspath(book_id, fmt)
            if path and os.path.exists(path):
                try:
                    with open(path, 'rb') as f:
                        mi = get_metadata(f, stream_type=fmt.lower())
                    cover_data = None
                    if mi.cover_data and mi.cover_data[1]:
                        cover_data = mi.cover_data[1]
                    elif mi.cover and os.path.exists(mi.cover):
                        with open(mi.cover, 'rb') as cf:
                            cover_data = cf.read()
                    if cover_data:
                        db.set_cover({book_id: cover_data})
                        self.gui.library_view.model().refresh_ids([book_id])
                        return
                except: continue

    def sync_all_icons(self):
        """Runs library sync in a background thread to prevent UI freeze."""
        # Using a ThreadedJob for the sync as well
        def sync_worker(db, book_ids, notifications, abort, log, has_audio_func):
            add_count = 0
            rem_count = 0
            total = len(book_ids)
            for i, bid in enumerate(book_ids):
                if abort.is_set(): break
                if has_audio_func(bid):
                    add_count += 1
                else:
                    rem_count += 1
                if i % 10 == 0:
                    notifications.put((i/total, f"Scanning book {i} of {total}..."))
            return add_count, rem_count, book_ids

        db = self.gui.current_db.new_api
        ids = list(db.all_book_ids())
        
        # We'll do the actual drawing back in the GUI thread via the callback
        job = ThreadedJob('audiobook_sync', 'Syncing Audiobook Icons', sync_worker, 
                          [db, ids, self.has_audio_format], {}, Dispatcher(self.on_sync_finished))
        self.gui.job_manager.run_threaded_job(job)
        self.gui.status_bar.show_message('Audiobook Generator: Started library-wide sync...', 3000)

    def on_sync_finished(self, job):
        if job.failed:
            self.gui.status_bar.show_message('Audiobook Generator: Sync failed!', 5000)
            return
        
        add_count, rem_count, ids = job.result
        
        # Drawing must happen in GUI thread
        for bid in ids:
            if self.has_audio_format(bid):
                self.apply_emblem_to_book(bid)
            else:
                self.remove_emblem_from_book(bid)
                
        self.gui.status_bar.show_message(f'Audiobook Generator: Sync complete ({add_count} icons, {rem_count} cleared).', 10000)

    def apply_settings(self):
        pass

    def apply_emblem_to_book(self, book_id):
        """Adds a cassette emblem to the book cover."""
        db = self.gui.current_db.new_api
        cover_data = db.cover(book_id)
        if not cover_data:
            return
            
        try:
            img = QImage.fromData(cover_data)
            if img.isNull():
                return
                
            # Load cassette emblem
            emblem_path = os.path.join(plugin_path, 'images', 'cassette.png')
            if not os.path.exists(emblem_path):
                return
                
            emblem = QImage(emblem_path)
            if emblem.isNull():
                return
                
            # Scale emblem to a fraction of the cover size (e.g., 1/4 width)
            w = img.width() // 4
            h = (emblem.height() * w) // emblem.width()
            emblem = emblem.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            
            # Draw emblem on bottom right
            painter = QPainter(img)
            painter.drawImage(img.width() - w - 10, img.height() - h - 10, emblem)
            painter.end()
            
            # Save back to DB
            ba = QBuffer()
            ba.open(QIODevice.OpenModeFlag.WriteOnly)
            img.save(ba, "JPG")
            db.set_cover({book_id: ba.data()})
            self.gui.library_view.model().refresh_ids([book_id])
        except:
            pass
