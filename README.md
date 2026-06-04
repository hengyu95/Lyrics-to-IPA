# Lyric IPA Finder

A vowel and diction tool for singers. Paste lyrics, click a word, get its IPA breakdown, vowel chart position, and articulation notes. Inline hints mark up the full lyrics so you can see diction issues across the whole phrase at once.

**Personal project built with LLM assistance. The singing tips are algorithmically generated and not verified. Cross-check anything important with your teacher.**

---

## Installation

Download the latest `.exe` from the [releases page](../../releases). No installation needed, just run it.

---

## Quick start

1. Pick or create a song slot from the dropdown at the top of the lyrics panel
2. Paste your lyrics in the **Lyrics** view
3. Click any word in any view to open its analysis on the right
4. Coloured highlights appear on words with diction notes; hover over a word to read its tip, or click the word to see it in the right panel — panel tips are selectable and copyable

---

## Lyrics panel

### Views

Three mutually exclusive view buttons in the lyrics header switch the main canvas:

- **Lyrics** — the editable canvas; paste and edit text here.
- **Notes** — read-only coaching mode: drag across a word or span to attach a short performance note; it appears as a sticky-note bubble beneath the line. Click a bubble to edit, right-click to delete.
- **IPA** — read-only view showing the lyrics with each word's IPA printed directly beneath it, line by line.

Clicking a word in **any** view opens that word's full analysis in the right panel and updates the phrase trajectory.

**Right-click a word** for:

- *Set custom IPA* — override the dictionary pronunciation. Useful for proper nouns, foreign words, and numbers. Enter without slashes, e.g. `valʒɑ̃` not `/valʒɑ̃/`. Words with accents or diacritics (résumé, über, caffè) are recognised as whole words and can be clicked and right-clicked the same way. The built-in dictionary won't transcribe most foreign words — set a custom IPA for those.
- *Toggle sustained note* — marks a word for long-note tips in the analysis panel (vibrato handling, vowel-specific warnings)
- *Dismiss hint* — hides the inline annotation for that word permanently for this song

**Missing-IPA indicator** — a button that appears in the lyrics header when some words have no IPA pronunciation. Click it to review the list and start the IPA-prompt flow.

**CLASSICAL / MT/CCM button** sets the singing style for the active song. Affects how aggressive certain tips are: R toxicity is a hard warning in classical mode, a soft note in MT/CCM; vowel-to-vowel glide insertion is presented as standard practice in MT/CCM and as one option among two in classical.

**HINTS button** opens a menu with a master on/off toggle, bulk enable/disable, and per-type checkboxes for the ten annotation categories.

**Song menu:**

- *Bulk Import IPAs* — paste a JSON object of word→IPA to set many custom pronunciations at once.
- *Generate IPA Prompt to Clipboard* — scans the lyrics for unrecognised words and builds a prompt to paste into an AI; import the returned JSON via Bulk Import.
- *Check for Missing IPAs* — lists words with no IPA and offers to generate that prompt for them.
- *Generate Direction Prompt to Clipboard* — builds a research-and-performance-direction prompt for an AI. You can optionally name the character or voice part you're singing; the prompt includes the pronunciations you've already fixed and your sustained-word marks, and asks the AI to end its reply with a NOTES-FOR-IMPORT block.
- *Import Coaching Notes* — paste the AI's reply from the Direction Prompt; the importer finds the NOTES-FOR-IMPORT block and adds those notes to the Notes view.
- *Export Cheat Sheet (Markdown / PDF)* — exports the lyrics with IPA beneath each line plus a word-reference table (IPA, sustained marks, and diction tips).
- *Reset Dismissed Hints* — restores all dismissed annotations for the active song.
- *Open Save Folder* — opens the folder containing `songs.json`.

**View menu** has font size, UI scale, and hint-highlight opacity controls. The opacity slider tones down the inline highlight background colours when many hint types are active; the underline still flags the word even at low opacity. All three settings persist across restarts.

---

