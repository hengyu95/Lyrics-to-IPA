"""Lyric IPA Finder — singing-aware vowel coach.

Click any word in the lyrics to see its IPA breakdown, the position of each
vowel on the chart, articulation tips, and modification advice for higher
pitches. Diphthongs are surfaced as units with sustain/glide pedagogy.
When a word has multiple valid pronunciations, they're tagged
'brighter'/'darker' so you can make a conscious stylistic choice.

Right-click any word to set a custom IPA — useful for proper nouns like
"Valjean" and prisoner numbers like "24601" that aren't in the dictionary.
Songs are stored as named save slots; each remembers its lyrics and its
custom-IPA overrides.
"""
from __future__ import annotations

import atexit
import base64
import html
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from io import StringIO
from os import path
from typing import Optional

# ── HiDPI must be set before QApplication is created ──────────────────────────
os.environ.setdefault('QT_AUTO_SCREEN_SCALE_FACTOR', '1')

from PyQt5.QtCore import (Qt, QPoint, QRect, QUrl, QSettings,
                          QStandardPaths, QTimer, pyqtSignal)
from PyQt5.QtGui import (QColor, QFont, QFontMetrics, QIcon, QLinearGradient,
                         QPainter, QPalette, QPolygon,
                         QTextCharFormat, QTextCursor)
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtWidgets import (QAction, QApplication, QComboBox, QDialog,
                             QDialogButtonBox, QFrame, QHBoxLayout,
                             QInputDialog, QLabel, QLineEdit, QMainWindow,
                             QMenu, QMessageBox, QPlainTextEdit, QPushButton,
                             QScrollArea, QSizePolicy, QSplitter, QStackedWidget,
                             QTextEdit, QToolButton, QToolTip, QVBoxLayout,
                             QWidget)
import svgwrite
import eng_to_ipa as ipa

try:
    from PyQt5.QtSvg import QSvgWidget
    HAS_QTSVG = True
except ImportError:
    HAS_QTSVG = False


# =============================================================================
# HiDPI scaling helpers  — call after QApplication exists
# =============================================================================

def _dpr() -> float:
    """Device pixel ratio of the primary screen (1.0 on normal displays,
    2.0 on Retina/4K with 200% scaling, etc.)."""
    screens = QApplication.screens()
    if screens:
        return screens[0].devicePixelRatio()
    return 1.0



def _scale(value: float) -> int:
    """Return *value* as an integer logical-pixel size.

    With ``AA_EnableHighDpiScaling`` enabled, Qt automatically converts
    logical pixels to physical pixels using the screen DPR, so callers
    should pass the intended *logical* size and let Qt do the rest.
    The user's UI-scale preference lives in the QSS stylesheet (build_style)
    where it can be updated dynamically; hard-coded widget sizes set via
    setFixedHeight/setMinimumSize do not respond to live style changes so
    they stay at neutral logical-pixel values.
    """
    return max(1, round(value))


def _scalef(value: float) -> float:
    """Floating-point version of _scale."""
    return float(value)


# =============================================================================
# Vowel database
# =============================================================================

@dataclass(frozen=True)
class Vowel:
    symbol: str
    x: int            # 0 (front) to 250 (back) on the trapezoid
    y: int            # 0 (close/high) to 300 (open/low)
    rounded: bool
    name: str
    tongue_height: str
    tongue_advance: str
    lips: str
    singing_note: str
    mod_high: Optional[str]   # single-step modification target at high pitch


_V = [
    Vowel('i', 0,   0,   False, 'close front unrounded',
          'high', 'front', 'spread, neutral',
          "Bright and forward. Don't over-spread the lips on high notes — "
          "that thins the tone.",
          'ɪ'),
    Vowel('y', 0,   0,   True,  'close front rounded',
          'high', 'front', 'rounded',
          'Bright tongue, rounded lips. French "tu", German "über".',
          'ʏ'),
    Vowel('ɪ', 50,  50,  False, 'near-close near-front unrounded',
          'near-high', 'near-front', 'neutral',
          "A common modification target for /i/ — slightly relaxed and rounder.",
          None),
    Vowel('ʏ', 50,  50,  True,  'near-close near-front rounded',
          'near-high', 'near-front', 'slightly rounded',
          'Modification target for /y/.',
          None),
    Vowel('e', 17,  100, False, 'close-mid front unrounded',
          'mid-high', 'front', 'neutral to spread',
          "In legit/classical, often relaxes toward /ɛ/ as pitch rises. Rare "
          "alone in English — usually part of the diphthong /eɪ/.",
          'ɛ'),
    Vowel('ø', 17,  100, True,  'close-mid front rounded',
          'mid-high', 'front', 'rounded',
          'French "deux", German "schön".',
          'œ'),
    Vowel('ɛ', 34,  200, False, 'open-mid front unrounded',
          'mid-low', 'front', 'neutral',
          "A comfortable open-front vowel. Stable across most of the range; "
          "usually no modification needed. At extreme soprano pitches "
          "some slight opening is acceptable but /ɛ/ itself carries well.",
          None),
    Vowel('œ', 34,  200, True,  'open-mid front rounded',
          'mid-low', 'front', 'rounded',
          'French "neuf".',
          None),
    Vowel('æ', 43,  250, False, 'near-open front unrounded',
          'low', 'front', 'spread',
          "Bright but tense. Belt-friendly; classical singers modify toward "
          "/ɛ/ to avoid the pinched quality at high pitch.",
          'ɛ'),
    Vowel('a', 50,  300, False, 'open front unrounded',
          'low', 'front', 'neutral',
          "Open and bright. Release the jaw — don't lateral-spread.",
          None),
    Vowel('ɶ', 50,  300, True,  'open front rounded',
          'low', 'front', 'rounded',
          'Rare. Some Scandinavian languages.',
          None),
    Vowel('ɨ', 125, 0,   False, 'close central unrounded',
          'high', 'central', 'neutral',
          'Shadowy, neutral high vowel. Russian "ы".',
          'ə'),
    Vowel('ʉ', 125, 0,   True,  'close central rounded',
          'high', 'central', 'rounded',
          'Swedish "du"; many Australian English /u/ variants.',
          'ʊ'),
    Vowel('ɘ', 137, 100, False, 'close-mid central unrounded',
          'mid-high', 'central', 'neutral',
          "Near-schwa. Pass through it; don't color it.",
          'ə'),
    Vowel('ɵ', 137, 100, True,  'close-mid central rounded',
          'mid-high', 'central', 'slightly rounded',
          'Lightly rounded schwa region.',
          'ə'),
    Vowel('ə', 139, 150, False, 'mid central (schwa)',
          'mid', 'central', 'neutral',
          "The most neutral vowel — tongue and lips at rest. Many singers "
          "over-weight schwa; resist it. On stressed syllables a schwa usually "
          "wants to be /ʌ/ instead.",
          None),
    Vowel('ɜ', 141, 200, False, 'open-mid central unrounded',
          'mid-low', 'central', 'neutral',
          'British "bird". The base vowel underlying the American r-colored /ɝ/. '
          'For classical/legit singing, de-rhotacize American /ɝ/ toward this.',
          None),
    Vowel('ɝ', 141, 200, False, 'open-mid central unrounded (r-colored)',
          'mid-low', 'central', 'neutral with retroflex/bunched r',
          'American English stressed r-vowel: "bird", "word", "her" (when stressed). '
          'R-coloring is a tongue posture layered on top of /ɜ/ — the tongue tip '
          'curls back or the tongue body bunches. For classical and legit musical '
          'theatre singing, release the r-color and sustain on /ɜ/ instead. '
          'Plotted at the same position as /ɜ/ since the base articulation is identical.',
          'ɜ'),
    Vowel('ɚ', 139, 150, False, 'mid central (r-colored schwa)',
          'mid', 'central', 'neutral with retroflex/bunched r',
          'American English unstressed r-vowel: "butter", "your", "over". '
          'The rhotacized counterpart of schwa /ə/ — same neutral tongue position '
          'but with added r-coloring. For sustained singing, release the r and '
          'settle into plain /ə/. Plotted at the schwa position on the trapezoid.',
          'ə'),
    Vowel('ɞ', 141, 200, True,  'open-mid central rounded',
          'mid-low', 'central', 'rounded',
          'Rare.',
          None),
    Vowel('ɐ', 143, 250, False, 'near-open central unrounded',
          'low', 'central', 'neutral',
          'Central and open — a comfortable resonance space for high notes.',
          None),
    Vowel('ɯ', 250, 0,   False, 'close back unrounded',
          'high', 'back', 'neutral',
          'Back tongue without lip rounding — dark without warmth.',
          'ɤ'),
    Vowel('u', 250, 0,   True,  'close back rounded',
          'high', 'back', 'rounded',
          'The darkest common vowel. On high notes, open lips slightly '
          'toward /ʊ/ — pursing locks the resonance.',
          'ʊ'),
    Vowel('ʊ', 210, 50,  True,  'near-close near-back rounded',
          'near-high', 'near-back', 'rounded',
          'A relaxed back vowel. Modification target for /u/ at high pitches.',
          'o'),
    Vowel('ɤ', 250, 100, False, 'close-mid back unrounded',
          'mid-high', 'back', 'neutral',
          'Mandarin "ㄜ"; back, mid-high, unrounded.',
          'ʌ'),
    Vowel('o', 250, 100, True,  'close-mid back rounded',
          'mid-high', 'back', 'rounded',
          'Round and dark. Sustain by keeping internal space — never by pursing. '
          'At high pitch, allow slight opening toward /ɔ/, preserving the lip-round.',
          'ɔ'),
    Vowel('ʌ', 250, 200, False, 'open-mid back unrounded',
          'mid-low', 'back', 'neutral',
          'American "cup". At high pitch some classical singers open toward /ɔ/ '
          '(British/round school); most American legit teachers prefer opening toward /ɑ/ '
          'to preserve the unrounded quality. Both are defensible — choose consciously '
          'and stay consistent within a phrase.',
          'ɔ'),
    Vowel('ɔ', 250, 200, True,  'open-mid back rounded',
          'mid-low', 'back', 'rounded',
          "British \"thought\". Rich and round — chiaroscuro's dark pole.",
          None),
    Vowel('ɑ', 250, 300, False, 'open back unrounded',
          'low', 'back', 'neutral',
          'American "father". Open, dark, comfortable on high notes.',
          None),
    Vowel('ɒ', 250, 300, True,  'open back rounded',
          'low', 'back', 'rounded',
          'British "lot". Slight rounding adds warmth without darkening fully.',
          None),
]
VOWELS = {v.symbol: v for v in _V}


# Familiar word examples for each vowel
VOWEL_EXAMPLES = {
    'i':  'beet',     'ɪ':  'bit',
    'y':  'tu (Fr.)', 'ʏ':  'Glück (Ger.)',
    'e':  'café',     'ø':  'deux (Fr.)',
    'ɛ':  'bed',      'œ':  'neuf (Fr.)',
    'æ':  'cat',      'a':  'spa',
    'ɶ':  '(rare)',
    'ɨ':  '(Russian)', 'ʉ':  '(Swedish)',
    'ɘ':  '(near schwa)', 'ɵ': '(rounded schwa)',
    'ə':  'sofa',
    'ɜ':  'her (Br.)', 'ɝ': 'bird (Am.)', 'ɚ': 'butter (Am.)', 'ɞ': '(rare)',
    'ɐ':  'butter',
    'ɯ':  '(Mandarin)',
    'u':  'boot',     'ʊ':  'book',
    'ɤ':  '(Mandarin)',
    'o':  'no (Sp.)',
    'ʌ':  'cup',      'ɔ':  'thought',
    'ɑ':  'father',   'ɒ':  'lot (Br.)',
}


# =============================================================================
# Diphthong database
# =============================================================================

@dataclass(frozen=True)
class Diphthong:
    symbol: str       # 'eɪ', 'aɪ', etc.
    name: str
    example: str
    primary: str      # sustained vowel
    glide: str        # vanishing vowel
    singing_note: str
    mod_primary: Optional[str]


_DI = [
    Diphthong('eɪ', 'long-A diphthong', 'say, plain, day, way', 'e', 'ɪ',
              "Sustain on /e/ for nearly the whole duration. Glide to /ɪ/ only "
              "at the very last moment, like a vanishing tail. Rushing to the "
              "/ɪ/ is the most common amateur mistake on this vowel.",
              'ɛ'),
    Diphthong('aɪ', 'long-I diphthong', 'sky, mine, time, my', 'a', 'ɪ',
              'Sustain on /a/ (an open, bright vowel). Late vanish to /ɪ/. '
              'At very high pitch, the /a/ may open further toward /ɑ/.',
              'ɑ'),
    Diphthong('aʊ', 'OW diphthong', 'how, now, mouth, out', 'a', 'ʊ',
              'Sustain on /a/. Late vanish to /ʊ/. Keep the lips open through '
              'the sustain — they only round at the very end.',
              'ɑ'),
    Diphthong('oʊ', 'long-O diphthong', 'no, go, slow, hold', 'o', 'ʊ',
              'Sustain on /o/. The /ʊ/ tail is barely there — many classical '
              'singers omit it entirely and sustain pure /o/.',
              'ɔ'),
    Diphthong('ɔɪ', 'OI diphthong', 'boy, joy, voice', 'ɔ', 'ɪ',
              'Sustain on /ɔ/ (round and dark). Late vanish to /ɪ/. The shift '
              'between rounded and spread is dramatic — control the lip motion.',
              'o'),
    Diphthong('ɪə', 'EAR diphthong', 'here, near, dear (Br.)', 'ɪ', 'ə',
              'Brief /ɪ/ relaxing into schwa. Mostly British/RP transcription.',
              None),
    Diphthong('eə', 'AIR diphthong', 'there, hair, care (Br.)', 'e', 'ə',
              'Open /e/ relaxing into schwa. Mostly British/RP.', None),
    Diphthong('ʊə', 'POOR diphthong', 'tour, poor (Br.)', 'ʊ', 'ə',
              '/ʊ/ relaxing into schwa. Mostly British/RP.', None),
]
DIPHTHONGS = {d.symbol: d for d in _DI}


def get_phone(symbol: str):
    return DIPHTHONGS.get(symbol) or VOWELS.get(symbol)


# =============================================================================
# Common function words — sung weak forms
# =============================================================================

FUNCTION_WORDS = {
    'the':    ['ðə', 'ði'],
    'a':      ['ə', 'eɪ'],
    'an':     ['ən', 'æn'],
    'of':     ['əv', 'ʌv'],
    'to':     ['tə', 'tu'],
    'for':    ['fɚ', 'fɔɹ'],
    'and':    ['ən', 'ænd'],
    'but':    ['bət', 'bʌt'],
    'or':     ['ɚ', 'ɔɹ'],
    'as':     ['əz', 'æz'],
    'in':     ['ɪn'],
    'on':     ['ɑn'],
    'at':     ['ət', 'æt'],
    'is':     ['ɪz'],
    'was':    ['wəz', 'wʌz'],
    'are':    ['ɚ', 'ɑɹ'],
    'were':   ['wɚ'],
    'my':     ['maɪ'],
    'your':   ['jɚ', 'jɔɹ'],
    'his':    ['hɪz'],
    'her':    ['hɚ'],
    'our':    ['aʊɚ', 'ɑɹ'],
    'their':  ['ðɛɚ', 'ðɛɹ'],
    'them':   ['ðəm'],
    'us':     ['əs'],
    'him':    ['hɪm'],
    'will':   ['wɪl'],
    'would':  ['wəd', 'wʊd'],
    'should': ['ʃəd', 'ʃʊd'],
    'could':  ['kəd', 'kʊd'],
    'have':   ['həv', 'hæv'],
    'has':    ['həz', 'hæz'],
    'had':    ['həd', 'hæd'],
    'do':     ['də', 'du'],
    'does':   ['dəz', 'dʌz'],
    'did':    ['dɪd'],
    'been':   ['bɪn', 'bin'],
    'than':   ['ðən', 'ðæn'],
    'that':   ['ðət', 'ðæt'],
    'with':   ['wɪð', 'wɪθ'],
}


# =============================================================================
# Brightness
# =============================================================================

def brightness(symbol: str) -> float:
    """Diphthongs use their primary vowel's brightness."""
    if symbol in DIPHTHONGS:
        return brightness(DIPHTHONGS[symbol].primary)
    v = VOWELS.get(symbol)
    if not v:
        return 0.5
    b = 1.0 - v.x / 250.0
    closeness = 1.0 - v.y / 300.0
    factor = 0.6 + 0.4 * closeness
    if b > 0.5:
        b = 0.5 + (b - 0.5) * factor
    else:
        b = 0.5 - (0.5 - b) * factor
    if v.rounded:
        b -= 0.18
    return max(0.0, min(1.0, b))


def brightness_label(symbol: str) -> str:
    b = brightness(symbol)
    if b >= 0.7:
        return 'bright'
    if b >= 0.4:
        return 'neutral'
    return 'dark'


def brightness_color(b: float) -> QColor:
    """Warm peach (bright) → cool blue (dark)."""
    if b >= 0.5:
        t = (b - 0.5) * 2
        r = int(106 + (216 - 106) * t)
        g = int(96 + (168 - 96) * t)
        bb = int(120 + (130 - 120) * t)
    else:
        t = b * 2
        r = int(60 + (106 - 60) * t)
        g = int(80 + (96 - 80) * t)
        bb = int(168 + (120 - 168) * t)
    return QColor(r, g, bb)




def _tts_temp_dir() -> str:
    """Return (creating if needed) a dedicated folder for TTS SSML temp files."""
    d = os.path.join(tempfile.gettempdir(), 'LyricsToIPA_tts')
    os.makedirs(d, exist_ok=True)
    return d


def _tts_cleanup() -> None:
    """Delete any leftover TTS temp files.  Called at exit and on startup."""
    d = os.path.join(tempfile.gettempdir(), 'LyricsToIPA_tts')
    if not os.path.isdir(d):
        return
    for name in os.listdir(d):
        if name.startswith('tts_') and name.endswith('.xml'):
            try:
                os.unlink(os.path.join(d, name))
            except OSError:
                pass


atexit.register(_tts_cleanup)


def _tts_speak(word: str, ipa_pron: str = '') -> None:
    """Speak *word* via system TTS, using *ipa_pron* where supported.

    Windows: writes SSML to a UTF-8 temp file and passes the path to
    PowerShell SAPI — this avoids every inline escaping problem with
    non-ASCII IPA characters.
    macOS: `say` (no IPA support; speaks the word).
    Linux: `espeak-ng` then `espeak` fallback.
    Non-blocking. Silently does nothing if TTS is unavailable.
    """
    try:
        if sys.platform == 'win32':
            safe_word = word.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            if ipa_pron:
                # XML-escape the IPA string for the ph attribute
                safe_ipa = (ipa_pron
                            .replace('&', '&amp;')
                            .replace('"', '&quot;')
                            .replace('<', '&lt;')
                            .replace('>', '&gt;'))
                ssml = (
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<speak version="1.0" '
                    'xmlns="http://www.w3.org/2001/10/synthesis" '
                    'xml:lang="en-US">'
                    f'<phoneme alphabet="ipa" ph="{safe_ipa}">{safe_word}</phoneme>'
                    '</speak>'
                )
            else:
                ssml = (
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<speak version="1.0" '
                    'xmlns="http://www.w3.org/2001/10/synthesis" '
                    f'xml:lang="en-US">{safe_word}</speak>'
                )

            # Write to a temp file in a dedicated subfolder so cleanup is
            # easy and leftover files stay contained.
            tmp_dir = _tts_temp_dir()
            import uuid as _uuid
            tmp_path = os.path.join(tmp_dir,
                                    f'tts_{_uuid.uuid4().hex}.xml')
            with open(tmp_path, 'w', encoding='utf-8') as _tf:
                _tf.write(ssml)

            # Forward slashes work fine in PowerShell paths and avoid
            # backslash escaping inside the double-quoted PS string.
            ps_path = tmp_path.replace('\\', '/')
            ps_cmd = (
                'Add-Type -AssemblyName System.Speech; '
                '$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; '
                f'$s.SpeakSsml([System.IO.File]::ReadAllText("{ps_path}")); '
                f'Remove-Item "{ps_path}"'
            )
            try:
                subprocess.Popen(
                    ['powershell', '-WindowStyle', 'Hidden', '-Command', ps_cmd],
                    creationflags=0x08000000,
                )
            except (OSError, FileNotFoundError):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

        elif sys.platform == 'darwin':
            subprocess.Popen(['say', word])

        else:
            subprocess.Popen(['espeak-ng', '-v', 'en', word])

    except (OSError, FileNotFoundError):
        try:
            subprocess.Popen(['espeak', '-v', 'en', word])
        except (OSError, FileNotFoundError):
            pass


@dataclass
class WordAnnotation:
    word: str
    word_lower: str
    block: int
    start: int       # char offset within block
    end: int
    abs_start: int   # absolute document position
    abs_end: int
    tip_type: str    # legato | vowel_glide | crash | r_toxicity | plosive | nasal | approx | fricative
    tip_text: str
    color: str       # underline hex
    bg_color: str    # background tint hex



@dataclass
class CoachingNote:
    anchor_start: str   # "word#N"
    anchor_end: str     # "word#N" (== anchor_start for a single word)
    text: str
    anchor_text: str = ''  # verbatim lyrics span; used to re-anchor if lyrics change


# =============================================================================
# Tokenization & syllable extraction
# =============================================================================

WORD_RE = re.compile(
    r"[A-Za-zÀ-ÖØ-öø-ÿ]+(?:['\u2018\u2019][A-Za-zÀ-ÖØ-öø-ÿ]+)*|[0-9]+"
)


def word_occurrences(lyrics: str) -> list:
    """Return list of (match, 'word#N') in document order."""
    counts: dict = {}
    out: list = []
    for m in WORD_RE.finditer(lyrics):
        wl = m.group().lower()
        out.append((m, f'{wl}#{counts.get(wl, 0)}'))
        counts[wl] = counts.get(wl, 0) + 1
    return out


def resolve_anchor(lyrics: str, start_key: str, end_key: str):
    """Return (abs_start, abs_end) covering the inclusive span, or None if
    either endpoint occurrence is missing."""
    pos = {k: m for m, k in word_occurrences(lyrics)}
    a, b = pos.get(start_key), pos.get(end_key)
    if a is None or b is None:
        return None
    lo, hi = sorted((a.start(), b.end()))   # tolerate reversed drag
    return (lo, hi)


def match_anchor_keys(lyrics: str, anchor: str, occ=None):
    """Return (start_key, end_key, is_ambiguous) for the first occurrence of
    *anchor* in *lyrics*, or None if not found.  *occ* may be a precomputed
    word_occurrences(lyrics)."""
    if not anchor:
        return None
    idx = lyrics.find(anchor)
    if idx == -1:
        idx = lyrics.lower().find(anchor.lower())
        if idx == -1:
            return None
    span_end = idx + len(anchor)
    second = lyrics.find(anchor, idx + 1)
    if second == -1:
        second = lyrics.lower().find(anchor.lower(), idx + 1)
    is_ambiguous = second != -1
    if occ is None:
        occ = word_occurrences(lyrics)
    start_key = end_key = None
    for wm, wkey in occ:
        ws, we = wm.start(), wm.end()
        if start_key is None and we > idx:
            start_key = wkey
        if ws < span_end:
            end_key = wkey
    if start_key is None or end_key is None:
        return None
    return (start_key, end_key, is_ambiguous)


def _coaching_wrap_text(text: str, fm: QFontMetrics, max_w: int) -> list:
    """Wrap *text* into lines no wider than *max_w* pixels.
    Always returns at least one element (may be empty string)."""
    words = text.split()
    if not words:
        return ['']
    lines: list = []
    cur = ''
    for w in words:
        candidate = (cur + ' ' + w).strip() if cur else w
        if fm.horizontalAdvance(candidate) <= max_w:
            cur = candidate
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or ['']

VOWEL_CHARS = ''.join(VOWELS.keys())
_vowel_re = re.compile(
    '|'.join(re.escape(d) for d in DIPHTHONGS) + f'|[{re.escape(VOWEL_CHARS)}]'
)


def find_syllable_vowels(text: str):
    """Return list of (symbol, start, end). Symbol may be a diphthong."""
    return [(m.group(), m.start(), m.end()) for m in _vowel_re.finditer(text)]



# =============================================================================
# Consonant classification & diction helpers
# =============================================================================

IPA_PLOSIVES     = {'p', 'b', 't', 'd', 'k', 'g', 'ʔ', 'tʃ', 'dʒ'}
IPA_NASALS       = {'m', 'n', 'ŋ'}
IPA_FRICATIVES   = {'f', 'v', 'θ', 'ð', 's', 'z', 'ʃ', 'ʒ', 'h'}
IPA_APPROXIMANTS = {'l', 'ɹ', 'r', 'w', 'j'}
IPA_ALL_CONS     = IPA_PLOSIVES | IPA_NASALS | IPA_FRICATIVES | IPA_APPROXIMANTS


def ipa_trailing_consonants(pron: str) -> list:
    """Consonant symbols that follow the last vowel in *pron*."""
    syls = find_syllable_vowels(pron)
    tail = pron[syls[-1][2]:] if syls else pron
    result, i = [], 0
    while i < len(tail):
        two = tail[i:i+2]
        if two in ('tʃ', 'dʒ'):
            result.append(two); i += 2
        elif tail[i] in IPA_ALL_CONS:
            result.append(tail[i]); i += 1
        else:
            i += 1
    return result


def ipa_leading_vowel(pron: str) -> Optional[str]:
    """First vowel symbol if *pron* starts with a vowel (after stress marks), else None."""
    stripped = pron.lstrip('ˈˌ')
    if stripped[:2] in DIPHTHONGS:
        return stripped[:2]
    if stripped and stripped[0] in VOWELS:
        return stripped[0]
    return None


def vowel_stress_info(pron: str, vowel_idx: int):
    """Return (is_stressed: bool, is_primary: bool) for the vowel at *vowel_idx*."""
    syls = find_syllable_vowels(pron)
    if not syls or vowel_idx >= len(syls):
        return True, False
    # No stress diacritics anywhere → treat as stressed (mono-syllable content word)
    if 'ˈ' not in pron and 'ˌ' not in pron:
        return True, len(syls) == 1
    _, s, _ = syls[vowel_idx]
    prev_end = syls[vowel_idx - 1][2] if vowel_idx > 0 else 0
    segment = pron[prev_end:s]
    primary = 'ˈ' in segment
    secondary = 'ˌ' in segment
    return (primary or secondary), primary


def consonant_release_tip(consonants: list) -> str:
    """Human-readable release tip for a list of IPA consonant symbols."""
    if not consonants:
        return ''
    plosives    = [c for c in consonants if c in IPA_PLOSIVES]
    nasals      = [c for c in consonants if c in IPA_NASALS]
    approx      = [c for c in consonants if c in IPA_APPROXIMANTS]
    fricatives  = [c for c in consonants if c in IPA_FRICATIVES]
    lines = []
    if plosives:
        s = ' '.join(f'/{c}/' for c in plosives)
        lines.append(f'Plosive exit ({s}) — snap off instantly. No shadow vowel after it.')
    if nasals:
        s = ' '.join(f'/{c}/' for c in nasals)
        lines.append(f'Nasal exit ({s}) — sustain the vowel; place the nasal late and short. '
                     f'It can carry pitch briefly into the release, but don\'t dwell on it.')
    if approx:
        for c in approx:
            if c == 'l':
                lines.append('/l/ exit — keep the tongue tip on the alveolar ridge; '
                             'do not pull the root back. Release the sides gently.')
            elif c in ('w', 'j'):
                lines.append(f'/{c}/ exit — a glide; let it vanish smoothly into '
                             'silence without a hard stop.')
            elif c in ('ɹ', 'r'):
                lines.append('/ɹ/ exit — release the tongue curl before the note ends; '
                             'de-rhotacize for classical/legit.')
            else:
                lines.append(f'/{c}/ exit — gentle release; no hard cutoff.')
    if fricatives:
        IPA_VOICED_FRIC = {'v', 'z', 'ʒ', 'ð'}
        voiced_f   = [c for c in fricatives if c in IPA_VOICED_FRIC]
        unvoiced_f = [c for c in fricatives if c not in IPA_VOICED_FRIC]
        if voiced_f:
            s = ' '.join(f'/{c}/' for c in voiced_f)
            lines.append(f'Voiced fricative exit ({s}) — these carry pitch and can '
                         f'be lengthened for expressive weight. Use them as a sustain resource.')
        if unvoiced_f:
            s = ' '.join(f'/{c}/' for c in unvoiced_f)
            lines.append(f'Unvoiced fricative exit ({s}) — dumps air; keep it brief '
                         f'and controlled. Do not linger.')
    return chr(10).join(lines)


# R-colored consonant (trailing)
IPA_RHOTIC = {'ɹ', 'r'}

# Voiced fricatives — sustainable expressive resources
IPA_VOICED_FRIC = {'v', 'z', 'ʒ', 'ð'}

# Unvoiced consonants (vocal cords open → air dump)
IPA_UNVOICED = {'p', 't', 'k', 'f', 's', 'ʃ', 'h', 'θ', 'tʃ'}

