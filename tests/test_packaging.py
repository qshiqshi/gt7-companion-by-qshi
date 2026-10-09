"""The build script: the parts that decide what may be shipped, without building anything."""
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gt7c_build", ROOT / "packaging" / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class WhatIsAsked(unittest.TestCase):
    def options(self, *argv):
        with redirect_stderr(io.StringIO()):
            return build.options(list(argv))

    def test_signing_takes_the_certificate_from_the_command_line_or_the_environment(self):
        with patch.object(build, "SYSTEM", "mac"), patch.dict(os.environ, {"GT7C_SIGN_IDENTITY": "From Env"}):
            self.assertEqual(self.options("--sign", "Given")[1], "Given")
            self.assertEqual(self.options("--sign")[1], "From Env")
            self.assertIsNone(self.options()[1])
        with patch.object(build, "SYSTEM", "mac"), patch.dict(os.environ, {"GT7C_SIGN_IDENTITY": ""}):
            with self.assertRaises(SystemExit):
                self.options("--sign")

    def test_nothing_unsigned_is_sent_to_apple_and_only_a_mac_signs(self):
        with patch.object(build, "SYSTEM", "mac"):
            with self.assertRaises(SystemExit):
                self.options("--notarize", "profile")
            args, identity = self.options("--sign", "Given", "--notarize", "profile", "--dmg")
            self.assertEqual((identity, args.notarize, args.dmg), ("Given", "profile", True))
        with patch.object(build, "SYSTEM", "windows"):
            for wrong in (("--sign", "Given"), ("--dmg",)):
                with self.assertRaises(SystemExit):
                    self.options(*wrong)


class WhatIsPacked(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)

    def test_every_package_of_the_build_has_one_exact_version(self):
        lines = [line.strip() for line in build.CONSTRAINTS.read_text(encoding="utf-8").splitlines()]
        pins = [line for line in lines if line and not line.startswith("#")]
        for pin in pins:
            self.assertRegex(pin, r"^[a-z0-9][a-z0-9-]*==[0-9][0-9a-z.]*$")
        names = [pin.split("==")[0] for pin in pins]
        self.assertEqual(len(names), len(set(names)), "a package is pinned twice")
        for needed in ("pyinstaller", "pywebview", "pystray", "pythonnet", "pyobjc-core", "uvicorn", "fastapi"):
            self.assertIn(needed, names)

    def test_the_constraints_reach_uv_as_a_path_without_spaces(self):
        python = self.home / "venv-mac" / "bin" / "python"          # the environment is there already
        python.parent.mkdir(parents=True)
        python.write_text("", encoding="utf-8")
        commands = []
        with patch.object(build, "SYSTEM", "mac"), patch.object(build, "BUILD", self.home), \
                patch.object(build.shutil, "which", return_value="/somewhere/uv"), \
                patch.object(build, "run", lambda *command: commands.append(command)):
            self.assertEqual(build.environment(fresh=False), python)
        (install,) = commands
        given = str(install[install.index("-c") + 1])                # uv splits this argument at spaces
        self.assertNotIn(" ", given)
        self.assertEqual((build.ROOT / given).resolve(), build.CONSTRAINTS.resolve())

    def test_versions_compare_by_number_not_by_letter(self):
        self.assertLess(build._version("9.0"), build._version("14.0"))
        self.assertLess(build._version("14.0"), build._version("26.0"))
        self.assertEqual(max(["11.0", "26.0", "9.3"], key=build._version), "26.0")

    def test_the_windows_zip_unpacks_to_one_folder_with_the_program_inside(self):
        program = self.home / "gt7companion"
        (program / "_internal" / "data").mkdir(parents=True)
        (program / "gt7companion.exe").write_bytes(b"MZ")
        (program / "_internal" / "data" / "texts.json").write_text("{}", encoding="utf-8")
        with patch.object(build, "DIST", self.home):
            target = build.windows_zip(program)
        self.assertEqual(target.name, "GT7-Companion-by-qshi-windows-x64.zip")
        with zipfile.ZipFile(target) as archive:
            self.assertEqual(sorted(archive.namelist()), ["GT7 Companion by qshi/_internal/data/texts.json",
                                                          "GT7 Companion by qshi/gt7companion.exe"])

    def test_a_text_file_is_no_program_file(self):
        note = self.home / "note.txt"
        note.write_text("plain", encoding="utf-8")
        self.assertFalse(build.is_mach_o(note))
        self.assertFalse(build.is_mach_o(self.home / "missing"))

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("otool"), "needs macOS with the developer tools")
    def test_a_program_file_for_a_newer_macos_stops_the_build_except_the_helper_of_the_box(self):
        helper = ROOT / "build" / build.BOX_HELPER             # built for macOS 26: too new for the app itself
        if not helper.is_file():
            self.skipTest("the helper is not built (python tools/build_box_helper.py)")
        frameworks = self.home / "Some.app" / "Contents" / "Frameworks"
        frameworks.mkdir(parents=True)
        shutil.copy(helper, frameworks / "something-else")
        shutil.copy(helper, frameworks / build.BOX_HELPER)
        self.assertTrue(build.is_mach_o(frameworks / "something-else"))
        problems = build.check_macos_files(self.home / "Some.app")
        self.assertEqual(problems, ["Contents/Frameworks/something-else: needs macOS 26.0"])
        self.assertEqual(build.check_macos_files(self.home / "Some.app", limit="26.0"), [])


if __name__ == "__main__":
    unittest.main()
