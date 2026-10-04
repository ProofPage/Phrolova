"""릴리즈 버전과 배포 메타데이터가 같은 값을 가리키는지 검증한다."""

import json
import re
from pathlib import Path

from app.version import __version__


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read_json(relative_path: str) -> dict:
    return json.loads((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))


def test_frontend_package_versions_match_backend_version() -> None:
    """private 패키지여도 설치·빌드 산출물에 기록되는 버전은 앱과 같아야 한다."""
    package = _read_json("frontend/package.json")
    package_lock = _read_json("frontend/package-lock.json")

    assert package["version"] == __version__
    assert package_lock["version"] == __version__
    assert package_lock["packages"][""]["version"] == __version__


def test_changelog_has_current_release_and_comparison_links() -> None:
    changelog = (PROJECT_ROOT / "docs/CHANGELOG.md").read_text(encoding="utf-8")
    release_versions = re.findall(r"^## \[(\d+\.\d+\.\d+)\] - ", changelog, re.MULTILINE)

    assert release_versions[0] == __version__
    assert (
        f"[Unreleased]: https://github.com/eruminyu/Rookery/compare/v{__version__}...HEAD"
        in changelog
    )
    assert (
        f"[{__version__}]: https://github.com/eruminyu/Rookery/compare/"
        f"v{release_versions[1]}...v{__version__}"
        in changelog
    )


def test_pyinstaller_version_resource_uses_backend_single_source() -> None:
    spec = (PROJECT_ROOT / "rookery.spec").read_text(encoding="utf-8")

    assert 'Path("backend/app/version.py")' in spec
    assert 'StringStruct("FileVersion", APP_VERSION)' in spec
    assert 'StringStruct("ProductVersion", APP_VERSION)' in spec
    assert "version=VERSION_RESOURCE" in spec