# Sibilants (mic-hostile)
IPA_SIBILANT = {'s', 'z', 'ʃ', 'ʒ', 'tʃ', 'dʒ'}

# Vowel-glide routing: which semi-vowel to insert before next vowel
# Front/central vowels → /j/ glide before next vowel
_GLIDE_J = {'i','ɪ','e','ɛ','æ','ə','ɜ','ɐ','ɨ','eɪ','aɪ','ɔɪ','ɪə','eə'}
# Back/round vowels → /w/ glide before next vowel
_GLIDE_W = {'u','ʊ','o','ɔ','ʌ','ɑ','ɒ','oʊ','aʊ','ʊə'}
# Anything in neither set (rare) defaults to /j/


def ipa_ends_with_vowel(pron: str) -> Optional[str]:
    """Return the final vowel symbol if *pron* ends on a vowel (nothing after
    it but length/stress marks), else None."""
    syls = find_syllable_vowels(pron)
    if not syls:
        return None
    sym, _, end = syls[-1]
    tail = pron[end:].strip('ːˈˌ')
    return sym if not tail else None


def ipa_leading_consonant(pron: str) -> Optional[str]:
    """First consonant symbol if *pron* starts with a consonant."""
    s = pron.lstrip('ˈˌ')
    two = s[:2]
    if two in ('tʃ', 'dʒ'):
        return two
    if s and s[0] in IPA_ALL_CONS:
        return s[0]
    return None


def consonant_crash_tip(trailing: list, next_leading: str) -> Optional[str]:
    """Return a tip string if trailing[-1] + next_leading forms a crash, else None."""
    if not trailing:
        return None
    last = trailing[-1]
    if last == next_leading and last in IPA_PLOSIVES:
        return (f'Geminate /{last}/{next_leading}/ — hold the first stop; '
                f'release only once on the second. Never double-articulate.')
    if last in IPA_PLOSIVES and next_leading in IPA_NASALS:
        return (f'/{last}/ before /{next_leading}/ — elide the plosive '
                f'completely; let the nasal carry the transition.')
    if last in IPA_PLOSIVES and next_leading in IPA_PLOSIVES and last != next_leading:
        return (f'/{last}/ into /{next_leading}/ — hold through the boundary; '
                f'release only on the second plosive.')
    return None


def _check_yod_coalescence(pron: str, next_ipa: Optional[str]) -> Optional[str]:
    """Detect /d/ or /t/ word-final before /j/ word-initial (yod-coalescence zone).
    e.g. 'did you' → potential /dɪdʒu/, 'don't you' → /doʊntʃu/.
    Returns a tip string if applicable, else None.
    """
    if not next_ipa:
        return None
    trailing = ipa_trailing_consonants(pron)
    if not trailing:
        return None
    last = trailing[-1]
    if last not in ('d', 't'):
        return None
    leading = next_ipa.lstrip('ˈˌ')
    if not leading.startswith('j'):
        return None
    result = 'dʒ' if last == 'd' else 'tʃ'
    return (f'Yod-coalescence — /{last}/ + /j/ may coalesce to /{result}/. '
            f'In speech this is natural; in sung diction decide whether you want '
            f'the coalescence or prefer to articulate both consonants cleanly.')


def _check_ng_release(pron: str) -> Optional[str]:
    """Detect word-final /ŋ/ that might attract a spurious /g/ tail.
    e.g. 'singing' — the /g/ should never sound; /ŋ/ closes nasally.
    """
    trailing = ipa_trailing_consonants(pron)
    if trailing and trailing[-1] == 'ŋ':
        return ('/ŋ/ exit — release nasally into silence. '
                'No /g/ tail after /ŋ/ in standard singing diction. '
                'Keep the back of the tongue raised against the soft palate '
                'and let the tone die there.')
    return None


def _check_spurious_diphthong(pron: str) -> Optional[str]:
    """Detect monophthong vowels that commonly attract a spurious glide in casual speech.
    Most at-risk: /ɔ/ → [ɔʊ], /o/ → [oʊ] in non-rhyming positions, /ɑ/ → [ɑʊ].
    """
    syls = find_syllable_vowels(pron)
    if not syls:
        return None
    # Check the last (most likely sustained) syllable vowel
    sym = syls[-1][0]
    risky = {
        'ɔ': ('/ɔ/', '/ɔʊ/'),
        'ɑ': ('/ɑ/', '/ɑʊ/'),
        'o': ('/o/', '/oʊ/'),
    }
    if sym in risky:
        mono, spurious = risky[sym]
        return (f'Monophthong risk — sustain {mono} as a pure vowel. '
                f'Resist the tendency to add a {spurious} glide-off '
                f'at the end of the note; that diphthongization is a speech '
                f'habit that muddies sustained tones.')
    return None


def _check_h_aspiration(pron: str) -> Optional[str]:
    """Flag word-initial /h/ — relevant at high pitch where aspiration can
    cause audible pre-phonation breath leak before the vowel onset.
    """
    stripped = pron.lstrip('ˈˌ')
    if stripped.startswith('h'):
        return ('/h/ onset — at high pitch, under-aspirate: '
                'bring the cords to closure before releasing the breath '
                'so the vowel onset is clean rather than breathy. '
                'Coordinate sub-glottal pressure with glottal closure '
                'rather than puffing air before the tone.')
    return None


# Every non-onset tip type compute_word_tips can emit. Used as the default
# "all hints on" set for call sites (e.g. auxiliary panels) that don't carry
# the user's live hint toggles.
ALL_HINT_TYPES = frozenset({
    'legato', 'vowel_glide', 'crash', 'r_toxicity', 'dark_l',
    'plosive', 'nasal', 'approx', 'fricative',
    'yod', 'ng_release', 'diphthong', 'aspiration',
})


def compute_word_tips(pron, next_ipa, has_punct_boundary, song_style, enabled):
    """Single source of truth for a word's diction tips.

    Returns an ordered list of (tip_type, tip_text). The first entry is the
    primary boundary/exit tip; any remaining entries are supplementary notes
    that stack on top of it (r-toxicity, yod, /ŋ/, spurious diphthong, /h/).

    An empty list means no primary tip fired — the caller may choose to show a
    phrase-initial glottal/onset note instead. Both the inline lyric
    annotations (and therefore the cheat-sheet export) and the click-to-view
    word detail panel route through this function so all three views agree.
    """
    if enabled is None:
        enabled = ALL_HINT_TYPES

    trailing  = ipa_trailing_consonants(pron)
    end_vowel = ipa_ends_with_vowel(pron)
    nlv = ipa_leading_vowel(next_ipa) if (next_ipa and not has_punct_boundary) else None
    nlc = ipa_leading_consonant(next_ipa) if (next_ipa and not has_punct_boundary) else None
    plosives   = [c for c in trailing if c in IPA_PLOSIVES]
    nasals     = [c for c in trailing if c in IPA_NASALS]
    approx     = [c for c in trailing if c in IPA_APPROXIMANTS]
    rhotics    = [c for c in trailing if c in IPA_RHOTIC]
    fricatives = [c for c in trailing if c in IPA_FRICATIVES]
    has_rhotic_vowel = any(s in ('ɚ', 'ɝ') for s, _, _ in find_syllable_vowels(pron))

    tip_type = tip = None
    r_tip = None  # may stack with the primary boundary tip

    # 1. Legato (consonant end -> next vowel start, no punct)
    if trailing and nlv is not None:
        cd = ' '.join(f'/{c}/' for c in trailing)
        tip = (f'Legato — carry {cd} into the opening /{nlv}/ '
               f'of the next word. Keep the breath connected.')
        tip_type = 'legato'
    # 2. Vowel-to-vowel glide (word ends on vowel, next starts vowel)
    elif end_vowel is not None and nlv is not None:
        glide = '/j/' if end_vowel in _GLIDE_J else '/w/'
        tip = (f'Vowel-to-vowel — insert a soft {glide} glide to avoid '
               f'a glottal stop before /{nlv}/. Keep airflow open.')
        tip_type = 'vowel_glide'
    # 3. Consonant crash
    elif trailing and nlc is not None:
        crash = consonant_crash_tip(trailing, nlc)
        if crash:
            tip, tip_type = crash, 'crash'

    # 4. R toxicity — stacks with the boundary tip; becomes primary if none yet
    if (rhotics or has_rhotic_vowel) and 'r_toxicity' in enabled:
        r_tip = ('American R — de-rhotacize: release the tongue curl/bunch '
                 'before the note sustains. Sustain on the base vowel '
                 '(ə or ɜ) instead of the r-colored form.')
        if tip_type is None:
            tip = r_tip
            tip_type = 'r_toxicity'
            r_tip = None

    # 5. Dark L — trailing /l/ not already captured; skipped in MT/CCM
    if tip_type is None and trailing and trailing[-1] == 'l' and song_style != 'mt_ccm':
        tip = ('Dark L exit \u2014 keep the tongue tip on the alveolar '
               'ridge. Do not pull the tongue root back; that '
               'swallows the resonance and darkens the sound.')
        tip_type = 'dark_l'

    # 6. Consonant exit fallback (no boundary interaction found above)
    if tip_type is None:
        if plosives:
            s = ' '.join(f'/{c}/' for c in plosives)
            tip = f'Plosive exit {s} — snap off cleanly, no shadow vowel.'
            tip_type = 'plosive'
        elif nasals:
            s = ' '.join(f'/{c}/' for c in nasals)
            tip = f'Nasal exit {s} — sustain the vowel; place the nasal late and short.'
            tip_type = 'nasal'
        elif approx and not rhotics:
            s = ' '.join(f'/{c}/' for c in approx)
            tip = f'Approximant exit {s} — gentle release, no hard cutoff.'
            tip_type = 'approx'
        elif fricatives:
            s = ' '.join(f'/{c}/' for c in fricatives)
            tip = f'Fricative exit {s} — control the airstream.'
            tip_type = 'fricative'

    # No primary tip (or its type is disabled) -> caller may show glottal onset.
    # Matches the engine: supplementary tips only stack on top of a primary.
    if tip_type is None or tip_type not in enabled:
        return []

    out = [(tip_type, tip)]
    if r_tip:
        out.append(('r_toxicity', r_tip))

    # 7. Supplementary word-level tips (stack freely with the boundary tip)
    if 'yod' in enabled:
        yod = _check_yod_coalescence(pron, next_ipa)
        if yod:
            out.append(('yod', yod))
    if 'ng_release' in enabled:
        ng = _check_ng_release(pron)
        if ng:
            out.append(('ng_release', ng))
    if 'diphthong' in enabled:
        dt = _check_spurious_diphthong(pron)
        if dt:
            out.append(('diphthong', dt))
    if 'aspiration' in enabled:
        asp = _check_h_aspiration(pron)
        if asp:
            out.append(('aspiration', asp))
    return out


# Background tints — the PRIMARY at-a-glance signal. The earlier tints were
# near-black and barely separated from the editor's dark navy (#1c2230). Each
# type now has its own shade, but shades are grouped into three hue bands so the
# *family* still reads instantly across the page while individual types remain
# distinguishable up close. All stay dark enough that the light text (#d8dfe8)
# is readable on top (contrast >= 4:1).
#   caution/avoid -> wine-red band  ·  release/exit -> teal band  ·  transition -> amber band
ANN_BG = {
    # caution / things to avoid  — wine-red band
    'r_toxicity':  '#751f2a',   # boldest red — strongest warning
    'crash':       '#7c2d32',
    'glottal':     '#722c43',
    'aspiration':  '#763a2e',
    'dark_l':      '#562e36',
    # consonant release / exit  — teal band
    'ng_release':  '#1c594d',
    'plosive':     '#24655f',
    'nasal':       '#2c6d57',
    'fricative':   '#295d65',
    'approx':      '#2f6a4b',
    # transition / glide / link  — amber band
    'yod':         '#5b4725',
    'legato':      '#6f571f',
    'diphthong':   '#744a25',
    'vowel_glide': '#776928',
}
# Foreground underline colors
ANN_COLOR = {
    'legato':      '#c8a060',
    'vowel_glide': '#90c878',
    'crash':       '#d08060',
    'r_toxicity':  '#e05050',
    'dark_l':      '#8898c8',
    'glottal':     '#a888c8',
    'plosive':     '#c06878',
    'nasal':       '#78b8a0',
    'approx':      '#7898d0',
    'fricative':   '#9878b0',
    'yod':         '#c8b848',
    'ng_release':  '#68c898',
    'diphthong':   '#c878a8',
    'aspiration':  '#78a8c8',
}


# Underline *style* per tip family. Color alone is hard to read at a glance
# (several categories share a red/orange hue), so the line shape encodes the
# pedagogical intent: wavy = caution/avoid, dotted = consonant release/exit,
# dashed = transition/glide/link. Color then disambiguates within a family.
ANN_UNDERLINE_STYLE = {
    # caution / things to avoid -> wavy
    'r_toxicity':  QTextCharFormat.WaveUnderline,
    'crash':       QTextCharFormat.WaveUnderline,
    'glottal':     QTextCharFormat.WaveUnderline,
    'aspiration':  QTextCharFormat.WaveUnderline,
    'dark_l':      QTextCharFormat.WaveUnderline,
    # consonant release / exit -> dotted
    'plosive':     QTextCharFormat.DotLine,
    'nasal':       QTextCharFormat.DotLine,
    'fricative':   QTextCharFormat.DotLine,
    'approx':      QTextCharFormat.DotLine,
    'ng_release':  QTextCharFormat.DotLine,
    # transition / glide / link -> dashed
    'legato':      QTextCharFormat.DashUnderline,
    'vowel_glide': QTextCharFormat.DashUnderline,
    'diphthong':   QTextCharFormat.DashUnderline,
    'yod':         QTextCharFormat.DashUnderline,
}

# Module-level cache for plain dictionary lookups (no custom IPA).
# Custom IPA is layered on top in get_pronunciations().
_DICT_CACHE: dict = {}


def dedupe_pronunciations(items):
    seen, out = set(), []
    for s in items:
        key = s.replace('ˈ', '').replace('ˌ', '')
        if key and key not in seen:
            seen.add(key)
            out.append(s)
    return out


def get_pronunciations(word: str, custom_ipa: Optional[dict] = None):
    word_l = word.lower()
    if custom_ipa and word_l in custom_ipa:
        # Strip surrounding slashes in case the user stored them (e.g. /valʒɑ̃/)
        return [custom_ipa[word_l].strip('/').replace('ː', '')]
    if word_l in FUNCTION_WORDS:
        return FUNCTION_WORDS[word_l].copy()

    if word_l in _DICT_CACHE:
        return _DICT_CACHE[word_l]
    raw = ipa.convert(word_l, retrieve_all=True) or []
    cleaned = [p.replace('ː', '') for p in raw if p and '*' not in p]

    if not cleaned and ("'" in word_l or '\u2019' in word_l or '\u2018' in word_l):
        stripped = word_l.replace("'", '').replace('\u2019', '').replace('\u2018', '')
        raw = ipa.convert(stripped, retrieve_all=True) or []
        cleaned = [p.replace('ː', '') for p in raw if p and '*' not in p]

    result = dedupe_pronunciations(cleaned)
    _DICT_CACHE[word_l] = result
    return result


def pronunciation_brightness(p: str) -> float:
    items = find_syllable_vowels(p)
    if not items:
        return 0.5
    return sum(brightness(s) for s, _, _ in items) / len(items)


def label_alternatives(items):
    if len(items) <= 1:
        return [(p, '') for p in items]
    scored = [(p, pronunciation_brightness(p)) for p in items]
    bmax = max(s for _, s in scored)
    bmin = min(s for _, s in scored)
    if bmax - bmin < 0.10:
        return [(p, '') for p, _ in scored]
    out = []
    for p, s in scored:
        if s >= bmax - 0.02:
            out.append((p, 'brighter'))
        elif s <= bmin + 0.02:
            out.append((p, 'darker'))
        else:
            out.append((p, ''))
    return out


# =============================================================================
# IPA HTML rendering — keeps stress markers, highlights vowels
# =============================================================================

COLOR_VOWEL = '#7898d0'
COLOR_STRESS = '#687890'


def render_ipa_html(p: str, highlight_token: Optional[str] = None,
                    highlight_index: int = -1) -> str:
    items = find_syllable_vowels(p)
    parts = ['/']
    last = 0
    for idx, (sym, s, e) in enumerate(items):
        pre = p[last:s]
        for ch in pre:
            if ch in ('ˈ', 'ˌ'):
                parts.append(
                    f'<span style="color:{COLOR_STRESS};'
                    f'font-weight:bold">{ch}</span>')
            else:
                parts.append(html.escape(ch))
        is_selected = (sym == highlight_token and idx == highlight_index)
        if is_selected:
            parts.append(
                f'<span style="color:#1c2230;background-color:{COLOR_VOWEL};'
                f'font-weight:bold;padding:0 4px;border-radius:3px">'
                f'{html.escape(sym)}</span>')
        else:
            parts.append(
                f'<span style="color:{COLOR_VOWEL};font-weight:bold">'
                f'{html.escape(sym)}</span>')
        last = e
    parts.append(html.escape(p[last:]))
    parts.append('/')
    return ''.join(parts)


# =============================================================================
# SVG chart
# =============================================================================

def create_vowel_chart_svg(highlight: Optional[str] = None) -> str:
    dwg = svgwrite.Drawing(
        profile='full', size=('100%', '100%'),
        viewBox='-65 -70 390 425',
        preserveAspectRatio='xMidYMid meet')

    marker = dwg.marker(insert=(5, 3), size=(7, 6), orient='auto',
                        id='mod-arrow')
    marker.add(dwg.path(d='M0,0 L6,3 L0,6 z', fill='#a8c8e8'))
    dwg.defs.add(marker)

    marker2 = dwg.marker(insert=(5, 3), size=(7, 6), orient='auto',
                         id='glide-arrow')
    marker2.add(dwg.path(d='M0,0 L6,3 L0,6 z', fill='#d8dfe8'))
    dwg.defs.add(marker2)

    grad = dwg.linearGradient(start=(0, 0), end=(1, 0), id='bg-bright')
    grad.add_stop_color(0.0, '#d8a878', opacity=0.32)
    grad.add_stop_color(0.5, '#5a607a', opacity=0.15)
    grad.add_stop_color(1.0, '#4878a8', opacity=0.32)
    dwg.defs.add(grad)

    dwg.add(dwg.polygon(points=[(0, 0), (250, 0), (250, 300), (50, 300)],
                        fill='url(#bg-bright)',
                        stroke='#5a6478', stroke_width=1.5))

    for s, e in [((17, 100), (250, 100)),
                 ((34, 200), (250, 200)),
                 ((125, 0), (150, 300))]:
        dwg.add(dwg.line(start=s, end=e, stroke='#3a4258', stroke_width=0.6,
                         stroke_dasharray='2,3'))

    for sym, v in VOWELS.items():
        if sym in ('ɚ', 'ɝ'):   # same coords as ə/ɜ; skip to avoid double-rendering
            continue
        dx = 8 if v.rounded else -8
        dwg.add(dwg.text(sym, insert=(v.x + dx, v.y + 5),
                         text_anchor='middle',
                         font_family='Charis SIL, Doulos SIL, Calibri, serif',
                         font_size='16', fill='#b8c0d0'))

    for x, txt in [(25, 'front'), (137, 'central'), (250, 'back')]:
        dwg.add(dwg.text(txt, insert=(x, -28), text_anchor='middle',
                         font_size='12', fill='#7888a0',
                         font_family='Inter, Segoe UI, sans-serif',
                         letter_spacing='1'))
    for y, txt in [(0, 'close'), (150, 'mid'), (300, 'open')]:
        dwg.add(dwg.text(txt, insert=(-18, y + 4), text_anchor='end',
                         font_size='12', fill='#7888a0',
                         font_family='Inter, Segoe UI, sans-serif'))

    if highlight in DIPHTHONGS:
        d = DIPHTHONGS[highlight]
        if d.primary in VOWELS and d.glide in VOWELS:
            pv = VOWELS[d.primary]
            gv = VOWELS[d.glide]
            pdx = 8 if pv.rounded else -8
            gdx = 8 if gv.rounded else -8
            pcx, pcy = pv.x + pdx, pv.y
            gcx, gcy = gv.x + gdx, gv.y

            ddx, ddy = gcx - pcx, gcy - pcy
            dist = math.hypot(ddx, ddy)
            if dist > 0:
                sx = pcx + 20 * ddx / dist
                sy = pcy + 20 * ddy / dist
                ex = gcx - 12 * ddx / dist
                ey = gcy - 12 * ddy / dist
                mx, my = (sx + ex) / 2, (sy + ey) / 2
                perp_x, perp_y = -ddy / dist, ddx / dist
                cx_q, cy_q = mx + perp_x * 18, my + perp_y * 18
                dwg.add(dwg.path(
                    d=f'M {sx},{sy} Q {cx_q},{cy_q} {ex},{ey}',
                    fill='none', stroke='#d8dfe8', stroke_width=2.2,
                    opacity=0.85, marker_end='url(#glide-arrow)'))

            dwg.add(dwg.circle(center=(gcx, gcy), r=13,
                               fill='#1c2230', stroke='#d8dfe8',
                               stroke_width=1.8, opacity=0.85))
            dwg.add(dwg.text(d.glide, insert=(gcx, gcy + 5),
                             text_anchor='middle',
                             font_family='Charis SIL, Doulos SIL, serif',
                             font_size='14', fill='#d8dfe8'))

            dwg.add(dwg.circle(center=(pcx, pcy), r=20,
                               fill='#7898d0', stroke='#a8c8e8',
                               stroke_width=2))
            dwg.add(dwg.text(d.primary, insert=(pcx, pcy + 7),
                             text_anchor='middle',
                             font_family='Charis SIL, Doulos SIL, serif',
                             font_size='22', font_weight='bold',
                             fill='#1c2230'))

            label_x = (pcx + gcx) / 2
            label_y = max(pcy, gcy) + 30
            dwg.add(dwg.text('sustain → vanish',
                             insert=(label_x, label_y),
                             text_anchor='middle', font_size='10',
                             fill='#98a8c0',
                             font_family='Inter, sans-serif',
                             letter_spacing='1', font_style='italic'))

    elif highlight in VOWELS:
        v = VOWELS[highlight]
        dx = 8 if v.rounded else -8
        cx, cy = v.x + dx, v.y

        if v.mod_high and v.mod_high in VOWELS and v.mod_high != highlight:
            m = VOWELS[v.mod_high]
            mdx = 8 if m.rounded else -8
            tx, ty = m.x + mdx, m.y
            ddx, ddy = tx - cx, ty - cy
            dist = math.hypot(ddx, ddy)
            if dist > 0:
                sx = cx + 20 * ddx / dist
                sy = cy + 20 * ddy / dist
                ex = tx - 11 * ddx / dist
                ey = ty - 11 * ddy / dist
                dwg.add(dwg.line(start=(sx, sy), end=(ex, ey),
                                 stroke='#a8c8e8', stroke_width=2,
                                 stroke_dasharray='4,3', opacity=0.75,
                                 marker_end='url(#mod-arrow)'))
                dwg.add(dwg.circle(center=(tx, ty), r=12,
                                   fill='#1c2230', stroke='#a8c8e8',
                                   stroke_width=1.4, opacity=0.7))

        dwg.add(dwg.circle(center=(cx, cy), r=20,
                           fill='#7898d0', stroke='#a8c8e8', stroke_width=2))
        dwg.add(dwg.text(highlight, insert=(cx, cy + 7),
                         text_anchor='middle',
                         font_family='Charis SIL, Doulos SIL, serif',
                         font_size='22', font_weight='bold',
                         fill='#1c2230'))

    stream = StringIO()
    dwg.write(stream)
    return stream.getvalue()


# =============================================================================
# Save / load
# =============================================================================

@dataclass
class Song:
    name: str = 'New Song'
    lyrics: str = ''
    custom_ipa: dict = field(default_factory=dict)
    pron_choices: dict = field(default_factory=dict)  # word -> preferred pron index
    dismissed_tips: set = field(default_factory=set)  # words whose inline hint is dismissed
    style: str = 'classical'  # 'classical' | 'mt_ccm'
    sustained_words: set = field(default_factory=set)  # words marked as sustained
    coaching_notes: list = field(default_factory=list)  # list[CoachingNote]

    def _present_words(self):
        """Set of lowercase words currently in the lyrics."""
        return {m.group().lower() for m in WORD_RE.finditer(self.lyrics)}

    def to_dict(self):
        pw = self._present_words()
        # pron_choices keys are either a plain lowercase word (legacy / word-level
        # default) or an occurrence key "word#N" (N = 0-based index of that word
        # among all its occurrences in the lyrics). Keep a key only if its base
        # word is still present and, for occurrence keys, the index is still valid.
        counts: dict = {}
        for m in WORD_RE.finditer(self.lyrics):
            wl = m.group().lower()
            counts[wl] = counts.get(wl, 0) + 1

        def keep_pron(k: str) -> bool:
            if '#' in k:
                base, _, idx = k.partition('#')
                if base not in counts:
                    return False
                try:
                    return int(idx) < counts[base]
                except ValueError:
                    return base in pw
            return k in pw

        return {'name': self.name, 'lyrics': self.lyrics,
                'custom_ipa': {k: v for k, v in self.custom_ipa.items() if k in pw},
                'pron_choices': {k: v for k, v in self.pron_choices.items() if keep_pron(k)},
                'dismissed_tips': [w for w in self.dismissed_tips if w in pw],
                'style': self.style,
                'sustained_words': [w for w in self.sustained_words if w in pw],
                'coaching_notes': [
                    {'start': n.anchor_start, 'end': n.anchor_end,
                     'text': n.text, 'anchor': n.anchor_text}
                    for n in self.coaching_notes
                ]}

    @classmethod
    def from_dict(cls, d):
        return cls(name=d.get('name', 'Untitled'),
                   lyrics=d.get('lyrics', ''),
                   custom_ipa=dict(d.get('custom_ipa', {})),
                   pron_choices=dict(d.get('pron_choices', {})),
                   dismissed_tips=set(d.get('dismissed_tips', [])),
                   style=d.get('style', 'classical'),
                   sustained_words=set(d.get('sustained_words', [])),
                   coaching_notes=[
                       CoachingNote(
                           d2.get('start', ''),
                           d2.get('end', ''),
                           d2.get('text', ''),
                           d2.get('anchor', ''))
                       for d2 in d.get('coaching_notes', [])
                   ])


class SongStore:
    def __init__(self, app_data_dir: str):
        self.dir = app_data_dir
        self.path = os.path.join(app_data_dir, 'songs.json')

    def load(self):
        if not os.path.exists(self.path):
            return [Song(name='Untitled')], 0
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            songs = [Song.from_dict(s) for s in data.get('songs', [])]
            active = max(0, min(data.get('active_index', 0),
                                max(0, len(songs) - 1)))
            return (songs or [Song(name='Untitled')]), active
        except (json.JSONDecodeError, IOError, KeyError):
            return [Song(name='Untitled')], 0

    def save(self, songs, active_index: int):
        try:
            os.makedirs(self.dir, exist_ok=True)
            data = {
                'songs': [s.to_dict() for s in songs],
                'active_index': active_index,
            }
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            # Rolling one-file backup: copy existing songs.json → songs.bak.json
            # before the atomic replace so a bad write never loses all data.
            bak = os.path.join(self.dir, 'songs.bak.json')
            if os.path.exists(self.path):
                try:
                    import shutil as _shutil
                    _shutil.copy2(self.path, bak)
                except OSError:
                    pass
            os.replace(tmp, self.path)  # atomic on Windows and POSIX
        except (IOError, OSError) as e:
            print(f'Warning: failed to save songs: {e}', file=sys.stderr)


# =============================================================================
# QSS theme — built dynamically so px values scale with DPI
# =============================================================================

