# VocaDB.py
# Addon implementation using VocaDB API

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
    USER_AGENT = "metadata-docker-vocadb-addon/1.0.0"

    required_env_vars = ["MD_VOCADB_LANG", "MD_VOCADB_SONG_USE_ORIGINAL", "MD_VOCADB_ARTIST_USE_ORIGINAL", "MD_VOCADB_ALBUM_USE_ORIGINAL", "MD_VOCADB_VOCALIST_USE_ORIGINAL", "MD_VOCADB_FETCH_COVER", "MD_VOCADB_REQUEST_DELAY"]

    # Environment variables (all optional with defaults)
    LANG = os.getenv("MD_VOCADB_LANG", "English")
    SONG_USE_ORIGINAL = os.getenv("MD_VOCADB_SONG_USE_ORIGINAL", "false").lower() in ('true', '1', 'yes', 'on')
    ARTIST_USE_ORIGINAL = os.getenv("MD_VOCADB_ARTIST_USE_ORIGINAL", "false").lower() in ('true', '1', 'yes', 'on')
    ALBUM_USE_ORIGINAL = os.getenv("MD_VOCADB_ALBUM_USE_ORIGINAL", "false").lower() in ('true', '1', 'yes', 'on')
    VOCALIST_USE_ORIGINAL = os.getenv("MD_VOCADB_VOCALIST_USE_ORIGINAL", "false").lower() in ('true', '1', 'yes', 'on')
    FETCH_COVER = os.getenv("MD_VOCADB_FETCH_COVER", "true").lower() in ('true', '1', 'yes', 'on')
    REQUEST_DELAY = float(os.getenv("MD_VOCADB_REQUEST_DELAY", "0.0"))

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.USER_AGENT
        })
        self._last_request_time = 0.0

    def _rate_limit(self):
        if self.REQUEST_DELAY > 0:
            now = time.time()
            elapsed = now - self._last_request_time
            if elapsed < self.REQUEST_DELAY:
                time.sleep(self.REQUEST_DELAY - elapsed)
            self._last_request_time = time.time()

    def _get(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self._rate_limit()
        url = self.BASE_URL + endpoint
        params.setdefault("fmt", "json")
        params["lang"] = self.LANG
        try:
            resp = self.session.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"VocaDB API error: {e}")

    # ---------- Helpers for extracting names ----------
    def _get_name(self, entity: Dict, use_original: bool) -> str:
        if use_original:
            # Try to get the original name (defaultName)
            original = entity.get("defaultName")
            if original and original.strip():
                return original
            # Fallback to localized name if original is missing
            localized = entity.get("name")
            if localized and localized.strip():
                return localized
            return "Unknown"
        else:
            # Prefer localized name
            localized = entity.get("name")
            if localized and localized.strip():
                return localized
            # Fallback to original name
            return entity.get("defaultName", "Unknown")

    def _get_artist_name(self, artist_data: Dict) -> str:
        return self._get_name(artist_data, self.ARTIST_USE_ORIGINAL)

    def _get_album_name(self, album_data: Dict) -> str:
        return self._get_name(album_data, self.ALBUM_USE_ORIGINAL)

    def _get_song_name(self, song_data: Dict) -> str:
        return self._get_name(song_data, self.SONG_USE_ORIGINAL)

    def _get_vocalist_name(self, artist_data: Dict) -> str:
        return self._get_name(artist_data, self.VOCALIST_USE_ORIGINAL)

    # ---------- Artist categorisation ----------
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
            art_type = art.get('categories')
            if art_type == 'Producer':
                producers.append(self._get_artist_name(art))
            elif art_type == 'Vocalist':
                vocalists.append(self._get_vocalist_name(art))
            else:
                if art_type not in others:
                    others[art_type] = []
                others[art_type].append(self._get_artist_name(art))

        if producers:
            result['main'] = producers
        else:
            first = artists[0]
            result['main'].append(self._get_artist_name(first))

        result['vocalists'] = vocalists
        result['others'] = others
        return result

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
        """Extract tags with category 'Genre' or 'Genres' (case‑insensitive)."""
        if not tags:
            return ""
        genre_names = []
        for tag in tags:
            # Sometimes the tag is nested under 'tag' key
            tag_obj = tag.get("tag", tag)
            # Get category from either 'categoryName' or 'category'
            category = tag_obj.get("categoryName") or tag.get("categoryName") or tag_obj.get("category") or tag.get("category")
            # Check if category is genre-like (case-insensitive)
            if category and category.lower() in ("genre", "genres"):
                name = tag_obj.get("name") or tag.get("name")
                if name:
                    genre_names.append(name.title())
        # If no genre tags found, fallback to any tag that isn't obviously non-genre
        if not genre_names:
            # Optionally: collect tags that are not in a blacklist
            # (but we'll just return empty to avoid false positives)
            pass
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
                field_name = f"vocadb_{art_type.lower()}"
                track[field_name] = "; ".join(names)

        if album_data:
            track["album"] = self._get_album_name(album_data)

            album_artist_obj = album_data.get('artist')
            if album_artist_obj:
                track['albumArtist'] = self._get_artist_name(album_artist_obj)
            else:
                album_artists = album_data.get('artists', [])
                if album_artists:
                    track['albumArtist'] = self._get_artist_name(album_artists[0])
                else:
                    if categorised['main']:
                        track['albumArtist'] = categorised['main'][0]
                    else:
                        track['albumArtist'] = track.get('artist', 'Unknown Artist')

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

        for key in ["artistType", "publishDate", "releaseDate", "version", "status", "ratingScore", "favoritedTimes"]:
            if key in song_data:
                track[f"vocadb_{key}"] = song_data[key]

        if "length" in song_data:
            track["length"] = song_data["length"]

        return self._clean_dict(track)

    # ---------- Required Methods ----------

    def search_songs(self, query: str, limit: int = 5, include_coverart: Optional[bool] = None) -> List[Dict[str, Any]]:
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

    def search_albums(self, query: str, limit: int = 5, include_coverart: Optional[bool] = None) -> List[Dict[str, Any]]:
        if include_coverart is None:
            include_coverart = self.FETCH_COVER
        params = {
            "query": query,
            "limit": min(limit, 100),
            "fields": "Artists,MainPicture,ReleaseEvent"
        }
        data = self._get("albums", params)
        results = []
        for album in data.get("items", []):
            entry = {
                "id": album.get("id"),
                "title": self._get_album_name(album),
            }
            album_artist_obj = album.get('artist')
            if album_artist_obj:
                entry["artist"] = self._get_artist_name(album_artist_obj)
            else:
                album_artists = album.get('artists', [])
                if album_artists:
                    entry["artist"] = self._get_artist_name(album_artists[0])
                else:
                    entry["artist"] = album.get('artistString', 'Unknown Artist')

            release_event = album.get("releaseEvent")
            if release_event:
                date_str = release_event.get("date")
                if date_str:
                    entry["year"] = self._format_date(date_str)

            if include_coverart:
                entry["coverart"] = self._get_cover_url(album)
            results.append(self._clean_dict(entry))
        return results[:limit]

    def fetch_song_metadata(self, song_id: str) -> Dict[str, Any]:
        params = {
            "fields": "Artists,Albums,ReleaseEvent,MainPicture,Tags"
        }
        data = self._get(f"songs/{song_id}", params)

        album_data = None
        if data.get("albums"):
            first_album_entry = data["albums"][0]
            album_data = first_album_entry.get("album", first_album_entry)

        track = self._build_track_metadata(data, album_data)

        if not track.get("picture"):
            track["picture"] = self._get_cover_url(data)

        return self._clean_dict(track)

    def fetch_album_metadata(self, album_id: str) -> List[Dict[str, Any]]:
        # Get album metadata (cover, date, main artist)
        album_params = {"fields": "Artists,MainPicture,ReleaseEvent,Tags"}
        album_data = self._get(f"albums/{album_id}", album_params)

        # Get tracks – try with fields first, fallback to no fields
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

            # If we have minimal data, fetch full song
            if not song_data.get("artists") or not song_data.get("tags"):
                song_id = song_data.get("id")
                if not song_id:
                    continue
                track = self.fetch_song_metadata(song_id)
            else:
                track = self._build_track_metadata(song_data, album_data)

            # Add track/disc numbers
            track_num = track_item.get("trackNumber")
            if track_num is not None:
                track["track"] = str(track_num)
            disc_num = track_item.get("discNumber")
            if disc_num is not None:
                track["disk"] = str(disc_num)

            # ALWAYS use the album cover art for every track
            if album_data:
                track["picture"] = self._get_cover_url(album_data)

            tracks.append(self._clean_dict(track))

        return tracks