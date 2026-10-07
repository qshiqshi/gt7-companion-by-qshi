"""The repository ships everything the program needs, and nothing it should not."""
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "gt7companion"


def git(*arguments: str) -> str:
    return subprocess.run(["git", *arguments], cwd=ROOT, capture_output=True, text=True, check=True).stdout


@unittest.skipUnless(shutil.which("git") and (ROOT / ".git").exists(), "not a git checkout")
class Repository(unittest.TestCase):
    def test_no_file_of_the_package_is_ignored_by_accident(self):
        ignored = [line[3:] for line in git("status", "--porcelain", "--ignored", "--", "src/gt7companion").splitlines()
                   if line.startswith("!! ")]
        ignored = [path for path in ignored if "__pycache__" not in path and not path.endswith(".DS_Store")]
        self.assertEqual(ignored, [])

    def test_every_file_a_page_asks_for_is_tracked(self):
        tracked = set(git("ls-files", "src/gt7companion/web").splitlines())
        wanted = set()
        for page in (PACKAGE / "web").glob("*.html"):
            wanted.update(re.findall(r'(?:src|href)="/(static/[^"?#]+)', page.read_text(encoding="utf-8")))
        wanted.update(re.findall(r'"(?:three|three/addons/)": "/(static/[^"]+)"',
                                 (PACKAGE / "web" / "index.html").read_text(encoding="utf-8")))
        for path in sorted(wanted):
            target = "src/gt7companion/web/" + path
            if path.endswith("/"):
                self.assertTrue(any(name.startswith(target) for name in tracked), path)
            else:
                self.assertIn(target, tracked)

    def test_start_files_and_guides_are_there(self):
        names = set(git("ls-files").splitlines())
        for name in ("start-mac.command", "start-windows.bat", "docs/INSTALL.md", "docs/INSTALL.de.md",
                     "README.md", "README.de.md", "LICENSE", "THIRD_PARTY_NOTICES.md"):
            self.assertIn(name, names)
        mode = git("ls-files", "--stage", "start-mac.command").split()[0]
        self.assertEqual(mode, "100755")                       # a double-click must be able to run it
        for guide in ("docs/INSTALL.md", "docs/INSTALL.de.md"):
            text = (ROOT / guide).read_text(encoding="utf-8")
            for needed in ("start-mac.command", "start-windows.bat", "python.org", "?obs=1", ".[wake]"):
                self.assertIn(needed, text, guide)

    def test_every_picture_in_the_guides_exists(self):
        tracked = set(git("ls-files").splitlines())
        for guide in ("README.md", "README.de.md", "docs/INSTALL.md", "docs/INSTALL.de.md"):
            text = (ROOT / guide).read_text(encoding="utf-8")
            pictures = re.findall(r'(?:src="|\]\()([^")]+\.(?:png|gif))', text)
            self.assertGreater(len(pictures), 4, guide)
            for picture in pictures:
                path = (Path(guide).parent / picture).as_posix()
                self.assertIn(path, tracked, f"{guide}: {picture}")

    def test_nothing_private_is_tracked(self):
        names = git("ls-files").splitlines()
        for name in names:
            self.assertNotRegex(name, r"(^|/)(config\.json|secrets\.json|settings\.json|twitch_token\.json|\.env)$")
            self.assertNotRegex(name, r"(?i)eurostile|\.(blend|psd|ai)$")
        self.assertNotIn("PLAN.md", names)
        self.assertNotIn("STATUS.md", names)


if __name__ == "__main__":
    unittest.main()