def build_style(dpr: float, ui_scale: float = 1.0) -> str:
    """Return the full QSS stylesheet.

    *ui_scale* is the user-controlled scale factor (0.25–2.0).  All logical
    sizes in the stylesheet — fonts, padding, borders, radii — are multiplied
    by it, so the whole text/layout shrinks or grows together.

    *dpr* is accepted for call-site compatibility but is not used inside the
    function.  With ``AA_EnableHighDpiScaling`` enabled, Qt automatically
    scales stylesheet logical-pixel values by the device pixel ratio, so
    we must express sizes in logical pixels only and let Qt handle the rest.
    Multiplying by DPR here would cause double-scaling on HiDPI screens.
    """

    def px(n: float) -> str:
        """Structural size in logical pixels, scaled by the user's preference."""
        return f'{max(1, round(n * ui_scale))}px'

    def fs(n: float) -> str:
        """Font size in logical pixels, scaled by the user's preference."""
        return f'{max(1, round(n * ui_scale))}px'

    return f"""
QMainWindow, QWidget {{
    background-color: #14181f;
    color: #d8dfe8;
    font-family: 'Inter', 'Segoe UI', sans-serif;
    font-size: {fs(13)};
}}
QTextEdit, QPlainTextEdit {{
    background-color: #1c2230;
    border: {px(1)} solid #2c344a;
    border-radius: {px(6)};
    padding: {px(14)};
    selection-background-color: #7898d0;
    selection-color: #14181f;
    font-family: 'Charis SIL', 'Georgia', serif;
    font-size: {fs(17)};
}}
QScrollArea {{ background-color: transparent; border: none; }}
QPushButton {{
    background-color: #1c2230;
    border: {px(1)} solid #3a4258;
    border-radius: {px(4)};
    padding: {px(8)} {px(16)};
    color: #d8dfe8;
    font-size: {fs(13)};
}}
QPushButton:hover {{ background-color: #283044; border-color: #7898d0; }}
QPushButton:pressed {{ background-color: #344058; }}
QPushButton:disabled {{ color: #4a5670; border-color: #1c2230; }}

QPushButton[role="vowel"] {{
    background-color: #1c2230;
    border: {px(1)} solid #4a5670;
    border-radius: {px(24)};
    min-width: {px(48)}; max-width: {px(48)};
    min-height: {px(48)}; max-height: {px(48)};
    font-family: 'Charis SIL', 'Doulos SIL', serif;
    font-size: {fs(20)};
    font-weight: bold;
    padding: 0;
}}
QPushButton[role="vowel"]:hover {{ border-color: #a8c8e8; }}
QPushButton[role="vowel"]:checked {{
    background-color: #7898d0;
    color: #14181f;
    border-color: #a8c8e8;
}}

QPushButton[role="alt"] {{
    text-align: left;
    padding: {px(10)} {px(16)};
    background-color: #1c2230;
    border: {px(1)} solid #2c344a;
    border-left: {px(4)} solid #3a4258;
    border-radius: {px(4)};
    font-family: 'Charis SIL', 'Doulos SIL', serif;
    font-size: {fs(16)};
}}
QPushButton[role="alt"][tag="brighter"] {{ border-left-color: #d8a878; }}
QPushButton[role="alt"][tag="darker"]   {{ border-left-color: #4878a8; }}
QPushButton[role="alt"][selected="true"] {{
    background-color: #283044;
    border-color: #7898d0;
}}
QPushButton[role="alt"][selected="true"][tag="darker"] {{
    border-color: #4878a8;
}}

QLabel#WordLabel {{
    font-size: {fs(30)};
    font-weight: bold;
    color: #a8c8e8;
    font-family: 'Charis SIL', 'Georgia', serif;
}}
QLabel#IpaLabel {{
    font-size: {fs(26)};
    color: #d8dfe8;
    font-family: 'Charis SIL', 'Doulos SIL', serif;
    padding: {px(2)} 0;
}}
QLabel#PanelTitle {{
    color: #6878a0;
    font-size: {fs(11)};
    font-weight: bold;
    letter-spacing: {px(2)};
}}
QLabel#Caption {{
    color: #98a8c0;
    font-size: {fs(12)};
    font-style: italic;
}}
QFrame#ArticulationCard {{
    background-color: #1c2230;
    border: {px(1)} solid #2c344a;
    border-radius: {px(6)};
}}
QLabel#CardTitle {{
    color: #a8c8e8;
    font-size: {fs(17)};
    font-weight: bold;
    font-family: 'Charis SIL', serif;
}}
QLabel#CardLine {{ color: #98a8c0; font-size: {fs(14)}; }}
QLabel#CardNotes {{
    color: #c8d0dc;
    font-size: {fs(14)};
    font-style: italic;
    padding-top: {px(4)};
    line-height: 130%;
}}
QFrame#LadderStep {{
    background-color: #283044;
    border: {px(1)} solid #3a4258;
    border-radius: {px(5)};
}}
QFrame#LadderStep:hover {{ background-color: #344058; border-color: #7898d0; }}
QLabel#LadderSym {{
    font-family: 'Charis SIL', 'Doulos SIL', serif;
    font-size: {fs(26)};
    font-weight: bold;
    color: #a8c8e8;
    background: transparent;
    border: none;
}}
QLabel#LadderExample {{
    color: #98a8c0;
    font-size: {fs(12)};
    font-style: italic;
    background: transparent;
    border: none;
}}
QLabel#LadderArrow {{
    color: #4a5670;
    font-size: {fs(20)};
    min-width: {px(14)};
    max-width: {px(22)};
}}
QLabel#LadderAxis {{
    color: #4a5670;
    font-size: {fs(11)};
    font-style: italic;
    letter-spacing: {px(1)};
    padding-top: {px(4)};
}}
QComboBox {{
    background-color: #1c2230;
    border: {px(1)} solid #3a4258;
    border-radius: {px(4)};
    padding: {px(6)} {px(10)};
    color: #d8dfe8;
    min-width: {px(200)};
    font-size: {fs(14)};
    font-family: 'Charis SIL', 'Georgia', serif;
    font-weight: bold;
}}
QComboBox:hover {{ border-color: #7898d0; }}
QComboBox QAbstractItemView {{
    background-color: #1c2230;
    border: {px(1)} solid #3a4258;
    color: #d8dfe8;
    selection-background-color: #283044;
    selection-color: #a8c8e8;
    padding: {px(4)};
}}
QComboBox::drop-down {{ border: none; width: {px(24)}; }}
QComboBox::down-arrow {{
    image: none;
    border-left: {px(4)} solid transparent;
    border-right: {px(4)} solid transparent;
    border-top: {px(6)} solid #7898d0;
    margin-right: {px(8)};
}}
QLineEdit {{
    background-color: #1c2230;
    border: {px(1)} solid #3a4258;
    border-radius: {px(4)};
    padding: {px(6)} {px(10)};
    color: #d8dfe8;
    font-size: {fs(14)};
    selection-background-color: #7898d0;
    selection-color: #14181f;
}}
QLineEdit:focus {{ border-color: #7898d0; }}
QSplitter::handle {{ background-color: #1c2230; width: {px(1)}; }}
QMenuBar {{ background-color: #14181f; color: #98a8c0; font-size: {fs(13)}; }}
QMenuBar::item:selected {{ background-color: #283044; }}
QMenu {{
    background-color: #1c2230;
    border: {px(1)} solid #2c344a;
    color: #d8dfe8;
    font-size: {fs(13)};
}}
QMenu::item {{ padding: {px(7)} {px(24)}; }}
QMenu::item:selected {{ background-color: #283044; }}
QMenu::separator {{ height: {px(1)}; background-color: #2c344a; margin: {px(4)} 0; }}
QScrollBar:vertical {{ background: #14181f; width: {px(10)}; border: none; }}
QScrollBar::handle:vertical {{
    background: #283044; border-radius: {px(5)}; min-height: {px(30)};
}}
QScrollBar::handle:vertical:hover {{ background: #3a4258; }}
QScrollBar::add-line, QScrollBar::sub-line {{ background: none; border: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QDialog {{ background-color: #14181f; }}
QLabel#ChiaroscuroTip {{
    color: #a8a080;
    font-size: {fs(11)};
    font-style: italic;
    padding-top: {px(2)};
}}

QPushButton#HintsToggle, QToolButton#HintsToggle {{
    background-color: #1c2230;
    border: {px(1)} solid #3a4258;
    border-radius: {px(4)};
    padding: {px(4)} {px(10)};
    color: #6878a0;
    font-size: {fs(11)};
    font-weight: bold;
    letter-spacing: {px(1)};
}}
QPushButton#HintsToggle:hover, QToolButton#HintsToggle:hover {{ border-color: #c8a060; color: #c8a060; }}
QPushButton#HintsToggle:checked, QToolButton#HintsToggle:checked {{
    background-color: #201a0a;
    border-color: #c8a060;
    color: #c8a060;
}}

QLabel#LegatoTip {{
    color: #c8a060;
    background-color: #1e1a10;
    border: {px(1)} solid #4a3a18;
    border-left: {px(3)} solid #c8a060;
    border-radius: {px(4)};
    font-size: {fs(12)};
    padding: {px(6)} {px(10)};
    line-height: 140%;
}}
QLabel#ConsonantTip {{
    color: #8898b0;
    background-color: #161c28;
    border: {px(1)} solid #2a3248;
    border-left: {px(3)} solid #4a6090;
    border-radius: {px(4)};
    font-size: {fs(12)};
    padding: {px(6)} {px(10)};
    line-height: 140%;
}}
QLabel#StressWarning {{
    color: #c89060;
    background-color: #1e1810;
    border: {px(1)} solid #4a3818;
    border-left: {px(3)} solid #c89060;
    border-radius: {px(4)};
    font-size: {fs(12)};
    padding: {px(6)} {px(10)};
    line-height: 140%;
}}
"""


def _blend_hex(base_hex: str, tint_hex: str, t: float) -> QColor:
    """Blend *base_hex* toward *tint_hex* by factor *t* (0.0 = base, 1.0 = tint)."""
    t = max(0.0, min(1.0, t))
    def _ch(h: str) -> tuple:
        h = h.lstrip('#')
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    br, bg, bb = _ch(base_hex)
    tr, tg, tb = _ch(tint_hex)
    return QColor(
        round(br + (tr - br) * t),
        round(bg + (tg - bg) * t),
        round(bb + (tb - bb) * t),
    )


# =============================================================================
# Widgets
# =============================================================================

class AspectRatioContainer(QWidget):
    """Wraps a child widget and letterboxes it to preserve a target aspect."""
    def __init__(self, child: QWidget, ratio: float):
        super().__init__()
        self._child = child
        self._ratio = ratio
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(child)
        child.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def resizeEvent(self, ev):
        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            super().resizeEvent(ev)
            return
        target_w_for_h = h * self._ratio
        if target_w_for_h <= w:
            margin = int((w - target_w_for_h) / 2)
            self.layout().setContentsMargins(margin, 0, margin, 0)
        else:
            target_h_for_w = w / self._ratio
            margin = int((h - target_h_for_w) / 2)
            self.layout().setContentsMargins(0, margin, 0, margin)
        super().resizeEvent(ev)


class LyricsEditor(QTextEdit):
    word_clicked = pyqtSignal(str, int, int)  # word, block_number, char_offset
    word_ipa_requested = pyqtSignal(str)
    content_changed = pyqtSignal()
    annotation_dismissed = pyqtSignal(str)   # word_lower
    word_sustain_toggled = pyqtSignal(str)    # word_lower

    def __init__(self):
        super().__init__()
        self._annotation_map = {}   # (block, start, end) -> WordAnnotation
        self._hint_opacity: float = 1.0
        self._last_annotations: list = []
        self.setMouseTracking(True)
        self.setPlaceholderText(
            "Paste lyrics here. Click any word to see its IPA, vowel chart, "
            "and singing tips.\n\n"
            "Right-click any word to set a custom IPA (useful for proper "
            "nouns like \"Valjean\" or prisoner numbers like \"24601\")."
        )
        self.textChanged.connect(self.content_changed.emit)

    def _word_at_cursor_pos(self, pos):
        cursor = self.cursorForPosition(pos)
        block = cursor.block()
        pos_in_block = cursor.positionInBlock()
        for m in WORD_RE.finditer(block.text()):
            if m.start() <= pos_in_block < m.end():
                return m.group(), block.blockNumber(), m.start()
        return None, -1, -1


    def set_annotations(self, annotations: list):
        """Apply background-tint + underline for all word annotations.
        Background tint is blended toward the editor base color by _hint_opacity
        (1.0 = full tint, 0.0 = invisible). Underlines are always solid at full
        color so the word remains flagged even at 0% opacity.
        """
        self._last_annotations = list(annotations)
        self._annotation_map = {
            (a.block, a.start, a.end): a for a in annotations
        }
        self._rebuild_extra_selections()

    def _rebuild_extra_selections(self):
        """Re-apply extra-selections using the current _hint_opacity."""
        _EDITOR_BASE = '#1c2230'
        selections = []
        for a in self._last_annotations:
            cur = QTextCursor(self.document())
            cur.setPosition(a.abs_start)
            cur.setPosition(a.abs_end, QTextCursor.KeepAnchor)
            fmt = QTextCharFormat()
            blended = _blend_hex(_EDITOR_BASE, a.bg_color, self._hint_opacity)
            fmt.setBackground(blended)
            fmt.setUnderlineStyle(
                ANN_UNDERLINE_STYLE.get(a.tip_type, QTextCharFormat.SingleUnderline))
            fmt.setUnderlineColor(QColor(a.color))
            sel = QTextEdit.ExtraSelection()
            sel.cursor = cur
            sel.format = fmt
            selections.append(sel)
        self.setExtraSelections(selections)

    def set_highlight_opacity(self, opacity: float):
        """Set hint-highlight opacity [0.0, 1.0] and re-draw existing annotations."""
        self._hint_opacity = max(0.0, min(1.0, opacity))
        self._rebuild_extra_selections()

    def clear_annotations(self):
        self._annotation_map = {}
        self._last_annotations = []
        self.setExtraSelections([])

    def _annotation_at_pos(self, pos):
        cur = self.cursorForPosition(pos)
        bn = cur.block().blockNumber()
        pip = cur.positionInBlock()
        for (b, s, e), ann in self._annotation_map.items():
            if b == bn and s <= pip <= e:
                return ann
        return None

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        ann = self._annotation_at_pos(event.pos())
        if ann:
            QToolTip.showText(event.globalPos(), ann.tip_text, self)
        else:
            QToolTip.hideText()

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            word, bn, offset = self._word_at_cursor_pos(event.pos())
            if word:
                self.word_clicked.emit(word.lower(), bn, offset)

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        word, _, _offset = self._word_at_cursor_pos(event.pos())
        ann = self._annotation_at_pos(event.pos())
        if word:
            menu.addSeparator()
            action = menu.addAction(f'Set custom IPA for "{word}"…')
            action.triggered.connect(
                lambda _, w=word: self.word_ipa_requested.emit(w.lower()))
        if ann:
            da = menu.addAction(f'Dismiss hint for "{ann.word}"')
            da.triggered.connect(
                lambda _, w=ann.word_lower: self.annotation_dismissed.emit(w))
        if word:
            menu.addSeparator()
            sa = menu.addAction(f'Toggle sustained note on "{word}"')
            sa.triggered.connect(
                lambda _, w=word.lower(): self.word_sustain_toggled.emit(w))
        menu.exec_(event.globalPos())

    def line_text(self, block_number: int) -> str:
        block = self.document().findBlockByNumber(block_number)
        return block.text() if block.isValid() else ''

    def insertFromMimeData(self, source):
        if source.hasText():
            text = source.text().replace('\r\n', '\n').replace('\r', '\n')
            self.insertPlainText(text)
        else:
            super().insertFromMimeData(source)


# =============================================================================
# Coaching Notes view — custom-painted read-only lyrics canvas with bubbles
# =============================================================================

class _NoteEditOverlay(QPlainTextEdit):
    """Floating inline editor placed over a coaching bubble while the user types.

    Emits ``commit_edit(True)`` on Ctrl+Enter or focus-out, and
    ``commit_edit(False)`` on Escape.  A ``_fired`` guard prevents the signal
    from firing more than once per instance.
    """
    commit_edit = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fired = False
        self.setFrameShape(QFrame.Box)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)

    def _fire(self, commit: bool):
        if not self._fired:
            self._fired = True
            self.commit_edit.emit(commit)

    def keyPressEvent(self, ev):
        k = ev.key()
        if k == Qt.Key_Escape:
            self._fire(False)
        elif k in (Qt.Key_Return, Qt.Key_Enter) and (ev.modifiers() & Qt.ControlModifier):
            self._fire(True)
        else:
            super().keyPressEvent(ev)

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        self._fire(True)   # focus-out → commit (empty → delete in _close_edit)


