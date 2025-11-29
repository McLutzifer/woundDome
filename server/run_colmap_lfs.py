import subprocess
from pathlib import Path
import shutil

# === ADAPT THESE TWO LINES TO YOUR SYSTEM ===
COLMAP_CMD = r"C:\Users\Admin\wounddome_server\colmap-x64-windows-cuda\COLMAP.bat"  # or colmap.exe
LFS_CMD    = r"C:\Users\Admin\repos\LichtFeld-Studio\build\LichtFeld-Studio.exe"
# ============================================

CAPTURES_DIR     = Path("captures")
COLMAP_WORKSPACE = Path("colmap_ws")
LFS_OUTPUT_DIR   = Path("lfs_output")


def run_colmap() -> None:
    CAPTURES_DIR.mkdir(exist_ok=True)
    COLMAP_WORKSPACE.mkdir(exist_ok=True)
    LFS_OUTPUT_DIR.mkdir(exist_ok=True)

    # Use absolute paths for safety
    img_path = CAPTURES_DIR.resolve()
    ws_path  = COLMAP_WORKSPACE.resolve()

    cmd = [
        COLMAP_CMD,
        "automatic_reconstructor",
        "--image_path", str(img_path),
        "--workspace_path", str(ws_path),
    ]

    print("Running COLMAP:")
    print(" ", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)

    print("\n--- COLMAP STDOUT ---")
    print(result.stdout)
    print("--- COLMAP STDERR ---")
    print(result.stderr)
    print("---------------------\n")

    if result.returncode != 0:
        print(f"[WARN] COLMAP exited with code {result.returncode} (continuing anyway for MVP).")


def ensure_images_in_workspace() -> None:
    """
    Make sure colmap_ws/images exists and contains the input images.
    LichtFeld-Studio expects this folder.
    """
    images_dir = COLMAP_WORKSPACE / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    # Copy all jpg/jpeg/png from captures/ into colmap_ws/images
    for f in CAPTURES_DIR.iterdir():
        if f.is_file() and f.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            target = images_dir / f.name
            shutil.copy2(f, target)
            print(f"Copied {f} -> {target}")


def run_lichtfeld() -> None:
    cmd = [
        LFS_CMD,
        "-d", str(COLMAP_WORKSPACE),
        "-o", str(LFS_OUTPUT_DIR),
    ]

    print("Running LichtFeld-Studio:")
    print(" ", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)

    print("\n--- LichtFeld STDOUT ---")
    print(result.stdout)
    print("--- LichtFeld STDERR ---")
    print(result.stderr)
    print("------------------------\n")

    if result.returncode != 0:
        print(f"LichtFeld-Studio exited with code {result.returncode}")


def main():
    # 1) Run COLMAP (even if it’s a bit flaky for now)
    run_colmap()

    # 2) Make sure colmap_ws/images exists and has our pictures
    ensure_images_in_workspace()

    # 3) Run LichtFeld on that workspace
    run_lichtfeld()


if __name__ == "__main__":
    main()
