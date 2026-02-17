import unittest

from notes_sync_linux.core import NotesDownloader


class CoreParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.downloader = NotesDownloader()

    def test_parse_yandex_pseudo_url_with_path(self) -> None:
        parsed = self.downloader._parse_yandex_public_pseudo_url(
            "ya-disk-public://abcDEF123:/folder/sub/notes.pdf"
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["public_key"], "ya-disk-public://abcDEF123")
        self.assertEqual(parsed["path"], "/folder/sub/notes.pdf")

    def test_resolve_docs_yandex_wrapped_url(self) -> None:
        url = (
            "https://docs.yandex.ru/docs/view?url=ya-disk-public://XYZ123:/Course/file.pdf&name=file.pdf"
        )
        source = self.downloader._parse_url(url)
        resource = self.downloader._resolve_yandex_public_resource(source)
        self.assertIsNotNone(resource)
        self.assertEqual(resource["public_key"], "ya-disk-public://XYZ123")
        self.assertEqual(resource["path"], "/Course/file.pdf")

    def test_make_safe_relative_path(self) -> None:
        rel = self.downloader._make_safe_relative_path(
            "/disk/FMC_folder/lectures/week1/notes.pdf",
            "/disk/FMC_folder",
        )
        self.assertEqual(rel, "lectures/week1/notes.pdf")


if __name__ == "__main__":
    unittest.main()