class CoachingView(QWidget):
    """Read-only lyrics canvas with speech-bubble coaching notes in gutters.

    Layout algorithm
    ----------------
    Lyrics are split on \\n into *blocks*.  Within each block, words are
    word-wrapped left-to-right.  After the last row of a block a *gutter* is
    reserved: each note whose resolved anchor_start falls in that block gets
    one bubble (rounded rect + upward connector triangle).  Bubbles stack
    vertically.  A minimal empty gutter keeps consistent vertical rhythm.

    HiDPI discipline
    ----------------
    * Font size comes from ``_font_pt`` (logical pt) — never multiplied by DPR.
    * All structural sizes (paddings, radii, triangle) go through ``_scale()``.
    * All text metrics come from ``QFontMetrics``.
    """

    notes_changed = pyqtSignal()
    word_clicked  = pyqtSignal(str, int, int)  # word_lower, block_number, char_offset

    # ── layout constants (raw logical px passed to _scale) ──────────────────
    _MARGIN      = 14   # left/right content margin
    _WORD_GAP    = 4    # horizontal gap between words on the same row
    _ROW_GAP     = 4    # extra vertical gap between wrapped rows inside a block
    _TEXT_GUTTER = 10   # gap from last text row to triangle apex
    _BUB_GAP     = 6    # vertical gap between successive bubbles in one gutter
    _BLOCK_GAP   = 20   # gap from end of gutter to start of next block's rows
    _GUT_EMPTY   = 6    # min gutter height when a block has no notes
    _BPAD_H      = 8    # horizontal text padding inside bubble
    _BPAD_V      = 5    # vertical text padding inside bubble
    _BRAD        = 6    # bubble corner radius
    _TRI_W       = 7    # connector triangle half-width
    _TRI_H       = 6    # connector triangle height
    _ACCENT_BAR  = 3    # width of accent left-border strip inside bubble

    _FOLD_SIZE   = 11   # dog-ear fold triangle size

    # ── theme (lyrics) ───────────────────────────────────────────────────────
    _C_BG     = '#14181f'
    _C_PANEL  = '#1c2230'
    _C_BORDER = '#2c344a'
    _C_TEXT   = '#d8dfe8'
    _C_MUTED  = '#98a8c0'
    _C_ACCENT = '#7898d0'

    # ── theme (post-it bubbles) ───────────────────────────────────────────────
    _C_BUB_BG      = '#f0e0a0'   # warm post-it yellow (paper face)
    _C_BUB_BORDER  = '#b89828'   # amber border visible on dark app bg
    _C_BUB_ACCENT  = '#7a5c00'   # dark amber left-bar (contrasts with yellow bg)
    _C_BUB_TEXT    = '#1c1a06'   # near-black ink on yellow

    def __init__(self):
        super().__init__()
        self._song: object = None
        self._lyrics: str = ''
        self._notes: list = []        # live reference to song.coaching_notes

        self._font_pt: int = 16       # synced from MainWindow._editor_font_size

        # layout cache (rebuilt by _relayout)
        self._word_infos:   list = []  # dicts: word, key, pw, h, x, y, bi
        self._bubble_infos: list = []  # dicts: note, rect, lines, tri_x, tri_y

        # interaction state
        self._press_word: object = None   # word-info dict at mouse-down
        self._hover_word: object = None   # word-info dict currently under cursor
        self._hovered_bubble_info: object = None   # bubble-info dict under cursor
        self._dragging: bool = False

        # edit-overlay state
        self._edit_note: object = None
        self._edit_is_new: bool = False
        self._edit_ov: object = None   # _NoteEditOverlay or None

        # undo stack (snapshot model — list of note-list snapshots)
        self._undo_stack: list = []
        self._UNDO_LIMIT = 50
        self._pending_undo = None   # pre-state for the open edit session, or None

        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.ClickFocus)
        self._total_h: int = _scale(100)

    # ── public API ───────────────────────────────────────────────────────────

    def set_song(self, song):
        self._close_edit(commit=True)
        # Reset undo history when switching to a different song.
        # Same-song refreshes (e.g. after import) must NOT clear the stack.
        if song is not self._song:
            self._undo_stack = []
        self._pending_undo = None
        self._song   = song
        self._lyrics = song.lyrics if song else ''
        self._notes  = song.coaching_notes if song else []
        self._relayout()

    def set_font_pt(self, pt: int):
        self._font_pt = pt
        self._relayout()

    def snapshot_notes(self) -> list:
        """Return a deep copy of the current notes list for undo."""
        return [CoachingNote(n.anchor_start, n.anchor_end, n.text, n.anchor_text)
                for n in self._notes]

    def push_undo(self, snapshot: list):
        """Push *snapshot* onto the undo stack, trimming at the limit."""
        self._undo_stack.append(snapshot)
        if len(self._undo_stack) > self._UNDO_LIMIT:
            del self._undo_stack[0]

    def undo(self) -> bool:
        """Pop the top snapshot and restore notes in-place.  Returns True on success."""
        if not self._undo_stack:
            return False
        self._close_edit(commit=False)   # abandon any open editor
        snap = self._undo_stack.pop()
        self._notes[:] = snap            # in-place → song.coaching_notes updates too
        self._relayout()
        self.notes_changed.emit()        # triggers autosave
        return True

    def clear_all_notes(self):
        """Delete all notes for the current song (undoable via Ctrl+Z)."""
        if not self._notes:
            return
        self.push_undo(self.snapshot_notes())
        self._notes[:] = []          # in-place so song.coaching_notes updates too
        self._relayout()
        self.notes_changed.emit()

    def sizeHint(self):
        from PyQt5.QtCore import QSize
        return QSize(max(200, self.width()), getattr(self, '_total_h', _scale(100)))

    # ── font ─────────────────────────────────────────────────────────────────

    def _font(self) -> QFont:
        return QFont('Inter', self._font_pt)

    def _bubble_font(self) -> QFont:
        """Bubble note font — Candara sits between Inter and handwritten."""
        return QFont('Candara', max(8, self._font_pt - 4))

    # ── layout ───────────────────────────────────────────────────────────────

    def _relayout(self):
        W = self.width()
        if W <= 10:
            self.update()
            return

        margin     = _scale(self._MARGIN)
        word_gap   = _scale(self._WORD_GAP)
        row_gap    = _scale(self._ROW_GAP)
        text_gut   = _scale(self._TEXT_GUTTER)
        bub_gap    = _scale(self._BUB_GAP)
        block_gap  = _scale(self._BLOCK_GAP)
        gut_empty  = _scale(self._GUT_EMPTY)
        bpad_h     = _scale(self._BPAD_H)
        bpad_v     = _scale(self._BPAD_V)
        tri_h      = _scale(self._TRI_H)
        tri_w      = _scale(self._TRI_W)
        acc_bar    = _scale(self._ACCENT_BAR)

        content_w  = max(_scale(60), W - 2 * margin)

        font  = self._font()
        fm    = QFontMetrics(font)
        lh    = fm.height()
        l_gap = _scale(2)   # gap between text lines inside a bubble

        bub_font = self._bubble_font()
        bfm      = QFontMetrics(bub_font)
        blh      = bfm.height()
        bl_gap   = _scale(2)

        blocks = self._lyrics.split('\n')

        # ── pass 1: tokenise words, assign keys ──────────────────────────────
        global_counts: dict = {}
        block_word_lists: list = []

        for block_text in blocks:
            wds: list = []
            for m in WORD_RE.finditer(block_text):
                wl = m.group().lower()
                n  = global_counts.get(wl, 0)
                global_counts[wl] = n + 1
                wds.append({
                    'word': m.group(),
                    'key':  f'{wl}#{n}',
                    'pw':   fm.horizontalAdvance(m.group()),
                    'h':    lh,
                    'co':   m.start(),   # char offset within the block/line
                })
            block_word_lists.append(wds)

        # ── pass 2: route notes to blocks ────────────────────────────────────
        key_to_bi: dict = {}
        for bi, wds in enumerate(block_word_lists):
            for wi in wds:
                key_to_bi[wi['key']] = bi

        block_notes: dict = {bi: [] for bi in range(len(blocks))}
        for note in self._notes:
            bi = key_to_bi.get(note.anchor_start)
            if bi is not None:
                block_notes[bi].append(note)

        # ── pass 3: assign positions ──────────────────────────────────────────
        self._word_infos   = []
        self._bubble_infos = []

        y = _scale(12)   # top padding

        for bi, (block_text, wds) in enumerate(zip(blocks, block_word_lists)):
            # --- word-wrap into rows ---
            rows: list = []
            cur_row: list = []
            cur_x = 0
            for raw_wi in wds:
                pw = raw_wi['pw']
                if cur_row and cur_x + word_gap + pw > content_w:
                    rows.append(cur_row)
                    cur_row = []
                    cur_x = 0
                wi = dict(raw_wi)   # copy so we can annotate with position
                wi['x']  = margin + cur_x
                wi['bi'] = bi
                cur_row.append(wi)
                cur_x += pw + word_gap
            if cur_row:
                rows.append(cur_row)

            # --- assign row y-positions ---
            row_y = y
            for row in rows:
                for wi in row:
                    wi['y'] = row_y
                self._word_infos.extend(row)
                row_y += lh + row_gap

            text_bottom = (row_y - row_gap) if rows else (y + lh)

            # --- build key→wi map for connector x-computation ----------------
            key_map: dict = {}
            for wi in self._word_infos:
                if wi.get('bi') == bi:
                    key_map[wi['key']] = wi

            # --- gutter -------------------------------------------------------
            notes_here = block_notes.get(bi, [])
            cur_bub_y  = text_bottom + text_gut  # apex y of first triangle row

            if not notes_here:
                y = cur_bub_y + gut_empty + block_gap
            else:
                # Per-note natural sizing then horizontal flow
                bub_single_max = min(W - margin, _scale(320))
                bub_min_w_     = _scale(50)
                flow_max_w     = W - margin   # row can extend to near right edge

                # Step 1 — compute each bubble's natural (content-fit) size
                sized = []
                for note in notes_here:
                    raw_w = (bfm.horizontalAdvance(note.text)
                             + 2 * bpad_h + acc_bar + _scale(10))
                    bub_w = max(bub_min_w_, min(raw_w, bub_single_max))
                    text_max_w = bub_w - 2 * bpad_h - acc_bar - _scale(4)
                    blines = _coaching_wrap_text(note.text, bfm, text_max_w)
                    bub_text_h = (len(blines) * blh
                                  + max(0, len(blines) - 1) * bl_gap)
                    bub_h = bub_text_h + 2 * bpad_v
                    sized.append((note, bub_w, bub_h, blines))

                # Step 2 — flow bubbles left-to-right, wrapping as needed
                row_x          = margin
                row_top_y      = cur_bub_y + tri_h
                tri_apex_row_y = cur_bub_y
                row_max_bot    = row_top_y   # tallest bubble bottom in cur row

                for note, bub_w, bub_h, blines in sized:
                    # Wrap to next row when this bubble won't fit
                    if row_x > margin and row_x + bub_w > flow_max_w:
                        row_top_y      = row_max_bot + bub_gap + tri_h
                        tri_apex_row_y = row_max_bot + bub_gap
                        row_x          = margin
                        row_max_bot    = row_top_y

                    bub_x = row_x
                    bub_y = row_top_y

                    # Triangle connector x — centre of anchor_start word
                    start_wi = key_map.get(note.anchor_start)
                    if start_wi:
                        raw_tri_x = start_wi['x'] + start_wi['pw'] // 2
                    else:
                        raw_tri_x = bub_x + bub_w // 2
                    tri_x = max(bub_x + tri_w + _scale(2),
                                min(raw_tri_x,
                                    bub_x + bub_w - tri_w - _scale(2)))

                    self._bubble_infos.append({
                        'note':        note,
                        'rect':        QRect(bub_x, bub_y, bub_w, bub_h),
                        'lines':       blines,
                        'tri_x':       tri_x,
                        'tri_apex_y':  tri_apex_row_y,
                    })

                    row_max_bot = max(row_max_bot, bub_y + bub_h)
                    row_x      += bub_w + bub_gap

                y = row_max_bot + block_gap

        self._total_h = y + _scale(12)
        self.setMinimumHeight(self._total_h)
        self.update()

    # ── painting ─────────────────────────────────────────────────────────────

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.fillRect(self.rect(), QColor(self._C_BG))

        if not self._lyrics:
            p.setPen(QColor(self._C_MUTED))
            p.setFont(self._font())
            p.drawText(self.rect(), Qt.AlignCenter,
                       'Switch to editor mode to enter lyrics,\n'
                       'then return here to add coaching notes.')
            return

        font = self._font()
        fm   = QFontMetrics(font)
        p.setFont(font)
        lh     = fm.height()
        bpad_h = _scale(self._BPAD_H)
        bpad_v = _scale(self._BPAD_V)
        brad   = _scale(self._BRAD)
        tri_h  = _scale(self._TRI_H)
        tri_w  = _scale(self._TRI_W)
        acc_bar = _scale(self._ACCENT_BAR)
        pad    = _scale(2)

        bub_font = self._bubble_font()
        bfm      = QFontMetrics(bub_font)
        blh      = bfm.height()
        bl_gap   = _scale(2)

        # ── determine the "active" note (being edited or hovered) ────────────
        active_note = None
        if self._edit_note is not None:
            active_note = self._edit_note
        elif self._hovered_bubble_info is not None:
            active_note = self._hovered_bubble_info['note']

        # ── collect keys by highlight tier ───────────────────────────────────
        # active_keys: span of the currently focused note (bright amber)
        # passive_keys: spans of all other notes (dim blue tint)
        active_keys:  set = set()
        passive_keys: set = set()

        def _span_keys(note):
            start_i = end_i = None
            for idx, wi in enumerate(self._word_infos):
                if wi['key'] == note.anchor_start and start_i is None:
                    start_i = idx
                if wi['key'] == note.anchor_end:
                    end_i = idx
            if start_i is not None and end_i is not None:
                lo = min(start_i, end_i)
                hi = max(start_i, end_i)
                return {self._word_infos[i]['key'] for i in range(lo, hi + 1)}
            return set()

        for bi_info in self._bubble_infos:
            note = bi_info['note']
            keys = _span_keys(note)
            if note is active_note:
                active_keys |= keys
            else:
                passive_keys |= keys

        # Active keys win over passive
        passive_keys -= active_keys

        # ── drag-selection highlight ──────────────────────────────────────────
        drag_keys: set = set()
        if self._dragging and self._press_word and self._hover_word:
            if self._press_word.get('bi') == self._hover_word.get('bi'):
                pi = next((i for i, w in enumerate(self._word_infos)
                           if w is self._press_word), None)
                hi_ = next((i for i, w in enumerate(self._word_infos)
                            if w is self._hover_word), None)
                if pi is not None and hi_ is not None:
                    lo = min(pi, hi_)
                    hi = max(pi, hi_)
                    for idx in range(lo, hi + 1):
                        drag_keys.add(self._word_infos[idx]['key'])

        # ── draw words ────────────────────────────────────────────────────────
        active_c  = QColor(self._C_BUB_ACCENT);  active_c.setAlpha(80)
        passive_c = QColor(self._C_ACCENT);       passive_c.setAlpha(45)
        drag_c    = QColor('#c0d0ff');             drag_c.setAlpha(40)

        for wi in self._word_infos:
            wr  = QRect(wi['x'] - pad, wi['y'],
                        wi['pw'] + 2 * pad, wi['h'])
            key = wi['key']
            if key in drag_keys:
                p.fillRect(wr, drag_c)
            elif key in active_keys:
                p.fillRect(wr, active_c)
            elif key in passive_keys:
                p.fillRect(wr, passive_c)
            p.setPen(QColor(self._C_TEXT))
            p.drawText(wi['x'], wi['y'], wi['pw'] + pad, wi['h'],
                       Qt.AlignLeft | Qt.AlignVCenter, wi['word'])

        # ── draw bubbles ──────────────────────────────────────────────────────
        c_bub_bg     = QColor(self._C_BUB_BG)
        c_bub_border = QColor(self._C_BUB_BORDER)
        c_bub_accent = QColor(self._C_BUB_ACCENT)
        c_bub_text   = QColor(self._C_BUB_TEXT)
        c_active_border = QColor(self._C_BUB_ACCENT).darker(130)

        # ruled lines: slightly darker than the yellow paper
        c_rule = QColor(self._C_BUB_BG).darker(118)
        c_rule.setAlpha(200)

        # dog-ear fold: face is lighter (like the paper backside); shadow is darker
        c_fold_face   = QColor('#fffde8')
        c_fold_shadow = QColor(self._C_BUB_BG).darker(128)

        fold_size = _scale(self._FOLD_SIZE)
        shadow_off = _scale(2)
        shadow_c = QColor(0, 0, 0, 45)

        for bi_info in self._bubble_infos:
            note       = bi_info['note']
            rect       = bi_info['rect']
            tri_x      = bi_info['tri_x']
            tri_apex_y = bi_info['tri_apex_y']
            lines      = bi_info['lines']
            is_active  = (note is active_note)

            border_c = c_active_border if is_active else c_bub_border

            # ── drop shadow ───────────────────────────────────────────────────
            shadow_rect = QRect(rect.left() + shadow_off,
                                rect.top() + shadow_off,
                                rect.width(), rect.height())
            p.setPen(Qt.NoPen)
            p.setBrush(shadow_c)
            p.drawRoundedRect(shadow_rect, brad, brad)

            # ── connector triangle ────────────────────────────────────────────
            tri_pts = QPolygon([
                QPoint(tri_x,         tri_apex_y),
                QPoint(tri_x - tri_w, rect.top()),
                QPoint(tri_x + tri_w, rect.top()),
            ])
            p.setPen(border_c)
            p.setBrush(c_bub_bg)
            p.drawPolygon(tri_pts)

            # ── bubble body ───────────────────────────────────────────────────
            p.setPen(border_c)
            p.setBrush(c_bub_bg)
            p.drawRoundedRect(rect, brad, brad)

            # ── paper grain texture (very subtle diagonal fibres) ─────────────
            grain_c = QColor('#4a3800')
            p.setOpacity(0.04)
            p.setPen(grain_c)
            grain_step = max(_scale(4), blh // 2)
            for gx in range(rect.left(), rect.right() + rect.height(), grain_step):
                p.drawLine(gx, rect.top(), gx - rect.height(), rect.bottom())
            p.setOpacity(1.0)

            # ── ruled notebook lines ──────────────────────────────────────────
            p.setPen(c_rule)
            rule_y = rect.top() + bpad_v + blh + bl_gap // 2
            rule_x1 = rect.left() + acc_bar + _scale(4)
            rule_x2 = rect.right() - _scale(4)
            while rule_y < rect.bottom() - _scale(3):
                p.drawLine(rule_x1, rule_y, rule_x2, rule_y)
                rule_y += blh + bl_gap

            # ── accent left-border strip ──────────────────────────────────────
            p.fillRect(QRect(rect.left() + _scale(1),
                             rect.top() + brad,
                             acc_bar,
                             rect.height() - 2 * brad),
                       c_bub_accent)

            # ── dog-ear fold (top-right corner) ──────────────────────────────
            # shadow triangle (slightly behind the fold)
            fold_shadow_pts = QPolygon([
                QPoint(rect.right() - fold_size + _scale(1), rect.top()),
                QPoint(rect.right(),                         rect.top() + fold_size - _scale(1)),
                QPoint(rect.right(),                         rect.top()),
            ])
            p.setPen(Qt.NoPen)
            p.setBrush(c_fold_shadow)
            p.drawPolygon(fold_shadow_pts)

            # fold face triangle
            fold_pts = QPolygon([
                QPoint(rect.right() - fold_size, rect.top()),
                QPoint(rect.right(),              rect.top() + fold_size),
                QPoint(rect.right(),              rect.top()),
            ])
            p.setBrush(c_fold_face)
            p.drawPolygon(fold_pts)

            # fold crease line
            p.setPen(border_c)
            p.drawLine(rect.right() - fold_size, rect.top(),
                       rect.right(),              rect.top() + fold_size)

            # ── bubble text (smaller font) ────────────────────────────────────
            p.setFont(bub_font)
            p.setPen(c_bub_text)
            tx = rect.left() + bpad_h + acc_bar
            ty = rect.top() + bpad_v
            tw = rect.width() - bpad_h - acc_bar - fold_size - _scale(2)
            for line in lines:
                p.drawText(tx, ty, tw, blh,
                           Qt.AlignLeft | Qt.AlignVCenter, line)
                ty += blh + bl_gap
            p.setFont(font)   # restore word font

        p.end()

    # ── hit-test helpers ──────────────────────────────────────────────────────

    def _word_at(self, pos) -> object:
        py, px = pos.y(), pos.x()
        fm  = QFontMetrics(self._font())
        lh  = fm.height()
        pad = _scale(4)
        for wi in self._word_infos:
            if (wi['x'] - pad <= px <= wi['x'] + wi['pw'] + pad
                    and wi['y'] - pad <= py <= wi['y'] + lh + pad):
                return wi
        return None

    def _bubble_at(self, pos) -> object:
        py, px = pos.y(), pos.x()
        for bi_info in self._bubble_infos:
            r = bi_info['rect']
            if r.contains(px, py):
                return bi_info
        return None

    # ── mouse events ──────────────────────────────────────────────────────────

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        # Note: any open overlay already received focusOutEvent → committed.
        bi_info = self._bubble_at(ev.pos())
        if bi_info:
            self._start_edit(bi_info['note'], is_new=False)
            return
        wi = self._word_at(ev.pos())
        if wi:
            # Emit word_clicked so the Analysis panel updates (additive, before note logic)
            self.word_clicked.emit(wi['word'].lower(), wi.get('bi', 0), wi.get('co', 0))
            self._press_word = wi
            self._hover_word = wi
            self._dragging   = False
            self.update()

    def mouseMoveEvent(self, ev):
        wi = self._word_at(ev.pos())
        self._hover_word = wi
        if self._press_word and wi and (ev.buttons() & Qt.LeftButton):
            if wi is not self._press_word:
                self._dragging = True
        # Update hovered bubble (only when not dragging a new span)
        if not self._dragging:
            self._hovered_bubble_info = self._bubble_at(ev.pos())
        self.update()

    def mouseReleaseEvent(self, ev):
        if ev.button() != Qt.LeftButton or self._press_word is None:
            self._press_word = None
            self._dragging   = False
            self._hovered_bubble_info = None
            self.update()
            return

        press    = self._press_word
        hover    = self._hover_word or press
        dragging = self._dragging

        self._press_word = None
        self._dragging   = False
        self._hovered_bubble_info = None
        self.update()
        if (dragging and hover is not press
                and hover.get('bi') == press.get('bi')):
            pi = next((i for i, w in enumerate(self._word_infos)
                       if w is press), None)
            hi_ = next((i for i, w in enumerate(self._word_infos)
                        if w is hover), None)
            if pi is not None and hi_ is not None:
                lo  = min(pi, hi_)
                hi  = max(pi, hi_)
                start_key = self._word_infos[lo]['key']
                end_key   = self._word_infos[hi]['key']
            else:
                start_key = end_key = press['key']
        else:
            start_key = end_key = press['key']

        # edit existing note at this exact span if it exists
        existing = next(
            (n for n in self._notes
             if n.anchor_start == start_key and n.anchor_end == end_key),
            None)
        if existing:
            self._start_edit(existing, is_new=False)
            return

        # create new note
        self._close_edit(commit=True)               # flush any prior session
        self._pending_undo = self.snapshot_notes()  # pre-create state (no new note yet)
        # Compute anchor_text from the span so the note can be re-matched later
        _span = resolve_anchor(self._lyrics, start_key, end_key)
        _anchor_text = self._lyrics[_span[0]:_span[1]] if _span else ''
        new_note = CoachingNote(
            anchor_start=start_key, anchor_end=end_key, text='',
            anchor_text=_anchor_text)
        self._notes.append(new_note)
        self._relayout()
        self._start_edit(new_note, is_new=True)     # internal flush is a no-op; won't overwrite pending

    def contextMenuEvent(self, ev):
        """Right-click a bubble → delete it immediately (undoable)."""
        bi_info = self._bubble_at(ev.pos())
        if not bi_info:
            return
        note = bi_info['note']
        self._close_edit(commit=True)
        if note in self._notes:
            self.push_undo(self.snapshot_notes())   # pre-delete snapshot
            self._notes.remove(note)
            self._relayout()
            self.notes_changed.emit()

    # ── edit overlay ──────────────────────────────────────────────────────────

    def _start_edit(self, note, is_new: bool):
        # Safety: commit any lingering edit (focus-out usually handles this
        # already, but guard for platform differences).
        self._close_edit(commit=True)

        self._edit_note   = note
        self._edit_is_new = is_new

        # Capture pre-state for existing notes so the edit can be undone.
        # For new notes the caller sets _pending_undo BEFORE appending, so
        # we must not overwrite it here.
        if not is_new:
            self._pending_undo = self.snapshot_notes()

        # find bubble rect (relayout first if note is freshly appended)
        bi_info = next((b for b in self._bubble_infos if b['note'] is note), None)
        if bi_info is None:
            self._relayout()
            bi_info = next(
                (b for b in self._bubble_infos if b['note'] is note), None)
        if bi_info is None:
            # still no rect → unresolved anchor; bail
            self._edit_note   = None
            self._edit_is_new = False
            return

        rect   = bi_info['rect']
        ov     = _NoteEditOverlay(self)
        bfont  = self._bubble_font()
        ov.setFont(bfont)
        ov.setStyleSheet(
            f"QPlainTextEdit {{"
            f" background-color: {self._C_BUB_BG};"
            f" color: {self._C_BUB_TEXT};"
            f" border: {max(1, _scale(1))}px solid {self._C_BUB_BORDER};"
            f" border-radius: {_scale(self._BRAD)}px;"
            f" padding: {_scale(self._BPAD_V)}px {_scale(self._BPAD_H)}px;"
            f" selection-background-color: {self._C_BUB_BORDER};"
            f" selection-color: {self._C_BUB_TEXT}; }}"
        )
        # Ensure the overlay is wide and tall enough to type comfortably.
        bfm    = QFontMetrics(bfont)
        min_w  = _scale(180)
        min_h  = bfm.height() * 3 + _scale(self._BPAD_V) * 2
        ov_w   = max(rect.width(),  min_w)
        ov_h   = max(rect.height(), min_h)
        # Clamp inside widget bounds
        ov_x   = max(0, min(rect.x(), self.width()  - ov_w))
        ov_y   = max(0, min(rect.y(), self.height() - ov_h))
        ov.setPlainText(note.text)
        ov.setGeometry(ov_x, ov_y, ov_w, ov_h)
        ov.commit_edit.connect(self._on_edit_done)
        ov.show()
        ov.raise_()
        ov.setFocus()
        if note.text:
            ov.selectAll()
        self._edit_ov = ov

    def _on_edit_done(self, commit: bool):
        self._close_edit(commit=commit)

    def _close_edit(self, *, commit: bool):
        ov = self._edit_ov
        if ov is None:
            return
        # Prevent re-entry: block the overlay's signals and set _fired flag.
        ov.blockSignals(True)
        ov._fired = True
        new_text = ov.toPlainText().strip()
        ov.hide()
        ov.deleteLater()
        self._edit_ov = None

        note   = self._edit_note
        is_new = self._edit_is_new
        self._edit_note   = None
        self._edit_is_new = False

        if note is None:
            return

        changed = False
        if commit:
            if new_text:
                if note.text != new_text:
                    note.text = new_text
                    changed = True
                elif is_new:
                    changed = True   # even if text unchanged, new note was added
            else:
                # empty → delete
                if note in self._notes:
                    self._notes.remove(note)
                    changed = True
        else:
            # cancel
            if is_new and note in self._notes:
                self._notes.remove(note)
                # Don't emit notes_changed for an abandoned new note

        # Commit or discard the pre-state captured before this edit session.
        if self._pending_undo is not None:
            if changed:
                self.push_undo(self._pending_undo)
            self._pending_undo = None

        self._relayout()
        if changed:
            self.notes_changed.emit()
        # Restore focus so Ctrl+Z works immediately after committing.
        self.setFocus()

    def keyPressEvent(self, ev):
        """Ctrl+Z undoes the last coaching-notes change (dedicated to this view;
        the lyrics QTextEdit keeps its own Ctrl+Z)."""
        if (ev.key() == Qt.Key_Z
                and (ev.modifiers() & Qt.ControlModifier)
                and not (ev.modifiers() & Qt.ShiftModifier)):
            if self.undo():
                return
        super().keyPressEvent(ev)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._relayout()
        # Keep edit overlay aligned if active
        if self._edit_ov and self._edit_note:
            bi_info = next(
                (b for b in self._bubble_infos if b['note'] is self._edit_note),
                None)
            if bi_info:
                self._edit_ov.setGeometry(bi_info['rect'])


# =============================================================================
# Interlinear IPA view — read-only, word on top, IPA beneath each word
# =============================================================================

class LyricsIpaView(QWidget):
    """Read-only canvas showing each lyric word with its IPA directly beneath.

    Words wrap line-by-line; each cell is max(word_width, ipa_width) so the
    two rows stay aligned per word.  Clicking a word (not the IPA row) emits
    word_clicked so the Analysis panel updates identically to the other views.
    """

    word_clicked = pyqtSignal(str, int, int)  # word_lower, block_number, char_offset

    # ── layout constants ───────────────────────────────────────────────────
    _MARGIN    = 14
    _WORD_GAP  = 8    # horizontal gap between cells on the same row
    _ROW_GAP   = 6    # extra vertical gap between wrapped rows
    _BLOCK_GAP = 20   # gap between lyrics lines (blocks)
    _IPA_GAP   = 2    # gap between word baseline and IPA top

    # ── theme ──────────────────────────────────────────────────────────────
    _C_BG    = '#14181f'
    _C_TEXT  = '#d8dfe8'   # word color (reuse CoachingView._C_TEXT)
    _C_MUTED = '#98a8c0'   # IPA color  (reuse CoachingView._C_MUTED)

    def __init__(self):
        super().__init__()
        self._blocks: list = []   # list of per-line lists: (word, ipa, bn, co)
        self._font_pt: int = 16
        # Hit-test cache: list of (QRect, word_lower, bn, co) — word box only
        self._word_rects: list = []
        self._total_h: int = _scale(100)
        # Diction hint overlay state
        self._ann_map: dict = {}     # (bn, co) → list[WordAnnotation]
        self._hints_enabled: bool = False
        self._hint_opacity: float = 0.5
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    # ── public API ─────────────────────────────────────────────────────────

    def set_view_data(self, blocks: list):
        """*blocks*: list of per-line lists of (word, ipa_str, block_number, char_offset)."""
        self._blocks = blocks
        self._relayout()

    def set_annotations(self, annotations: list, enabled: bool):
        """Update the diction-hint overlay.  *annotations* is the same list that
        LyricsEditor.set_annotations receives; *enabled* gates the whole feature."""
        self._hints_enabled = enabled
        m: dict = {}
        if enabled:
            for a in annotations:
                m.setdefault((a.block, a.start), []).append(a)
        self._ann_map = m
        self.update()

    def set_highlight_opacity(self, opacity: float):
        self._hint_opacity = max(0.0, min(1.0, opacity))
        self.update()

    def set_font_pt(self, pt: int):
        self._font_pt = pt
        self._relayout()

    def sizeHint(self):
        from PyQt5.QtCore import QSize
        return QSize(max(200, self.width()), getattr(self, '_total_h', _scale(100)))

    # ── fonts ──────────────────────────────────────────────────────────────

    def _word_font(self) -> QFont:
        return QFont('Inter', self._font_pt)

    def _ipa_font(self) -> QFont:
        return QFont('Charis SIL', max(8, self._font_pt - 3))

    def _ipa_cell_width(self, ifm: QFontMetrics, s: str) -> int:
        """Cell width for an IPA string, sized to never clip hooked/tailed glyphs.

        Qt's horizontalAdvance() misses rightward glyph overhang (ɚ, ɹ, ɾ …).
        boundingRect().right() + 1 gives the rightmost ink pixel from draw
        position 0, which is what actually matters for clip avoidance.
        A generous fixed pad covers any remaining sub-pixel / rounding slop.
        """
        br = ifm.boundingRect(s)
        # br.right() is the inclusive rightmost x of the ink rect relative to
        # the draw origin; +1 converts to an exclusive (width-style) value.
        right_edge = max(ifm.horizontalAdvance(s), br.right() + 1, br.width())
        return right_edge + _scale(12)

    # ── layout ─────────────────────────────────────────────────────────────

    def _relayout(self):
        W = self.width()
        if W <= 10:
            self.update()
            return

        margin    = _scale(self._MARGIN)
        word_gap  = _scale(self._WORD_GAP)
        row_gap   = _scale(self._ROW_GAP)
        block_gap = _scale(self._BLOCK_GAP)
        ipa_gap   = _scale(self._IPA_GAP)
        content_w = max(_scale(60), W - 2 * margin)

        wfm  = QFontMetrics(self._word_font())
        wlh  = wfm.height()
        ifm  = QFontMetrics(self._ipa_font())
        ilh  = ifm.height()
        pair_h = wlh + ipa_gap + ilh

        self._word_rects = []
        y = _scale(12)

        for line_list in self._blocks:
            if not line_list:
                y += block_gap
                continue

            # word-wrap into rows based on cell widths
            rows: list = []
            cur_row: list = []
            cur_x = 0
            for item in line_list:
                word, ipa_str, bn, co = item
                ww = wfm.horizontalAdvance(word)
                iw = self._ipa_cell_width(ifm, ipa_str)
                cell_w = max(ww, iw)
                if cur_row and cur_x + word_gap + cell_w > content_w:
                    rows.append(cur_row)
                    cur_row = []
                    cur_x = 0
                cur_row.append((word, ipa_str, bn, co, ww, iw, cell_w))
                cur_x += cell_w + word_gap
            if cur_row:
                rows.append(cur_row)

            for row in rows:
                x = margin
                for (word, ipa_str, bn, co, ww, iw, cell_w) in row:
                    # Only the word row is clickable
                    self._word_rects.append(
                        (QRect(x, y, cell_w, wlh), word.lower(), bn, co))
                    x += cell_w + word_gap
                y += pair_h + row_gap

            y += block_gap - row_gap   # replace last row_gap with block_gap

        self._total_h = y + _scale(12)
        self.setMinimumHeight(self._total_h)
        self.update()

    # ── painting ───────────────────────────────────────────────────────────

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.fillRect(self.rect(), QColor(self._C_BG))

        if not self._blocks:
            p.setPen(QColor(self._C_MUTED))
            p.setFont(self._word_font())
            p.drawText(self.rect(), Qt.AlignCenter,
                       'Switch to IPA view after entering lyrics.')
            return

        margin    = _scale(self._MARGIN)
        word_gap  = _scale(self._WORD_GAP)
        row_gap   = _scale(self._ROW_GAP)
        block_gap = _scale(self._BLOCK_GAP)
        ipa_gap   = _scale(self._IPA_GAP)
        content_w = max(_scale(60), self.width() - 2 * margin)

        wfont = self._word_font()
        wfm   = QFontMetrics(wfont)
        wlh   = wfm.height()
        ifont = self._ipa_font()
        ifm   = QFontMetrics(ifont)
        ilh   = ifm.height()
        pair_h = wlh + ipa_gap + ilh

        y = _scale(12)
        for line_list in self._blocks:
            if not line_list:
                y += block_gap
                continue

            rows: list = []
            cur_row: list = []
            cur_x = 0
            for item in line_list:
                word, ipa_str, bn, co = item
                ww = wfm.horizontalAdvance(word)
                iw = self._ipa_cell_width(ifm, ipa_str)
                cell_w = max(ww, iw)
                if cur_row and cur_x + word_gap + cell_w > content_w:
                    rows.append(cur_row)
                    cur_row = []
                    cur_x = 0
                cur_row.append((word, ipa_str, bn, co, ww, iw, cell_w))
                cur_x += cell_w + word_gap
            if cur_row:
                rows.append(cur_row)

            for row in rows:
                x = margin
                for (word, ipa_str, bn, co, ww, iw, cell_w) in row:
                    # ── diction hint: bg tint + underline ────────────────
                    if self._hints_enabled:
                        anns = self._ann_map.get((bn, co))
                        if anns:
                            _C_BG_HEX = self._C_BG
                            tinted = _blend_hex(_C_BG_HEX, anns[0].bg_color,
                                                self._hint_opacity)
                            p.fillRect(x, y, cell_w, wlh, tinted)
                            # Solid underline (full color, ignores opacity)
                            ul_y = y + wlh - _scale(1)
                            p.setPen(QColor(anns[0].color))
                            p.drawLine(x + (cell_w - ww) // 2, ul_y,
                                       x + (cell_w - ww) // 2 + ww, ul_y)
                    # Word centered in its cell
                    word_x = x + (cell_w - ww) // 2
                    p.setFont(wfont)
                    p.setPen(QColor(self._C_TEXT))
                    p.drawText(word_x, y, ww + _scale(2), wlh,
                               Qt.AlignLeft | Qt.AlignVCenter, word)
                    # IPA centered beneath it (iw already includes right padding)
                    ipa_x = x + (cell_w - iw) // 2
                    p.setFont(ifont)
                    p.setPen(QColor(self._C_MUTED))
                    p.drawText(ipa_x, y + wlh + ipa_gap, iw, ilh,
                               Qt.AlignLeft | Qt.AlignVCenter, ipa_str)
                    x += cell_w + word_gap
                y += pair_h + row_gap

            y += block_gap - row_gap

        p.end()

    # ── hit-test / events ──────────────────────────────────────────────────

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._relayout()

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        pos = ev.pos()
        for (rect, word_lower, bn, co) in self._word_rects:
            if rect.contains(pos):
                self.word_clicked.emit(word_lower, bn, co)
                return

    def mouseMoveEvent(self, ev):
        if self._hints_enabled and self._ann_map:
            pos = ev.pos()
            for (rect, word_lower, bn, co) in self._word_rects:
                if rect.contains(pos):
                    anns = self._ann_map.get((bn, co))
                    if anns:
                        tip = '\n\n'.join(dict.fromkeys(a.tip_text for a in anns))
                        QToolTip.showText(ev.globalPos(), tip, self)
                        return
        QToolTip.hideText()


class VowelChartView(QWidget):
    def __init__(self):
        super().__init__()
        self._current = None
        self._ui_scale = 1.0
        self.setMinimumSize(_scale(280), _scale(320))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if HAS_QTSVG:
            self._view = QSvgWidget(self)
            self._view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        else:
            self._view = QLabel(self)
            self._view.setAlignment(Qt.AlignCenter)
            self._view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self._view)

        self.show_vowel(None)

    def setUiScale(self, scale: float):
        self._ui_scale = scale
        self.setMinimumSize(round(280 * scale), round(320 * scale))
        self.show_vowel(self._current)   # re-render at new size

    def show_vowel(self, sym):
        self._current = sym
        svg_str = create_vowel_chart_svg(sym)
        if HAS_QTSVG:
            self._view.load(svg_str.encode('utf-8'))
        else:
            size = min(self.width(), self.height()) or _scale(320)
            uri = 'data:image/svg+xml;base64,' + base64.b64encode(
                svg_str.encode()).decode()
            self._view.setText(f'<img src="{uri}" width="{size}">')

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if not HAS_QTSVG:
            self.show_vowel(self._current)


class BrightnessBar(QWidget):
    """Horizontal bar showing where a vowel falls on the brightness spectrum."""

    def __init__(self):
        super().__init__()
        self._b = None
        self._ui_scale = 1.0
        self._refresh_height()

    def _refresh_height(self):
        """Recalculate fixed height from font metrics so labels are never clipped."""
        f = QFont('Inter', round(9 * self._ui_scale))
        fm = QFontMetrics(f)
        h = _scale(4) + _scale(14) + _scale(4) + fm.height() + _scale(4)
        self.setFixedHeight(max(_scale(36), h))

    def setUiScale(self, scale: float):
        self._ui_scale = scale
        self._refresh_height()
        self.update()

    def set_brightness(self, b):
        self._b = b
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        bar_left = 0
        bar_right = self.width()
        bar_top = _scale(4)
        bar_h = _scale(14)

        grad = QLinearGradient(bar_left, 0, bar_right, 0)
        grad.setColorAt(0.0, QColor('#4878a8'))
        grad.setColorAt(0.5, QColor('#5a607a'))
        grad.setColorAt(1.0, QColor('#d8a878'))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(bar_left, bar_top, bar_right - bar_left, bar_h,
                          _scale(7), _scale(7))

        # Font: logical point size only — Qt's HiDPI machinery scales to physical
        # pixels automatically. Never multiply by _dpr() here.
        f = QFont('Inter', round(9 * self._ui_scale))
        fm = QFontMetrics(f)
        p.setPen(QColor('#7888a0'))
        p.setFont(f)
        label_y = bar_top + bar_h + _scale(4)
        label_h = fm.height()
        dark_w   = fm.horizontalAdvance('dark')   + _scale(6)
        bright_w = fm.horizontalAdvance('bright') + _scale(6)
        p.drawText(bar_left, label_y, dark_w, label_h,
                   Qt.AlignLeft | Qt.AlignTop, 'dark')
        p.drawText(bar_right - bright_w, label_y, bright_w, label_h,
                   Qt.AlignRight | Qt.AlignTop, 'bright')

        if self._b is not None:
            x = bar_left + int(self._b * (bar_right - bar_left))
            cy = bar_top + bar_h // 2
            r = _scale(7)
            p.setPen(QColor('#14181f'))
            p.setBrush(QColor('#d8dfe8'))
            p.drawEllipse(x - r, cy - r, r * 2, r * 2)


class LadderStep(QFrame):
    clicked = pyqtSignal(str)

    def __init__(self, sym: str):
        super().__init__()
        self.sym = sym
        self.setObjectName('LadderStep')
        self.setCursor(Qt.PointingHandCursor)

        sym_lbl = QLabel(sym)
        sym_lbl.setObjectName('LadderSym')
        sym_lbl.setAlignment(Qt.AlignCenter)

        ex = VOWEL_EXAMPLES.get(sym, '')
        ex_lbl = QLabel(ex if ex else '—')
        ex_lbl.setObjectName('LadderExample')
        ex_lbl.setAlignment(Qt.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(_scale(10), _scale(6), _scale(10), _scale(6))
        layout.setSpacing(0)
        layout.addWidget(sym_lbl)
        layout.addWidget(ex_lbl)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.clicked.emit(self.sym)
        super().mousePressEvent(ev)


class ArticulationCard(QFrame):
    step_clicked = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName('ArticulationCard')
        self.setFrameShape(QFrame.StyledPanel)

        self.title = QLabel('Select a vowel above')
        self.title.setObjectName('CardTitle')
        self.title.setWordWrap(True)
        self.title.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.subtitle = QLabel('')
        self.subtitle.setObjectName('CardLine')
        self.subtitle.setWordWrap(True)
        self.subtitle.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.tongue = QLabel('')
        self.tongue.setObjectName('CardLine')
        self.tongue.setWordWrap(True)
        self.tongue.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.lips = QLabel('')
        self.lips.setObjectName('CardLine')
        self.lips.setWordWrap(True)
        self.lips.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.brightness_bar = BrightnessBar()
        self.notes = QLabel('')
        self.notes.setObjectName('CardNotes')
        self.notes.setWordWrap(True)
        self.notes.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)

        self.stress_warning = QLabel('')
        self.stress_warning.setObjectName('StressWarning')
        self.stress_warning.setWordWrap(True)
        self.stress_warning.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.stress_warning.setVisible(False)

        self.sustained_label = QLabel('')
        self.sustained_label.setObjectName('LegatoTip')
        self.sustained_label.setWordWrap(True)
        self.sustained_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.sustained_label.setVisible(False)

        self.section_header = QLabel('MODIFICATION AT HIGH PITCH')
        self.section_header.setObjectName('PanelTitle')
        self.section_caption = QLabel('')
        self.section_caption.setObjectName('Caption')
        self.section_caption.setWordWrap(True)
        self.section_caption.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)

        self.ladder_row = QHBoxLayout()
        self.ladder_row.setSpacing(_scale(8))
        self.ladder_row.setContentsMargins(0, _scale(4), 0, 0)
        ladder_widget = QWidget()
        ladder_widget.setLayout(self.ladder_row)

        self.ladder_axis = QLabel('')
        self.ladder_axis.setObjectName('LadderAxis')
        self.ladder_axis.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(_scale(8))
        layout.setContentsMargins(_scale(16), _scale(16), _scale(16), _scale(16))
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addWidget(self.tongue)
        layout.addWidget(self.lips)
        layout.addWidget(self.brightness_bar)
        layout.addWidget(self.notes)
        layout.addWidget(self.stress_warning)
        layout.addWidget(self.sustained_label)
        layout.addSpacing(_scale(10))
        layout.addWidget(self.section_header)
        layout.addWidget(self.section_caption)
        layout.addWidget(ladder_widget)
        layout.addWidget(self.ladder_axis)

    def set_stress_warning(self, text: str):
        self.stress_warning.setText(text)
        self.stress_warning.setVisible(bool(text))

    def show_phone(self, sym):
        if sym in DIPHTHONGS:
            self._show_diphthong(sym)
        elif sym in VOWELS:
            self._show_vowel(sym)
        else:
            self._show_empty()

    def _show_empty(self):
        self.title.setText('Select a vowel above')
        self.subtitle.setText('')
        self.tongue.setText('')
        self.lips.setText('')
        self.notes.setText('')
        self.brightness_bar.set_brightness(None)
        self.set_stress_warning('')
        self.sustained_label.setVisible(False)
        self.section_header.setText('')
        self.section_caption.setText('')
        self._clear_ladder()
        self.ladder_axis.setText('')

    def _show_vowel(self, sym):
        v = VOWELS[sym]
        example = VOWEL_EXAMPLES.get(sym, '')
        if example:
            self.title.setText(f'/{sym}/   ·   as in "{example}"')
        else:
            self.title.setText(f'/{sym}/')
        self.subtitle.setText(v.name)
        self.tongue.setText(
            f'Tongue: {v.tongue_height}, {v.tongue_advance}')
        self.lips.setText(f'Lips: {v.lips}')
        self.brightness_bar.set_brightness(brightness(sym))
        self.notes.setText(v.singing_note)

        self.section_header.setText('MODIFICATION AT HIGH PITCH')
        if v.mod_high and v.mod_high in VOWELS:
            self.section_caption.setText(
                "As pitch rises, this vowel relaxes toward the target on the "
                "right. Click either step to hear it.")
            self._build_ladder([sym, v.mod_high])
            self.ladder_axis.setText(
                '← comfortable pitch        ·        higher pitch →')
        else:
            self.section_caption.setText(
                'Already neutral — usually no modification needed at high pitch.')
            self._clear_ladder()
            step = LadderStep(sym)
            step.clicked.connect(self.step_clicked.emit)
            self.ladder_row.addWidget(step)
            self.ladder_row.addStretch()
            self.ladder_axis.setText('')

    def _show_diphthong(self, sym):
        d = DIPHTHONGS[sym]
        self.title.setText(f'/{sym}/   ·   {d.name} (as in {d.example})')
        self.subtitle.setText(
            f'A diphthong: glides from /{d.primary}/ to /{d.glide}/')
        if d.primary in VOWELS:
            pv = VOWELS[d.primary]
            self.tongue.setText(
                f'Primary /{d.primary}/ — tongue: {pv.tongue_height}, '
                f'{pv.tongue_advance}')
            self.lips.setText(f'Primary /{d.primary}/ — lips: {pv.lips}')
            self.brightness_bar.set_brightness(brightness(d.primary))
        self.notes.setText(d.singing_note)

        self.section_header.setText('DIPHTHONG GLIDE')
        self.section_caption.setText(
            "Sustain on the primary vowel for almost the whole duration. "
            "Vanish to the glide only at the very end. Click either to hear it.")
        self._build_ladder([d.primary, d.glide], glide_labels=True)
        self.ladder_axis.setText(
            '← sustain (most of the note)        ·        vanish (final ms) →')

    def _clear_ladder(self):
        while self.ladder_row.count():
            item = self.ladder_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _build_ladder(self, steps, glide_labels=False):
        self._clear_ladder()
        for i, s in enumerate(steps):
            if i > 0:
                arrow_char = '⇝' if glide_labels else '→'
                arrow = QLabel(arrow_char)
                arrow.setObjectName('LadderArrow')
                arrow.setAlignment(Qt.AlignCenter)
                self.ladder_row.addWidget(arrow)
            step = LadderStep(s)
            step.clicked.connect(self.step_clicked.emit)
            self.ladder_row.addWidget(step)
        self.ladder_row.addStretch()


