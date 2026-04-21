from pathlib import Path

from scripts.stage3_generate_audio import DEFAULT_REF_AUDIO, DEFAULT_REF_TEXT, main


def test_default_reference_files_exist() -> None:
    assert DEFAULT_REF_AUDIO.exists()
    assert DEFAULT_REF_TEXT.exists()


def test_main_allows_dry_run_without_explicit_reference_paths(tmp_path: Path) -> None:
    script_path = tmp_path / "script.txt"
    script_path.write_text(
        "[TITLE] Demo\n[SCENE: 00:00:01 - 00:00:10]\n一段旁白\n",
        encoding="utf-8",
    )

    result = main(["--script", str(script_path), "--output-dir", str(tmp_path), "--dry-run"])

    assert result == 0