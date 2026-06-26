# VocaDB.py
# Addon implementation using VocaDB API
# v1.0.4

import os
import requests
import time
from typing import List, Dict, Any, Optional
from addon_base import MetadataFetcher

class VocaDB(MetadataFetcher):
    name = "VocaDB"
    id = "vocadb"
    description = "Fetch song and album metadata from VocaDB"

    BASE_URL = "https://vocadb.net/api/"
    USER_AGENT = "metadata-docker-vocadb-addon/1.0.4"

    required_env_vars = ["MD_VOCADB_LANG", "MD_VOCADB_LYRICS_LANG", "MD_VOCADB_SONG_USE_ORIGINAL",
                        "MD_VOCADB_ARTIST_USE_ORIGINAL", "MD_VOCADB_ALBUM_USE_ORIGINAL", "MD_VOCADB_VOCALIST_USE_ORIGINAL",
                        "MD_VOCADB_FETCH_COVER", "MD_VOCADB_REQUEST_DELAY"]  

    # All have defaults
    LANG = os.getenv("MD_VOCADB_LANG", "English")
    LYRICS_LANG = os.getenv("MD_VOCADB_LYRICS_LANG", LANG)
    SONG_USE_ORIGINAL = os.getenv("MD_VOCADB_SONG_USE_ORIGINAL", "false").lower() in ('true', '1', 'yes', 'on')
    ARTIST_USE_ORIGINAL = os.getenv("MD_VOCADB_ARTIST_USE_ORIGINAL", "false").lower() in ('true', '1', 'yes', 'on')
    ALBUM_USE_ORIGINAL = os.getenv("MD_VOCADB_ALBUM_USE_ORIGINAL", "false").lower() in ('true', '1', 'yes', 'on')
    VOCALIST_USE_ORIGINAL = os.getenv("MD_VOCADB_VOCALIST_USE_ORIGINAL", "false").lower() in ('true', '1', 'yes', 'on')
    FETCH_COVER = os.getenv("MD_VOCADB_FETCH_COVER", "true").lower() in ('true', '1', 'yes', 'on')
    REQUEST_DELAY = float(os.getenv("MD_VOCADB_REQUEST_DELAY", "0.0"))

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.USER_AGENT})
        self._last_request_time = 0.0

    def _rate_limit(self):
        if self.REQUEST_DELAY > 0:
            now = time.time()
            elapsed = now - self._last_request_time
            if elapsed < self.REQUEST_DELAY:
                time.sleep(self.REQUEST_DELAY - elapsed)
            self._last_request_time = time.time()

    def _get(self, endpoint: str, params: Dict[str, Any], lang_override: Optional[str] = None) -> Dict[str, Any]:
        self._rate_limit()
        url = self.BASE_URL + endpoint
        params.setdefault("fmt", "json")
        lang = lang_override if lang_override is not None else self.LANG
        params["lang"] = lang

        try:
            resp = self.session.get(url, params=params, timeout=20)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"VocaDB API error: {e}")

    # ---------- Helpers for extracting names ----------
    def _get_name(self, entity: Dict, use_original: bool) -> str:
        if use_original:
            original = entity.get("defaultName")
            if original and original.strip():
                return original
            localized = entity.get("name")
            if localized and localized.strip():
                return localized
            return "Unknown"
        else:
            localized = entity.get("name")
            if localized and localized.strip():
                return localized
            return entity.get("defaultName", "Unknown")

    def _get_artist_name(self, artist_data: Dict) -> str:
        return self._get_name(artist_data, self.ARTIST_USE_ORIGINAL)

    def _get_album_name(self, album_data: Dict) -> str:
        return self._get_name(album_data, self.ALBUM_USE_ORIGINAL)

    def _get_song_name(self, song_data: Dict) -> str:
        return self._get_name(song_data, self.SONG_USE_ORIGINAL)

    def _get_vocalist_name(self, artist_data: Dict) -> str:
        return self._get_name(artist_data, self.VOCALIST_USE_ORIGINAL)

    def _get_album_description(self, album_data: Dict) -> Optional[str]:
        desc = album_data.get('description')
        if desc and desc.strip():
            return desc
        return None

    # ---------- Artist detection for albums ----------
    def _get_album_main_artist(self, album_data: Dict) -> str:
        """Return the Producer (or first artist) as the main artist."""
        artists = album_data.get('artists', [])
        artist_obj = album_data.get('artist')

        # First, look for a Producer in the artists list
        for art in artists:
            art_type = art.get('artistType')
            if not art_type:
                categories = art.get('categories')
                if isinstance(categories, list):
                    if "Producer" in categories:
                        art_type = "Producer"
                elif isinstance(categories, str) and categories == "Producer":
                    art_type = "Producer"
            if art_type == 'Producer':
                return self._get_artist_name(art)

        # If no Producer, use the 'artist' object if present
        if artist_obj:
            return self._get_artist_name(artist_obj)

        # If still nothing, use the first artist or artistString
        if artists:
            return self._get_artist_name(artists[0])

        return album_data.get('artistString', 'Unknown Artist')

    def _get_album_label(self, album_data: Dict) -> Optional[str]:
        """Return the label artist if present (categories contains 'Label')."""
        artists = album_data.get('artists', [])
        for art in artists:
            categories = art.get('categories')
            if isinstance(categories, list):
                if "Label" in categories:
                    return self._get_artist_name(art)
            elif isinstance(categories, str) and categories == "Label":
                return self._get_artist_name(art)
        return None

    # ---------- Artist categorisation for songs ----------
    def _categorise_artists(self, artists: List[Dict]) -> Dict[str, List[str]]:
        result = {
            'main': [],
            'vocalists': [],
            'others': {}
        }
        if not artists:
            return result

        producers = []
        vocalists = []
        others = {}
        for art in artists:
            art_type = art.get('artistType')
            if not art_type:
                categories = art.get('categories')
                if isinstance(categories, list):
                    if "Producer" in categories:
                        art_type = "Producer"
                    elif "Vocalist" in categories:
                        art_type = "Vocalist"
                    else:
                        art_type = categories[0] if categories else None
                elif isinstance(categories, str):
                    if categories == "Producer":
                        art_type = "Producer"
                    elif categories == "Vocalist":
                        art_type = "Vocalist"
                    else:
                        art_type = categories
                # else leave as None

            if art_type == 'Producer':
                producers.append(self._get_artist_name(art))
            elif art_type == 'Vocalist':
                vocalists.append(self._get_vocalist_name(art))
            else:
                key = art_type if art_type else 'other'
                if key not in others:
                    others[key] = []
                others[key].append(self._get_artist_name(art))

        if producers:
            result['main'] = producers
        else:
            first = artists[0]
            result['main'].append(self._get_artist_name(first))

        result['vocalists'] = vocalists
        result['others'] = others

        return result

    def _extract_lyrics(self, lyrics_list: List[Dict]) -> Optional[str]:
        if not lyrics_list:
            return None

        # Map our language names to VocaDB translationType and culture filter
        lang_map = {
            'English': ('Translation', 'en'),      # Translation with cultureCode containing 'en'
            'Romaji': ('Romanized', None),         # Romanized (no culture filter needed)
            'Japanese': ('Original', None),        # Original (Japanese)
            'Default': ('Original', None)
        }
        target_type, target_culture = lang_map.get(self.LYRICS_LANG, ('Original', None))

        # Try to find the exact match
        for lyric in lyrics_list:
            if lyric.get('translationType') == target_type:
                if target_culture is not None:
                    cultures = lyric.get('cultureCodes', [])
                    # Check if any culture code starts with the target (e.g., 'en' for English)
                    if any(c.lower().startswith(target_culture) for c in cultures):
                        return lyric.get('value')
                else:
                    # No culture filter needed (Romaji or Original)
                    return lyric.get('value')

        # Fallback: try Original, then Romanized, then any available
        for lyric in lyrics_list:
            if lyric.get('translationType') == 'Original':
                return lyric.get('value')
        for lyric in lyrics_list:
            if lyric.get('translationType') == 'Romanized':
                return lyric.get('value')
        for lyric in lyrics_list:
            if lyric.get('value'):
                return lyric.get('value')
        return None

    # ---------- Other helpers ----------
    @staticmethod
    def _format_date(date_str: Optional[str]) -> Optional[str]:
        if date_str:
            if 'T' in date_str:
                return date_str[:10]
            if len(date_str) >= 10:
                return date_str[:10]
            return date_str
        return None

    def _format_genres(self, tags: List[Dict]) -> str:
        if not tags:
            return ""
        genre_names = []
        for tag in tags:
            tag_obj = tag.get("tag", tag)
            category = tag_obj.get("categoryName") or tag.get("categoryName") or tag_obj.get("category") or tag.get("category")
            if category and category.lower() in ("genre", "genres"):
                name = tag_obj.get("name") or tag.get("name")
                if name:
                    genre_names.append(name.title())
        return "; ".join(genre_names)

    def _get_cover_url(self, entity: Dict) -> Optional[str]:
        if not self.FETCH_COVER:
            return None
        main_pic = entity.get("mainPicture")
        if main_pic:
            return main_pic.get("urlOriginal") or main_pic.get("urlThumb")
        return None

    def _clean_dict(self, d: Dict) -> Dict:
        return {k: v for k, v in d.items() if v is not None and v != ""}

    def _build_track_metadata(self, song_data: Dict, album_data: Dict = None) -> Dict[str, Any]:
        track = {}

        track["id"] = song_data.get("id")
        track["title"] = self._get_song_name(song_data)

        artists = song_data.get("artists", [])
        categorised = self._categorise_artists(artists)

        artist_parts = categorised['main'] + categorised['vocalists']
        if artist_parts:
            track["artist"] = "; ".join(artist_parts)
        else:
            track["artist"] = song_data.get("artistString", "Unknown Artist")

        if categorised['vocalists']:
            track["vocalists"] = "; ".join(categorised['vocalists'])

        for art_type, names in categorised['others'].items():
            if names:
                if art_type and art_type != 'other':
                    field_name = f"vocadb_{art_type.lower()}"
                    track[field_name] = "; ".join(names)
                else:
                    if "vocadb_other" in track:
                        track["vocadb_other"] += "; " + "; ".join(names)
                    else:
                        track["vocadb_other"] = "; ".join(names)

        if album_data:
            track["album"] = self._get_album_name(album_data)
            track['albumArtist'] = self._get_album_main_artist(album_data)

            desc = self._get_album_description(album_data)
            if desc:
                track["description"] = desc

            # Extract label if present
            label = self._get_album_label(album_data)
            if label:
                track["label"] = label
                track["vocadb_label"] = label

            release_event = album_data.get("releaseEvent")
            if release_event:
                date_str = release_event.get("date")
                if date_str:
                    formatted = self._format_date(date_str)
                    track["year"] = formatted
                    track["vocadb_full_date"] = date_str

            track["picture"] = self._get_cover_url(album_data)

            labels = album_data.get("labels", [])
            if labels:
                track["publisher"] = labels[0].get("name")

            if "releaseType" in album_data:
                track["releaseType"] = album_data["releaseType"]

            track["vocadb_album_id"] = album_data.get("id")
        else:
            track["picture"] = self._get_cover_url(song_data)

        tags = song_data.get("tags", [])
        track["genre"] = self._format_genres(tags)

        if "lyrics" in song_data:
            lyrics_list = song_data.get("lyrics")
            if isinstance(lyrics_list, list):
                track["unsyncedLyrics"] = self._extract_lyrics(lyrics_list)
            elif isinstance(lyrics_list, str):
                track["unsyncedLyrics"] = lyrics_list

        for key in ["artistType", "publishDate", "releaseDate", "version", "status", "ratingScore", "favoritedTimes"]:
            if key in song_data:
                track[f"vocadb_{key}"] = song_data[key]

        if "length" in song_data:
            track["length"] = song_data["length"]

        return self._clean_dict(track)

    # ---------- Required Methods ----------

    def search_songs(self, query: str, limit: int = 5, include_coverart: Optional[bool] = None) -> List[Dict[str, Any]]:
        try:
            if include_coverart is None:
                include_coverart = self.FETCH_COVER
            params = {
                "query": query,
                "limit": min(limit, 100),
                "fields": "Artists,MainPicture"
            }
            data = self._get("songs", params)
            results = []
            for song in data.get("items", []):
                entry = {
                    "id": song.get("id"),
                    "title": self._get_song_name(song),
                }
                artists = song.get("artists", [])
                categorised = self._categorise_artists(artists)
                artist_parts = categorised['main'] + categorised['vocalists']
                if artist_parts:
                    entry["artist"] = "; ".join(artist_parts)
                else:
                    entry["artist"] = song.get("artistString", "Unknown Artist")

                if include_coverart:
                    entry["coverart"] = self._get_cover_url(song)
                results.append(self._clean_dict(entry))
            return results[:limit]
        except Exception as e:
            return []

    def search_albums(self, query: str, limit: int = 5, include_coverart: Optional[bool] = None) -> List[Dict[str, Any]]:
        try:
            if include_coverart is None:
                include_coverart = self.FETCH_COVER
            params = {
                "query": query,
                "limit": min(limit, 100),
                "fields": "Artists,MainPicture,ReleaseEvent,Description"
            }
            data = self._get("albums", params)
            results = []
            for album in data.get("items", []):
                entry = {
                    "id": album.get("id"),
                    "title": self._get_album_name(album),
                    "artist": self._get_album_main_artist(album)
                }

                desc = self._get_album_description(album)
                if desc:
                    entry["description"] = desc

                release_event = album.get("releaseEvent")
                if release_event:
                    date_str = release_event.get("date")
                    if date_str:
                        entry["year"] = self._format_date(date_str)

                if include_coverart:
                    entry["coverart"] = self._get_cover_url(album)
                results.append(self._clean_dict(entry))
            return results[:limit]
        except Exception as e:
            return []

    def fetch_song_metadata(self, song_id: str, album_data: Dict = None) -> Dict[str, Any]:
        params = {
            "fields": "Artists,Albums,ReleaseEvent,MainPicture,Tags,Lyrics"
        }
        try:
            data = self._get(f"songs/{song_id}", params)
        except Exception as e:
            raise RuntimeError(f"Failed to fetch song {song_id}: {e}")

        if self.LYRICS_LANG != self.LANG:
            try:
                lyrics_params = {"fields": "Lyrics"}
                lyrics_data = self._get(f"songs/{song_id}", lyrics_params, lang_override=self.LYRICS_LANG)
                if "lyrics" in lyrics_data:
                    data["lyrics"] = lyrics_data["lyrics"]
            except Exception:
                pass

        if album_data is None and data.get("albums"):
            first_album_entry = data["albums"][0]
            album_data = first_album_entry.get("album", first_album_entry)

        track = self._build_track_metadata(data, album_data)

        if not track.get("picture"):
            track["picture"] = self._get_cover_url(data)

        return self._clean_dict(track)

    def fetch_album_metadata(self, album_id: str) -> List[Dict[str, Any]]:
        album_params = {"fields": "Artists,MainPicture,ReleaseEvent,Tags,Description"}
        album_data = self._get(f"albums/{album_id}", album_params)

        try:
            tracks_data = self._get(
                f"albums/{album_id}/tracks",
                {"fields": "Artists,Tags"}
            )
        except Exception:
            tracks_data = self._get(f"albums/{album_id}/tracks", {})

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
            except Exception as e:
                print(f"[ERROR] Failed to fetch full song {song_id}: {e}")
                continue

            track_num = track_item.get("trackNumber")
            if track_num is not None:
                track["track"] = str(track_num)
            disc_num = track_item.get("discNumber")
            if disc_num is not None:
                track["disk"] = str(disc_num)

            if album_data:
                track["picture"] = self._get_cover_url(album_data)

            tracks.append(self._clean_dict(track))

        return tracks