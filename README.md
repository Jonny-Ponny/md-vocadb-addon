# md-vocadb-addon

Addon for [metadata-docker](https://github.com/Jonny-Ponny/metadata-docker) that uses the [VocaDB](https://vocadb.net/) API to fetch song and album metadata from the VocaDB database, which specialises in Vocaloid/UTAU and related music.

Current addon version: `1.1.2`. Source: [md-vocadb-addon](https://github.com/Jonny-Ponny/md-vocadb-addon).

## Addon structure

This addon follows the same base class structure as described in [metadata-docker](https://github.com/Jonny-Ponny/metadata-docker). It inherits from `MetadataFetcher` and implements the four core methods: `search_songs`, `fetch_song_metadata`, `search_albums`, and `fetch_album_metadata`.

## Environment Variables

VocaDB supports multiple languages for names (song titles, artist names, album titles, vocalist names). This addon provides control over which language is used for each entity type via environment variables. All variables are optional; defaults are used if not set.

| Variable | Purpose | Allowed Values | Default |
|----------|---------|----------------|---------|
| `MD_VOCADB_LANG` | Primary language for the API (`lang` parameter). Affects all `name` fields unless overridden by specific `*_USE_ORIGINAL` flags. | `Default`, `English`, `Romaji`, `Japanese` | `English` |
| `MD_VOCADB_LYRICS_LANG` | Language for lyrics. `Default` uses the song's original lyrics in their original language (Japanese, English, etc.), not a translation. Other values use lyrics in the configured language when available. | `English`, `Romaji`, `Japanese`, `Default` | Value of `MD_VOCADB_LANG` |
| `MD_VOCADB_SONG_USE_ORIGINAL` | If `true`, use the original title for songs instead of the localized name from `MD_VOCADB_LANG`. | `true`/`false` | `false` |
| `MD_VOCADB_ARTIST_USE_ORIGINAL` | If `true`, use original names for producers in the `artist` field and for `albumArtist`. | `true`/`false` | `false` |
| `MD_VOCADB_ALBUM_USE_ORIGINAL` | If `true`, use the original name for albums instead of the localized name. | `true`/`false` | `false` |
| `MD_VOCADB_VOCALIST_USE_ORIGINAL` | If `true`, use original names for vocalists in both the `artist` field and the separate `vocalists` field. | `true`/`false` | `false` |
| `MD_VOCADB_FETCH_COVER` | Whether to fetch cover art URLs. Disabling speeds up search responses. | `true`/`false` | `true` |
| `MD_VOCADB_REQUEST_DELAY` | Delay in seconds between API requests. Set to `0` for no delay (VocaDB does not enforce strict rate limits). | Float | `0.0` |

### Language Selection Examples

- **All English**: leave all defaults (`MD_VOCADB_LANG=English`, all `*_USE_ORIGINAL=false`).
- **All original**: set both artist flags to `true` (or set `MD_VOCADB_LANG=Japanese`/`Default`).
- **Mixed - original Japanese producers, English vocalists**:
  - `MD_VOCADB_LANG=English`
  - `MD_VOCADB_ARTIST_USE_ORIGINAL=true`
  - `MD_VOCADB_VOCALIST_USE_ORIGINAL=false`
  - Resulting `artist`: `黒うさP; Hatsune Miku`
- **Mixed - English producers, original Japanese vocalists**:
  - `MD_VOCADB_LANG=English`
  - `MD_VOCADB_ARTIST_USE_ORIGINAL=false`
  - `MD_VOCADB_VOCALIST_USE_ORIGINAL=true`
  - Resulting `artist`: `KurousaP; 初音ミク`

The `*_USE_ORIGINAL` flags override the primary language for that specific entity type. "Original" means the artist's VocaDB default name, which is usually Japanese for Japanese producers but may be another language for artists whose default name is English. If a name is not available in the requested form, the addon falls back to the other available name, so you should not get `"Unknown"` for a name that exists in the database.

VocaDB artist objects in song/album responses do not include `defaultName`. When either artist-related `*_USE_ORIGINAL` flag is enabled, the addon makes additional `lang=Default` requests to resolve original artist names. This affects response time slightly but makes the language flags work correctly.

## Implementation Notes

- **Rate limiting**: VocaDB's public API does not enforce strict rate limits, but the addon includes an optional delay (`MD_VOCADB_REQUEST_DELAY`). The delay state is class-level because metadata-docker creates a new fetcher instance per request.
- **Artist categorisation**: Artist credits are classified using VocaDB's `categories` field, falling back to `artistType` only when categories are missing:
  - **Main artists** (`categories` contains `Producer`) - the primary creators.
  - **Vocalists** (`categories` contains `Vocalist`) - voicebanks and singers.
  - Other roles (Illustrator, Animator, Lyricist, etc.) are ignored and are not returned as metadata fields.
- **Artist field language**: The combined `artist` field contains producers followed by vocalists. Producers follow `MD_VOCADB_ARTIST_USE_ORIGINAL`; vocalists follow `MD_VOCADB_VOCALIST_USE_ORIGINAL`. This allows each part to use a different language. If no categorised artists are available, the `artistString` from the corresponding language response is used as a fallback.
- **Vocalists field**: The separate `vocalists` field follows `MD_VOCADB_VOCALIST_USE_ORIGINAL`, matching the vocalist part of the `artist` field.
- **Cover art**: Uses the `urlOriginal` (largest) image from VocaDB, falling back to `urlThumb`.
- **Genres**: Only tags with category `Genre`/`Genres` are returned in the `genre` field.
- **Date**: Album release dates and song publish dates are returned as `date` in `YYYY-MM-DD` format when available.
- **Track/disc numbers**: Returned as `trackNumber` and `diskNumber`.
- **Publisher**: Taken from the album's label artist, falling back to the album's `labels` list when present.
- **Lyrics language**: `Default` returns the original lyrics (whatever language the song was originally written in). Other values prefer an original or translation in that language, then fall back to the original, romanized, or any available lyrics. Remasters, remixes, and covers also inherit lyrics from the version they are based on; song-specific lyrics take priority over inherited ones.
- **Release type**: Taken from VocaDB's `discType` field (Album, Single, EP, Compilation, etc.).

## Metadata Fields

The addon returns a flat dictionary (or list of dictionaries) that includes the standard fields expected by metadata-docker:

- `id` - unique identifier (search results only, passed back to the fetch method)
- `title` - song title
- `artist` - producers and vocalists, separated by `; `; producers and vocalists each follow their own language flag
- `vocalists` - vocalists as a separate field, using the vocalist language flag
- `album` - song album
- `albumArtist` - the main artist (Producer) of the album
- `date` - release/publish date
- `genre` - music genres (semicolon-separated)
- `picture` - cover art URL (original resolution)
- `trackNumber` - track number (for album tracks)
- `diskNumber` - disc number (for multi-disc albums)
- `publisher` - label/record company
- `releaseType` - album type (e.g. Album, EP, Single)
- `description` - album description
- `unsyncedLyrics` - lyrics in the configured lyrics language
- `extraInfo` - display-only duration and song type; never written as a tag
- `coverart` - cover art URL for search results only

VocaDB identifiers are returned as `vocadb_song_id` and `vocadb_album_id`. These identifiers and the `vocalists` field are addon-specific keys, so metadata-docker writes them as custom tags if they are selected. Role-based fields such as `vocadb_illustrator`, `vocadb_animator`, and `vocadb_lyricist` are no longer emitted.

## Using This Addon

1. Place the addon file (`VocaDB.py`) and its requirements file in metadata-docker's `/addons` folder.
2. Restart the container. The addon will be discovered automatically.
3. Configure the desired environment variables in your `docker-compose.yml` or container runtime.

## Troubleshooting

- **"Unknown" for names**: Ensure the entity has the requested name variant; the addon falls back to the available version. If both are missing, `"Unknown"` is returned.
- **Artist language not changing**: `MD_VOCADB_ARTIST_USE_ORIGINAL` controls producers and `albumArtist`; `MD_VOCADB_VOCALIST_USE_ORIGINAL` controls vocalists in both the `artist` and `vocalists` fields. Set them independently for mixed-language artist strings.
- **Slow responses**: Set `MD_VOCADB_FETCH_COVER=false` to skip cover art fetching, decrease `MD_VOCADB_REQUEST_DELAY`, or disable the artist `*_USE_ORIGINAL` flags to avoid the extra language-lookup request.
