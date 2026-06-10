# Lyric IPA Finder

A vowel and diction tool for singers. Paste lyrics, click a word, get its IPA breakdown, vowel chart position, and articulation notes. Inline hints mark up the full lyrics so diction issues are visible across the whole phrase at once. Mark high notes, climaxes, and breath placements to unlock phrase-budget feedback, a tension watchlist, and a direction prompt grounded in your actual choices.

**Personal project built with LLM assistance. The singing tips are algorithmically generated and not verified. Cross-check anything important with your teacher.**

---

## Installation

Download the latest `.exe` from the [releases page](../../releases). No installation needed, just run it.

---

## Quick start

1. Pick or create a song slot from the dropdown at the top of the lyrics panel
2. Paste your lyrics
3. Click any word to open its analysis on the right
4. Coloured highlights appear on words with diction notes; hover to read them
5. Right-click any word to set custom IPA, toggle sustained, or mark it as a high note or breath point

---

## Lyrics panel

**Click a word** to open its full analysis on the right.

**Right-click a word** for a context menu with:

- *Set custom IPA* — override the dictionary pronunciation. Useful for proper nouns, foreign words, numbers. Enter without slashes, e.g. `valʒɑ̃`
- *Dismiss hint* — hides the inline annotation for that word for this song
- *Toggle sustained note* — marks a word for long-note pedagogy in the analysis panel
- *High note on "word"* submenu — `None` / `High ▲` / `Climax ▲▲`. A small triangle glyph appears above the word in all three views. The Analysis panel shows a banner with vowel-planning and breath-banking advice. Climax marks additionally affect the modification-ladder caption.
- *Breath after "word"* submenu — `None` / `Full breath ✓` / `Catch-breath '`. Glyphs appear inline in the lyrics editor, IPA view, and Notes view. Phrase-budget feedback activates once at least one breath mark is set.

**High and breath glyphs** track scrolling in all three views and appear in the cheat-sheet export.

---

## Style button

The **LEGIT** / **CONTEMPORARY** button (top-right of the lyrics panel, next to the song name) sets the singing discipline for the active song. Stored as `classical` / `mt_ccm` in `songs.json`.

| Feature | Legit / Classical | Contemporary / Pop-MT |
|---|---|---|
| R toxicity tip | Always fires on rhotic words | Skipped on ordinary notes; fires on sustained/high/climax with a sustain-release reminder |
| Spurious diphthong check | Active | Skipped (speech-timed diphthongs are idiomatic) |
| Vowel-to-vowel glide tip | Soft glide liaison recommended | Both options presented (connect *or* deliberate separation) |
| Phrase-initial glottal tip | Balanced onset recommended | Glottal/cry onsets framed as expressive tools |
| Modification ladder caption | Legit relaxation toward target | MT/belt framing: keep speech vowel, narrow not round |
| Diphthong section caption | Sustain on primary, vanish late | Same + note that earlier glide is idiomatic in contemporary |
| Dark L | Flagged | Not flagged |

Style changes take effect immediately, recompute all hints, and re-run the Analysis panel for the current word.

---

## Inline hint types

Background tints on words. Hover to read the tip; right-click to dismiss.

| Colour family | Type | What it flags |
|---|---|---|
| **Amber — transitions** | Legato link | Consonant-final before vowel-initial. Carry the consonant across. |
| | Vowel glide | Vowel-final before vowel-initial. Insert /j/ or /w/ (or deliberate separation in contemporary). |
| **Wine-red — caution** | R toxicity | Trailing /r/ or r-coloured vowel. De-rhotacize for legit; sustain-release reminder for contemporary on emphatic notes. |
| | Consonant crash | Difficult stop/nasal cluster at a boundary. |
| | Dark L | Trailing /l/ (legit only). Keep tongue tip forward. |
| | Phrase-initial glottal | Line or post-punctuation vowel onset. Framing depends on style. |
| | Aspiration | Pronounced /h/ in a phrase-medial position. |
| **Teal — consonant exits** | Plosive exit | Trailing stop. Snap off cleanly. |
| | Nasal exit | Nasal final. Sustain vowel; place the nasal late. |
| | Approximant exit | /l/, /w/, /j/, /r/ final. Advice per consonant. |
| | Fricative exit | Voiced = sustain resource; unvoiced = air-dump risk. |
| **Other** | Yod coalescence | /t/, /d/, /n/, /s/, /z/ before /j/. |
| | /ŋ/ release | Trailing /ŋ/. Nasal ring carries pitch; don't let it burst. |
| | Spurious diphthong | Unexpected diphthong shape (legit mode only). |

Multiple tips on the same word are stacked: hover shows all, background tint follows the primary (first) tip. The IPA view mirrors this when **Show Diction Hints in IPA View** is on (View menu).

Punctuation (`,;:.!?`) suppresses legato tips at phrase boundaries. "the" auto-resolves /ði/ / /ðə/ by context.

---

## Phrase trajectory

Colour bar below the lyrics — warm for bright vowels, cool for dark. Gaps separate words. Click a syllable-vowel button in the analysis panel to highlight its position.

Warnings below the bar:

- **Chiaroscuro** — line brightness very skewed; counterbalance suggestion
- **Breath support** — > 55% unvoiced consonants; high air-drain risk
- **Phrase budget** — once breath marks exist, shows syllable count for the phrase containing the current word, with long-phrase and ends-on-marked-note warnings

---

## Analysis panel

**Speak** — reads the word via SAPI/SSML using the selected IPA.

**PRONUNCIATIONS** — multiple forms with brightness tags. Preference saved per occurrence.

**SYLLABLE VOWELS** — one button per vowel. Clicking highlights it on the chart and in the trajectory bar.

