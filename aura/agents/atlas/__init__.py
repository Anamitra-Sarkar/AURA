"""ATLAS file system agent."""

from .models import FileContent, FileEntry, FileMatch, OperationResult, WatchHandle
from .tools import (
    compress_folder,
    copy_file,
    delete_file,
    extract_archive,
    list_directory,
    move_file,
    open_file,
    read_file,
    rename_file,
    search_files,
    set_event_bus,
    watch_folder,
    write_file,
)

__all__ = [
    "FileContent",
    "FileEntry",
    "FileMatch",
    "OperationResult",
    "WatchHandle",
    "compress_folder",
    "copy_file",
    "delete_file",
    "extract_archive",
    "list_directory",
    "move_file",
    "open_file",
    "read_file",
    "rename_file",
    "search_files",
    "set_event_bus",
    "watch_folder",
    "write_file",
]
