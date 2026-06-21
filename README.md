# md-vocadb-addon

Addon for [metadata-docker](https://github.com/Jonny-Ponny/metadata-docker) that uses the [VocaDB](https://vocadb.net/) API to fetch song and album metadata from the VocaDB database, which specialises in Vocaloid/UTAU and related music.

## Addon structure

This addon follows the same base class structure as described in the [metadata-docker](https://github.com/Jonny-Ponny/metadata-docker). It inherits from `MetadataFetcher` and implements the four core methods: `search_songs`, `fetch_song_metadata`, `search_albums`, and `fetch_album_metadata`.

## Environment Variables

VocaDB supports multiple languages for names (song titles, artist names, album titles, vocalist names). This addon provides control over which language is used for each entity type via environment variables. All variables are optional, defaults are used if not set.

| Variable | Purpose | Allowed Values | Default |
|----------|---------|----------------|---------|
| `MD_VOCADB_LANG` | Primary language for the API (`lang` parameter). Affects all `name` fields unless overridden by specific `*_USE_ORIGINAL` flags. | `Default`, `English`, `Romaji`, `Japanese` | `English` |
| `MD_VOCADB_SONG_USE_ORIGINAL` | If `true`, use the original (usually Japanese) title for songs instead of the localized name from `MD_VOCADB_LANG`. | `true`/`false` | `false` |
| `MD_VOCADB_ARTIST_USE_ORIGINAL` | If `true`, use the original name for artists (producers, vocalists, etc.) instead of the localized name. | `true`/`false` | `false` |
| `MD_VOCADB_ALBUM_USE_ORIGINAL` | If `true`, use the original name for albums instead of the localized name. | `true`/`false` | `false` |
| `MD_VOCADB_VOCALIST_USE_ORIGINAL` | If `true`, use the original name for vocalists (when they appear as a separate field) instead of the localized name. | `true`/`false` | `false` |
| `MD_VOCADB_FETCH_COVER` | Whether to fetch cover art URLs. Disabling speeds up search responses. | `true`/`false` | `true` |
| `MD_VOCADB_REQUEST_DELAY` | Delay in seconds between API requests. Set to `0` for no delay (VocaDB does not enforce strict rate limits). | Float | `0.0` |

### Language Selection Examples

- **All English**: leave all defaults (`MD_VOCADB_LANG=English`, all `*_USE_ORIGINAL=false`).
- **Original Japanese for all**: set `MD_VOCADB_LANG=Japanese` (or `Default`) and all `*_USE_ORIGINAL=false` (or you can also set `MD_VOCADB_LANG=Default` and all `*_USE_ORIGINAL=true`).
- **Mixed** - e.g., English song titles, but original Japanese artist names:
  - `MD_VOCADB_LANG=English`
  - `MD_VOCADB_SONG_USE_ORIGINAL=false`
  - `MD_VOCADB_ARTIST_USE_ORIGINAL=true`

The `*_USE_ORIGINAL` flags override the primary language for that specific entity type. If a name is not available in the requested form, the addon falls back to the other available name (e.g., if original is missing, it uses the localized version, and vice versa), so you should never get `"Unknown"` for a name that exists in the database.

## Implementation Notes

- **Rate limiting**: VocaDB’s public API does not enforce strict rate limits, but the addon includes an optional delay (`MD_VOCADB_REQUEST_DELAY`).
- **Artist categorisation**: The addon separates artists into:
  - **Main artist** (Producer) - the primary creator.
  - **Vocalists** - voicebanks.
  - Other roles (Illustrator, Lyricist, Animator, etc.) - stored as `vocadb_<role>` fields.
- **Cover art**: Uses the `urlOriginal` (largest) image from VocaDB, falling back to `urlThumb`.
- **Genres**: Only tags with category `Genre`/`Genres` are returned in the `genre` field.
- **Date**: Release dates are formatted as `YYYY-MM-DD` in the `year` field; the full ISO date is available as `vocadb_full_date` if needed.

## Metadata Fields

The addon returns a flat dictionary (or list of dictionaries) that includes the standard fields expected by metadata-docker:

- `id` - unique identifier (required for search results)
- `title` - song title
- `artist` - main artists (Producers) and vocalists, separated by `; `
- `album` - song album
- `albumArtist` - the main artist (Producer) of the album
- `year` - release date in `YYYY-MM-DD` format
- `genre` - music genres (semicolon‑separated)
- `picture` - cover art URL (original resolution)
- `track` - track number (for album tracks)
- `disk` - disc number (for multi‑disc albums)
- `vocalists` - list of vocalists (separate field)
- `publisher` - label/record company
- `releaseType` - album type (e.g., Album, EP, Single)

Additional VocaDB‑specific fields are prefixed with `vocadb_` (e.g., `vocadb_album_id`, `vocadb_version`, `vocadb_status`, `vocadb_ratingScore`, `vocadb_favoritedTimes`, and role‑based fields like `vocadb_illustrator`, `vocadb_animator`, `vocadb_lyricist`).

## Using This Addon

1. Place the addon file (`VocaDB.py`) and its requirements file in metadata-docker `/addons` folder.
2. Restart the container. The addon will be discovered automatically.
3. Configure the desired environment variables in your `docker-compose.yml` or container runtime.

## Troubleshooting

- **"Unknown" for names**: Ensure the entity has the requested name variant; the addon falls back to the available version. If both are missing, `"Unknown"` is returned.
- **Slow responses**: Set `MD_VOCADB_FETCH_COVER=false` to skip cover art fetching, or decrease `MD_VOCADB_REQUEST_DELAY`.