**Vowel chart** — IPA trapezoid. High-pitch modification targets shown with a dashed arrow. Diphthongs show the arc.

**Articulation card** — tongue, lips, brightness bar, singing notes. Contains:

- *Stress warning* — if the selected vowel is unstressed
- *High-note / climax banner* (▲ or ▲▲) — appears when the word is marked; gives vowel-planning and breath-banking advice, with a climax-specific intensity note
- *Sustained-note tips* — when the word is marked sustained; vowel-specific vibrato and tension notes
- *Modification ladder* — the high-pitch target vowel. Caption wording follows the song style (legit vs. contemporary/belt framing)
- *Diphthong section* — glide timing; contemporary note appended in Contemporary mode

**Panel tips** — boundary and supplementary tips for the current word, same text as the hover tooltip.

---

## Three views

Switch with the **Lyrics / Notes / IPA** buttons above the lyrics area.

**Lyrics** — the main editing and hint view.

**Notes** — the coaching notes canvas. Click-drag to anchor a note across a word span. Each note shows a folded sticky-bubble. Ctrl+Z undoes. Undo is scoped to the Notes view and resets on song switch.

**IPA** — interlinear layout: each word above its IPA transcription. Hover for the same diction tooltips as the Lyrics view (when IPA hints are on). Click a word to open it in the Analysis panel. High/breath mark glyphs appear above/after words.

---

## Song menu

| Action | Description |
|---|---|
| Bulk Import IPAs | Paste `{"word": "ipa"}` JSON to set multiple custom pronunciations |
| Generate IPA Prompt | Builds a prompt for unknown words; import the returned JSON via Bulk Import |
| Check for Missing IPAs | Lists words with no pronunciation |
| Generate Direction Prompt | Builds a nine-section research/coaching prompt grounded in your marks; see below |
| Import Coaching Notes | Paste the NOTES-FOR-IMPORT block from a Direction Prompt response |
| Tension Watchlist | Shows risk alerts for all emphatic (sustained/high/climax) words |
| Export Cheat Sheet (Markdown) | Interlinear lyrics + word reference table + tension section as `.md` |
| Export Cheat Sheet (PDF) | Same as Markdown, as a PDF |
| Reset Dismissed Hints | Restores all dismissed annotations for this song |
| Change Save Folder | Move where `songs.json` is stored; optionally copies existing data |
| Open Save Folder | Opens the save folder in Explorer |

---

## Direction Prompt

**Song → Generate Direction Prompt** copies a prompt to the clipboard that you paste into an AI assistant (Claude, ChatGPT, etc.). The AI returns nine prose sections followed by a `NOTES-FOR-IMPORT` block.

Sections in the prompt:

1. Identification
2. Dramatic Context
3. Emotional Arc
4. Phrasing and Expression
5. Acting Direction
6. Singing Direction
7. Tradition and Interpretation
8. Pitfalls
9. Breath, Support, and Body *(phrase-by-phrase breath strategy, support pacing, body reminders at specific words)*

**Grounding data included in the prompt** (when present):

- Custom IPA overrides you have set
- Words you have marked sustained
- High/climax marks with human-readable labels
- Your breath plan as lyrics with ✓/' spliced in

The import block draws coaching notes from sections 4, 5, and 9. Import via **Song → Import Coaching Notes**.

---

## Tension Watchlist

**Song → Tension Watchlist** scans all emphatic words (sustained, high, or climax marks) and reports heuristic tension risks:

- Close vowel (/i/, /y/, /u/) on a high or climax note → squeeze risk
- /æ/ under load → jaw tension
- Trailing /l/ on a held word → tongue-root pull-back
- Trailing rhotic or r-coloured vowel on a held note → curl/bunch tension
- Consonant cluster leading into a high or climax note → throat-setting risk

The watchlist also appears as a section in both PDF and Markdown cheat-sheet exports (only when non-empty).

---

## Cheat sheet export

**Song → Export Cheat Sheet** produces a `.md` or `.pdf` file with:

- **Lyrics section** — interlinear text/IPA with ▲/▲▲/✓/' glyphs spliced into the text line
- **Word Reference table** — one row per unique word; IPA shows all distinct pronunciations used across occurrences (e.g. `/ðə/ · /ði/`); Marks column shows ⭐ (sustained), ▲ (high), ▲▲ (climax)
- **Tension Watchlist section** — only when emphatic marks exist
- Footer legend: ⭐ = sustained · ▲ = high note · ▲▲ = climax · ✓/' = breath marks

---

## View menu

| Item | Description |
|---|---|
| Adjust Lyrics Font Size | Changes editor font; persists |
| Adjust UI Scale | Scales all UI elements; persists |
| Adjust Hint Highlight Opacity | How strongly background tints show |
| Show Diction Hints in IPA View | Mirrors the editor's tints and tooltips in the IPA view |
| Clear All Coaching Notes for This Song | Removes all notes for the active song (undoable with Ctrl+Z in the Notes view) |

---

## Save data

Each song slot stores: lyrics, custom IPA overrides, preferred pronunciations (per occurrence), dismissed hints, sustained-word marks, high-note and breath marks, coaching notes, and the style setting.

Everything lives in `songs.json` in a **pinned save folder**. The folder is fixed the first time the app runs (from the platform default), and written into settings so renaming the app never silently moves your data. Use **Song → Change Save Folder** to relocate it; the app offers to copy existing data.

A rolling backup `songs.bak.json` is maintained automatically.

---

## Keyboard shortcuts

| Key | Action |
|---|---|
| Ctrl+Z | Undo last note edit (Notes view only) |
| Click a word | Open in analysis panel |
| Right-click a word | Context menu (IPA, marks, hints) |

---

*All algorithmic coaching tips are heuristics. Verify important advice with a qualified teacher.*