## Inline hint types

Background tints on words in the lyrics. Hover to read the tip; right-click to dismiss. The highlight intensity is adjustable via the View-menu opacity slider — the underline still flags the word even at low opacity.

| Colour | Type | What it flags |
|---|---|---|
| Dark amber | Legato link | Consonant-final word before a vowel-initial word. Carry the consonant across. |
| Olive | Vowel glide | Vowel-final word before a vowel-initial word. Insert /j/ or /w/ to avoid a glottal stop. |
| Wine red | Consonant crash | Stop-into-stop or stop-into-nasal at a word boundary. |
| Deep crimson | R toxicity | Trailing /r/ or r-coloured vowel (/ɚ/, /ɝ/). De-rhotacize for classical/legit. |
| Dark maroon | Dark L | Trailing /l/. Keep the tongue tip forward; don't pull the root back. |
| Deep wine | Phrase-initial glottal | Phrase or line opens on a vowel. Use a balanced onset unless a glottal attack is intentional. |
| Teal | Plosive exit | Trailing stop. Snap off cleanly; no shadow vowel. |
| Teal green | Nasal / voiced fricative exit | Pitch-carrying consonant. Can be sustained for expressive weight. |
| Forest teal | Approximant exit | /l/, /w/, /j/, /r/ exit. Advice differs per consonant. |
| Steel teal | Fricative exit | Voiced fricatives flagged as sustain resources; unvoiced as air-dump risks. |

Hints are grouped into three hue families: **amber** (transitions — legato, vowel glide), **wine-red** (things to avoid — r toxicity, crashes, glottal, dark L), and **teal** (consonant exits). Underline colours remain individually distinctive and match the old palette if you find them easier to read.

Punctuation (`,;:.!?`) suppresses legato tips at phrase boundaries. "the" automatically resolves to /ði/ before a vowel and /ðə/ before a consonant.

---

## Phrase trajectory

A colour bar below the lyrics showing every vowel in the current line, warm for bright vowels and cool for dark ones. Gaps separate words. Click a syllable vowel button in the analysis panel to highlight its position in the bar.

**Play line vowels** — plays every vowel in the current line in order through the TTS engine. The **Gap** selector beside it sets the pause between vowels during playback.

Two warnings appear below when triggered:

- **Chiaroscuro** - line average brightness is very skewed; suggests how to counter-balance
- **Breath support** - more than 55% of the line's consonants are unvoiced, which drains air support quickly

Both thresholds are rough heuristics. Treat them as prompts, not rules.

---

## Analysis panel

**Speak button** — reads the word using the currently selected pronunciation. Uses SAPI SSML with IPA input on Windows, so custom pronunciations like `valʒɑ̃` are passed directly to the synthesiser rather than guessed from spelling.

**Play vowel sound** — plays the currently selected vowel through the same TTS engine.

**PRONUNCIATIONS** — multiple pronunciations shown with brightness tags. Click to select. Preference is saved per song.

**SYLLABLE VOWELS** — one button per vowel in the selected pronunciation. Clicking highlights that vowel on the chart and in the trajectory bar.

**Vowel chart** — IPA trapezoid with the selected vowel highlighted. High-pitch modification targets shown with a dashed arrow. Diphthongs show the sustain-to-glide arc.

**Articulation card** — tongue position, lip shape, brightness bar, singing notes. Shows a stress warning when the selected vowel is on an unstressed syllable. If the word is marked as sustained (right-click in the lyrics), a sustained-note section appears with vowel-specific tips and vibrato notes.

**Panel tips** — same text as the hover tooltip for the current word, so you can read it without going back to the lyrics.

---

## Save data

Each song slot remembers lyrics, custom IPA overrides, preferred pronunciations, dismissed hints, sustained word marks, coaching notes, and the style setting. Everything is stored in a single `songs.json` file. A rolling backup, `songs.bak.json`, is written alongside it before each save as a safety net against accidental edits. Use **Song > Open Save Folder** to locate them.