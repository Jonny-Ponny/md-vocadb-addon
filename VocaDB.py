# VocaDB.py
# Addon implementation using the VocaDB API

import os
import threading
import time
from typing import Any, Dict, List, Optional

import requests
from addon_base import MetadataFetcher


def _env_flag(name: str, default: str = "False") -> bool:
    return os.getenv(name, default).strip().lower() in ("true", "1", "yes", "on")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


class VocaDB(MetadataFetcher):
    name = "VocaDB"
    id = "vocadb"
    description = "Fetch song and album metadata from VocaDB"
    version = "1.1.3"
    github = "https://github.com/Jonny-Ponny/md-vocadb-addon"

    BASE_URL = "https://vocadb.net/api/"
    USER_AGENT = (
        f"metadata-docker-vocadb-addon/{version} "
        "(https://github.com/Jonny-Ponny/md-vocadb-addon)"
    )

    required_env_vars = [
        "MD_VOCADB_LANG",
        "MD_VOCADB_LYRICS_LANG",
        "MD_VOCADB_SONG_USE_ORIGINAL",
        "MD_VOCADB_ARTIST_USE_ORIGINAL",
        "MD_VOCADB_ALBUM_USE_ORIGINAL",
        "MD_VOCADB_VOCALIST_USE_ORIGINAL",
        "MD_VOCADB_FETCH_COVER",
        "MD_VOCADB_REQUEST_DELAY",
    ]

    # All have defaults
    LANG = os.getenv("MD_VOCADB_LANG", "English")
    LYRICS_LANG = os.getenv("MD_VOCADB_LYRICS_LANG", LANG)
    # Map lyric language names to VocaDB culture codes for language matching.
    LYRICS_CULTURE_CODES = {
        "english": "en",
        "japanese": "ja",
        "korean": "ko",
        "chinese": "zh",
        "spanish": "es",
        "french": "fr",
        "german": "de",
        "italian": "it",
        "russian": "ru",
        "portuguese": "pt",
    }
    SONG_USE_ORIGINAL = _env_flag("MD_VOCADB_SONG_USE_ORIGINAL")
    ARTIST_USE_ORIGINAL = _env_flag("MD_VOCADB_ARTIST_USE_ORIGINAL")
    ALBUM_USE_ORIGINAL = _env_flag("MD_VOCADB_ALBUM_USE_ORIGINAL")
    VOCALIST_USE_ORIGINAL = _env_flag("MD_VOCADB_VOCALIST_USE_ORIGINAL")
    FETCH_COVER = _env_flag("MD_VOCADB_FETCH_COVER", "True")
    REQUEST_DELAY = _env_float("MD_VOCADB_REQUEST_DELAY", 0.0)

    REQUEST_TIMEOUT = 20

    # The app creates a new fetcher instance per API request, so keep the
    # rate-limit state on the class.
    _rate_lock = threading.Lock()
    _last_request_time = 0.0

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.USER_AGENT})

    def _rate_limit(self):
        if self.REQUEST_DELAY <= 0:
            return
        cls = type(self)
        with cls._rate_lock:
            now = time.monotonic()
            elapsed = now - cls._last_request_time
            if elapsed < self.REQUEST_DELAY:
                time.sleep(self.REQUEST_DELAY - elapsed)
            cls._last_request_time = time.monotonic()

    def _get(
        self,
        endpoint: str,
        params: Dict[str, Any],
        lang_override: Optional[str] = None,
    ) -> Any:
        self._rate_limit()
        request_params = dict(params)
        request_params.setdefault("fmt", "json")
        request_params["lang"] = (
            lang_override if lang_override is not None else self.LANG
        )

        try:
            resp = self.session.get(
                self.BASE_URL + endpoint,
                params=request_params,
                timeout=self.REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"VocaDB API error: {e}")

    # ---------- Helpers for extracting names ----------
    @staticmethod
    def _get_name(entity: Any, use_original: bool) -> str:
        if not isinstance(entity, dict):
            return "Unknown"
        preferred = entity.get("defaultName") if use_original else entity.get("name")
        fallback = entity.get("name") if use_original else entity.get("defaultName")
        for value in (preferred, fallback):
            if isinstance(value, str) and value.strip():
                return value
        return "Unknown"

    def _get_artist_name(self, artist_data: Dict) -> str:
        return self._get_name(artist_data, self.ARTIST_USE_ORIGINAL)

    def _get_album_name(self, album_data: Dict) -> str:
        return self._get_name(album_data, self.ALBUM_USE_ORIGINAL)

    def _get_song_name(self, song_data: Dict) -> str:
        return self._get_name(song_data, self.SONG_USE_ORIGINAL)

    def _get_vocalist_name(self, artist_data: Dict) -> str:
        return self._get_name(artist_data, self.VOCALIST_USE_ORIGINAL)

    def _get_artist_string_fallback(
        self, entity: Dict, use_original: Optional[bool] = None
    ) -> str:
        """Return the artistString fallback, honoring the original-name flags.

        The localized response and the lang=Default response both contain an
        artistString. Prefer the default one when original names were requested
        so a missing/uncategorised artist list does not silently fall back to
        the localized string.
        """
        if use_original is None:
            use_original = self.ARTIST_USE_ORIGINAL or self.VOCALIST_USE_ORIGINAL
        if use_original:
            default_artist_string = entity.get("defaultArtistString")
            if isinstance(default_artist_string, str) and default_artist_string.strip():
                return default_artist_string
        artist_string = entity.get("artistString")
        if isinstance(artist_string, str) and artist_string.strip():
            return artist_string
        return "Unknown Artist"

    def _get_album_description(self, album_data: Dict) -> Optional[str]:
        desc = album_data.get("description")
        if isinstance(desc, str) and desc.strip():
            return desc
        return None

    # ---------- Artist helpers ----------
    @staticmethod
    def _get_categories(artist_data: Dict) -> set:
        """Return lower-case categories for an artist credit entry."""
        if not isinstance(artist_data, dict):
            return set()
        categories = artist_data.get("categories")
        values = []
        if isinstance(categories, str):
            values = [part.strip() for part in categories.split(",")]
        elif isinstance(categories, list):
            values = [str(part).strip() for part in categories]

        # Fall back to artistType only when the song/album credit has no
        # categories at all.
        if not values:
            artist_type = artist_data.get("artistType")
            if isinstance(artist_type, str):
                values = [artist_type]

        return {value.lower() for value in values if value}

    def _get_album_main_artist(self, album_data: Dict) -> str:
        """Return the Producer (or first artist) as the main artist."""
        artists = album_data.get("artists") or []
        for art in artists:
            if "producer" in self._get_categories(art):
                return self._get_artist_name(art)

        artist_obj = album_data.get("artist")
        if artist_obj:
            return self._get_artist_name(artist_obj)

        artist_string = self._get_artist_string_fallback(
            album_data, use_original=self.ARTIST_USE_ORIGINAL
        )
        if artist_string != "Unknown Artist":
            return artist_string

        if artists:
            return self._get_artist_name(artists[0])

        return "Unknown Artist"

    def _get_album_label(self, album_data: Dict) -> Optional[str]:
        """Return the label artist if present (category 'Label')."""
        for art in album_data.get("artists") or []:
            if "label" in self._get_categories(art):
                return self._get_artist_name(art)
        return None

    def _categorise_artists(self, artists: List[Dict]) -> Dict[str, List[Dict]]:
        result = {"main": [], "vocalists": []}
        for art in artists or []:
            categories = self._get_categories(art)
            if "producer" in categories:
                result["main"].append(art)
            if "vocalist" in categories:
                result["vocalists"].append(art)
        return result

    @staticmethod
    def _join_names(names: List[str]) -> str:
        unique = []
        seen = set()
        for name in names:
            if name and name not in seen:
                seen.add(name)
                unique.append(name)
        return "; ".join(unique)

    def _build_artist_string(self, artists: List[Dict], fallback: str) -> str:
        """Build the combined artist field from producers and vocalists.

        Producers use MD_VOCADB_ARTIST_USE_ORIGINAL and vocalists use
        MD_VOCADB_VOCALIST_USE_ORIGINAL, so the two parts can use different
        languages (for example, original Japanese producers with English
        vocalists).
        """
        categorised = self._categorise_artists(artists)
        names = [self._get_artist_name(art) for art in categorised["main"]]
        names += [
            self._get_vocalist_name(art) for art in categorised["vocalists"]
        ]
        return self._join_names(names) or fallback or "Unknown Artist"

    # ---------- Original artist names ----------
    def _needs_original_artist_names(self) -> bool:
        # With lang=Default the regular "name" field already contains the
        # original name, so there is nothing extra to fetch.
        if str(self.LANG).strip().lower() == "default":
            return False
        return self.ARTIST_USE_ORIGINAL or self.VOCALIST_USE_ORIGINAL

    @staticmethod
    def _collect_artist_names(data: Any) -> Dict[str, Dict[Any, str]]:
        if not isinstance(data, dict):
            return {"entries": {}, "artists": {}, "artistStrings": {}}

        items = data.get("items")
        if not isinstance(items, list):
            items = [data]

        entry_names = {}
        artist_names = {}
        artist_strings = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            artist_string = item.get("artistString")
            if (
                item_id is not None
                and isinstance(artist_string, str)
                and artist_string.strip()
            ):
                artist_strings[item_id] = artist_string

            for entry in item.get("artists") or []:
                entry_id = entry.get("id")
                entry_name = entry.get("name")
                if entry_id is not None and isinstance(entry_name, str) and entry_name:
                    entry_names[entry_id] = entry_name

                artist = entry.get("artist") or {}
                artist_id = artist.get("id")
                artist_name = artist.get("name")
                if artist_id is not None and isinstance(artist_name, str) and artist_name:
                    artist_names[artist_id] = artist_name

        return {
            "entries": entry_names,
            "artists": artist_names,
            "artistStrings": artist_strings,
        }

    def _fetch_original_artist_names(
        self, endpoint: str, params: Dict[str, Any]
    ) -> Dict[str, Dict[Any, str]]:
        """Fetch artist names and artistString with lang=Default.

        VocaDB's artist contracts do not include defaultName, so the localized
        response is not enough to honor the *_USE_ORIGINAL settings.
        """
        try:
            data = self._get(endpoint, params, lang_override="Default")
        except Exception:
            return {"entries": {}, "artists": {}, "artistStrings": {}}
        return self._collect_artist_names(data)

    @staticmethod
    def _apply_original_artist_names(
        artists: List[Dict], original_names: Dict[str, Dict[Any, str]]
    ) -> None:
        entry_names = original_names.get("entries", {})
        artist_names = original_names.get("artists", {})
        for entry in artists or []:
            if not isinstance(entry, dict):
                continue
            artist = entry.get("artist") or {}
            original = entry_names.get(entry.get("id"))
            if not original:
                original = artist_names.get(artist.get("id"))
            if original:
                entry["defaultName"] = original
                if isinstance(artist, dict):
                    artist["defaultName"] = original

    @classmethod
    def _apply_original_item_artist_names(
        cls, item: Dict, original_names: Dict[str, Dict[Any, str]]
    ) -> None:
        """Apply default artist names and artistString to a song/album item."""
        if not isinstance(item, dict):
            return
        cls._apply_original_artist_names(item.get("artists"), original_names)

        original_artist_string = original_names.get("artistStrings", {}).get(
            item.get("id")
        )
        if original_artist_string:
            item["defaultArtistString"] = original_artist_string

    @classmethod
    def _apply_original_album_artist_names(
        cls, album_data: Dict, original_names: Dict[str, Dict[Any, str]]
    ) -> None:
        cls._apply_original_item_artist_names(album_data, original_names)
        artist = album_data.get("artist")
        if isinstance(artist, dict):
            original = original_names.get("artists", {}).get(artist.get("id"))
            if original:
                artist["defaultName"] = original

    # ---------- Lyrics ----------
    @staticmethod
    def _lyric_value(lyric: Dict) -> Optional[str]:
        if not isinstance(lyric, dict):
            return None
        value = lyric.get("value")
        if isinstance(value, str) and value.strip():
            return value
        return None

    @staticmethod
    def _lyric_matches_culture(lyric: Dict, culture_code: str) -> bool:
        cultures = lyric.get("cultureCodes") or []
        return any(
            isinstance(culture, str)
            and culture.lower().startswith(culture_code)
            for culture in cultures
        )

    @classmethod
    def _find_lyric(
        cls,
        lyrics_list: List[Dict],
        translation_type: str,
        culture_code: Optional[str] = None,
    ) -> Optional[str]:
        for lyric in lyrics_list:
            if not isinstance(lyric, dict):
                continue
            if lyric.get("translationType") != translation_type:
                continue
            value = cls._lyric_value(lyric)
            if not value:
                continue
            if culture_code is not None and not cls._lyric_matches_culture(
                lyric, culture_code
            ):
                continue
            return value
        return None

    def _extract_lyrics(self, lyrics_list: List[Dict]) -> Optional[str]:
        if not lyrics_list:
            return None

        lyrics_lang = (self.LYRICS_LANG or "Default").strip()
        normalized_lang = lyrics_lang.lower()

        # "Default" means the song's original lyrics, whatever language the
        # original happens to be in (Japanese, English, etc.).
        if normalized_lang in ("default", "original", ""):
            value = self._find_lyric(lyrics_list, "Original")
            if value:
                return value
            value = self._find_lyric(lyrics_list, "Romanized")
            if value:
                return value

        # Romaji/romanized lyrics are not tied to a culture code.
        elif normalized_lang in ("romaji", "romanized"):
            value = self._find_lyric(lyrics_list, "Romanized")
            if value:
                return value
            value = self._find_lyric(lyrics_list, "Original")
            if value:
                return value

        else:
            # Map the configured language to a VocaDB culture code.
            culture_code = self.LYRICS_CULTURE_CODES.get(normalized_lang)
            if culture_code is not None:
                # Prefer an original whose language already matches the
                # request (e.g. an English-original song), then a translation.
                for translation_type in ("Original", "Translation"):
                    value = self._find_lyric(
                        lyrics_list, translation_type, culture_code
                    )
                    if value:
                        return value

            # Requested language unavailable: fall back to the original,
            # then romanized, then any available lyrics.
            value = self._find_lyric(lyrics_list, "Original")
            if value:
                return value
            value = self._find_lyric(lyrics_list, "Romanized")
            if value:
                return value

        for lyric in lyrics_list:
            value = self._lyric_value(lyric)
            if value:
                return value
        return None

    def _collect_song_lyrics(self, song_data: Dict) -> List[Dict]:
        """Collect the song's own lyrics and those inherited from its parents.

        VocaDB exposes these as ``lyricsFromParents``: remasters, remixes and
        covers inherit lyrics from the version they are based on. Own entries
        are kept first so song-specific lyrics win over inherited ones.
        """
        lyrics = []
        seen_ids = set()

        def add_lyrics(items: Any) -> None:
            if not isinstance(items, list):
                return
            for lyric in items:
                if not isinstance(lyric, dict):
                    continue
                lyric_id = lyric.get("id")
                if lyric_id is not None:
                    if lyric_id in seen_ids:
                        continue
                    seen_ids.add(lyric_id)
                lyrics.append(lyric)

        add_lyrics(song_data.get("lyrics"))

        original_id = song_data.get("originalVersionId")
        visited = {song_data.get("id")}
        while original_id is not None and original_id not in visited:
            visited.add(original_id)
            try:
                original_data = self._get(
                    f"songs/{original_id}", {"fields": "Lyrics"}
                )
            except Exception:
                break

            add_lyrics(original_data.get("lyrics"))
            original_id = original_data.get("originalVersionId")

        return lyrics

    # ---------- Other helpers ----------
    @staticmethod
    def _format_date(date_value: Any) -> Optional[str]:
        """Format a VocaDB date string or PartialDate object."""
        if not date_value:
            return None

        if isinstance(date_value, str):
            value = date_value.strip()
            if not value:
                return None
            if "T" in value:
                value = value.split("T", 1)[0]
            return value[:10] if len(value) >= 10 else value

        if isinstance(date_value, dict):
            if date_value.get("isEmpty"):
                return None
            year = date_value.get("year")
            if not year:
                return None
            month = date_value.get("month")
            day = date_value.get("day")
            if month and day:
                return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
            if month:
                return f"{int(year):04d}-{int(month):02d}"
            return f"{int(year):04d}"

        return None

    def _get_album_date(self, album_data: Dict) -> Optional[str]:
        for key in ("releaseDate", "releaseEvent", "publishDate"):
            formatted = self._format_date(album_data.get(key))
            if formatted:
                return formatted

        for event in album_data.get("releaseEvents") or []:
            if isinstance(event, dict):
                formatted = self._format_date(event.get("date"))
                if formatted:
                    return formatted

        return None

    @staticmethod
    def _format_duration(length_seconds: Any) -> str:
        if not isinstance(length_seconds, (int, float)) or length_seconds <= 0:
            return ""
        total_seconds = int(round(length_seconds))
        return f"{total_seconds // 60}:{total_seconds % 60:02d}"

    def _format_genres(self, tags: List[Dict]) -> str:
        if not tags:
            return ""

        genre_names = []
        seen = set()
        for tag in tags:
            tag_obj = tag.get("tag", tag)
            category = (
                tag_obj.get("categoryName")
                or tag.get("categoryName")
                or tag_obj.get("category")
                or tag.get("category")
            )
            if not isinstance(category, str) or category.lower() not in ("genre", "genres"):
                continue
            name = tag_obj.get("name") or tag.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            formatted = name.strip().title()
            if formatted not in seen:
                seen.add(formatted)
                genre_names.append(formatted)
        return "; ".join(genre_names)

    def _get_cover_url(self, entity: Dict) -> Optional[str]:
        if not self.FETCH_COVER:
            return None
        main_pic = entity.get("mainPicture")
        if main_pic:
            return main_pic.get("urlOriginal") or main_pic.get("urlThumb")
        return None

    @staticmethod
    def _clean_dict(d: Dict) -> Dict:
        return {k: v for k, v in d.items() if v is not None and v != ""}

    @staticmethod
    def _clamp_limit(limit: int) -> int:
        try:
            value = int(limit)
        except (TypeError, ValueError):
            return 5
        return max(1, min(value, 100))

    # ---------- Metadata builders ----------
    def _build_track_metadata(
        self, song_data: Dict, album_data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        track = {}
        track["title"] = self._get_song_name(song_data)

        artists = song_data.get("artists", [])
        track["artist"] = self._build_artist_string(
            artists, self._get_artist_string_fallback(song_data)
        )

        categorised = self._categorise_artists(artists)
        if categorised["vocalists"]:
            vocalists = self._join_names(
                [self._get_vocalist_name(art) for art in categorised["vocalists"]]
            )
            if vocalists:
                track["vocalists"] = vocalists

        if album_data:
            track["album"] = self._get_album_name(album_data)
            track["albumArtist"] = self._get_album_main_artist(album_data)

            desc = self._get_album_description(album_data)
            if desc:
                track["description"] = desc

            publisher = self._get_album_label(album_data)
            if not publisher:
                labels = album_data.get("labels", [])
                if labels:
                    publisher = labels[0].get("name")
            if publisher:
                track["publisher"] = publisher

            catalog_number = album_data.get("catalogNumber")
            if isinstance(catalog_number, str) and catalog_number.strip():
                # Not a standard metadata-docker field, so the app writes it
                # as a custom tag: TXXX:CatalogNumber, CATALOGNUMBER, etc.
                track["CatalogNumber"] = catalog_number.strip()

            date_str = self._get_album_date(album_data)
            if date_str:
                track["date"] = date_str

            track["picture"] = self._get_cover_url(album_data)

            release_type = album_data.get("discType") or album_data.get("releaseType")
            if release_type:
                track["releaseType"] = release_type

            album_id = album_data.get("id")
            if album_id is not None:
                track["vocadb_album_id"] = album_id
        else:
            date_str = self._format_date(song_data.get("publishDate"))
            if date_str:
                track["date"] = date_str
            track["picture"] = self._get_cover_url(song_data)

        song_id = song_data.get("id")
        if song_id is not None:
            track["vocadb_song_id"] = song_id

        track["genre"] = self._format_genres(song_data.get("tags", []))

        lyrics = song_data.get("lyrics")
        if isinstance(lyrics, list):
            extracted = self._extract_lyrics(lyrics)
            if extracted:
                track["unsyncedLyrics"] = extracted
        elif isinstance(lyrics, str) and lyrics:
            track["unsyncedLyrics"] = lyrics

        extra = []
        duration = self._format_duration(song_data.get("lengthSeconds"))
        if duration:
            extra.append(duration)
        song_type = song_data.get("songType")
        if song_type:
            extra.append(song_type)
        if extra:
            track["extraInfo"] = " · ".join(extra)

        return self._clean_dict(track)

    @staticmethod
    def _select_song_album(
        albums: List[Dict], song_data: Dict
    ) -> Optional[Dict]:
        """Pick the most relevant album from a song's album list.

        VocaDB lists compilations and video releases alongside the original
        album/single, and the first entry is not always the original release.
        Prefer albums/singles/EPs and an album whose artist credit matches the
        song credit.
        """
        if not albums:
            return None

        preferred_types = {"album", "single", "ep"}
        song_artist_string = song_data.get("artistString")
        best_album = None
        best_score = None

        for album in albums:
            if not isinstance(album, dict):
                continue
            disc_type = str(
                album.get("discType") or album.get("releaseType") or ""
            ).lower()
            score = 0
            if disc_type in preferred_types:
                score += 2
            elif disc_type in ("compilation", "video"):
                score -= 2
            if song_artist_string and album.get("artistString") == song_artist_string:
                score += 3
            if best_score is None or score > best_score:
                best_score = score
                best_album = album

        return best_album or next(
            (album for album in albums if isinstance(album, dict)), None
        )

    def _fetch_album_data(self, album_id: str) -> Dict[str, Any]:
        album_data = self._get(
            f"albums/{album_id}",
            {"fields": "Artists,MainPicture,Tags,Description"},
        )
        if self._needs_original_artist_names():
            original_names = self._fetch_original_artist_names(
                f"albums/{album_id}", {"fields": "Artists"}
            )
            self._apply_original_album_artist_names(album_data, original_names)
        return album_data

    # ---------- Required methods ----------
    def search_songs(
        self, query: str, limit: int = 5, include_coverart: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        try:
            if include_coverart is None:
                include_coverart = self.FETCH_COVER
            limit = self._clamp_limit(limit)
            params = {
                "query": query,
                "maxResults": limit,
                "fields": "Artists,MainPicture",
            }
            data = self._get("songs", params)

            original_names = {}
            if self._needs_original_artist_names():
                original_names = self._fetch_original_artist_names(
                    "songs",
                    {"query": query, "maxResults": limit, "fields": "Artists"},
                )

            results = []
            for song in data.get("items", []):
                artists = song.get("artists", [])
                self._apply_original_item_artist_names(song, original_names)

                entry = {
                    "id": song.get("id"),
                    "title": self._get_song_name(song),
                    "artist": self._build_artist_string(
                        artists, self._get_artist_string_fallback(song)
                    ),
                }

                date_str = self._format_date(song.get("publishDate"))
                if date_str:
                    entry["date"] = date_str

                extra = []
                duration = self._format_duration(song.get("lengthSeconds"))
                if duration:
                    extra.append(duration)
                if song.get("songType"):
                    extra.append(song["songType"])
                if extra:
                    entry["extraInfo"] = " · ".join(extra)

                if include_coverart:
                    cover = self._get_cover_url(song)
                    if cover:
                        entry["coverart"] = cover

                results.append(self._clean_dict(entry))
            return results
        except Exception:
            return []

    def search_albums(
        self, query: str, limit: int = 5, include_coverart: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        try:
            if include_coverart is None:
                include_coverart = self.FETCH_COVER
            limit = self._clamp_limit(limit)
            params = {
                "query": query,
                "maxResults": limit,
                "fields": "Artists,MainPicture,Description",
            }
            data = self._get("albums", params)

            original_names = {}
            if self._needs_original_artist_names():
                original_names = self._fetch_original_artist_names(
                    "albums",
                    {"query": query, "maxResults": limit, "fields": "Artists"},
                )

            results = []
            for album in data.get("items", []):
                artists = album.get("artists", [])
                self._apply_original_album_artist_names(album, original_names)

                entry = {
                    "id": album.get("id"),
                    "title": self._get_album_name(album),
                    "artist": self._get_album_main_artist(album),
                }

                desc = self._get_album_description(album)
                if desc:
                    entry["description"] = desc

                date_str = self._get_album_date(album)
                if date_str:
                    entry["date"] = date_str

                release_type = album.get("discType") or album.get("releaseType")
                if release_type:
                    entry["releaseType"] = release_type

                extra = []
                if release_type:
                    extra.append(release_type)
                if album.get("catalogNumber"):
                    extra.append(album["catalogNumber"])
                if extra:
                    entry["extraInfo"] = " · ".join(extra)

                if include_coverart:
                    cover = self._get_cover_url(album)
                    if cover:
                        entry["coverart"] = cover

                results.append(self._clean_dict(entry))
            return results
        except Exception:
            return []

    def fetch_song_metadata(
        self, song_id: str, album_data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        params = {"fields": "Artists,Albums,MainPicture,Tags,Lyrics"}
        try:
            data = self._get(f"songs/{song_id}", params)
        except Exception as e:
            raise RuntimeError(f"Failed to fetch song {song_id}: {e}")

        if self._needs_original_artist_names():
            original_names = self._fetch_original_artist_names(
                f"songs/{song_id}", {"fields": "Artists"}
            )
            self._apply_original_item_artist_names(data, original_names)

        # Lyrics are not localized by the API's lang parameter, so fetch the
        # full set once and merge in lyrics inherited from parent versions.
        if isinstance(data.get("lyrics", []), list):
            data["lyrics"] = self._collect_song_lyrics(data)

        if album_data is None and data.get("albums"):
            selected_album = self._select_song_album(data["albums"], data)
            album_id = selected_album.get("id") if selected_album else None
            if album_id:
                try:
                    album_data = self._fetch_album_data(album_id)
                except Exception:
                    album_data = selected_album
            else:
                album_data = selected_album

        track = self._build_track_metadata(data, album_data)

        if not track.get("picture"):
            cover = self._get_cover_url(data)
            if cover:
                track["picture"] = cover

        return self._clean_dict(track)

    def fetch_album_metadata(self, album_id: str) -> List[Dict[str, Any]]:
        album_data = self._fetch_album_data(album_id)

        try:
            tracks_data = self._get(
                f"albums/{album_id}/tracks",
                {"fields": "Artists,Tags"},
            )
        except Exception:
            tracks_data = self._get(f"albums/{album_id}/tracks", {})

        if not isinstance(tracks_data, list):
            tracks_data = []

        tracks = []
        for track_item in tracks_data:
            song_data = track_item.get("song")
            if not song_data:
                continue

            song_id = song_data.get("id")
            if not song_id:
                continue

            try:
                track = self.fetch_song_metadata(song_id, album_data=album_data)
            except Exception:
                continue

            track_num = track_item.get("trackNumber")
            if track_num is not None:
                track["trackNumber"] = str(track_num)
            disc_num = track_item.get("discNumber")
            if disc_num is not None:
                track["diskNumber"] = str(disc_num)

            if album_data:
                cover = self._get_cover_url(album_data)
                if cover:
                    track["picture"] = cover

            tracks.append(self._clean_dict(track))

        return tracks
