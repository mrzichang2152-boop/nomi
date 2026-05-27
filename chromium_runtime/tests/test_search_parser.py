import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_parse_google_search_results_extracts_title_url_and_snippet():
    from app.runtime import parse_google_search_results

    results = parse_google_search_results(
        [
            {
                "title": "Qwen3 Documentation",
                "url": "https://example.com/qwen3",
                "snippet": "Qwen3 model usage and API examples.",
            },
            {
                "title": "",
                "url": "https://example.com/empty",
                "snippet": "skip me",
            },
        ]
    )

    assert results == [
        {
            "title": "Qwen3 Documentation",
            "url": "https://example.com/qwen3",
            "snippet": "Qwen3 model usage and API examples.",
            "rank": 1,
        }
    ]


def test_extract_google_clicked_result_detects_non_google_navigation():
    from app.runtime import extract_google_clicked_result

    clicked = extract_google_clicked_result(
        previous_url="https://www.google.com/search?q=qwen3",
        current_url="https://example.com/qwen3",
        title="Qwen3 Documentation",
    )

    assert clicked == {
        "from_search_url": "https://www.google.com/search?q=qwen3",
        "clicked_url": "https://example.com/qwen3",
        "clicked_title": "Qwen3 Documentation",
        "capture_scope": "search_result_click",
    }


def test_extract_google_clicked_result_ignores_google_navigation():
    from app.runtime import extract_google_clicked_result

    assert extract_google_clicked_result(
        previous_url="https://www.google.com/search?q=qwen3",
        current_url="https://www.google.com/search?q=qwen3&start=10",
        title="Google",
    ) is None
