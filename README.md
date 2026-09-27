# muz

A command-line and TUI tool for keeping a music library tidy: find duplicates,
fix tags, split artists and genres, embed covers and lyrics, fetch missing
metadata, rename files into a clean folder structure and convert formats.
Every change can be undone.

> **Linux only.** muz is written for Linux file systems and is not tested on
> Windows or macOS. It does not handle Windows path rules (reserved names,
> `\ : * ? " < > |`, case-insensitive names) and refuses to start elsewhere.

## Library layout

muz expects the usual layout:

```
/music/
├── <Album artist>/
│   └── <Album>/
│       ├── 01 - Title.flac
│       └── cover.jpg
```

The **ALBUMARTIST** tag decides which artist folder a track belongs to.
Tracks without it are reported and never guessed.

## What muz changes and what it does not

- **Reads** every common audio format: MP3, FLAC, M4A/ALAC/AAC, Ogg Vorbis,
  Opus, WMA, WAV, AIFF, APE, WavPack, Musepack, DSF.
- **Writes** tags only to **MP3 and FLAC**. Other formats are shown in
  statistics, compared by `--dupes` and can be converted by `--convert`, but
  their tags are never touched.
- MP3 tags are saved as **ID3v2.4**: that is the only ID3 version that stores
  several artists or genres properly.
- **Dry run by default.** Without `--apply` muz only shows what it would do.
  With `--apply` you pick the changes and confirm them with `[Y/n]`.
- **Nothing is deleted.** Duplicates and converted originals are moved to
  `.muztrash/`.
- **Everything is undoable** with `--undo N`.

## Files muz keeps in the library

All service files start with a dot, so Navidrome ignores them
(`Scanner.IgnoreDotFolders` is on by default) and they never show up in a player.

| Path | What it is |
|---|---|
| `.muzrules.toml` | Rules for this library: artist exceptions and aliases, genre aliases, path template, conversion quality. Created with defaults on the first run; muz never rewrites it. |
| `.muzhistory/` | One folder per applied run, e.g. `003_2026-09-27_14-32_split-artists_412-changes/` with `changes.jsonl` (for undo) and `summary.txt` (readable). |
| `.muztrash/` | Files moved out by a run, under a folder with the same name as the run, keeping their original paths. Delete it when you are sure. |
| `.muzcache.db` | Scan cache. Files whose size and modification time did not change are not read again. Safe to delete. |

## Install

### Docker (recommended for servers)

Nothing but Docker is installed on the host. The image is based on
`python:3.14-slim` and includes ffmpeg, fpcalc and SpotiFLAC.

```sh
git clone https://github.com/mimic890/muzscript.git
cd muzscript
# point MUSIC_DIR at your library, set PUID/PGID if your user id is not 1000 (`id`)
printf 'MUSIC_DIR=/srv/music\nPUID=1000\nPGID=1000\n' > .env
docker compose build
docker compose run --rm muz            # dashboard
docker compose run --rm muz --dupes    # any muz arguments
```

The container runs as your user, so moved and converted files keep your
ownership. Build a smaller image without SpotiFLAC with
`docker compose build --build-arg SPOTIFLAC=0`.

A shell alias makes it feel native:

```sh
alias muz='docker compose -f ~/muzscript/docker-compose.yml run --rm muz'
```

### pipx / pip

Needs Python 3.12+ (3.14 recommended), plus `ffmpeg` for `--convert` and
`fpcalc` (`libchromaprint-tools`) for `--dupes --acoustic`.

```sh
pipx install "git+https://github.com/mimic890/muzscript.git#egg=muz[spotiflac]"
# or without SpotiFLAC:
pipx install "git+https://github.com/mimic890/muzscript.git"
```

## Usage

```
muz [LIBRARY] [ACTION] [--apply] [--auto] [--yes]
```

`LIBRARY` defaults to `$MUZ_LIBRARY`, then `/music`, then the current folder.

Run without an action to open the **dashboard**: number of tracks per format,
size and length, artist and album folders, other files by extension and a list
of things to check (missing album artist, covers, lyrics...). Press `r` to
rescan and `q` to quit. The layout follows the terminal width.

### Actions

