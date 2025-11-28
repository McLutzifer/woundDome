import subprocess
from pathlib import Path

COLMAP_CMD = "colmap"
LFS_CMD = r"C:\path\to\LichtFeld-Studio.exe"


CAPTURES_DIR = Path("captures")          # where the HTTP server puts images
COLMAP_WORKSPACE = Path("colmap_ws")     # COLMAP workspace (will be created)
LFS_OUTPUT_DIR = Path("lfs_output")      # LichtFeld output


def run_colmap():
    """Run COLMAP automatic reconstruction on the images in CAPTURES_DIR."""
    CAPTURES_DIR.mkdir(exist_ok=True)
    COLMAP_WORKSPACE.mkdir(exist_ok=True)
    LFS_OUTPUT_DIR.mkdir(exist_ok=True)
 
    cmd = [
        COLMAP_CMD,
        "automatic_reconstructor",
        "--image_path", str(CAPTURES_DIR),          #input
        "--workspace_path", str(COLMAP_WORKSPACE),  #output
    ]

    print("Running COLMAP:")
    print(" ", " ".join(cmd))
    subprocess.run(cmd, check=True)


def run_lichtfeld():
    """Run LichtFeld-Studio on the COLMAP workspace."""
    cmd = [
        LFS_CMD,
        "-d", str(COLMAP_WORKSPACE),  # COLMAP workspace folder
        "-o", str(LFS_OUTPUT_DIR),    # output folder
    ]

    print("Running LichtFeld-Studio:")
    print(" ", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main():
    run_colmap()
    run_lichtfeld()


if __name__ == "__main__":
    main()