class PhraseTrajectoryBar(QWidget):
    vowel_cell_clicked = pyqtSignal(int)  # trajectory cell index

    def __init__(self):
        super().__init__()
        self._items = []  # (vowel_symbol, word_index)
        self._highlight_index = -1
        self._cell_rects = []  # list of (x, w) per cell, built in paintEvent
        self._ui_scale = 1.0
        self.setCursor(Qt.PointingHandCursor)
        self._refresh_height()

    def _refresh_height(self):
        """Derive widget height from font metrics so vowel labels are never clipped."""
        f_label = QFont('Charis SIL', round(12 * self._ui_scale))
        fm = QFontMetrics(f_label)
        label_strip_h = fm.height() + _scale(4)
        total_h = _scale(10) + _scale(32) + label_strip_h + _scale(8)
        h = max(_scale(60), total_h)
        self.setMinimumHeight(h)
        self.setMaximumHeight(h)

    def setUiScale(self, scale: float):
        self._ui_scale = scale
        self._refresh_height()
        self.update()

    def set_phrase(self, items):
        self._items = list(items)
        self._highlight_index = -1
        self.update()

    def set_highlight(self, index: int):
        self._highlight_index = index
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        p.setPen(QColor('#2c344a'))
        p.setBrush(QColor('#1c2230'))
        p.drawRoundedRect(rect, _scale(6), _scale(6))

        if not self._items:
            p.setPen(QColor('#4a5670'))
            # Logical point size only — no _dpr() multiplication
            f = QFont('Inter', round(11 * self._ui_scale))
            f.setItalic(True)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter,
                       "Click a word to see its line's vowel trajectory")
            return

        # Derive label strip height from actual font metrics to avoid clipping
        f_label = QFont('Charis SIL', round(12 * self._ui_scale))
        fm_label = QFontMetrics(f_label)
        label_strip_h = fm_label.height() + _scale(4)

        n = len(self._items)
        margin = _scale(10)
        usable_w = self.width() - 2 * margin
        word_gap = _scale(5)
        word_indices = [wi for _, wi in self._items]
        n_word_gaps = sum(1 for i in range(1, n)
                          if word_indices[i] != word_indices[i - 1])
        total_gap_w = word_gap * n_word_gaps
        cell_total_w = (usable_w - total_gap_w) / n if n > 0 else 0

        bar_top = _scale(10)
        bar_h = self.height() - bar_top - label_strip_h - _scale(8)

        self._cell_rects = []
        x = float(margin)
        for i, (vsym, wi) in enumerate(self._items):
            if i > 0 and word_indices[i] != word_indices[i - 1]:
                x += word_gap
            b = brightness(vsym)
            color = brightness_color(b)
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            cell_x = int(x)
            cell_w = max(2, int(cell_total_w) - 2)
            self._cell_rects.append((cell_x, cell_w))
            p.drawRoundedRect(cell_x, bar_top, cell_w, bar_h, _scale(4), _scale(4))

            if i == self._highlight_index:
                p.setPen(QColor('#d8dfe8'))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(cell_x - 1, bar_top - 1,
                                  cell_w + 2, bar_h + 2, _scale(5), _scale(5))

            p.setPen(QColor('#d8dfe8'))
            p.setFont(f_label)
            label_y = bar_top + bar_h + _scale(2)
            p.drawText(cell_x, label_y, cell_w, fm_label.height(),
                       Qt.AlignCenter, vsym)

            x += cell_total_w

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton or not self._cell_rects:
            return
        x = ev.x()
        for i, (cx, cw) in enumerate(self._cell_rects):
            if cx <= x < cx + cw:
                self.vowel_cell_clicked.emit(i)
                return


