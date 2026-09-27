"""File extensions muz knows about."""

# Files muz is allowed to modify. Everything else is read-only.
WRITABLE_EXTS = frozenset({".mp3", ".flac"})

# Audio files muz reads (stats, duplicates, conversion sources).
AUDIO_EXTS = frozenset(
    {
        ".mp3", ".flac", ".m4a", ".mp4", ".aac", ".alac", ".ogg", ".oga",
        ".opus", ".wma", ".wav", ".aif", ".aiff", ".ape", ".wv", ".mpc",
        ".dsf", ".dff",
    }
)

# Extensions whose codec is always lossless. .m4a is decided by its codec.
LOSSLESS_EXTS = frozenset({".flac", ".wav", ".aif", ".aiff", ".ape", ".wv", ".alac", ".dsf", ".dff"})

IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".webp"})
LYRICS_EXTS = frozenset({".lrc", ".txt"})