| Action | What it does |
|---|---|
| `--stats` | The dashboard statistics as plain output (also used when there is no terminal). |
| `--dupes` | Finds the same recording stored more than once: identical audio (FLAC audio MD5, MP3 frames without tags), same ISRC, or same main artist + title with the same length ("feat.", "Remastered" and similar are ignored). With `--apply` you choose which copy to keep; the best one is marked ★ (lossless, bit depth, sample rate, bitrate, then tag completeness). Add `--acoustic` to check candidates by sound with Chromaprint. |
| `--artists` | Splits `A feat. B, C` into the multi-valued `ARTISTS` tag (and `ALBUMARTIST` into `ALBUMARTISTS`). `ARTIST` keeps its display text. Exceptions such as `Simon & Garfunkel` are not split; aliases merge spellings of one artist. |
| `--genres` | Splits `Rock, Pop` into separate `GENRE` values and merges spellings (`hip hop` → `Hip-Hop`). |
| `--clean` | Removes junk values (the SpotiFLAC link in `DESCRIPTION` by default), `[ar:] [ti:] [by:]` header lines in embedded lyrics, extra spaces and repeated values. |
| `--embed` | Embeds `cover.jpg` / `folder.jpg` / ... into tracks without a cover, and `Track.lrc` / `Track.txt` into tracks without lyrics. |
| `--fetch KINDS` | Fills missing data from the internet: `tags`, `lyrics`, `covers` or `all` (comma-separated). Only empty fields are filled. Uses SpotiFLAC (Deezer, Apple Music, Qobuz, Tidal, many lyrics sources) when installed, otherwise Deezer + LRCLIB. |
| `--rename` | Moves and renames files to match `paths.template`. Lyrics files travel with their track; when a whole album folder moves, its cover and other files move too, and empty folders are removed. |
| `--convert MODE` | `auto`: every file that is not MP3/FLAC becomes FLAC if it is lossless (ALAC, WAV...) or MP3 if it is lossy. `mp3`: everything that is not MP3 (FLAC included) becomes MP3. `flac`: lossless files become FLAC. All tags, lyrics and the cover are copied; the original goes to `.muztrash/`. |
| `--report artists` | All artists with track counts, plus names that look like the same artist (case, punctuation, Cyrillic vs. Latin). |
| `--report genres` | All genres with track counts. |
| `--report missing` | Tracks missing album artist, album, title, track number, cover, lyrics, genre or date. |
| `--search TEXT` | Tracks whose artist, album artist, album, title or path contains TEXT. |
| `--history` | Previous runs with their numbers. |
| `--undo N` | Reverts run N (tags, covers, moves, trash, conversions). The undo is itself a run and can be undone. |

### Options

| Option | Meaning |
|---|---|
| `--apply` | Choose and write changes. Asks `[Y/n]` before writing. |
| `--auto` | With `--apply`: accept every suggestion instead of asking one by one (for `--dupes`: keep the ★ copy). |
| `-y`, `--yes` | Answer yes to the final `[Y/n]` (for scripts and cron). |
| `--acoustic` | With `--dupes`: verify matches by sound. |
| `--no-cache` | Read every file again instead of using `.muzcache.db`. |

### Choosing changes

With `--apply`, identical problems are asked once: 40 tracks with
`ARTIST = "A feat. B"` are one question.

```
y  accept     e  edit (type values separated by |)     s  skip
a  accept this and all remaining                       q  stop (keeps choices so far)
```

For duplicates: `Enter` keeps ★, `1` or `1,3` keeps those copies, `s` skips,
`a` keeps ★ in all remaining groups, `q` stops.

### Examples

```sh
muz /music                                  # dashboard
muz /music --dupes                          # list duplicates
muz /music --dupes --acoustic --apply       # choose which copies to keep
muz /music --clean --apply --auto --yes     # clean everything, no questions
muz /music --artists --apply                # split artists, one question per problem
muz /music --fetch lyrics,covers --apply
muz /music --rename                         # preview the new folder structure
muz /music --convert auto --apply
muz /music --history
muz /music --undo 3
```

## `.muzrules.toml`

Created on the first run. The most useful parts:

```toml
[artists]
separators = [", ", "; ", " / ", " & ", " feat. ", " feat ", " ft. ", " ft ", " featuring ", " x ", " vs. "]
exceptions = ["Simon & Garfunkel", "Earth, Wind & Fire", "Tyler, The Creator"]

[artists.aliases]
"Eldzhey" = ["Allj", "Элджей"]

[genres.aliases]
"Hip-Hop" = ["hip hop", "hiphop"]

[clean]
junk = ["SpotiFLAC", "github.com/"]
junk_fields = ["DESCRIPTION", "COMMENT", "URL"]

[paths]
# Fields: {albumartist} {album} {title} {artist} {year} {genre}
#         {track} {disc} {disctotal} {tracktotal}
#         {tracknum} = "07", or "2-07" on multi-disc albums
template = "{albumartist}/{album}/{tracknum} - {title}"

[convert]
mp3_quality = "V0"      # or "320"
flac_compression = 8

[fetch]
provider = "auto"       # "spotiflac" or "builtin"
```

In file and folder names `/` inside a tag becomes `_`, a leading dot is removed
(it would hide the entry from Navidrome) and every name is kept within the
255-byte Linux limit.

## SpotiFLAC

`--fetch` can use [SpotiFLAC](https://github.com/BartolomeoRusso9/SpotiFLAC-Module-Version)
(MIT) as its source. SpotiFLAC changes its internal API between major versions,
so muz pins an exact version (`SpotiFLAC==5.0.0`) and calls it from one file,
`src/muz/providers/spotiflac.py`. If SpotiFLAC is missing or fails, muz uses its
built-in Deezer + LRCLIB client instead. Tracks downloaded with SpotiFLAC carry
an `ISRC` tag, which makes lookups exact.

## Development

```sh
python3.14 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest          # needs ffmpeg and fpcalc; tests generate their own audio files
```

## License

MIT
