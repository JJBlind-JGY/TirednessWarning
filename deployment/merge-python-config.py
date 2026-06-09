import argparse
from pathlib import Path

import yaml


DEFAULTS = {
    "mediapipe_eye_model": "./models/face_landmarker.task",
    "mp_blink_threshold": 0.5,
    "yawn_model": "./models/yawn_model_80_lite.onnx",
    "yawn_threshold": 0.8,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    args = parser.parse_args()

    config_path = Path(args.config)
    current = {}
    if config_path.exists():
        current = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(current, dict):
        raise ValueError(f"Expected a YAML mapping in {config_path}")

    changed = False
    for key, value in DEFAULTS.items():
        if key not in current:
            current[key] = value
            changed = True

    if changed:
        config_path.write_text(
            yaml.safe_dump(current, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    print(f"Python config ready: {config_path}")


if __name__ == "__main__":
    main()
