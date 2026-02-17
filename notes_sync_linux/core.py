from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import tempfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
DISPLAY_FORMAT = "%Y-%m-%d %H:%M"


def now_iso() -> str:
    return datetime.utcnow().strftime(ISO_FORMAT)


def iso_to_display(value: Optional[str]) -> str:
    if not value:
        return "-"
    for fmt in (ISO_FORMAT, "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return datetime.strptime(value, fmt).strftime(DISPLAY_FORMAT)
        except ValueError:
            continue
    return value


@dataclass
class SyncedFileItem:
    relative_path: str
    local_relative_path: str
    sha256: str = ""
    modified_at: Optional[str] = None
    size_bytes: Optional[int] = None
    mime_type: Optional[str] = None

    @property
    def id(self) -> str:
        return self.local_relative_path

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "local_relative_path": self.local_relative_path,
            "sha256": self.sha256,
            "modified_at": self.modified_at,
            "size_bytes": self.size_bytes,
            "mime_type": self.mime_type,
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "SyncedFileItem":
        return SyncedFileItem(
            relative_path=raw.get("relative_path") or raw.get("relativePath") or "",
            local_relative_path=raw.get("local_relative_path") or raw.get("localRelativePath") or "",
            sha256=raw.get("sha256") or "",
            modified_at=raw.get("modified_at") or raw.get("modifiedAt"),
            size_bytes=raw.get("size_bytes") if raw.get("size_bytes") is not None else raw.get("sizeBytes"),
            mime_type=raw.get("mime_type") or raw.get("mimeType"),
        )


@dataclass
class NoteItem:
    id: str
    title: str
    url: str
    file_name: str
    is_group: bool = False
    parent_id: Optional[str] = None
    sha256: Optional[str] = None
    last_checked_at: Optional[str] = None
    last_updated_at: Optional[str] = None
    status: str = "Never synced"
    last_error: Optional[str] = None
    source_type: Optional[str] = None
    folder_files: list[SyncedFileItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "file_name": self.file_name,
            "is_group": self.is_group,
            "parent_id": self.parent_id,
            "sha256": self.sha256,
            "last_checked_at": self.last_checked_at,
            "last_updated_at": self.last_updated_at,
            "status": self.status,
            "last_error": self.last_error,
            "source_type": self.source_type,
            "folder_files": [f.to_dict() for f in self.folder_files],
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "NoteItem":
        folder_files_raw = raw.get("folder_files")
        if folder_files_raw is None:
            folder_files_raw = raw.get("folderFiles")
        return NoteItem(
            id=str(raw.get("id") or uuid.uuid4()),
            title=raw.get("title") or "Untitled",
            url=raw.get("url") or "",
            file_name=raw.get("file_name") or raw.get("fileName") or "",
            is_group=bool(raw.get("is_group") if raw.get("is_group") is not None else raw.get("isGroup", False)),
            parent_id=raw.get("parent_id") if raw.get("parent_id") is not None else raw.get("parentId"),
            sha256=raw.get("sha256"),
            last_checked_at=raw.get("last_checked_at") or raw.get("lastCheckedAt"),
            last_updated_at=raw.get("last_updated_at") or raw.get("lastUpdatedAt"),
            status=raw.get("status") or "Never synced",
            last_error=raw.get("last_error") or raw.get("lastError"),
            source_type=raw.get("source_type") or raw.get("sourceType"),
            folder_files=[SyncedFileItem.from_dict(x) for x in (folder_files_raw or [])],
        )


@dataclass
class AppConfig:
    check_interval_minutes: int = 180
    skip_video_files: bool = False
    skip_large_files: bool = False
    max_file_size_mb: int = 100
    file_sort_mode: str = "name"
    notes: list[NoteItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        sort_mode = (self.file_sort_mode or "name").strip().lower()
        if sort_mode not in ("name", "date"):
            sort_mode = "name"
        return {
            "check_interval_minutes": max(5, int(self.check_interval_minutes)),
            "skip_video_files": bool(self.skip_video_files),
            "skip_large_files": bool(self.skip_large_files),
            "max_file_size_mb": max(1, int(self.max_file_size_mb)),
            "file_sort_mode": sort_mode,
            "notes": [n.to_dict() for n in self.notes],
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "AppConfig":
        notes_raw = raw.get("notes") or []

        check_interval = raw.get("check_interval_minutes")
        if check_interval is None:
            check_interval = raw.get("checkIntervalMinutes", 180)

        skip_video = raw.get("skip_video_files")
        if skip_video is None:
            skip_video = raw.get("skipVideoFiles", False)

        skip_large = raw.get("skip_large_files")
        if skip_large is None:
            skip_large = raw.get("skipLargeFiles", False)

        max_size = raw.get("max_file_size_mb")
        if max_size is None:
            max_size = raw.get("maxFileSizeMB", 100)

        sort_mode = raw.get("file_sort_mode")
        if sort_mode is None:
            sort_mode = raw.get("fileSortMode", "name")
        normalized_sort_mode = str(sort_mode or "name").strip().lower()
        if normalized_sort_mode not in ("name", "date"):
            normalized_sort_mode = "name"

        return AppConfig(
            check_interval_minutes=max(5, int(check_interval or 180)),
            skip_video_files=bool(skip_video),
            skip_large_files=bool(skip_large),
            max_file_size_mb=max(1, int(max_size or 100)),
            file_sort_mode=normalized_sort_mode,
            notes=[NoteItem.from_dict(n) for n in notes_raw],
        )


@dataclass
class DownloadOptions:
    skip_video_files: bool = False
    skip_large_files: bool = False
    max_file_size_bytes: int = 100 * 1_048_576


@dataclass
class FolderDownloadPreview:
    remote_path: str
    local_relative_path: str
    modified_at: Optional[str]
    size_bytes: Optional[int]
    mime_type: Optional[str]


@dataclass
class FolderDownloadProgress:
    processed_count: int
    total_count: int
    latest_file: Optional[FolderDownloadPreview]


@dataclass
class DownloadedFolderFile:
    remote_path: str
    local_relative_path: str
    temp_path: Optional[Path]
    modified_at: Optional[str]
    size_bytes: Optional[int]
    mime_type: Optional[str]
    was_skipped: bool
    download_error: Optional[str]


@dataclass
class SyncResult:
    note: NoteItem
    updated_count: int
    error_count: int


class DownloadError(RuntimeError):
    pass


class SyncCancelled(RuntimeError):
    pass


class StorageManager:
    def __init__(self) -> None:
        home = Path.home()
        self.base_dir = home / ".notes-sync-app-linux"
        self.pdf_dir = self.base_dir / "pdfs"
        self.sources_dir = self.base_dir / "sources"
        self.temp_dir = self.base_dir / "tmp"
        self.config_file = self.base_dir / "config.json"

        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.pdf_dir.mkdir(parents=True, exist_ok=True)
        self.sources_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def load_config(self) -> AppConfig:
        if not self.config_file.exists():
            return AppConfig()

        raw = json.loads(self.config_file.read_text(encoding="utf-8"))
        return AppConfig.from_dict(raw)

    def save_config(self, config: AppConfig) -> None:
        payload = json.dumps(config.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        tmp_file = self.config_file.with_suffix(".tmp")
        tmp_file.write_text(payload, encoding="utf-8")
        tmp_file.replace(self.config_file)

    def make_file_name(self, title: str, note_id: str) -> str:
        folded = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii").lower()
        slug = re.sub(r"[^a-z0-9]+", "-", folded).strip("-")
        if not slug:
            slug = "note"
        return f"{slug[:36]}-{note_id[:8]}.pdf"

    def single_file_path(self, note: NoteItem) -> Path:
        return self.pdf_dir / note.file_name

    def source_dir(self, note: NoteItem) -> Path:
        return self.sources_dir / note.id

    def source_file_path(self, note: NoteItem, local_relative_path: str) -> Path:
        return self.source_dir(note) / local_relative_path


class NotesDownloader:
    VIDEO_EXTENSIONS = {
        "3gp",
        "avi",
        "flv",
        "m2ts",
        "m4v",
        "mkv",
        "mov",
        "mp4",
        "mpeg",
        "mpg",
        "mts",
        "ogv",
        "ts",
        "webm",
        "wmv",
    }

    def __init__(self) -> None:
        self.request_timeout = 120

    def download_source(
        self,
        source: str,
        temp_dir: Path,
        options: DownloadOptions,
        progress_cb: Optional[Callable[[FolderDownloadProgress], None]] = None,
        cancel_event: Optional["threading.Event"] = None,
    ) -> tuple[str, Any]:
        self._check_cancel(cancel_event)
        source_url = self._parse_url(source)
        host = (source_url.hostname or "").lower()
        absolute = source_url.geturl().lower()

        if (
            absolute.startswith("ya-disk-public://")
            or "yadi.sk" in host
            or "disk.yandex" in host
            or "disk.360.yandex" in host
            or "docs.yandex" in host
        ):
            return self._download_from_yandex(source_url, temp_dir, options, progress_cb, cancel_event)

        if "drive.google.com" in host or "docs.google.com" in host:
            data = self._download_from_google_drive(source_url, cancel_event)
        else:
            data = self._fetch_bytes(self._normalize_direct_download_url(source_url), cancel_event)

        temp_path = self._write_temp_file(data, temp_dir, preferred_ext="pdf")
        return ("single", temp_path)

    def download_single_file_to_temp(
        self,
        source: str,
        remote_path: str,
        temp_dir: Path,
        cancel_event: Optional["threading.Event"] = None,
    ) -> Path:
        self._check_cancel(cancel_event)
        source_url = self._parse_url(source)

        resource = self._resolve_yandex_public_resource(source_url)
        if not resource:
            raise DownloadError("Single-file on-demand download is currently supported only for Yandex folder sources")

        data = self._download_from_yandex_resource(resource["public_key"], remote_path, cancel_event)
        ext = Path(remote_path).suffix.lstrip(".") or "bin"
        return self._write_temp_file(data, temp_dir, preferred_ext=ext)

    def _download_from_yandex(
        self,
        source_url: urllib.parse.ParseResult,
        temp_dir: Path,
        options: DownloadOptions,
        progress_cb: Optional[Callable[[FolderDownloadProgress], None]],
        cancel_event: Optional["threading.Event"],
    ) -> tuple[str, Any]:
        resource = self._resolve_yandex_public_resource(source_url)
        if not resource:
            raise DownloadError("Unsupported Yandex link format")

        root_resource = self._fetch_yandex_public_resource(resource["public_key"], resource.get("path"), cancel_event)
        if root_resource and root_resource.get("type") == "dir":
            files = self._download_yandex_folder_files(
                resource["public_key"],
                root_resource.get("path") or resource.get("path"),
                temp_dir,
                options,
                progress_cb,
                cancel_event,
            )
            return ("folder", files)

        try:
            data = self._download_from_yandex_resource(resource["public_key"], resource.get("path"), cancel_event)
            ext = Path(resource.get("path") or "").suffix.lstrip(".") or "pdf"
            return ("single", self._write_temp_file(data, temp_dir, preferred_ext=ext))
        except DownloadError:
            root_resource = self._fetch_yandex_public_resource(resource["public_key"], None, cancel_event)
            if root_resource and root_resource.get("type") == "dir":
                files = self._download_yandex_folder_files(
                    resource["public_key"],
                    root_resource.get("path"),
                    temp_dir,
                    options,
                    progress_cb,
                    cancel_event,
                )
                return ("folder", files)
            raise

    def _download_yandex_folder_files(
        self,
        public_key: str,
        folder_path: Optional[str],
        temp_dir: Path,
        options: DownloadOptions,
        progress_cb: Optional[Callable[[FolderDownloadProgress], None]],
        cancel_event: Optional["threading.Event"],
    ) -> list[DownloadedFolderFile]:
        entries = self._collect_yandex_files(public_key, folder_path, cancel_event=cancel_event)
        files = [x for x in entries if x.get("type") == "file" and x.get("path")]

        results: list[DownloadedFolderFile] = []
        if progress_cb:
            progress_cb(FolderDownloadProgress(processed_count=0, total_count=len(files), latest_file=None))

        processed = 0
        for entry in files:
            self._check_cancel(cancel_event)
            remote_path = entry["path"]
            local_path = self._make_safe_relative_path(remote_path, folder_path)
            modified_at = self._normalize_modified(entry.get("modified"))
            size_bytes = entry.get("size")
            mime_type = entry.get("mime_type")

            temp_path: Optional[Path] = None
            was_skipped = False
            download_error: Optional[str] = None

            if options.skip_video_files and self._is_video_entry(entry):
                was_skipped = True
            elif options.skip_large_files and options.max_file_size_bytes > 0 and isinstance(size_bytes, int) and size_bytes > options.max_file_size_bytes:
                was_skipped = True
            else:
                try:
                    data = self._download_from_yandex_resource(public_key, remote_path, cancel_event)
                    ext = Path(entry.get("name") or "").suffix.lstrip(".") or "bin"
                    temp_path = self._write_temp_file(data, temp_dir, preferred_ext=ext)
                except Exception as exc:  # noqa: BLE001
                    download_error = str(exc)

            results.append(
                DownloadedFolderFile(
                    remote_path=remote_path,
                    local_relative_path=local_path,
                    temp_path=temp_path,
                    modified_at=modified_at,
                    size_bytes=size_bytes if isinstance(size_bytes, int) else None,
                    mime_type=mime_type,
                    was_skipped=was_skipped,
                    download_error=download_error,
                )
            )

            processed += 1
            if progress_cb:
                progress_cb(
                    FolderDownloadProgress(
                        processed_count=processed,
                        total_count=len(files),
                        latest_file=FolderDownloadPreview(
                            remote_path=remote_path,
                            local_relative_path=local_path,
                            modified_at=modified_at,
                            size_bytes=size_bytes if isinstance(size_bytes, int) else None,
                            mime_type=mime_type,
                        ),
                    )
                )

        return sorted(results, key=lambda x: x.local_relative_path.lower())

    def _collect_yandex_files(
        self,
        public_key: str,
        path: Optional[str],
        depth: int = 0,
        cancel_event: Optional["threading.Event"] = None,
    ) -> list[dict[str, Any]]:
        self._check_cancel(cancel_event)
        if depth > 8:
            return []

        resource = self._fetch_yandex_public_resource(public_key, path, cancel_event)
        if not resource:
            return []

        r_type = resource.get("type")
        if r_type == "file":
            return [resource]
        if r_type != "dir":
            return []

        files: list[dict[str, Any]] = []
        items = (((resource.get("_embedded") or {}).get("items")) or [])
        for item in items:
            i_type = item.get("type")
            if i_type == "file":
                files.append(item)
            elif i_type == "dir" and item.get("path"):
                files.extend(self._collect_yandex_files(public_key, item["path"], depth + 1, cancel_event))

        return files

    def _download_from_yandex_resource(
        self,
        public_key: str,
        path: Optional[str],
        cancel_event: Optional["threading.Event"],
    ) -> bytes:
        self._check_cancel(cancel_event)
        payload = self._request_yandex_download_payload(public_key, path, cancel_event)
        href = payload.get("href")
        if not href:
            raise DownloadError("Yandex Disk did not provide direct download URL")
        return self._fetch_bytes(self._parse_url(href), cancel_event)

    def _request_yandex_download_payload(
        self,
        public_key: str,
        path: Optional[str],
        cancel_event: Optional["threading.Event"],
    ) -> dict[str, Any]:
        payload = self._request_yandex_download_payload_attempt(public_key, path, cancel_event)
        if payload:
            return payload
        if path:
            payload = self._request_yandex_download_payload_attempt(public_key, None, cancel_event)
            if payload:
                return payload
        raise DownloadError("Yandex Disk did not provide direct download URL")

    def _request_yandex_download_payload_attempt(
        self,
        public_key: str,
        path: Optional[str],
        cancel_event: Optional["threading.Event"],
    ) -> Optional[dict[str, Any]]:
        self._check_cancel(cancel_event)
        query = {"public_key": public_key}
        if path:
            query["path"] = path

        url = self._parse_url(
            "https://cloud-api.yandex.net/v1/disk/public/resources/download?"
            + urllib.parse.urlencode(query, quote_via=urllib.parse.quote)
        )
        data, status, _ = self._fetch_bytes_and_response(url, cancel_event)
        if status == 404:
            return None
        if status < 200 or status >= 300:
            raise DownloadError(f"HTTP error {status}")

        try:
            payload = json.loads(data.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise DownloadError("Yandex Disk returned invalid response") from exc

        return payload if payload.get("href") else None

    def _fetch_yandex_public_resource(
        self,
        public_key: str,
        path: Optional[str],
        cancel_event: Optional["threading.Event"],
    ) -> Optional[dict[str, Any]]:
        self._check_cancel(cancel_event)
        query: dict[str, str] = {
            "public_key": public_key,
            "limit": "200",
        }
        if path:
            query["path"] = path

        url = self._parse_url(
            "https://cloud-api.yandex.net/v1/disk/public/resources?"
            + urllib.parse.urlencode(query, quote_via=urllib.parse.quote)
        )
        data, status, _ = self._fetch_bytes_and_response(url, cancel_event)
        if status == 404:
            return None
        if status < 200 or status >= 300:
            raise DownloadError(f"HTTP error {status}")

        try:
            return json.loads(data.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise DownloadError("Yandex Disk returned invalid response") from exc

    def _download_from_google_drive(
        self,
        source_url: urllib.parse.ParseResult,
        cancel_event: Optional["threading.Event"],
    ) -> bytes:
        self._check_cancel(cancel_event)
        export = self._build_google_workspace_export_url(source_url)
        if export:
            return self._fetch_bytes(export, cancel_event)

        file_id = self._extract_google_drive_file_id(source_url)
        base = self._parse_url("https://drive.google.com/uc")
        first_url = self._replace_query(
            base,
            {
                "export": "download",
                "id": file_id,
            },
        )
        first_data, _, first_headers = self._fetch_bytes_and_response(first_url, cancel_event)
        if not self._looks_like_html(first_data, first_headers):
            return first_data

        token = self._extract_google_drive_token(first_data, first_headers)
        if not token:
            raise DownloadError("Google Drive confirmation token not found")

        second_url = self._replace_query(
            base,
            {
                "export": "download",
                "id": file_id,
                "confirm": token,
            },
        )

        second_data, _, second_headers = self._fetch_bytes_and_response(second_url, cancel_event)
        if self._looks_like_html(second_data, second_headers):
            raise DownloadError("Google Drive returned HTML instead of file content")

        return second_data

    def _extract_google_drive_file_id(self, source_url: urllib.parse.ParseResult) -> str:
        absolute = source_url.geturl()
        match = re.search(r"/file/d/([a-zA-Z0-9_-]+)", absolute)
        if match:
            return match.group(1)

        query = urllib.parse.parse_qs(source_url.query)
        file_id = (query.get("id") or [""])[0]
        if file_id:
            return file_id

        raise DownloadError("Unsupported Google Drive URL format")

    def _extract_google_drive_token(self, data: bytes, headers: dict[str, str]) -> Optional[str]:
        cookie = headers.get("set-cookie", "")
        match = re.search(r"download_warning[^=]*=([^;]+)", cookie)
        if match:
            return match.group(1)

        text = data.decode("utf-8", errors="ignore")
        patterns = [
            r"confirm=([0-9A-Za-z_]+)&",
            r'name="confirm" value="([0-9A-Za-z_]+)"',
        ]
        for pattern in patterns:
            m = re.search(pattern, text)
            if m:
                return html.unescape(m.group(1))
        return None

    def _build_google_workspace_export_url(self, source_url: urllib.parse.ParseResult) -> Optional[urllib.parse.ParseResult]:
        host = (source_url.hostname or "").lower()
        if "docs.google.com" not in host:
            return None

        path = source_url.path
        patterns = [
            (r"/document/d/([A-Za-z0-9_-]+)", "https://docs.google.com/document/d/{id}/export?format=pdf"),
            (r"/spreadsheets/d/([A-Za-z0-9_-]+)", "https://docs.google.com/spreadsheets/d/{id}/export?format=pdf"),
            (r"/presentation/d/([A-Za-z0-9_-]+)", "https://docs.google.com/presentation/d/{id}/export/pdf"),
        ]

        for pattern, template in patterns:
            match = re.search(pattern, path)
            if match:
                return self._parse_url(template.format(id=match.group(1)))

        return None

    def _normalize_direct_download_url(self, source_url: urllib.parse.ParseResult) -> urllib.parse.ParseResult:
        host = (source_url.hostname or "").lower()

        if "dropbox.com" in host:
            q = urllib.parse.parse_qs(source_url.query)
            q.pop("dl", None)
            q.pop("raw", None)
            q["dl"] = ["1"]
            return self._replace_query(source_url, {k: v[-1] for k, v in q.items()})

        if host == "github.com":
            chunks = [x for x in source_url.path.split("/") if x]
            if len(chunks) >= 5 and chunks[2] == "blob":
                owner, repo, _, branch = chunks[:4]
                remaining = "/".join(chunks[4:])
                return self._parse_url(f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{remaining}")

        return source_url

    def _resolve_yandex_public_resource(self, source_url: urllib.parse.ParseResult, depth: int = 0) -> Optional[dict[str, Optional[str]]]:
        if depth > 5:
            return None

        parsed_pseudo = self._parse_yandex_public_pseudo_url(source_url.geturl())
        if parsed_pseudo:
            return parsed_pseudo

        host = (source_url.hostname or "").lower()
        if "docs.yandex" in host:
            query = urllib.parse.parse_qs(source_url.query)
            wrapped = (query.get("url") or [None])[0]
            if not wrapped:
                return {"public_key": source_url.geturl(), "path": None}
            decoded = urllib.parse.unquote(wrapped)
            parsed = self._parse_yandex_public_pseudo_url(decoded)
            if parsed:
                return parsed
            try:
                nested = self._parse_url(decoded)
            except DownloadError:
                return None
            return self._resolve_yandex_public_resource(nested, depth + 1)

        if "yadi.sk" in host or "disk.yandex" in host or "disk.360.yandex" in host:
            return {"public_key": source_url.geturl(), "path": None}

        return None

    def _parse_yandex_public_pseudo_url(self, raw: str) -> Optional[dict[str, Optional[str]]]:
        trimmed = raw.strip()
        prefix = "ya-disk-public://"
        if not trimmed.lower().startswith(prefix):
            return None

        remainder = trimmed[len(prefix) :]
        if not remainder:
            return None

        path: Optional[str] = None
        if ":/" in remainder:
            key_part, path_part = remainder.split(":/", 1)
            cleaned = path_part.strip("/")
            path = f"/{cleaned}" if cleaned else None
        else:
            key_part = remainder

        key_part = key_part.strip().replace(" ", "+")
        if not key_part:
            return None

        return {
            "public_key": prefix + key_part,
            "path": path,
        }

    def _make_safe_relative_path(self, remote_path: str, root_path: Optional[str]) -> str:
        remote_parts = self._sanitized_path_parts(remote_path)
        root_parts = self._sanitized_path_parts(root_path)

        relative = remote_parts
        if len(remote_parts) >= len(root_parts) and remote_parts[: len(root_parts)] == root_parts:
            relative = remote_parts[len(root_parts) :]

        if not relative and remote_parts:
            relative = [remote_parts[-1]]

        if not relative:
            relative = [str(uuid.uuid4())]

        return "/".join(relative)

    def _sanitized_path_parts(self, path: Optional[str]) -> list[str]:
        if not path:
            return []
        return [x for x in path.split("/") if x and x not in (".", "..")]

    def _is_video_entry(self, entry: dict[str, Any]) -> bool:
        mime = (entry.get("mime_type") or "").lower()
        if mime.startswith("video/"):
            return True

        name = (entry.get("name") or "").lower()
        ext = Path(name).suffix.lstrip(".")
        return ext in self.VIDEO_EXTENSIONS

    def _normalize_modified(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        return value

    def _write_temp_file(self, data: bytes, temp_dir: Path, preferred_ext: Optional[str]) -> Path:
        ext = preferred_ext or "bin"
        if ext.startswith("."):
            ext = ext[1:]
        with tempfile.NamedTemporaryFile(delete=False, dir=temp_dir, suffix=f".{ext}") as tmp:
            tmp.write(data)
            return Path(tmp.name)

    def _fetch_bytes(self, url: urllib.parse.ParseResult, cancel_event: Optional["threading.Event"]) -> bytes:
        data, status, _ = self._fetch_bytes_and_response(url, cancel_event)
        if status < 200 or status >= 300:
            raise DownloadError(f"HTTP error {status}")
        return data

    def _fetch_bytes_and_response(
        self,
        url: urllib.parse.ParseResult,
        cancel_event: Optional["threading.Event"],
    ) -> tuple[bytes, int, dict[str, str]]:
        self._check_cancel(cancel_event)
        req = urllib.request.Request(url.geturl(), headers={"User-Agent": "NotesSyncLinux/1.0"})

        try:
            with urllib.request.urlopen(req, timeout=self.request_timeout) as resp:
                data = resp.read()
                status = resp.getcode() or 0
                headers = {k.lower(): v for k, v in resp.headers.items()}
                return data, status, headers
        except urllib.error.HTTPError as exc:
            data = exc.read() if exc.fp else b""
            headers = {k.lower(): v for k, v in (exc.headers.items() if exc.headers else [])}
            return data, exc.code, headers
        except urllib.error.URLError as exc:
            raise DownloadError(str(exc.reason)) from exc

    def _looks_like_html(self, data: bytes, headers: dict[str, str]) -> bool:
        content_type = (headers.get("content-type") or "").lower()
        if "text/html" in content_type:
            return True
        prefix = data[:256].decode("utf-8", errors="ignore").lower()
        return "<html" in prefix or "<!doctype html" in prefix

    def _replace_query(self, url: urllib.parse.ParseResult, query_dict: dict[str, str]) -> urllib.parse.ParseResult:
        return url._replace(query=urllib.parse.urlencode(query_dict, quote_via=urllib.parse.quote))

    def _parse_url(self, value: str) -> urllib.parse.ParseResult:
        parsed = urllib.parse.urlparse(value)
        if not parsed.scheme:
            parsed = urllib.parse.urlparse("https://" + value)
        if parsed.scheme not in ("http", "https", "ya-disk-public"):
            raise DownloadError("Invalid URL")
        if parsed.scheme in ("http", "https") and not parsed.netloc:
            raise DownloadError("Invalid URL")
        return parsed

    def _check_cancel(self, cancel_event: Optional["threading.Event"]) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise SyncCancelled("Cancelled")


class SyncEngine:
    def __init__(self, storage: StorageManager, downloader: NotesDownloader) -> None:
        self.storage = storage
        self.downloader = downloader

    def sync_single_note(
        self,
        note: NoteItem,
        options: DownloadOptions,
        progress_cb: Optional[Callable[[FolderDownloadProgress], None]] = None,
        cancel_event: Optional["threading.Event"] = None,
    ) -> SyncResult:
        note.last_checked_at = now_iso()

        try:
            result_type, payload = self.downloader.download_source(
                note.url,
                self.storage.temp_dir,
                options,
                progress_cb=progress_cb,
                cancel_event=cancel_event,
            )

            if result_type == "single":
                temp_path: Path = payload
                try:
                    new_hash = self._sha256_file(temp_path)
                    destination = self.storage.single_file_path(note)

                    has_changes = True
                    if destination.exists():
                        has_changes = self._sha256_file(destination) != new_hash

                    if has_changes:
                        self._replace_file(temp_path, destination)
                        note.last_updated_at = now_iso()
                        note.status = "Updated"
                    else:
                        temp_path.unlink(missing_ok=True)
                        note.status = "No changes"

                    note.sha256 = new_hash
                    note.source_type = "file"
                    note.folder_files = []

                    source_dir = self.storage.source_dir(note)
                    if source_dir.exists():
                        shutil.rmtree(source_dir, ignore_errors=True)

                    note.last_error = None
                    return SyncResult(note=note, updated_count=1 if has_changes else 0, error_count=0)
                finally:
                    temp_path.unlink(missing_ok=True)

            downloaded_files: list[DownloadedFolderFile] = payload
            updated_count = self._apply_folder_sync(note, downloaded_files)
            note.last_error = None
            return SyncResult(note=note, updated_count=updated_count, error_count=0)

        except SyncCancelled:
            note.status = "Stopped"
            note.last_error = None
            return SyncResult(note=note, updated_count=0, error_count=0)
        except Exception as exc:  # noqa: BLE001
            note.status = f"Error: {exc}"
            note.last_error = str(exc)
            return SyncResult(note=note, updated_count=0, error_count=1)

    def download_missing_file(
        self,
        note: NoteItem,
        file_item: SyncedFileItem,
        cancel_event: Optional["threading.Event"] = None,
    ) -> tuple[Path, str]:
        temp_path = self.downloader.download_single_file_to_temp(
            source=note.url,
            remote_path=file_item.relative_path,
            temp_dir=self.storage.temp_dir,
            cancel_event=cancel_event,
        )

        destination = self.storage.source_file_path(note, file_item.local_relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)

        self._replace_file(temp_path, destination)
        new_hash = self._sha256_file(destination)
        return destination, new_hash

    def _apply_folder_sync(self, note: NoteItem, downloaded_files: list[DownloadedFolderFile]) -> int:
        file_manager_root = self.storage.source_dir(note)
        file_manager_root.mkdir(parents=True, exist_ok=True)
        previous_source_type = note.source_type

        previous_items = note.folder_files or []
        previous_by_path = {x.local_relative_path: x for x in previous_items}

        changed_count = 0
        removed_count = 0
        failed_count = 0
        skipped_count = 0

        legacy_file = self.storage.single_file_path(note)
        legacy_file.unlink(missing_ok=True)

        next_items: list[SyncedFileItem] = []

        for file in downloaded_files:
            destination = self.storage.source_file_path(note, file.local_relative_path)
            destination.parent.mkdir(parents=True, exist_ok=True)

            if file.temp_path is not None:
                new_hash = self._sha256_file(file.temp_path)
                has_changes = True
                if destination.exists():
                    has_changes = self._sha256_file(destination) != new_hash

                if has_changes:
                    self._replace_file(file.temp_path, destination)
                    changed_count += 1
                else:
                    file.temp_path.unlink(missing_ok=True)
            else:
                if file.was_skipped:
                    skipped_count += 1
                elif file.download_error:
                    failed_count += 1

                if destination.exists():
                    new_hash = self._sha256_file(destination)
                else:
                    new_hash = (previous_by_path.get(file.local_relative_path).sha256 if previous_by_path.get(file.local_relative_path) else "") or ""

            next_items.append(
                SyncedFileItem(
                    relative_path=file.remote_path,
                    local_relative_path=file.local_relative_path,
                    sha256=new_hash,
                    modified_at=file.modified_at,
                    size_bytes=file.size_bytes,
                    mime_type=file.mime_type,
                )
            )

        next_paths = {x.local_relative_path for x in next_items}
        for old in previous_items:
            if old.local_relative_path in next_paths:
                continue
            old_file = self.storage.source_file_path(note, old.local_relative_path)
            if old_file.exists():
                old_file.unlink(missing_ok=True)
                removed_count += 1

        self._cleanup_empty_directories(file_manager_root)

        note.source_type = "folder"
        note.folder_files = sorted(next_items, key=lambda x: x.local_relative_path.lower())
        note.sha256 = None

        if changed_count > 0 or removed_count > 0 or previous_source_type != "folder":
            note.last_updated_at = now_iso()

        if not next_items:
            note.status = "Folder synced: 0 files"
        elif changed_count > 0 or removed_count > 0 or failed_count > 0 or skipped_count > 0:
            note.status = (
                f"Folder synced: {len(next_items)} files "
                f"({changed_count} updated, {removed_count} removed, {failed_count} failed, {skipped_count} skipped)"
            )
        else:
            note.status = f"Folder no changes: {len(next_items)} files"

        return 1 if changed_count > 0 or removed_count > 0 or previous_source_type != "folder" else 0

    def _sha256_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def _replace_file(self, temp_path: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            destination.unlink(missing_ok=True)
        shutil.move(str(temp_path), str(destination))

    def _cleanup_empty_directories(self, root: Path) -> None:
        if not root.exists():
            return

        all_dirs = [p for p in root.rglob("*") if p.is_dir()]
        all_dirs.sort(key=lambda p: len(p.parts), reverse=True)
        for directory in all_dirs:
            try:
                next(directory.iterdir())
            except StopIteration:
                directory.rmdir()
            except OSError:
                pass