class AnalysisPanel(QWidget):
    play_requested = pyqtSignal(str)
    vowel_selected = pyqtSignal(int)
    pronunciation_chosen = pyqtSignal(str, int)  # (word, pron_index)

    def __init__(self):
        super().__init__()
        self._pronunciations = []
        self._current_pron_index = 0
        self._current_vowel = None
        self._current_word = ''
        self._current_syllables = []
        self._next_ipa = None

        word_header = QWidget()
        wh_layout = QHBoxLayout(word_header)
        wh_layout.setContentsMargins(0, 0, 0, 0)
        wh_layout.setSpacing(_scale(8))
        self.word_label = QLabel('Click a word to begin')
        self.word_label.setObjectName('WordLabel')
        self.word_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.speak_btn = QPushButton('▶ Speak')
        self.speak_btn.setEnabled(False)
        self.speak_btn.clicked.connect(self._on_speak)
        wh_layout.addWidget(self.word_label, 1)
        wh_layout.addWidget(self.speak_btn)

        self.ipa_label = QLabel('')
        self.ipa_label.setObjectName('IpaLabel')
        self.ipa_label.setTextFormat(Qt.RichText)
        self.ipa_label.setWordWrap(True)
        self.ipa_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)

        self.legato_tip = QLabel('')
        self.legato_tip.setObjectName('LegatoTip')
        self.legato_tip.setWordWrap(True)
        self.legato_tip.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.legato_tip.setVisible(False)

        self.consonant_tip = QLabel('')
        self.consonant_tip.setObjectName('ConsonantTip')
        self.consonant_tip.setWordWrap(True)
        self.consonant_tip.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.consonant_tip.setVisible(False)

        alt_header = QLabel('PRONUNCIATIONS')
        alt_header.setObjectName('PanelTitle')
        self.alt_layout = QVBoxLayout()
        self.alt_layout.setSpacing(_scale(4))
        alt_wrap = QWidget()
        alt_wrap.setLayout(self.alt_layout)

        vowel_header = QLabel('SYLLABLE VOWELS')
        vowel_header.setObjectName('PanelTitle')
        self.vowel_btn_layout = QHBoxLayout()
        self.vowel_btn_layout.setSpacing(_scale(8))
        self.vowel_btn_layout.addStretch()
        vowel_btn_wrap = QWidget()
        vowel_btn_wrap.setLayout(self.vowel_btn_layout)

        self.chart = VowelChartView()
        self.chart_container = AspectRatioContainer(self.chart, 390 / 425)
        self.chart_container.setMinimumHeight(_scale(360))

        self.card = ArticulationCard()
        self.card.step_clicked.connect(self._set_current_vowel)

        self.play_btn = QPushButton('▶  Play vowel sound')
        self.play_btn.clicked.connect(self._on_play)
        self.play_btn.setEnabled(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(_scale(20), _scale(20), _scale(20), _scale(20))
        layout.setSpacing(_scale(10))
        layout.addWidget(word_header)
        layout.addWidget(self.ipa_label)
        layout.addWidget(self.legato_tip)
        layout.addWidget(self.consonant_tip)
        layout.addSpacing(_scale(4))
        layout.addWidget(alt_header)
        layout.addWidget(alt_wrap)
        layout.addSpacing(_scale(4))
        layout.addWidget(vowel_header)
        layout.addWidget(vowel_btn_wrap)
        layout.addWidget(self.chart_container, 1)
        layout.addWidget(self.card)
        layout.addWidget(self.play_btn)

    def setUiScale(self, scale: float):
        """Propagate UI scale to the chart and its container."""
        self.chart.setUiScale(scale)
        self.chart_container.setMinimumHeight(round(360 * scale))

    def show_word(self, word, pronunciations, initial_index=0, next_ipa=None,
                  song_style='classical', enabled_hints=None, has_punct_boundary=False):
        self._pronunciations = pronunciations
        self._current_pron_index = 0
        self._current_word = word
        self._next_ipa = next_ipa
        self._song_style = song_style
        self._enabled_hints = enabled_hints
        self._has_punct_boundary = has_punct_boundary
        self.word_label.setText(word)
        self.speak_btn.setEnabled(bool(word and word != 'Click a word to begin'))

        if not pronunciations:
            self.ipa_label.setText(
                '<span style="color:#6878a0;font-style:italic">'
                'No pronunciation found. Right-click the word in the lyrics '
                'to set a custom IPA.</span>')
            self._clear_alts()
            self._clear_vowel_buttons()
            self.chart.show_vowel(None)
            self.card.show_phone(None)
            self.play_btn.setEnabled(False)
            self.speak_btn.setEnabled(False)
            self.legato_tip.setVisible(False)
            self.consonant_tip.setVisible(False)
            return

        self._populate_alts(pronunciations)
        idx = initial_index if 0 <= initial_index < len(pronunciations) else 0
        self._select_pronunciation(idx)

    def _populate_alts(self, pronunciations):
        self._clear_alts()
        if len(pronunciations) <= 1:
            return
        labelled = label_alternatives(pronunciations)
        for i, (p, tag) in enumerate(labelled):
            display_p = render_ipa_html(p)
            text = display_p
            if tag:
                text = f'{display_p}   ·   {tag}'
            btn = QPushButton()
            btn.setText('')
            btn.setProperty('role', 'alt')
            if tag:
                btn.setProperty('tag', tag)
            btn.setProperty('selected', 'false')
            inner = QLabel(text)
            inner.setTextFormat(Qt.RichText)
            inner.setStyleSheet('background: transparent; color: #d8dfe8;')
            inner.setAttribute(Qt.WA_TransparentForMouseEvents)
            inner_l = QHBoxLayout(btn)
            inner_l.setContentsMargins(_scale(14), _scale(8), _scale(14), _scale(8))
            inner_l.addWidget(inner)
            btn.clicked.connect(
                lambda _, idx=i: self._select_pronunciation(idx, from_user=True))
            self.alt_layout.addWidget(btn)

    def _select_pronunciation(self, idx, from_user: bool = False):
        if idx < 0 or idx >= len(self._pronunciations):
            return
        self._current_pron_index = idx
        p = self._pronunciations[idx]
        # Only persist the choice when the user explicitly clicked an alt button,
        # not during the auto-init call from show_word (Bug 3 fix).
        if from_user:
            self.pronunciation_chosen.emit(self._current_word, idx)
        self._update_word_tips(p)

        for i in range(self.alt_layout.count()):
            w = self.alt_layout.itemAt(i).widget()
            if w is None:
                continue
            w.setProperty('selected', 'true' if i == idx else 'false')
            w.style().unpolish(w)
            w.style().polish(w)

        self._current_syllables = find_syllable_vowels(p)
        first_sym = self._current_syllables[0][0] if self._current_syllables else None
        self._render_ipa(p, first_sym, 0)
        self._populate_vowel_buttons(self._current_syllables)
        self._set_current_vowel(first_sym, 0 if first_sym else None)

    def _render_ipa(self, p, highlight_sym, highlight_idx):
        if highlight_sym is None:
            self.ipa_label.setText('/' + html.escape(p) + '/')
        else:
            self.ipa_label.setText(
                render_ipa_html(p, highlight_sym, highlight_idx))

    def _populate_vowel_buttons(self, syllables):
        self._clear_vowel_buttons()
        for idx, (sym, _, _) in enumerate(syllables):
            btn = QPushButton(sym)
            btn.setProperty('role', 'vowel')
            btn.setCheckable(True)
            btn.clicked.connect(
                lambda _, s=sym, i=idx: self._set_current_vowel(s, i))
            self.vowel_btn_layout.insertWidget(
                self.vowel_btn_layout.count() - 1, btn)

    def _set_current_vowel(self, sym, index=None):
        if index is None and sym is not None:
            # When multiple syllables share the same symbol (e.g. "bobo" → /oʊ/,/oʊ/),
            # prefer the syllable nearest the current one rather than always the first.
            # Falls back to first match if no current index is tracked.
            cur = self._current_pron_index  # reuse as a rough "last syllable touched" hint
            best = None
            best_dist = float('inf')
            for i, (s, _, _) in enumerate(self._current_syllables):
                if s == sym:
                    dist = abs(i - cur)
                    if dist < best_dist:
                        best_dist = dist
                        best = i
            index = best
        self._current_vowel = sym
        self.chart.show_vowel(sym)
        self.card.show_phone(sym)
        self.play_btn.setEnabled(sym is not None)

        for i in range(self.vowel_btn_layout.count()):
            w = self.vowel_btn_layout.itemAt(i).widget()
            if isinstance(w, QPushButton):
                w.setChecked(w.text() == sym)

        if self._pronunciations and self._current_pron_index < len(self._pronunciations):
            self._render_ipa(
                self._pronunciations[self._current_pron_index], sym,
                index if index is not None else -1)

        self._update_stress_warning(index)
        if index is not None and index >= 0:
            self.vowel_selected.emit(index)

    def _update_word_tips(self, pron: str):
        """Refresh the panel tips from the shared tip engine, so the panel, the
        hover tooltip, and the cheat-sheet export all show the same advice.
        The primary boundary tip goes in the top label; any stacked notes
        (r-toxicity, /ŋ/, yod, spurious diphthong, /h/) go in the second.
        """
        tips = compute_word_tips(
            pron, self._next_ipa,
            getattr(self, '_has_punct_boundary', False),
            getattr(self, '_song_style', 'classical'),
            getattr(self, '_enabled_hints', None))

        boundary = {'legato', 'vowel_glide', 'crash'}
        legato_text = next((txt for tt, txt in tips if tt in boundary), '')
        cons_text = '\n\n'.join(txt for tt, txt in tips if tt not in boundary)

        self.legato_tip.setText(legato_text)
        self.legato_tip.setVisible(bool(legato_text))
        self.consonant_tip.setText(cons_text)
        self.consonant_tip.setVisible(bool(cons_text))

    def _update_stress_warning(self, vowel_idx):
        """Refresh stress warning (feature 3) for the currently selected vowel."""
        if vowel_idx is None or not self._pronunciations:
            self.card.set_stress_warning('')
            return
        pron = (self._pronunciations[self._current_pron_index]
                if self._current_pron_index < len(self._pronunciations) else '')
        if not pron:
            self.card.set_stress_warning('')
            return
        stressed, _ = vowel_stress_info(pron, vowel_idx)
        if not stressed:
            sym = self._current_vowel or ''
            if sym in ('ə', 'ɪ', 'ɚ', 'ɘ'):
                self.card.set_stress_warning(
                    '⚠  Unstressed weak vowel — resist coloring or weighting '
                    'this syllable. Keep it light and neutral; any deliberate '
                    'shaping here will distort the natural speech rhythm.')
            else:
                self.card.set_stress_warning(
                    '⚠  Unstressed syllable — the stress falls elsewhere in '
                    'this word. Don’t over-sing this vowel; let it stay '
                    'subordinate to the stressed syllable.')
        else:
            self.card.set_stress_warning('')

    def select_vowel_at(self, syllable_idx: int):
        """Public: select vowel at position *syllable_idx* in current pronunciation."""
        if syllable_idx < len(self._current_syllables):
            sym, _, _ = self._current_syllables[syllable_idx]
            self._set_current_vowel(sym, syllable_idx)

    def _clear_alts(self):
        while self.alt_layout.count():
            item = self.alt_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _clear_vowel_buttons(self):
        while self.vowel_btn_layout.count() > 1:
            item = self.vowel_btn_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _show_sustained_tips(self, is_sustained: bool, vowel: Optional[str]):
        """Show or hide sustained-note pedagogy in the articulation card."""
        if not is_sustained or vowel is None:
            self.card.sustained_label.setVisible(False)
            return
        tips = []
        if vowel in ('i', 'y'):
            tips.append('Sustained /i/ or /y/ — risk of thinning. '
                        'Keep internal pharyngeal space open; resist spreading the lips too wide.')
        elif vowel in ('u', 'ʊ'):
            tips.append('Sustained /u/ — risk of locking. '
                        'Open the lip circle slightly as pitch rises; '
                        'pursing tightens resonance instead of freeing it.')
        elif vowel in ('æ',):
            tips.append('Sustained /æ/ — risk of pinching at height. '
                        'Classical: relax toward /ɛ/. '
                        'Belt/MT: keep the brightness but release jaw tension.')
        if vowel not in ('i', 'y', 'u', 'ʊ', 'æ'):
            tips.append('Vibrato: aim for a natural oscillation centred on '
                        'the written pitch. '
                        'If the note is marked straight (non-vibrato), '
                        'keep the larynx stable and support steady sub-glottal pressure.')
        if not tips:
            tips.append('Sustained note — keep vowel integrity throughout; '
                        'resist letting the resonance drift as support fades.')
        self.card.sustained_label.setText(chr(10).join(tips))
        self.card.sustained_label.setVisible(True)

    def _on_speak(self):
        if not self._current_word or self._current_word == 'Click a word to begin':
            return
        # Use the currently selected pronunciation so Valjean etc. are correct
        ipa_pron = ''
        if self._pronunciations and self._current_pron_index < len(self._pronunciations):
            ipa_pron = self._pronunciations[self._current_pron_index]
        # Strip surrounding slashes in case the user stored the IPA with them
        ipa_pron = ipa_pron.strip('/')
        _tts_speak(self._current_word, ipa_pron)

    def _on_play(self):
        if self._current_vowel:
            self.play_requested.emit(self._current_vowel)


class CustomIpaDialog(QDialog):
    def __init__(self, word, current_ipa, default_ipas, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Custom IPA')
        self.setMinimumWidth(_scale(460))

        info = QLabel(
            f'Set IPA for <b style="color:#a8c8e8">"{html.escape(word)}"</b>.<br>'
            f'<span style="color:#98a8c0;font-size:11px;font-style:italic">'
            f'Use IPA characters directly. Copy from the chart if needed.'
            f'</span>')
        info.setTextFormat(Qt.RichText)
        info.setWordWrap(True)

        if default_ipas:
            default_text = (
                f'<span style="color:#98a8c0">Dictionary form: '
                f'<span style="color:#7898d0">/{"/  /".join(default_ipas)}/</span>'
                f'</span>')
        else:
            default_text = (
                '<span style="color:#98a8c0">'
                'No dictionary pronunciation available for this word.</span>')
        default = QLabel(default_text)
        default.setTextFormat(Qt.RichText)
        default.setWordWrap(True)

        self.edit = QLineEdit()
        f = QFont('Charis SIL', 14)
        self.edit.setFont(f)
        self.edit.setText(current_ipa or '')
        self.edit.setPlaceholderText('e.g. valʒɑ̃')

        cheat = QLabel(
            '<span style="color:#6878a0;font-size:11px">'
            'Quick reference: ə ɛ æ ɑ ɔ ʌ ʊ ɪ ʃ ʒ ð θ ŋ ɹ ɚ ɝ • diphthongs eɪ aɪ aʊ oʊ ɔɪ'
            '</span>')
        cheat.setTextFormat(Qt.RichText)
        cheat.setWordWrap(True)

        btns = QDialogButtonBox()
        self.reset_btn = btns.addButton('Clear override',
                                        QDialogButtonBox.DestructiveRole)
        btns.addButton(QDialogButtonBox.Cancel)
        self.save_btn = btns.addButton(QDialogButtonBox.Save)
        self.save_btn.clicked.connect(self.accept)
        btns.rejected.connect(self.reject)
        self.reset_btn.clicked.connect(self._on_reset)
        self._reset_clicked = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(_scale(20), _scale(20), _scale(20), _scale(16))
        layout.setSpacing(_scale(10))
        layout.addWidget(info)
        layout.addWidget(default)
        layout.addWidget(self.edit)
        layout.addWidget(cheat)
        layout.addSpacing(_scale(4))
        layout.addWidget(btns)

    def _on_reset(self):
        self._reset_clicked = True
        self.accept()

    def result_ipa(self):
        if self._reset_clicked:
            return ''
        import unicodedata
        raw = self.edit.text().strip().strip('/')
        raw = unicodedata.normalize('NFC', raw).strip()
        if not raw:
            return ''
        # Warn if no recognisable vowel or diphthong found
        has_vowel = any(
            raw[i:i+2] in DIPHTHONGS or raw[i] in VOWELS
            for i in range(len(raw))
        )
        if not has_vowel:
            from PyQt5.QtWidgets import QMessageBox
            res = QMessageBox.warning(
                self, 'No vowel found',
                f'The IPA string "{raw}" contains no recognised vowel or '
                f'diphthong. Save anyway?',
                QMessageBox.Save | QMessageBox.Cancel,
                QMessageBox.Cancel)
            if res != QMessageBox.Save:
                return None  # caller treats None as 'user cancelled'
        return raw


class SongSelectorBar(QWidget):
    song_changed = pyqtSignal(int)
    new_requested = pyqtSignal()
    rename_requested = pyqtSignal()
    delete_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.combo = QComboBox()
        self.combo.currentIndexChanged.connect(self.song_changed.emit)
        new_btn = QPushButton('+  New')
        new_btn.clicked.connect(self.new_requested.emit)
        rename_btn = QPushButton('Rename')
        rename_btn.clicked.connect(self.rename_requested.emit)
        del_btn = QPushButton('Delete')
        del_btn.clicked.connect(self.delete_requested.emit)

        title = QLabel('SONG')
        title.setObjectName('PanelTitle')

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_scale(8))
        layout.addWidget(title)
        layout.addWidget(self.combo, 1)
        layout.addWidget(new_btn)
        layout.addWidget(rename_btn)
        layout.addWidget(del_btn)

    def refresh(self, songs, active_index):
        self.combo.blockSignals(True)
        self.combo.clear()
        for s in songs:
            self.combo.addItem(s.name)
        if 0 <= active_index < self.combo.count():
            self.combo.setCurrentIndex(active_index)
        self.combo.blockSignals(False)


class BulkImportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Bulk Import Custom IPAs')
        self.setMinimumSize(_scale(560), _scale(380))

        info = QLabel(
            'Paste a JSON object mapping words to IPA. Existing overrides for '
            'the same words will be replaced; others stay as-is.<br>'
            '<span style="color:#98a8c0;font-style:italic;font-size:11px">'
            'Example: <code>{"valjean": "valʒɑ̃", "cosette": "kɔzɛt"}</code>'
            '</span>')
        info.setTextFormat(Qt.RichText)
        info.setWordWrap(True)

        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText('{\n  "valjean": "valʒɑ̃",\n  "cosette": "kɔzɛt"\n}')

        btns = QDialogButtonBox(
            QDialogButtonBox.Cancel | QDialogButtonBox.Apply)
        btns.button(QDialogButtonBox.Apply).clicked.connect(self.accept)
        btns.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(info)
        layout.addWidget(self.edit)
        layout.addWidget(btns)

    def parsed(self):
        try:
            text = self.edit.toPlainText().strip()
            if not text:
                return {}
            data = json.loads(text)
            if not isinstance(data, dict):
                return None
            return {str(k).lower(): str(v) for k, v in data.items()}
        except (json.JSONDecodeError, ValueError):
            return None



class _CoachingImportDialog(QDialog):
    """Paste-in dialog for importing a NOTES-FOR-IMPORT block from the
    Direction Prompt output."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Import Coaching Notes')
        self.setMinimumSize(_scale(560), _scale(380))

        info = QLabel(
            'Paste the full output from the Direction Prompt AI response below. '
            'The importer will find the <b>NOTES-FOR-IMPORT</b> block at the end '
            'and extract the coaching notes from it.<br>'
            '<span style="color:#98a8c0;font-style:italic;font-size:11px">'
            'The block starts with <code>NOTES-FOR-IMPORT</code> and the JSON '
            'is surrounded by <code>&lt;&lt;&lt;</code> and '
            '<code>&gt;&gt;&gt;</code>.</span>')
        info.setTextFormat(Qt.RichText)
        info.setWordWrap(True)

        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText(
            'Paste the AI response here…\n\n'
            'NOTES-FOR-IMPORT\n'
            '<<<\n'
            '{"notes": [{"anchor": "…", "note": "…"}, …]}\n'
            '>>>')

        btns = QDialogButtonBox(
            QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(info)
        layout.addWidget(self.edit, 1)
        layout.addWidget(btns)


# =============================================================================
# Main window
# =============================================================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings('Heng', 'LyricIPAFinder')
        self.player = QMediaPlayer()
        self.setWindowIcon(_app_icon())

        app_data = QStandardPaths.writableLocation(
            QStandardPaths.AppLocalDataLocation)
        if not app_data:
            app_data = os.path.expanduser('~/.lyric_ipa_finder')
        self.store = SongStore(app_data)
        self.songs, self.active_index = self.store.load()

        self._pron_cache = {}
        self._pron_index_cache = {}  # pron_choices mirror (occurrence keys + legacy word keys)
        self._current_block_number = -1
        self._current_line_items = []
        self._current_clicked_word_idx = -1
        self._current_clicked_occ_key = None  # "word#N" for the last-clicked occurrence
        self._current_char_offset = -1  # in-block offset of the last-clicked word
        self._missing_audio_warned: set = set()  # warn once per missing symbol
        # Sequential vowel playback (Play line vowels) — hold-cap model:
        # each vowel sounds for at most _seq_hold_ms ms, then advances.
        self._vowel_seq: list = []
        self._vowel_seq_idx = 0
        self._vowel_seq_active = False
        self._seq_hold_ms: int = 320   # default: Fast preset
        self._seq_hold = QTimer(self)
        self._seq_hold.setSingleShot(True)
        self._seq_hold.setInterval(self._seq_hold_ms)
        self._seq_hold.timeout.connect(self._on_seq_hold_elapsed)
        self.player.mediaStatusChanged.connect(self._on_media_status)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)
        self._save_timer.timeout.connect(self._persist_songs)

        self._editor_font_size = 16
        self._ui_scale: float = 1.0  # adjusted via View → Adjust UI Scale
        self._hint_opacity: float = 0.5  # hint-highlight blend opacity [0.0, 1.0]
        self._ipa_hints_enabled: bool = False  # Show diction hints in IPA view
        self._annotations_enabled = True
        self._enabled_hint_types = {'legato','vowel_glide','crash','r_toxicity','dark_l','glottal','plosive','nasal','approx','fricative','yod','ng_release','diphthong','aspiration'}
        self._word_annotations = []
        self._annotation_timer = QTimer(self)
        self._annotation_timer.setSingleShot(True)
        self._annotation_timer.setInterval(900)
        self._annotation_timer.timeout.connect(self._compute_annotations)

        self._init_ui()
        self._restore_state()
        self._load_active_song()

    def _init_ui(self):
        self.setWindowTitle('Lyric IPA Finder')
        self.setStyleSheet(build_style(_dpr(), self._ui_scale))

        self.song_bar = SongSelectorBar()
        self.song_bar.song_changed.connect(self._on_song_changed)
        self.song_bar.new_requested.connect(self._on_new_song)
        self.song_bar.rename_requested.connect(self._on_rename_song)
        self.song_bar.delete_requested.connect(self._on_delete_song)

        self.editor = LyricsEditor()
        self._apply_editor_font()
        self.editor.word_clicked.connect(self._on_word_clicked)
        self.editor.word_ipa_requested.connect(self._on_word_ipa_requested)
        self.editor.content_changed.connect(self._on_lyrics_changed)
        self.editor.annotation_dismissed.connect(self._on_annotation_dismissed)
        self.editor.word_sustain_toggled.connect(self._on_word_sustain_toggled)

        editor_container = QWidget()
        ec_layout = QVBoxLayout(editor_container)
        ec_layout.setContentsMargins(_scale(20), _scale(16), _scale(12), _scale(20))
        ec_layout.setSpacing(_scale(8))

        ec_layout.addWidget(self.song_bar)
        ec_layout.addSpacing(_scale(4))

        lyrics_header = QWidget()
        lh_layout = QHBoxLayout(lyrics_header)
        lh_layout.setContentsMargins(0, 0, 0, 0)
        lh_layout.setSpacing(_scale(8))
        lyrics_title = QLabel('LYRICS')
        lyrics_title.setObjectName('PanelTitle')
        self.hints_btn = QToolButton()
        self.hints_btn.setObjectName('HintsToggle')
        self.hints_btn.setPopupMode(QToolButton.InstantPopup)
        self.hints_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._hints_menu = self._build_hints_menu()
        self.hints_btn.setMenu(self._hints_menu)
        self._update_hints_btn_label()
        lh_layout.addWidget(lyrics_title)
        lh_layout.addStretch()
        self.missing_ipa_btn = QToolButton()
        self.missing_ipa_btn.setObjectName('HintsToggle')
        self.missing_ipa_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.missing_ipa_btn.setToolTip(
            'Some words have no IPA pronunciation. Click to review and '
            'generate an IPA prompt.')
        self.missing_ipa_btn.clicked.connect(self._on_check_missing_ipa)
        self.missing_ipa_btn.setVisible(False)
        lh_layout.addWidget(self.missing_ipa_btn)
        self.style_btn = QToolButton()
        self.style_btn.setObjectName('HintsToggle')
        self.style_btn.setPopupMode(QToolButton.InstantPopup)
        self.style_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._style_menu = self._build_style_menu()
        self.style_btn.setMenu(self._style_menu)
        lh_layout.addWidget(self.style_btn)
        lh_layout.addWidget(self.hints_btn)

        # Three-way mutually-exclusive view buttons: Lyrics / Notes / IPA
        from PyQt5.QtWidgets import QButtonGroup
        self._view_btn_group = QButtonGroup(self)
        self._view_btn_group.setExclusive(True)

        self.lyrics_view_btn = QToolButton()
        self.lyrics_view_btn.setObjectName('HintsToggle')
        self.lyrics_view_btn.setCheckable(True)
        self.lyrics_view_btn.setChecked(True)
        self.lyrics_view_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.lyrics_view_btn.setText('Lyrics')
        self.lyrics_view_btn.setToolTip('Show the live lyrics editor (page 0).')

        self.coaching_btn = QToolButton()
        self.coaching_btn.setObjectName('HintsToggle')
        self.coaching_btn.setCheckable(True)
        self.coaching_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.coaching_btn.setText('Notes')
        self.coaching_btn.setToolTip(
            'Coaching Notes mode — attach performance notes to words or spans. '
            'Lyrics become read-only while active.')

        self.ipa_view_btn = QToolButton()
        self.ipa_view_btn.setObjectName('HintsToggle')
        self.ipa_view_btn.setCheckable(True)
        self.ipa_view_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.ipa_view_btn.setText('IPA')
        self.ipa_view_btn.setToolTip(
            'Interlinear IPA view — shows each word with its IPA printed beneath.')

        self._view_btn_group.addButton(self.lyrics_view_btn, 0)
        self._view_btn_group.addButton(self.coaching_btn,    1)
        self._view_btn_group.addButton(self.ipa_view_btn,    2)
        self._view_btn_group.buttonClicked.connect(self._on_view_btn_clicked)

        lh_layout.addWidget(self.lyrics_view_btn)
        lh_layout.addWidget(self.coaching_btn)
        lh_layout.addWidget(self.ipa_view_btn)
        ec_layout.addWidget(lyrics_header)

        # Stack: page 0 = live editor, page 1 = coaching view, page 2 = IPA view
        self.coaching_view = CoachingView()
        self.coaching_view.notes_changed.connect(self._schedule_save)
        self.coaching_view.word_clicked.connect(self._on_word_clicked)
        coaching_scroll = QScrollArea()
        coaching_scroll.setWidgetResizable(True)
        coaching_scroll.setFrameShape(QFrame.NoFrame)
        coaching_scroll.setWidget(self.coaching_view)

        self.ipa_view = LyricsIpaView()
        self.ipa_view.word_clicked.connect(self._on_word_clicked)
        ipa_scroll = QScrollArea()
        ipa_scroll.setWidgetResizable(True)
        ipa_scroll.setFrameShape(QFrame.NoFrame)
        ipa_scroll.setWidget(self.ipa_view)

        self.lyrics_stack = QStackedWidget()
        self.lyrics_stack.addWidget(self.editor)       # page 0
        self.lyrics_stack.addWidget(coaching_scroll)   # page 1
        self.lyrics_stack.addWidget(ipa_scroll)        # page 2
        ec_layout.addWidget(self.lyrics_stack, 1)

        traj_title = QLabel('PHRASE TRAJECTORY')
        traj_title.setObjectName('PanelTitle')
        traj_caption = QLabel(
            "Each cell is one vowel from the current line, colored by "
            "brightness (warm = bright, cool = dark). Gaps separate words. "
            "Click a vowel in the analysis panel to spotlight where it sits "
            "in the phrase — useful for seeing the tone-color arc of the line "
            "and which vowels carry the line's color."
        )
        traj_caption.setObjectName('Caption')
        traj_caption.setWordWrap(True)
        self.trajectory = PhraseTrajectoryBar()
        ec_layout.addSpacing(_scale(4))
        traj_header = QWidget()
        th_layout = QHBoxLayout(traj_header)
        th_layout.setContentsMargins(0, 0, 0, 0)
        th_layout.setSpacing(_scale(8))
        th_layout.addWidget(traj_title)
        th_layout.addStretch()
        # Speed selector for Play line vowels
        self._seq_speed_label = QLabel('Speed:')
        self._seq_speed_label.setObjectName('Caption')
        self._seq_speed_combo = QComboBox()
        self._seq_speed_combo.setToolTip(
            'Maximum sounding duration per vowel when playing the line in sequence.')
        for label, ms in self._SEQ_SPEED_PRESETS:
            self._seq_speed_combo.addItem(label, ms)
        self._seq_speed_combo.setCurrentIndex(0)  # default: Fast (320 ms hold)
        self._seq_speed_combo.currentIndexChanged.connect(self._on_seq_speed_changed)
        th_layout.addWidget(self._seq_speed_label)
        th_layout.addWidget(self._seq_speed_combo)
        self.play_line_btn = QToolButton()
        self.play_line_btn.setObjectName('HintsToggle')
        self.play_line_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.play_line_btn.setText('▶  Play line vowels')
        self.play_line_btn.setToolTip(
            'Play every vowel in the current line in order, left to right.')
        self.play_line_btn.clicked.connect(self._play_line_vowels)
        th_layout.addWidget(self.play_line_btn)
        ec_layout.addWidget(traj_header)
        ec_layout.addWidget(traj_caption)
        ec_layout.addWidget(self.trajectory)
        self.chiaroscuro_label = QLabel('')
        self.chiaroscuro_label.setObjectName('ChiaroscuroTip')
        self.chiaroscuro_label.setWordWrap(True)
        self.chiaroscuro_label.setVisible(False)
        ec_layout.addWidget(self.chiaroscuro_label)
        self.breath_label = QLabel('')
        self.breath_label.setObjectName('ChiaroscuroTip')
        self.breath_label.setWordWrap(True)
        self.breath_label.setVisible(False)
        ec_layout.addWidget(self.breath_label)

        self.analysis = AnalysisPanel()
        self.analysis.play_requested.connect(self._play_vowel)
        self.analysis.vowel_selected.connect(self._on_vowel_selected_in_analysis)
        self.analysis.pronunciation_chosen.connect(self._on_pronunciation_chosen)
        self.trajectory.vowel_cell_clicked.connect(self._on_trajectory_cell_clicked)

        analysis_scroll = QScrollArea()
        analysis_scroll.setWidgetResizable(True)
        analysis_scroll.setFrameShape(QFrame.NoFrame)
        analysis_scroll.setWidget(self.analysis)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(editor_container)
        splitter.addWidget(analysis_scroll)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([_scale(640), _scale(640)])
        self.setCentralWidget(splitter)

        self._setup_menu()
        self.resize(_scale(1320), _scale(880))

    def _setup_menu(self):
        s = self.menuBar().addMenu('&Song')
        a = QAction('&Bulk Import IPAs…', self)
        a.triggered.connect(self._on_bulk_import)
        s.addAction(a)
        a = QAction('&Generate IPA Prompt to Clipboard', self)
        a.triggered.connect(self._on_generate_prompt)
        s.addAction(a)
        a = QAction('&Check for Missing IPAs…', self)
        a.triggered.connect(self._on_check_missing_ipa)
        s.addAction(a)
        a = QAction('Generate &Direction Prompt to Clipboard', self)
        a.triggered.connect(self._on_generate_direction_prompt)
        s.addAction(a)
        a = QAction('&Import Coaching Notes…', self)
        a.triggered.connect(self._on_import_coaching_notes)
        s.addAction(a)
        s.addSeparator()
        a = QAction('Export Cheat Sheet (Markdown)...', self)
        a.triggered.connect(lambda: self._on_export_cheat_sheet('md'))
        s.addAction(a)
        a = QAction('Export Cheat Sheet (PDF)...', self)
        a.triggered.connect(lambda: self._on_export_cheat_sheet('pdf'))
        s.addAction(a)
        s.addSeparator()
        a = QAction('Reset Dismissed Hints', self)
        a.triggered.connect(self._on_reset_dismissed_hints)
        s.addAction(a)
        s.addSeparator()
        a = QAction('Open Save Folder', self)
        a.triggered.connect(self._on_open_save_folder)
        s.addAction(a)

        s = self.menuBar().addMenu('&View')
        a = QAction('&Adjust Lyrics Font Size…', self)
        a.triggered.connect(self._adjust_font_size)
        s.addAction(a)
        a = QAction('Adjust &UI Scale…', self)
        a.triggered.connect(self._adjust_ui_scale)
        s.addAction(a)
        a = QAction('Adjust Hint Highlight &Opacity…', self)
        a.triggered.connect(self._adjust_hint_opacity)
        s.addAction(a)
        s.addSeparator()
        a = QAction('Show Diction Hints in IPA View', self)
        a.setCheckable(True)
        a.setChecked(self._ipa_hints_enabled)
        a.triggered.connect(self._on_toggle_ipa_hints)
        s.addAction(a)
        self._ipa_hints_action = a
        s.addSeparator()
        a = QAction('Clear All Coaching Notes for This Song…', self)
        a.triggered.connect(self._on_clear_all_coaching_notes)
        s.addAction(a)

    def _apply_editor_font(self):
        """Set lyrics editor font via a widget-level stylesheet so it
        overrides the global QSS font-size rule reliably.
        Font family comes from the global QSS; only size is set here.
        An effective size is computed by scaling the base point size by
        the current UI scale so Notes and IPA views track UI scale too.
        """
        eff = max(8, round(self._editor_font_size * self._ui_scale))
        self.editor.setStyleSheet(
            f"QTextEdit {{ font-size: {eff}pt; }}"
        )
        if hasattr(self, 'coaching_view'):
            self.coaching_view.set_font_pt(eff)
        if hasattr(self, 'ipa_view'):
            self.ipa_view.set_font_pt(eff)

    def _adjust_ui_scale(self):
        """Let the user scale the whole UI (layout + fonts) as a percentage.

        The range 25–200 % is relative to the logical base sizes defined in
        build_style.  On a 4K / HiDPI screen the default is already divided by
        the device-pixel-ratio so 100 % here equals a comfortable physical size.
        Going below 50 % is unusual but available for very large displays or
        unusual DPI situations.
        """
        pct = round(self._ui_scale * 100)
        new_pct, ok = QInputDialog.getInt(
            self, 'UI Scale',
            'UI scale (%):\n'
            '100 % = comfortable default for this screen.\n'
            'Lower values shrink the entire interface.',
            value=pct, min=25, max=200, step=5)
        if ok:
            self._ui_scale = new_pct / 100.0
            self.setStyleSheet(build_style(_dpr(), self._ui_scale))
            self.trajectory.setUiScale(self._ui_scale)
            self.analysis.card.brightness_bar.setUiScale(self._ui_scale)
            self.analysis.setUiScale(self._ui_scale)
            self._apply_editor_font()

    def _adjust_font_size(self):
        new, ok = QInputDialog.getInt(
            self, 'Adjust Font Size', 'Lyrics font size:',
            value=self._editor_font_size, min=8, max=40)
        if ok:
            self._editor_font_size = new
            self._apply_editor_font()

    def _adjust_hint_opacity(self):
        """Open a live-preview slider dialog for hint-highlight opacity."""
        from PyQt5.QtWidgets import QSlider, QDialogButtonBox as _DBB
        original = self._hint_opacity
        dlg = QDialog(self)
        dlg.setWindowTitle('Hint Highlight Opacity')
        dlg.setMinimumWidth(_scale(320))

        desc = QLabel(
            'Adjust how strongly the background colour behind each '
            'annotated word is shown.\n'
            '0% = underline only (invisible tint), '
            '100% = full tint colour.')
        desc.setWordWrap(True)

        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(round(original * 100))
        slider.setTickPosition(QSlider.TicksBelow)
        slider.setTickInterval(10)

        pct_label = QLabel(f'{slider.value()}%')
        pct_label.setAlignment(Qt.AlignCenter)

        def _on_slider(v):
            pct_label.setText(f'{v}%')
            self.editor.set_highlight_opacity(v / 100.0)
            self.ipa_view.set_highlight_opacity(v / 100.0)

        slider.valueChanged.connect(_on_slider)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(_scale(16), _scale(16), _scale(16), _scale(12))
        layout.setSpacing(_scale(10))
        layout.addWidget(desc)
        layout.addWidget(slider)
        layout.addWidget(pct_label)
        layout.addWidget(btns)

        if dlg.exec_() == QDialog.Accepted:
            self._hint_opacity = slider.value() / 100.0
        else:
            # Restore original value on cancel
            self.editor.set_highlight_opacity(original)
            self.ipa_view.set_highlight_opacity(original)
            self._hint_opacity = original

    def _on_clear_all_coaching_notes(self):
        """Prompt, then delete all coaching notes for the active song (undoable)."""
        if not self.active_song or not self.active_song.coaching_notes:
            QMessageBox.information(self, 'No Notes',
                                    'There are no coaching notes for this song.')
            return
        n = len(self.active_song.coaching_notes)
        name = self.active_song.name
        ans = QMessageBox.question(
            self, 'Clear All Coaching Notes',
            f'Delete all {n} coaching note{"s" if n != 1 else ""} for '
            f'"{name}"?\n\nThis can be undone with Ctrl+Z in the Notes view.',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ans == QMessageBox.Yes:
            self.coaching_view.clear_all_notes()

    def _on_toggle_ipa_hints(self, checked: bool):
        self._ipa_hints_enabled = checked
        self.ipa_view.set_annotations(self._word_annotations, checked)

    # ---- Song handling ----

    @property
    def active_song(self):
        return self.songs[self.active_index]

    def _load_active_song(self):
        self.song_bar.refresh(self.songs, self.active_index)
        song = self.active_song
        self.editor.blockSignals(True)
        self.editor.setPlainText(song.lyrics)
        self.editor.blockSignals(False)
        self._pron_cache.clear()
        self._pron_index_cache = dict(song.pron_choices)
        self._update_style_btn_label()
        self._annotation_timer.start()   # recompute hints after load
        self.analysis.show_word('Click a word to begin', [])
        self.trajectory.set_phrase([])
        self._current_line_items = []
        self._current_clicked_word_idx = -1
        self._current_block_number = -1
        self._current_clicked_occ_key = None
        self._current_char_offset = -1
        self._vowel_seq_active = False
        self._update_missing_ipa_indicator()
        if hasattr(self, 'coaching_view'):
            self._reanchor_notes_to_lyrics(song)
            self.coaching_view.set_song(song)
        # Always return to the lyrics editor when switching songs
        if hasattr(self, 'lyrics_stack'):
            self.lyrics_stack.setCurrentIndex(0)
        if hasattr(self, '_view_btn_group'):
            self.lyrics_view_btn.setChecked(True)

    def _reanchor_notes_to_lyrics(self, song):
        """Re-point any coaching note whose anchor_text no longer matches its
        stored word-key span.  Only orphaned / mis-pointing notes are moved;
        correctly placed notes are never disturbed (skip-on-span-match rule)."""
        if not song or not song.coaching_notes:
            return
        lyrics = song.lyrics
        occ = word_occurrences(lyrics)
        def _norm(s):
            return ' '.join(s.split()).lower()
        changed = False
        for n in song.coaching_notes:
            if not n.anchor_text:
                continue
            span = resolve_anchor(lyrics, n.anchor_start, n.anchor_end)
            # Correctly placed already — never disturb it
            if span is not None and _norm(lyrics[span[0]:span[1]]) == _norm(n.anchor_text):
                continue
            res = match_anchor_keys(lyrics, n.anchor_text, occ)
            if res:
                sk, ek, _amb = res
                if (sk, ek) != (n.anchor_start, n.anchor_end):
                    n.anchor_start, n.anchor_end = sk, ek
                    changed = True
        if changed:
            self._schedule_save()

    def _on_song_changed(self, idx):
        if idx < 0 or idx >= len(self.songs) or idx == self.active_index:
            return
        self.active_song.lyrics = self.editor.toPlainText()
        self.active_index = idx
        self._load_active_song()
        self._schedule_save()

    def _on_view_btn_clicked(self, btn):
        """Three-way view switch: Lyrics (0), Notes (1), IPA (2)."""
        idx = self._view_btn_group.id(btn)
        if idx == 0:
            # Lyrics editor — just show it
            self.lyrics_stack.setCurrentIndex(0)
        elif idx == 1:
            # Notes / coaching view — flush editor text first
            self.active_song.lyrics = self.editor.toPlainText()
            self._reanchor_notes_to_lyrics(self.active_song)
            self.coaching_view.set_song(self.active_song)
            self.lyrics_stack.setCurrentIndex(1)
            self.coaching_view.setFocus()   # Ctrl+Z works without an extra click
        elif idx == 2:
            # Interlinear IPA view — flush editor text, rebuild view data
            self.active_song.lyrics = self.editor.toPlainText()
            blocks = self._build_ipa_view_data()
            self.ipa_view.set_view_data(blocks)
            self.ipa_view.set_annotations(self._word_annotations, self._ipa_hints_enabled)
            self.lyrics_stack.setCurrentIndex(2)

    def _on_coaching_toggle(self, checked: bool):
        """Switch between the live editor (page 0) and the coaching view (page 1).
        Kept for backward compatibility; the main UI now uses _on_view_btn_clicked."""
        if checked:
            self.active_song.lyrics = self.editor.toPlainText()
            self.coaching_view.set_song(self.active_song)
            self.lyrics_stack.setCurrentIndex(1)
        else:
            self.lyrics_stack.setCurrentIndex(0)

    def _on_new_song(self):
        name, ok = QInputDialog.getText(
            self, 'New Song', 'Name:', text='Untitled')
        if not ok or not name.strip():
            return
        self.active_song.lyrics = self.editor.toPlainText()
        self.songs.append(Song(name=name.strip()))
        self.active_index = len(self.songs) - 1
        self._load_active_song()
        self._schedule_save()

    def _on_rename_song(self):
        new, ok = QInputDialog.getText(
            self, 'Rename Song', 'Name:', text=self.active_song.name)
        if ok and new.strip():
            self.active_song.name = new.strip()
            self.song_bar.refresh(self.songs, self.active_index)
            self._schedule_save()

    def _on_delete_song(self):
        if len(self.songs) <= 1:
            QMessageBox.information(
                self, 'Cannot Delete',
                'At least one song must remain. Rename or replace this one instead.')
            return
        confirm = QMessageBox.question(
            self, 'Delete Song',
            f'Delete "{self.active_song.name}"? This cannot be undone.',
            QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        del self.songs[self.active_index]
        self.active_index = max(0, self.active_index - 1)
        self._load_active_song()
        self._schedule_save()

    def _on_lyrics_changed(self):
        self.active_song.lyrics = self.editor.toPlainText()
        self._schedule_save()
        self._annotation_timer.start()
        # If IPA view is currently shown, keep it in sync
        if (hasattr(self, 'lyrics_stack') and
                self.lyrics_stack.currentIndex() == 2):
            blocks = self._build_ipa_view_data()
            self.ipa_view.set_view_data(blocks)
            self.ipa_view.set_annotations(self._word_annotations, self._ipa_hints_enabled)

    def _schedule_save(self):
        self._save_timer.start()

    def _persist_songs(self):
        self.store.save(self.songs, self.active_index)

    # ---- Custom IPA ----

    def _on_word_ipa_requested(self, word):
        word_l = word.lower()
        custom = self.active_song.custom_ipa
        current = custom.get(word_l, '')
        if word_l in FUNCTION_WORDS:
            defaults = FUNCTION_WORDS[word_l]
        else:
            raw = ipa.convert(word_l, retrieve_all=True) or []
            defaults = [p for p in raw if p and '*' not in p]
        dlg = CustomIpaDialog(word, current, defaults, self)
        if dlg.exec_() != QDialog.Accepted:
            return
        new = dlg.result_ipa()
        if new is None:  # user cancelled (including cancel on vowel warning)
            return
        if new == '':
            custom.pop(word_l, None)
        else:
            custom[word_l] = new
        self._pron_cache.pop(word_l, None)
        if self._current_block_number >= 0:
            line = self.editor.line_text(self._current_block_number)
            self._update_trajectory(line)
            if self.analysis.word_label.text() == word_l:
                prons = self._cached_pronunciations(word_l)
                self.analysis.show_word(word_l, prons)
        self._schedule_save()
        self._annotation_timer.start()

    # ---- Word handling ----

    def _on_pronunciation_chosen(self, word, idx):
        """Remember the user's preferred pronunciation for *this occurrence only*,
        persist it, and refresh trajectory."""
        key = self._current_clicked_occ_key
        if key is None:
            # No position context (shouldn't normally happen) — fall back to a
            # word-level choice so the selection still takes effect somewhere.
            key = word.lower()
        self._pron_index_cache[key] = idx
        self.active_song.pron_choices[key] = idx
        self._schedule_save()
        self._annotation_timer.start()
        if self._current_block_number >= 0:
            self._update_trajectory(self.editor.line_text(self._current_block_number),
                                    self._current_char_offset)
        if (hasattr(self, 'lyrics_stack') and
                self.lyrics_stack.currentIndex() == 2):
            self.ipa_view.set_view_data(self._build_ipa_view_data())
            self.ipa_view.set_annotations(self._word_annotations, self._ipa_hints_enabled)

    def _context_aware_pronunciations(self, word, next_ipa=None):
        """Apply next-word context rules to select a pronunciation.
        'the'  -> /ði/ before a vowel, /ðə/ before a consonant.
        'a'    -> contemporary default /ə/ before all words; /eɪ/ is an older
                  stage-diction convention (contested in newer coaching) but both
                  forms remain available in the PRONUNCIATIONS panel for a conscious
                  stylistic choice.
        'to'   -> /tu/ before a vowel, /tə/ otherwise.
        """
        prons = self._cached_pronunciations(word)
        wl = word.lower()
        if not next_ipa or wl not in ('the', 'to'):
            return prons
        vowel_next = ipa_leading_vowel(next_ipa) is not None
        if wl == 'the':
            return ['ði'] if vowel_next else ['ðə']
        if wl == 'to':
            return ['tu'] if vowel_next else ['tə']
        return prons

    def _get_next_word_ipa(self, line_text: str, clicked_word: str,
                           clicked_offset: int = -1) -> Optional[str]:
        """Return the preferred IPA for the word immediately after *clicked_word*
        in *line_text*, or None at a punctuation boundary.
        Uses *clicked_offset* (char position in line) to disambiguate repeated words.
        """
        matches = list(WORD_RE.finditer(line_text))
        for i, m in enumerate(matches):
            # Match by position when available, else by string (fallback)
            pos_match = (clicked_offset >= 0 and
                         m.start() <= clicked_offset < m.end())
            str_match = (clicked_offset < 0 and
                         m.group().lower() == clicked_word.lower())
            if (pos_match or str_match) and i + 1 < len(matches):
                between = line_text[m.end():matches[i + 1].start()]
                if re.search(r'[,;:.!?]', between):
                    return None
                nxt = matches[i + 1]
                nw = nxt.group()
                next_prons = self._context_aware_pronunciations(nw, None)
                if not next_prons:
                    return None
                nxt_abs = self._abs_offset(self._current_block_number, nxt.start())
                preferred = self._preferred_index(nw.lower(), nxt_abs)
                return next_prons[min(preferred, len(next_prons) - 1)]
        return None


    # ---- Sequential playback speed presets ----

    # (label, gap_ms) — gap inserted between vowels after audio finishes
    _SEQ_SPEED_PRESETS = [
        ('Fast',   320),
        ('Faster', 170),
    ]

    def _on_seq_speed_changed(self, index: int):
        ms = self._seq_speed_combo.itemData(index)
        if ms is None:
            return
        self._seq_hold_ms = int(ms)
        self._seq_hold.setInterval(self._seq_hold_ms)
        self.settings.setValue('seqHoldMs', self._seq_hold_ms)

    # ---- Inline annotation hints ----

    # Hint type labels for display
    _HINT_TYPE_LABELS = {
        'legato':      'Legato links',
        'vowel_glide': 'Vowel glides (anti-glottal)',
        'crash':       'Consonant crashes',
        'r_toxicity':  'R toxicity',
        'dark_l':      'Dark L trap',
        'glottal':     'Phrase-initial glottal',
        'plosive':     'Plosive exits',
        'nasal':       'Nasal exits',
        'approx':      'Approximant exits',
        'fricative':   'Fricative exits',
        'yod':         'Yod-coalescence',
        'ng_release':  '/ŋ/ release (no G tail)',
        'diphthong':   'Spurious diphthongization',
        'aspiration':  '/h/ aspiration at height',
    }

    def _build_style_menu(self) -> QMenu:
        menu = QMenu(self)
        self._act_style_classical = QAction('Classical / Legit', menu)
        self._act_style_classical.setCheckable(True)
        self._act_style_classical.triggered.connect(
            lambda: self._on_style_changed('classical'))
        menu.addAction(self._act_style_classical)
        self._act_style_mt = QAction('MT / CCM / Pop', menu)
        self._act_style_mt.setCheckable(True)
        self._act_style_mt.triggered.connect(
            lambda: self._on_style_changed('mt_ccm'))
        menu.addAction(self._act_style_mt)
        return menu

    def _update_style_btn_label(self):
        style = self.active_song.style if hasattr(self, 'songs') else 'classical'
        if style == 'mt_ccm':
            self.style_btn.setText('MT/CCM')
            if hasattr(self, '_act_style_mt'):
                self._act_style_mt.setChecked(True)
                self._act_style_classical.setChecked(False)
        else:
            self.style_btn.setText('CLASSICAL')
            if hasattr(self, '_act_style_classical'):
                self._act_style_classical.setChecked(True)
                self._act_style_mt.setChecked(False)

    def _on_style_changed(self, style: str):
        self.active_song.style = style
        self._update_style_btn_label()
        self._schedule_save()
        self._compute_annotations()
        # Rerun analysis panel tips for current word if any
        word = self.analysis.word_label.text()
        if word and word != 'Click a word to begin':
            abs_start = self._abs_offset(self._current_block_number,
                                         self._current_char_offset)
            prons = self._context_aware_pronunciations(word, self._get_next_word_ipa(
                self.editor.line_text(self._current_block_number), word)
                if self._current_block_number >= 0 else None)
            preferred = self._preferred_index(word.lower(), abs_start)
            if prons:
                self.analysis._update_word_tips(prons[min(preferred, len(prons)-1)])

    def _build_hints_menu(self) -> QMenu:
        menu = QMenu(self)
        # Master on/off toggle at the top
        self._act_hints_enabled = QAction('Hints enabled', menu)
        self._act_hints_enabled.setCheckable(True)
        self._act_hints_enabled.setChecked(True)
        self._act_hints_enabled.triggered.connect(self._on_hints_toggled)
        menu.addAction(self._act_hints_enabled)
        menu.addSeparator()
        # Convenience bulk actions
        a_all = QAction('Enable all types', menu)
        a_all.triggered.connect(lambda: self._set_all_hint_types(True))
        menu.addAction(a_all)
        a_none = QAction('Disable all types', menu)
        a_none.triggered.connect(lambda: self._set_all_hint_types(False))
        menu.addAction(a_none)
        menu.addSeparator()
        # Per-type checkable actions
        for tip_type, label in self._HINT_TYPE_LABELS.items():
            act = QAction(label, menu)
            act.setCheckable(True)
            act.setChecked(tip_type in self._enabled_hint_types)
            act.triggered.connect(
                lambda checked, t=tip_type: self._on_hint_type_toggled(t, checked))
            menu.addAction(act)
        return menu

    def _update_hints_btn_label(self):
        n = len(self._enabled_hint_types)
        total = len(self._HINT_TYPE_LABELS)
        if not self._annotations_enabled:
            self.hints_btn.setText('HINTS (off)')
        elif n == total:
            self.hints_btn.setText('HINTS')
        else:
            self.hints_btn.setText(f'HINTS ({n}/{total})')

    def _set_all_hint_types(self, enabled: bool):
        if enabled:
            self._enabled_hint_types = set(self._HINT_TYPE_LABELS.keys())
        else:
            self._enabled_hint_types = set()
        # Sync checkmarks in menu
        for act in self._hints_menu.actions():
            if act.isCheckable():
                act.setChecked(enabled)
        self._update_hints_btn_label()
        self._compute_annotations()

    def _on_hint_type_toggled(self, tip_type: str, checked: bool):
        if checked:
            self._enabled_hint_types.add(tip_type)
        else:
            self._enabled_hint_types.discard(tip_type)
        self._update_hints_btn_label()
        self._compute_annotations()

    def _on_hints_toggled(self, checked: bool):
        self._annotations_enabled = checked
        # Keep the menu action checkmark in sync
        if hasattr(self, '_act_hints_enabled'):
            self._act_hints_enabled.setChecked(checked)
        self._update_hints_btn_label()
        if checked:
            self._compute_annotations()
        else:
            self.editor.clear_annotations()

    def _on_annotation_dismissed(self, word_lower: str):
        self.active_song.dismissed_tips.add(word_lower)
        self._schedule_save()
        self._compute_annotations()

    def _on_reset_dismissed_hints(self):
        self.active_song.dismissed_tips.clear()
        self._schedule_save()
        self._compute_annotations()

    def _compute_annotations(self):
        """Scan all lyrics and compute inline diction annotations."""
        if not self._annotations_enabled:
            self.editor.clear_annotations()
            if hasattr(self, 'ipa_view'):
                self.ipa_view.set_annotations([], self._ipa_hints_enabled)
            return
        doc = self.editor.document()
        dismissed = self.active_song.dismissed_tips
        song_style = getattr(self.active_song, 'style', 'classical')
        annotations = []

        for block_num in range(doc.blockCount()):
            block = doc.findBlockByNumber(block_num)
            line_text = block.text()
            matches = list(WORD_RE.finditer(line_text))

            for i, m in enumerate(matches):
                word = m.group()
                word_l = word.lower()
                if word_l in dismissed:
                    continue

                # ── glottal onset check (this word opens a phrase) ────────
                # True if word is first on the line, or preceded by punctuation.
                # Stored as a pending annotation so a regular tip on the same
                # (block, start, end) range takes priority (Bug 2 fix).
                glottal_annotation = None
                phrase_opener = (i == 0)
                if not phrase_opener and i > 0:
                    before = line_text[matches[i-1].end():m.start()]
                    phrase_opener = bool(re.search(r'[,;:.!?]', before))
                if phrase_opener and 'glottal' in self._enabled_hint_types:
                    # Only flag if the word starts with a vowel
                    prons_check = self._cached_pronunciations(word)
                    preferred_c = self._preferred_index(word_l, block.position() + m.start())
                    pron_check = prons_check[min(preferred_c, len(prons_check)-1)] if prons_check else ''
                    if pron_check and ipa_leading_vowel(pron_check) is not None:
                        glottal_annotation = WordAnnotation(
                            word=word, word_lower=word_l,
                            block=block_num, start=m.start(), end=m.end(),
                            abs_start=block.position() + m.start(),
                            abs_end=block.position() + m.end(),
                            tip_type='glottal',
                            tip_text=('Phrase-initial vowel \u2014 if you intend a glottal attack here '
                                      'for dramatic effect, that is a valid choice. '
                                      'If not, use a clean balanced onset (appoggio): '
                                      'let the breath flow a split-second before the tone '
                                      'to avoid an unintentional glottal strike.'),
                            color=ANN_COLOR['glottal'],
                            bg_color=ANN_BG['glottal'],
                        )

                # ── next-word context ─────────────────────────────────────
                next_ipa = None
                has_punct_boundary = False
                if i + 1 < len(matches):
                    between = line_text[m.end():matches[i + 1].start()]
                    has_punct_boundary = bool(re.search(r'[,;:.!?]', between))
                    nxt = matches[i + 1]
                    nw = nxt.group()
                    np = self._cached_pronunciations(nw)
                    next_ipa = np[min(self._preferred_index(nw.lower(), block.position() + nxt.start()), len(np) - 1)] if np else None

                prons = self._context_aware_pronunciations(
                    word, None if has_punct_boundary else next_ipa)
                if not prons:
                    continue
                preferred = self._preferred_index(word_l, block.position() + m.start())
                pron = prons[min(preferred, len(prons) - 1)]
                # ── classify — single source of truth, shared with the word
                #    detail panel and cheat-sheet export so all three agree
                tips = compute_word_tips(
                    pron, next_ipa, has_punct_boundary,
                    song_style, self._enabled_hint_types)

                if not tips:
                    # No regular tip — emit the pending glottal onset note if any
                    if glottal_annotation:
                        annotations.append(glottal_annotation)
                    continue

                # Regular tip(s) fire on this range — skip glottal to avoid overlap
                for tt, txt in tips:
                    annotations.append(WordAnnotation(
                        word=word, word_lower=word_l,
                        block=block_num, start=m.start(), end=m.end(),
                        abs_start=block.position() + m.start(),
                        abs_end=block.position() + m.end(),
                        tip_type=tt, tip_text=txt,
                        color=ANN_COLOR[tt],
                        bg_color=ANN_BG[tt],
                    ))

        self._word_annotations = annotations
        self.editor.set_annotations(annotations)
        if hasattr(self, 'ipa_view'):
            self.ipa_view.set_annotations(annotations, self._ipa_hints_enabled)
        self._update_missing_ipa_indicator()

    def _on_word_sustain_toggled(self, word_lower: str):
        sw = self.active_song.sustained_words
        if word_lower in sw:
            sw.discard(word_lower)
        else:
            sw.add(word_lower)
        self._schedule_save()
        # Re-show analysis tips if this is the currently selected word
        if self.analysis.word_label.text().lower() == word_lower:
            self.analysis._show_sustained_tips(
                word_lower in self.active_song.sustained_words,
                self.analysis._current_vowel)

    def _on_word_clicked(self, word, block_number, char_offset=-1):
        self._current_block_number = block_number
        line = self.editor.line_text(block_number)
        self._current_char_offset = char_offset
        abs_start = self._abs_offset(block_number, char_offset)
        self._current_clicked_occ_key = self._occ_key(word.lower(), abs_start)
        next_ipa = self._get_next_word_ipa(line, word, char_offset)
        prons = self._context_aware_pronunciations(word, next_ipa)
        preferred = self._preferred_index(word.lower(), abs_start)
        self.analysis.show_word(
            word, prons, initial_index=preferred, next_ipa=next_ipa,
            song_style=getattr(self.active_song, 'style', 'classical'),
            enabled_hints=self._enabled_hint_types)
        self.analysis._show_sustained_tips(
            word.lower() in self.active_song.sustained_words,
            self.analysis._current_vowel)
        self._update_trajectory(line, char_offset)

    def _cached_pronunciations(self, word):
        cache_key = word.lower()
        if cache_key not in self._pron_cache:
            self._pron_cache[cache_key] = get_pronunciations(
                word, self.active_song.custom_ipa)
        return self._pron_cache[cache_key]

    # ---- Per-occurrence pronunciation choice ----------------------------------
    # A pronunciation choice belongs to a specific occurrence of a word, not to
    # every copy of that word in the song. Occurrences are identified by
    # "word#N" where N is the 0-based index of the occurrence among all matches
    # of the same word across the whole lyrics. This is stable against edits
    # elsewhere in the document (adding text before line 1 does not shift the
    # occurrence index of a word unless you add another copy of that same word).

    def _abs_offset(self, block_number: int, char_offset: int) -> int:
        """Document position for a (block, in-block offset) pair, or -1."""
        if block_number < 0 or char_offset < 0:
            return -1
        block = self.editor.document().findBlockByNumber(block_number)
        if not block.isValid():
            return -1
        return block.position() + char_offset

    def _occ_key(self, word_lower: str, abs_start: int) -> Optional[str]:
        """Occurrence key 'word#N' for the word starting at *abs_start*."""
        if abs_start is None or abs_start < 0:
            return None
        text = self.editor.toPlainText()
        occ = sum(1 for m in WORD_RE.finditer(text)
                  if m.group().lower() == word_lower and m.start() < abs_start)
        return f'{word_lower}#{occ}'

    def _preferred_index(self, word_lower: str, abs_start: int = -1) -> int:
        """Preferred pronunciation index: per-occurrence choice first, then a
        legacy word-level choice, else 0."""
        pc = self._pron_index_cache
        occ_key = self._occ_key(word_lower, abs_start)
        if occ_key is not None and occ_key in pc:
            return pc[occ_key]
        if word_lower in pc:  # legacy / word-level default
            return pc[word_lower]
        return 0

    def _update_trajectory(self, line_text, clicked_offset: int = -1):
        items = []
        word_idx = 0
        clicked_word = self.analysis.word_label.text()
        clicked_word_idx = -1
        matches = list(WORD_RE.finditer(line_text))
        block = self.editor.document().findBlockByNumber(self._current_block_number)
        line_base = block.position() if block.isValid() else -1
        for i, m in enumerate(matches):
            w = m.group()
            abs_start = (line_base + m.start()) if line_base >= 0 else -1
            # Next word's IPA for context-aware function-word resolution
            next_ipa = None
            if i + 1 < len(matches):
                nxt = matches[i + 1]
                nw_word = nxt.group()
                np = self._cached_pronunciations(nw_word)
                nxt_abs = (line_base + nxt.start()) if line_base >= 0 else -1
                next_ipa = np[min(self._preferred_index(nw_word.lower(), nxt_abs), len(np) - 1)] if np else None
            prons = self._context_aware_pronunciations(w, next_ipa)
            if not prons:
                word_idx += 1
                continue
            preferred_idx = self._preferred_index(w.lower(), abs_start)
            pron = prons[min(preferred_idx, len(prons) - 1)]
            syls = find_syllable_vowels(pron)
            for sym, _, _ in syls:
                items.append((sym, word_idx))
            # Match by char position when available; fall back to first string match.
            # This disambiguates repeated words on the same line (Bug 4 fix).
            pos_match = (clicked_offset >= 0 and m.start() <= clicked_offset < m.end())
            str_match = (clicked_offset < 0 and w.lower() == clicked_word.lower())
            if (pos_match or str_match) and clicked_word_idx == -1:
                clicked_word_idx = word_idx
            word_idx += 1
        self._current_line_items = items
        self._current_clicked_word_idx = clicked_word_idx
        self.trajectory.set_phrase(items)
        self._update_chiaroscuro(items)
        self._update_breath_and_sibilance(line_text)

    def _update_breath_and_sibilance(self, line_text: str):
        """Scan line IPA for unvoiced consonant density (breath leak).
        Uses the same while-loop affricate-aware tokenizer as ipa_trailing_consonants
        so tʃ/dʒ are counted as one phone, not double- or triple-counted.
        """
        matches = list(WORD_RE.finditer(line_text))
        block = self.editor.document().findBlockByNumber(self._current_block_number)
        line_base = block.position() if block.isValid() else -1
        all_phones = []
        for m in matches:
            prons = self._cached_pronunciations(m.group())
            if not prons:
                continue
            abs_start = (line_base + m.start()) if line_base >= 0 else -1
            preferred = self._preferred_index(m.group().lower(), abs_start)
            pron = prons[min(preferred, len(prons) - 1)]
            # Walk character by character; consume digraphs in one step
            i = 0
            while i < len(pron):
                two = pron[i:i+2]
                if two in ('tʃ', 'dʒ'):
                    all_phones.append(two); i += 2
                elif pron[i] in IPA_ALL_CONS:
                    all_phones.append(pron[i]); i += 1
                else:
                    i += 1

        if all_phones:
            unvoiced = sum(1 for p in all_phones if p in IPA_UNVOICED)
            ratio = unvoiced / len(all_phones)
            if ratio >= 0.55:
                self.breath_label.setText(
                    f'\u2697 High unvoiced density ({ratio:.0%} of consonants) \u2014 '
                    f'these open the glottis and release air. '
                    f'Engage breath support actively throughout; '
                    f'resist letting sub-glottal pressure drop between words.')
                self.breath_label.setVisible(True)
                return
        self.breath_label.setVisible(False)

    def _update_chiaroscuro(self, items):
        """Show a brightness-balance warning for the current phrase."""
        if not items:
            self.chiaroscuro_label.setVisible(False)
            return
        avg = sum(brightness(s) for s, _ in items) / len(items)
        if avg > 0.63:
            msg = (f'Very bright phrase (∅ {avg:.0%}) — risk of shrill resonance. '
                   f'Counter-balance: round lips on eligible vowels, '
                   f'or modify toward darker variants at high pitch.')
            self.chiaroscuro_label.setText(msg)
            self.chiaroscuro_label.setVisible(True)
        elif avg < 0.37:
            msg = (f'Very dark phrase (∅ {avg:.0%}) — risk of muffled tone. '
                   f'Keep the sound forward; resist swallowing. '
                   f'Brighten on eligible vowels to restore chiaroscuro balance.')
            self.chiaroscuro_label.setText(msg)
            self.chiaroscuro_label.setVisible(True)
        else:
            self.chiaroscuro_label.setVisible(False)

    def _on_trajectory_cell_clicked(self, cell_index: int):
        """A cell in the trajectory bar was clicked — select the corresponding
        word and highlight the appropriate syllable in the analysis panel.
        """
        if not self._current_line_items or cell_index >= len(self._current_line_items):
            return
        vsym, word_idx = self._current_line_items[cell_index]
        # Count which syllable index within that word this cell is
        syl_idx = sum(1 for _, wi in self._current_line_items[:cell_index]
                      if wi == word_idx)
        self.trajectory.set_highlight(cell_index)
        # Drive the analysis panel to that syllable if it's already showing the word
        if self._current_clicked_word_idx == word_idx:
            self.analysis.select_vowel_at(syl_idx)

    def _on_vowel_selected_in_analysis(self, syllable_idx):
        if not self._current_line_items:
            return
        if self._current_clicked_word_idx < 0:
            return
        target = -1
        running = 0
        for i, (_, wi) in enumerate(self._current_line_items):
            if wi == self._current_clicked_word_idx:
                if running == syllable_idx:
                    target = i
                    break
                running += 1
        self.trajectory.set_highlight(target)

    def _resolve_audio(self, sym):
        """Return the audio file path for *sym*, or None if none exists."""
        candidates = [sym]
        if sym in DIPHTHONGS:
            candidates.append(DIPHTHONGS[sym].primary)
        # R-colored vowels fall back to their base vowel if no dedicated audio
        if sym == 'ɝ':
            candidates.append('ɜ')
        elif sym == 'ɚ':
            candidates.append('ə')
        for c in candidates:
            audio = self._resource_path(path.join('Audio', f'{c}.mp3'))
            if path.exists(audio):
                return audio
        if sym not in self._missing_audio_warned:
            self._missing_audio_warned.add(sym)
            print(f'Audio: no file found for /{sym}/ (tried: '
                  f'{[path.join("Audio", f"{c}.mp3") for c in candidates]})',
                  file=sys.stderr)
        return None

    def _play_vowel(self, sym):
        # A single vowel play cancels any sequence currently in progress.
        self._vowel_seq_active = False
        audio = self._resolve_audio(sym)
        if audio:
            self.player.setMedia(QMediaContent(QUrl.fromLocalFile(audio)))
            self.player.play()

    # ---- Sequential vowel playback (Play line vowels) ----

    def _play_line_vowels(self):
        """Play every vowel in the current line in order, left to right."""
        syms = [sym for sym, _ in self._current_line_items]
        if not syms:
            QMessageBox.information(
                self, 'No Line Selected',
                'Click a word in a line first, then play its vowels in sequence.')
            return
        self._vowel_seq = syms
        self._vowel_seq_idx = 0
        self._vowel_seq_active = True
        self._play_seq_current()

    def _play_seq_current(self):
        if not self._vowel_seq_active:
            return
        if self._vowel_seq_idx >= len(self._vowel_seq):
            self._vowel_seq_active = False
            self.trajectory.set_highlight(-1)
            return
        sym = self._vowel_seq[self._vowel_seq_idx]
        self.trajectory.set_highlight(self._vowel_seq_idx)
        audio = self._resolve_audio(sym)
        if audio:
            self.player.setMedia(QMediaContent(QUrl.fromLocalFile(audio)))
            self.player.play()
            self._seq_hold.start()   # cap this vowel's sounding duration
        else:
            # No audio for this vowel — skip straight to the next one.
            self._advance_vowel_seq()

    def _advance_vowel_seq(self):
        self._vowel_seq_idx += 1
        self._play_seq_current()

    def _on_seq_hold_elapsed(self):
        """Hold-cap timer fired — stop the clip and move to the next vowel."""
        if not self._vowel_seq_active:
            return
        self.player.stop()
        self._advance_vowel_seq()

    def _on_media_status(self, status):
        """Clip ended before the hold cap — cancel the cap and advance early."""
        if status == QMediaPlayer.EndOfMedia and self._vowel_seq_active:
            self._seq_hold.stop()
            self._advance_vowel_seq()

    @staticmethod
    def _resource_path(relative):
        base = getattr(sys, '_MEIPASS',
                       path.dirname(path.abspath(__file__)))
        return path.join(base, relative)

    # ---- Bulk import / prompt generation ----

    def _on_bulk_import(self):
        dlg = BulkImportDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return
        data = dlg.parsed()
        if data is None:
            QMessageBox.warning(
                self, 'Invalid JSON',
                "Couldn't parse that as a JSON object mapping words to IPA.")
            return
        if not data:
            return
        self.active_song.custom_ipa.update(data)
        self._pron_cache.clear()
        if self._current_block_number >= 0:
            line = self.editor.line_text(self._current_block_number)
            self._update_trajectory(line)
        QMessageBox.information(
            self, 'Imported',
            f'Imported {len(data)} custom IPA entries.')
        self._schedule_save()
        self._annotation_timer.start()

    def _missing_ipa_words(self):
        """Lowercase words in the lyrics with no usable IPA (not custom, not a
        function word, and the dictionary returns nothing), preserving order."""
        lyrics = self.editor.toPlainText()
        seen = set()
        unknown = []
        for m in WORD_RE.finditer(lyrics):
            w = m.group().lower()
            if w in seen:
                continue
            seen.add(w)
            if w in self.active_song.custom_ipa:
                continue
            if w in FUNCTION_WORDS:
                continue
            raw = ipa.convert(w, retrieve_all=True) or []
            cleaned = [p for p in raw if p and '*' not in p]
            if not cleaned:
                unknown.append(w)
        return unknown

    def _update_missing_ipa_indicator(self):
        """Show/hide the lyrics-header badge that flags words lacking IPA."""
        if not hasattr(self, 'missing_ipa_btn'):
            return
        n = len(self._missing_ipa_words())
        if n:
            self.missing_ipa_btn.setText(
                f'⚠ {n} word needs IPA' if n == 1
                else f'⚠ {n} words need IPA')
            self.missing_ipa_btn.setVisible(True)
        else:
            self.missing_ipa_btn.setVisible(False)

    def _on_check_missing_ipa(self):
        """Report words with no IPA and offer to start the prompt → import flow."""
        unknown = self._missing_ipa_words()
        if not unknown:
            QMessageBox.information(
                self, 'IPA Check',
                'Every word in this song resolves to an IPA pronunciation. '
                'Nothing is missing.')
            return
        preview = ', '.join(unknown[:25]) + ('…' if len(unknown) > 25 else '')
        resp = QMessageBox.question(
            self, 'Missing IPA',
            f'{len(unknown)} word(s) have no IPA pronunciation:\n\n{preview}\n\n'
            'Generate an IPA prompt for these now? Paste it into an AI, then '
            'use Song → Bulk Import IPAs… with the returned JSON.',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if resp == QMessageBox.Yes:
            self._on_generate_prompt()

    def _on_generate_prompt(self):
        lyrics = self.editor.toPlainText()
        unknown = self._missing_ipa_words()

        prompt = (
            "I'm singing the following song. Please provide an IPA "
            "transcription for each of the unrecognized words listed "
            "below — proper nouns, foreign names, numbers, and so on. "
            "Use standard IPA. Return JSON only: a single object mapping "
            "the word (lowercase) to the IPA string. No prose, no code "
            "fences.\n\n"
            f"Song: {self.active_song.name}\n\n"
            "Words to transcribe:\n"
            + "\n".join(f"- {w}" for w in unknown)
            + "\n\nLyrics for context:\n"
            + lyrics
        )
        clipboard = QApplication.clipboard()
        clipboard.setText(prompt)
        QMessageBox.information(
            self, 'Prompt Copied',
            f'A prompt for {len(unknown)} unrecognized word(s) has been '
            f'copied to your clipboard. Paste it to an AI, then use '
            f'Song → Bulk Import IPAs… with the returned JSON.')

    def _on_generate_direction_prompt(self):
        lyrics = self.editor.toPlainText().strip()
        if not lyrics:
            QMessageBox.information(
                self, 'Nothing to Research',
                "This song has no lyrics yet. Add lyrics before generating "
                "a direction prompt.")
            return

        # Optional: let the singer name their role/voice rather than forcing the
        # AI to guess it (the guess is the riskiest part of the whole prompt).
        role, ok = QInputDialog.getText(
            self, 'Who are you singing?',
            'Character or voice part you are singing (optional).\n'
            'Leave blank to let the AI infer it from the lyrics.',
            text='')
        if not ok:
            return
        role = role.strip()

        name = self.active_song.name
        placeholder_names = {'Untitled', 'New Song'}
        if name in placeholder_names:
            title_note = (
                f'("{name}" may be a placeholder title — '
                f'please identify the work from the lyrics alone)'
            )
        else:
            title_note = ''

        raw_style = getattr(self.active_song, 'style', 'classical')
        if raw_style == 'mt_ccm':
            style_phrase = 'musical theatre / CCM / pop'
        else:
            style_phrase = 'classical / legit'

        title_line = f'"{name}"' + (f' {title_note}' if title_note else '')

        # Fold in the work I have already done in this app so the singing and
        # phrasing advice is grounded in my actual choices, not generic rules.
        song = self.active_song
        present = song._present_words()
        custom = {k: v for k, v in song.custom_ipa.items() if k in present}
        sustained = sorted(w for w in song.sustained_words if w in present)
        context_bits = []
        if custom:
            pairs = ', '.join(f'{w} = /{v}/' for w, v in sorted(custom.items()))
            context_bits.append(
                "Pronunciations I have already fixed for this song (treat these "
                f"as given — do not re-transcribe them): {pairs}.")
        if sustained:
            context_bits.append(
                "Words I am holding as sustained notes (long tones — your singing "
                "and phrasing notes should give these particular attention): "
                f"{', '.join(sustained)}.")
        diction_context = ('\n\n' + '\n\n'.join(context_bits)) if context_bits else ''

        # Step B varies depending on whether I named my role.
        if role:
            step_b = (
                f"Step B — Character. I am singing: {role}. Confirm this against "
                f"the score or libretto and attribute my lines accordingly. If "
                f"the lyrics clearly do not fit that role, tell me before "
                f"proceeding. All acting and singing direction below is for this "
                f"role only.\n\n")
        else:
            step_b = (
                "Step B — Character identification. From the lines provided, "
                "determine which single character I am most likely playing. State "
                "that character's name and explain your reasoning in one sentence. "
                "All acting and singing direction below must be for that character "
                "only. If you cannot determine which character I am playing, say "
                "so and ask before proceeding.\n\n")

        prompt = (
            f"You are a vocal coach, stage director, and music scholar. "
            f"I am preparing to sing the song below and need research and "
            f"performance direction. My broad singing discipline is "
            f"{style_phrase}, but that is background only — ground your advice in "
            f"the specific vocal tradition and casting conventions of this "
            f"particular role and work.\n\n"
            f"Accuracy matters more than completeness. Where you are not sure of "
            f"a fact — the work's identity, a recording, a musical detail — say "
            f"so plainly rather than inventing it, and use web search to verify "
            f"where you can. I am still building my technical vocabulary, so "
            f"briefly gloss any specialist term in plain language the first time "
            f"you use it.\n\n"
            f"Song title: {title_line}\n\n"
            f"Lyrics (verbatim, between the markers):\n"
            f"<lyrics>\n{lyrics}\n</lyrics>"
            f"{diction_context}\n\n"
            f"BEFORE YOU WRITE ANYTHING ELSE, do these two steps and state your "
            f"findings at the top of your response:\n\n"
            f"Step A — Line attribution. Look up the score or libretto for this "
            f"number (web search if you can). Identify every character who sings "
            f"in it and label which lines belong to whom. Do not assume all "
            f"lyrics are sung by one character. If a line is shared, spoken, or "
            f"you cannot determine its speaker with confidence, flag it. Do not "
            f"guess — a wrong attribution corrupts everything that follows.\n\n"
            f"{step_b}"
            f"With those resolved, respond in plain prose under the numbered "
            f"section headers below. No JSON, no code fences, no markdown tables "
            f"in sections 1–8. "
            f"Cite recordings as performer + year + medium (cast album, film, "
            f"broadcast), and only cite ones you are confident are real. If a "
            f"section does not apply, say so briefly rather than padding.\n\n"
            f"A note on the music: you have the lyrics, not the score. For "
            f"well-known repertoire you may know the melody, rhythm, and dynamics "
            f"or be able to look them up — use that. But only assert a specific "
            f"musical fact (a high note, a belt, a held forte, the tessitura, a "
            f"ritardando) when you can actually verify it from the score or a "
            f"recording. When you are inferring from the words alone, say so and "
            f"phrase it conditionally. Emphasis and stress that follow from the "
            f"meaning of the text are always fair game.\n\n"
            f"1. Identification\n"
            f"Name the work and confirm which character I am singing. Note an "
            f"edition, key, or transposition only if it affects diction or which "
            f"vowels land on which pitches. Keep this short — I do not need the "
            f"composer's biography, premiere history, or production lineage. If "
            f"you cannot identify the work with confidence, say so and stop "
            f"rather than inventing context.\n\n"
            f"2. Dramatic Context\n"
            f"Briefly: my character's situation — who they are singing to or "
            f"about, where this number sits in the show, and what immediately "
            f"precedes and follows it. For art song or Lieder, give the poetic "
            f"context instead: poet, source poem, and the speaker's situation.\n\n"
            f"3. Emotional Arc\n"
            f"Track how my character's inner state moves across the song. Mark "
            f"every turning point by the lyric phrase where it occurs — not by "
            f"bar number. Detailed enough that I can annotate a printed lyric "
            f"sheet.\n\n"
            f"4. Phrasing and Expression\n"
            f"Working phrase by phrase, suggest where to stress, lean, grow, and "
            f"recede; which words carry the line; and where to breathe so the "
            f"phrasing serves the sense. Derive emphasis and stress from the "
            f"meaning of the text (always available to you). Tie dynamics and "
            f"shaping to the actual music only where you can verify it — "
            f"otherwise mark the suggestion as conditional per the note above.\n\n"
            f"5. Acting Direction\n"
            f"Concrete, beat-by-beat acting notes for my lines only: where to "
            f"lean in, where to pull back, what subtext shifts a line's reading, "
            f"what stillness or gesture serves a moment. No generic notes like "
            f"'feel it deeply'. Anchor every note to a specific word or phrase.\n\n"
            f"CRITICAL CONSTRAINT on Section 5: every acting note must be "
            f"compatible with what the music as written demands at that moment "
            f"(subject to the note above on verifying musical facts). If the "
            f"music calls for a belt, a sustained forte, or a climactic high "
            f"note, do not direct me to pull back, go quiet, or make the moment "
            f"smaller. Instead, show how my character's inner state justifies and "
            f"fuels the vocal intensity the music requires. The acting serves the "
            f"music; it does not override it.\n\n"
            f"6. Singing Direction\n"
            f"Research the specific vocal tradition for this role: how it has "
            f"been cast and coached, what technique authoritative productions and "
            f"recordings use, the expected vocal colour and weight. Name the "
            f"technique explicitly (for example: mix-belt at the break, legato "
            f"sostenuto through the phrase, speech-quality onset on the verse), "
            f"glossing each. Address breath strategy on long phrases and any "
            f"vowel modification the tessitura demands. Where I have marked "
            f"sustained words or fixed pronunciations above, build your advice "
            f"around those.\n\n"
            f"7. Tradition and Interpretation\n"
            f"Describe well-known recordings or stage interpretations and how "
            f"they differ, naming specific singers and productions you are "
            f"confident are real. Note where the standard reading has been "
            f"challenged or where multiple defensible readings coexist.\n\n"
            f"8. Pitfalls\n"
            f"Common mistakes specific to this song and role — rushed phrases, "
            f"misplaced emphases, vowel traps, clichéd dramatic choices. For each, "
            f"name the word or line, say why the mistake happens, and what to do "
            f"instead.\n\n"
            f"After the eight prose sections, output exactly one import block — "
            f"this only, nothing after it:\n"
            f"NOTES-FOR-IMPORT\n"
            f"<<<\n"
            + '{"notes": [{"anchor": "<span copied verbatim from the lyrics>",'
              ' "note": "<short direction>"}]}\n'
            + f">>>\n\n"
            f"Rules for the import block: anchor must be copied verbatim from "
            f"the lyrics between the <lyrics> markers above (same words, "
            f"capitalisation, punctuation) so it matches by exact text. Prefer "
            f"the shortest unambiguous span; extend with a neighbouring word if "
            f"the span repeats elsewhere. note is one actionable direction under "
            f"~15 words (e.g. 'go loud', 'darken the vowel', 'spit the "
            f"consonant'). Draw 5\u201320 notes from sections 4 and 5 only. "
            f"This JSON block is the only place JSON is allowed in your response."
        )

        QApplication.clipboard().setText(prompt)
        QMessageBox.information(
            self, 'Direction Prompt Copied',
            "A research and direction prompt has been copied to your clipboard.\n\n"
            "Paste it into an AI assistant. After the eight prose sections the "
            "response will contain a NOTES-FOR-IMPORT block that you can bring "
            "in via Song \u2192 Import Coaching Notes\u2026")

    def _on_import_coaching_notes(self):
        """Open paste dialog, parse NOTES-FOR-IMPORT block, append CoachingNotes."""
        if not self.active_song:
            QMessageBox.information(self, 'No Song', 'No active song to import into.')
            return

        dlg = _CoachingImportDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return

        raw = dlg.edit.toPlainText()

        # Extract JSON between <<< and >>>
        import re as _re
        m = _re.search(r'<<<\s*(.*?)\s*>>>', raw, _re.DOTALL)
        if not m:
            QMessageBox.warning(
                self, 'Import Failed',
                'No NOTES-FOR-IMPORT block found.\n\n'
                'Make sure the text contains the block delimited by '
                '<<< and >>>.')
            return

        json_text = m.group(1).strip()
        try:
            import json as _json
            data = _json.loads(json_text)
        except Exception as exc:
            QMessageBox.warning(
                self, 'Import Failed',
                f'Could not parse the JSON block:\n{exc}')
            return

        notes_raw = data.get('notes', [])
        if not isinstance(notes_raw, list):
            QMessageBox.warning(self, 'Import Failed',
                                'Expected a JSON object with a "notes" list.')
            return

        lyrics = self.active_song.lyrics
        occ = word_occurrences(lyrics)  # list of (match, "word#N")

        # Snapshot BEFORE appending so one Ctrl+Z reverts the whole import batch.
        pre_import = [CoachingNote(n.anchor_start, n.anchor_end, n.text)
                      for n in self.active_song.coaching_notes]

        matched = 0
        ambiguous = 0
        unmatched_anchors = []

        for entry in notes_raw:
            anchor = (entry.get('anchor') or '').strip()
            note_text = (entry.get('note') or '').strip()
            if not anchor or not note_text:
                continue

            res = match_anchor_keys(lyrics, anchor, occ)
            if res is None:
                unmatched_anchors.append(anchor)
                continue

            start_key, end_key, is_ambiguous = res

            self.active_song.coaching_notes.append(
                CoachingNote(start_key, end_key, note_text, anchor_text=anchor))

            if is_ambiguous:
                ambiguous += 1
            else:
                matched += 1

        # Refresh coaching view and persist
        if hasattr(self, 'coaching_view'):
            self.coaching_view.set_song(self.active_song)
            # Push pre-import snapshot AFTER set_song so same-song refresh
            # doesn't clear the stack, and one Ctrl+Z removes the whole batch.
            if (matched + ambiguous) > 0:
                self.coaching_view.push_undo(pre_import)
        self._schedule_save()

        # Build report
        total_placed = matched + ambiguous
        lines = [f'Imported {total_placed} note(s).']
        if ambiguous:
            lines.append(
                f'{ambiguous} anchor(s) appeared more than once in the lyrics '
                f'— the first occurrence was used.')
        if unmatched_anchors:
            lines.append(
                f'{len(unmatched_anchors)} anchor(s) could not be found '
                f'and were not imported:')
            for a in unmatched_anchors:
                lines.append(f'  • {a}')
            lines.append(
                '\nYou can add these manually in Coaching Notes mode '
                'by clicking the relevant word(s).')

        msg = QMessageBox(self)
        msg.setWindowTitle('Import Complete')
        msg.setIcon(QMessageBox.Information if not unmatched_anchors
                    else QMessageBox.Warning)
        msg.setText('\n'.join(lines))
        # Make text selectable so user can copy unmatched anchors
        for lbl in msg.findChildren(QLabel):
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        msg.exec_()

    def _on_open_save_folder(self):
        path_ = self.store.dir
        os.makedirs(path_, exist_ok=True)
        from PyQt5.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(path_))

    def _restore_state(self):
        geo = self.settings.value('geometry')
        if geo:
            self.restoreGeometry(geo)
        state = self.settings.value('windowState')
        if state:
            self.restoreState(state)
        # Persist editor font size
        self._editor_font_size = int(
            self.settings.value('editorFontSize', self._editor_font_size))
        self._apply_editor_font()
        # Persist UI scale — new key 'uiScale'; fall back to old 'uiFontScale'
        # if the user has an existing settings file from before this fix.
        if self.settings.contains('uiScale'):
            self._ui_scale = float(self.settings.value('uiScale', self._ui_scale))
        elif self.settings.contains('uiFontScale'):
            # Old setting stored a font-only scale — treat it as the overall scale.
            self._ui_scale = float(self.settings.value('uiFontScale', 1.0))
        # else keep default 1.0
        self.setStyleSheet(build_style(_dpr(), self._ui_scale))
        self.trajectory.setUiScale(self._ui_scale)
        self.analysis.card.brightness_bar.setUiScale(self._ui_scale)
        self.analysis.setUiScale(self._ui_scale)
        self._apply_editor_font()
        # Persist enabled hint types
        saved_hints = self.settings.value('enabledHintTypes', None)
        if saved_hints is not None:
            # QSettings stores lists as QVariant; normalise to set of str
            if isinstance(saved_hints, str):
                saved_hints = [saved_hints]
            self._enabled_hint_types = set(saved_hints)
            # Sync menu checkmarks
            if hasattr(self, '_hints_menu'):
                for act in self._hints_menu.actions():
                    if act.isCheckable() and act.text() in self._HINT_TYPE_LABELS.values():
                        key = next((k for k, v in self._HINT_TYPE_LABELS.items()
                                    if v == act.text()), None)
                        if key:
                            act.setChecked(key in self._enabled_hint_types)
        self._update_hints_btn_label()
        # Persist hint-highlight opacity
        saved_opacity = self.settings.value('hintOpacity', None)
        if saved_opacity is not None:
            self._hint_opacity = max(0.0, min(1.0, float(saved_opacity)))
        self.editor.set_highlight_opacity(self._hint_opacity)
        if hasattr(self, 'ipa_view'):
            self.ipa_view.set_highlight_opacity(self._hint_opacity)
        # Restore IPA hints toggle
        saved_ipa_hints = self.settings.value('ipaHintsEnabled', None)
        if saved_ipa_hints is not None:
            self._ipa_hints_enabled = saved_ipa_hints in (True, 'true', 'True', 1, '1')
        if hasattr(self, '_ipa_hints_action'):
            self._ipa_hints_action.setChecked(self._ipa_hints_enabled)
        # Persist Play-line-vowels hold speed
        saved_hold = self.settings.value('seqHoldMs', None)
        if saved_hold is not None:
            self._seq_hold_ms = int(saved_hold)
            self._seq_hold.setInterval(self._seq_hold_ms)
            # Sync combo to the nearest preset by hold_ms
            best_idx = 0
            best_diff = abs(self._seq_hold_ms - self._SEQ_SPEED_PRESETS[0][1])
            for i, (_, ms) in enumerate(self._SEQ_SPEED_PRESETS):
                diff = abs(self._seq_hold_ms - ms)
                if diff < best_diff:
                    best_diff, best_idx = diff, i
            self._seq_speed_combo.blockSignals(True)
            self._seq_speed_combo.setCurrentIndex(best_idx)
            self._seq_speed_combo.blockSignals(False)
        # (Any legacy speed setting from prior versions is silently ignored.)


    def _line_to_ipa_words(self, line_text: str,
                            line_base: int = -1) -> list:
        """Return (word, ipa_string, char_offset_in_line) for each WORD_RE match.

        ipa_string is the bare pronunciation WITHOUT slashes (the caller adds
        them as needed).  Words with no pronunciation get '?' as the ipa_string.
        Uses the identical context-aware logic as the trajectory bar:
        per-occurrence _preferred_index, next-word next_ipa resolution,
        _context_aware_pronunciations, and custom IPA.  This is the single
        source of truth for per-word IPA so both _line_to_ipa and the
        LyricsIpaView read from here.
        """
        matches = list(WORD_RE.finditer(line_text))
        result = []
        for i, m in enumerate(matches):
            w = m.group()
            wl = w.lower()
            abs_start = (line_base + m.start()) if line_base >= 0 else -1
            # Next-word IPA for context-aware function-word resolution (the/to)
            next_ipa = None
            if i + 1 < len(matches):
                nxt = matches[i + 1]
                np = self._cached_pronunciations(nxt.group())
                if np:
                    nxt_abs = (line_base + nxt.start()) if line_base >= 0 else -1
                    idx = self._preferred_index(nxt.group().lower(), nxt_abs)
                    next_ipa = np[min(idx, len(np) - 1)]
            prons = self._context_aware_pronunciations(w, next_ipa)
            if prons:
                preferred = self._preferred_index(wl, abs_start)
                pron = prons[min(preferred, len(prons) - 1)]
            else:
                pron = '?'
            result.append((w, pron, m.start()))
        return result

    def _line_to_ipa(self, line_text: str, line_base: int = -1) -> str:
        """Render a line of lyrics as IPA, preserving punctuation and spacing.

        Delegates per-word IPA resolution to _line_to_ipa_words so both
        this method and LyricsIpaView share the same single source of truth.
        *line_base* is the absolute offset of this line within the full lyrics;
        when given, per-occurrence pronunciation choices are honoured.
        """
        word_list = self._line_to_ipa_words(line_text, line_base)
        if not word_list:
            return line_text  # punctuation/whitespace only — pass through
        matches = list(WORD_RE.finditer(line_text))
        parts = []
        last_end = 0
        for (w, pron, _co), m in zip(word_list, matches):
            parts.append(line_text[last_end:m.start()])
            if pron == '?':
                parts.append(f'/{w}?/')
            else:
                parts.append(f'/{pron}/')
            last_end = m.end()
        parts.append(line_text[last_end:])
        return ''.join(parts)

    def _build_ipa_view_data(self) -> list:
        """Build the blocks structure for LyricsIpaView.set_view_data.

        Returns a list of per-line lists; each inner list contains
        (word, ipa_str, block_number, char_offset_in_line) for every word
        on that line.  Blank lines produce an empty inner list so spacing
        is preserved.  Uses the same line_base tracking as _build_cheat_sheet_data.
        """
        song = self.active_song
        blocks = []
        line_base = 0
        for bn, raw_line in enumerate(song.lyrics.splitlines()):
            if raw_line.strip():
                word_list = self._line_to_ipa_words(raw_line, line_base)
                line_data = [
                    (w, pron, bn, co)
                    for (w, pron, co) in word_list
                ]
                blocks.append(line_data)
            else:
                blocks.append([])
            line_base += len(raw_line) + 1  # +1 for the newline separator
        return blocks

    def _build_cheat_sheet_data(self) -> dict:
        """Build structured cheat sheet data shared by all export formats.

        Returns a dict with:
          - title (str)
          - style (str)
          - lyric_blocks: list of (text_line, ipa_line) tuples. Blank lines
            in the source lyrics become ('', '') so spacing is preserved.
          - word_entries: list of (word, ipa, sustained_bool, [unique_tips])
            tuples. Each word appears once; identical tip texts are deduped.
        """
        song = self.active_song

        lyric_blocks = []
        line_base = 0
        for raw_line in song.lyrics.splitlines():
            if raw_line.strip():
                lyric_blocks.append((raw_line, self._line_to_ipa(raw_line, line_base)))
            else:
                lyric_blocks.append(('', ''))
            line_base += len(raw_line) + 1  # +1 for the newline separator

        word_entries = []
        seen = set()
        for m in WORD_RE.finditer(song.lyrics):
            w = m.group()
            wl = w.lower()
            if wl in seen:
                continue
            seen.add(wl)
            prons = self._context_aware_pronunciations(w, None)
            preferred = self._pron_index_cache.get(wl, 0)
            pron = prons[min(preferred, len(prons) - 1)] if prons else '?'
            sustained = wl in song.sustained_words
            # Deduplicate tip texts: identical annotations on multiple
            # occurrences of the same word collapse to one entry.
            tips_seen = set()
            tips = []
            for ann in self._word_annotations:
                if ann.word_lower == wl and ann.tip_text not in tips_seen:
                    tips_seen.add(ann.tip_text)
                    tips.append(ann.tip_text)
            word_entries.append((w, pron, sustained, tips))

        return {
            'title': song.name,
            'style': song.style,
            'lyric_blocks': lyric_blocks,
            'word_entries': word_entries,
        }

    def _build_cheat_sheet_lines(self) -> list:
        """Return Markdown cheat sheet as a list of lines."""
        data = self._build_cheat_sheet_data()
        lines = [f'# {data["title"]}', '']

        # ── Lyrics with interlinear IPA ──────────────────────────────────────
        lines.append('## Lyrics')
        lines.append('')
        for text, ipa_line in data['lyric_blocks']:
            if text:
                lines.append(text)
                lines.append(ipa_line)
                lines.append('')
            else:
                lines.append('')

        # ── Word reference (unique words, deduplicated tips) ─────────────────
        lines.append('## Word Reference')
        lines.append('')
        lines.append('| Word | IPA | Sustained | Notes |')
        lines.append('|---|---|---|---|')
        for w, pron, sustained, tips in data['word_entries']:
            sustained_tag = '⭐' if sustained else ''
            tip_cell = ' • '.join(tips) if tips else ''
            # Pipe and newline characters would break the markdown table row
            tip_cell = tip_cell.replace('|', '\\|').replace('\n', ' ')
            lines.append(f'| {w} | /{pron}/ | {sustained_tag} | {tip_cell} |')

        lines.append('')
        lines.append(f'*Style: {data["style"]}  |  Generated by Lyric IPA Finder*')
        return lines

    def _on_export_cheat_sheet(self, fmt: str):
        # Flush any pending annotation recompute so the tips are current (Bug 7 fix).
        self._annotation_timer.stop()
        # Keep song.lyrics in step with the editor so occurrence-based
        # pronunciation choices line up with what is being exported.
        self.active_song.lyrics = self.editor.toPlainText()
        self._compute_annotations()
        from PyQt5.QtWidgets import QFileDialog
        name_safe = re.sub(r'[^\w\s-]', '', self.active_song.name).strip() or 'song'
        ext = 'md' if fmt == 'md' else 'pdf'
        default = f'{name_safe}_ipa.{ext}'
        path_, _ = QFileDialog.getSaveFileName(
            self, 'Export Cheat Sheet', default,
            'Markdown (*.md)' if fmt == 'md' else 'PDF (*.pdf)')
        if not path_:
            return

        if fmt == 'md':
            lines = self._build_cheat_sheet_lines()
            with open(path_, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            QMessageBox.information(self, 'Exported',
                                    f'Cheat sheet saved to:\n{path_}')
            return

        data = self._build_cheat_sheet_data()

        # PDF — try reportlab, fall back to HTML via QPrinter
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import mm
            from reportlab.platypus import (SimpleDocTemplate, Paragraph,
                                            Spacer, Table, TableStyle,
                                            KeepTogether)
            from reportlab.lib import colors as rlc

            doc = SimpleDocTemplate(path_, pagesize=A4,
                                    leftMargin=18*mm, rightMargin=18*mm,
                                    topMargin=18*mm, bottomMargin=18*mm)
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                'TitleHeader', parent=styles['Title'],
                fontSize=20, leading=24,
                textColor=rlc.HexColor('#2c3a58'),
                spaceAfter=4)
            section_style = ParagraphStyle(
                'Section', parent=styles['Heading2'],
                fontSize=13, leading=16,
                textColor=rlc.HexColor('#4a6090'),
                spaceBefore=6, spaceAfter=6,
                borderPadding=0)
            lyric_text_style = ParagraphStyle(
                'LyricText', parent=styles['Normal'],
                fontSize=11, leading=14,
                textColor=rlc.HexColor('#1c2230'),
                spaceAfter=1)
            lyric_ipa_style = ParagraphStyle(
                'LyricIPA', parent=styles['Normal'],
                fontSize=10, leading=13,
                textColor=rlc.HexColor('#5a6890'),
                fontName='Helvetica-Oblique',
                leftIndent=10,
                spaceAfter=6)
            cell_style = ParagraphStyle(
                'Cell', parent=styles['Normal'],
                fontSize=9, leading=12)
            cell_word_style = ParagraphStyle(
                'CellWord', parent=cell_style,
                fontName='Helvetica-Bold')
            cell_ipa_style = ParagraphStyle(
                'CellIPA', parent=cell_style,
                textColor=rlc.HexColor('#2c3a58'))
            footer_style = ParagraphStyle(
                'Footer', parent=styles['Italic'],
                fontSize=9, textColor=rlc.HexColor('#7888a0'))

            story = [Paragraph(html.escape(data['title']), title_style),
                     Spacer(1, 4*mm)]

            # ── Lyrics section ──────────────────────────────────────────────
            story.append(Paragraph('Lyrics', section_style))
            for text, ipa_line in data['lyric_blocks']:
                if text:
                    # Keep each line+IPA pair on the same page if possible
                    pair = [Paragraph(html.escape(text), lyric_text_style),
                            Paragraph(html.escape(ipa_line), lyric_ipa_style)]
                    story.append(KeepTogether(pair))
                else:
                    story.append(Spacer(1, 3*mm))

            story.append(Spacer(1, 6*mm))

            # ── Word reference table (deduplicated tips) ────────────────────
            story.append(Paragraph('Word Reference', section_style))
            story.append(Spacer(1, 2*mm))

            table_data = [['Word', 'IPA', '★', 'Notes']]
            for w, pron, sustained, tips in data['word_entries']:
                sustained_tag = '★' if sustained else ''
                tip_str = ' • '.join(tips) if tips else ''
                table_data.append([
                    Paragraph(html.escape(w), cell_word_style),
                    Paragraph(f'/{html.escape(pron)}/', cell_ipa_style),
                    sustained_tag,
                    Paragraph(html.escape(tip_str), cell_style),
                ])

            col_widths = [28*mm, 38*mm, 7*mm, None]
            t = Table(table_data, colWidths=col_widths, repeatRows=1)
            t.setStyle(TableStyle([
                ('BACKGROUND',     (0, 0), (-1, 0),  rlc.HexColor('#2c3a58')),
                ('TEXTCOLOR',      (0, 0), (-1, 0),  rlc.HexColor('#ffffff')),
                ('FONTSIZE',       (0, 0), (-1, 0),  9),
                ('FONTNAME',       (0, 0), (-1, 0),  'Helvetica-Bold'),
                ('ALIGN',          (2, 0), (2, -1),  'CENTER'),
                ('GRID',           (0, 0), (-1, -1), 0.3, rlc.HexColor('#b8c0d0')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1),
                 [rlc.HexColor('#ffffff'), rlc.HexColor('#f4f6fb')]),
                ('TEXTCOLOR',      (0, 1), (-1, -1), rlc.HexColor('#1c2230')),
                ('VALIGN',         (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING',    (0, 0), (-1, -1), 5),
                ('RIGHTPADDING',   (0, 0), (-1, -1), 5),
                ('TOPPADDING',     (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING',  (0, 0), (-1, -1), 4),
            ]))
            story.append(t)
            story.append(Spacer(1, 4*mm))
            story.append(Paragraph(
                f'Style: {data["style"]}  |  ★ = sustained note  |  '
                f'Generated by Lyric IPA Finder',
                footer_style))
            doc.build(story)
            QMessageBox.information(self, 'Exported',
                                    f'Cheat sheet saved to:\n{path_}')

        except ImportError:
            # reportlab not available — fall back to styled HTML via QPrinter
            from PyQt5.QtPrintSupport import QPrinter
            from PyQt5.QtGui import QTextDocument
            printer = QPrinter(QPrinter.HighResolution)
            printer.setOutputFormat(QPrinter.PdfFormat)
            printer.setOutputFileName(path_)
            printer.setPageSize(QPrinter.A4)

            parts = [
                '<html><head><style>',
                'body { font-family: sans-serif; color: #1c2230; }',
                'h1 { color: #2c3a58; margin-bottom: 4px; }',
                'h2 { color: #4a6090; margin-top: 18px; '
                '     border-bottom: 1px solid #b8c0d0; padding-bottom: 3px; }',
                '.lyric { font-size: 11pt; margin: 4px 0 1px 0; }',
                '.ipa   { font-size: 10pt; color: #5a6890; '
                '         font-style: italic; margin: 0 0 8px 14px; }',
                '.blank { height: 8px; }',
                'table { border-collapse: collapse; width: 100%; '
                '        margin-top: 6px; }',
                'th { background: #2c3a58; color: #fff; '
                '     padding: 6px; text-align: left; font-size: 9pt; }',
                'td { border: 1px solid #b8c0d0; padding: 5px; '
                '     vertical-align: top; font-size: 9pt; }',
                'tr:nth-child(even) td { background: #f4f6fb; }',
                '.word { font-weight: bold; }',
                '.ipacell { color: #2c3a58; }',
                '.center { text-align: center; }',
                '.footer { font-style: italic; color: #7888a0; '
                '          font-size: 9pt; margin-top: 12px; }',
                '</style></head><body>',
                f'<h1>{html.escape(data["title"])}</h1>',
                '<h2>Lyrics</h2>',
            ]
            for text, ipa_line in data['lyric_blocks']:
                if text:
                    parts.append(f'<p class="lyric">{html.escape(text)}</p>')
                    parts.append(f'<p class="ipa">{html.escape(ipa_line)}</p>')
                else:
                    parts.append('<div class="blank"></div>')

            parts.append('<h2>Word Reference</h2>')
            parts.append('<table>'
                         '<tr><th>Word</th><th>IPA</th>'
                         '<th class="center">★</th><th>Notes</th></tr>')
            for w, pron, sustained, tips in data['word_entries']:
                sustained_tag = '★' if sustained else ''
                tip_str = html.escape(' • '.join(tips)) if tips else ''
                parts.append(
                    f'<tr><td class="word">{html.escape(w)}</td>'
                    f'<td class="ipacell">/{html.escape(pron)}/</td>'
                    f'<td class="center">{sustained_tag}</td>'
                    f'<td>{tip_str}</td></tr>')
            parts += [
                '</table>',
                f'<p class="footer">Style: {html.escape(data["style"])} | '
                f'★ = sustained note | Generated by Lyric IPA Finder</p>',
                '</body></html>',
            ]
            tdoc = QTextDocument()
            tdoc.setHtml('\n'.join(parts))
            tdoc.print_(printer)
            QMessageBox.information(self, 'Exported',
                                    f'Cheat sheet saved to:\n{path_}')

    def closeEvent(self, event):
        self._save_timer.stop()
        self._annotation_timer.stop()
        self.active_song.lyrics = self.editor.toPlainText()
        self._persist_songs()
        self.settings.setValue('geometry', self.saveGeometry())
        self.settings.setValue('windowState', self.saveState())
        self.settings.setValue('editorFontSize', self._editor_font_size)
        self.settings.setValue('uiScale', self._ui_scale)
        self.settings.setValue('hintOpacity', self._hint_opacity)
        self.settings.setValue('ipaHintsEnabled', self._ipa_hints_enabled)
        self.settings.setValue('enabledHintTypes', list(self._enabled_hint_types))
        super().closeEvent(event)


def _resource_base() -> str:
    """Directory holding bundled resources (PyInstaller _MEIPASS or script dir)."""
    return getattr(sys, '_MEIPASS', path.dirname(path.abspath(__file__)))


def _app_icon() -> QIcon:
    """Locate the application icon PNG and return a QIcon.

    Looks for common names first, then falls back to the first *.png sitting
    next to the executable / script. Rename your icon to one of the preferred
    names (icon.png) to be safe, or drop it in the same folder as the exe.
    """
    base = _resource_base()
    preferred = ('icon.png', 'app.png', 'LyricsToIPA.png', 'logo.png')
    for name in preferred:
        p = path.join(base, name)
        if path.exists(p):
            return QIcon(p)
    try:
        for name in sorted(os.listdir(base)):
            if name.lower().endswith('.png'):
                return QIcon(path.join(base, name))
    except OSError:
        pass
    return QIcon()


def main():
    # ── HiDPI flags must come before QApplication() ───────────────────────────
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    # Sweep any TTS temp files left over from a previous crash
    _tts_cleanup()

    # On Windows, set an explicit AppUserModelID so the taskbar shows our icon
    # and groups the window under this app rather than the python launcher.
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                'Heng.LyricsToIPA.1')
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName('Lyric IPA Finder')
    app.setStyle('Fusion')
    app.setWindowIcon(_app_icon())
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor('#14181f'))
    pal.setColor(QPalette.WindowText, QColor('#d8dfe8'))
    pal.setColor(QPalette.Base, QColor('#1c2230'))
    pal.setColor(QPalette.Text, QColor('#d8dfe8'))
    pal.setColor(QPalette.Button, QColor('#1c2230'))
    pal.setColor(QPalette.ButtonText, QColor('#d8dfe8'))
    pal.setColor(QPalette.Highlight, QColor('#7898d0'))
    pal.setColor(QPalette.HighlightedText, QColor('#14181f'))
    app.setPalette(pal)

    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()