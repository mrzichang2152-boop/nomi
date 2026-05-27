import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_parse_chromium_bookmarks_extracts_folder_path_title_and_url():
    from app.runtime import parse_chromium_bookmarks

    payload = {
        "roots": {
            "bookmark_bar": {
                "type": "folder",
                "name": "书签栏",
                "children": [
                    {
                        "type": "folder",
                        "name": "AI",
                        "children": [
                            {
                                "type": "url",
                                "name": "Qwen docs",
                                "url": "https://example.com/qwen",
                                "date_added": "13361040000000000",
                            }
                        ],
                    }
                ],
            },
            "other": {
                "type": "folder",
                "name": "其他书签",
                "children": [
                    {
                        "type": "url",
                        "name": "PAR repo",
                        "url": "https://github.com/example/par",
                    }
                ],
            },
        }
    }

    bookmarks = parse_chromium_bookmarks(payload)

    assert bookmarks == [
        {
            "title": "Qwen docs",
            "url": "https://example.com/qwen",
            "folder_path": "书签栏 / AI",
            "date_added": "13361040000000000",
            "capture_scope": "chromium_bookmarks",
        },
        {
            "title": "PAR repo",
            "url": "https://github.com/example/par",
            "folder_path": "其他书签",
            "date_added": "",
            "capture_scope": "chromium_bookmarks",
        },
    ]


def test_parse_chromium_bookmarks_skips_invalid_and_deduplicates_urls():
    from app.runtime import parse_chromium_bookmarks

    payload = {
        "roots": {
            "bookmark_bar": {
                "type": "folder",
                "name": "bar",
                "children": [
                    {"type": "url", "name": "No URL"},
                    {"type": "url", "name": "One", "url": "https://example.com"},
                    {"type": "url", "name": "Duplicate", "url": "https://example.com"},
                ],
            }
        }
    }

    bookmarks = parse_chromium_bookmarks(payload)

    assert len(bookmarks) == 1
    assert bookmarks[0]["title"] == "One"
