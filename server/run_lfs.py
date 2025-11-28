import subprocess
from pathlib import Path

INPUT_DIR = Path("captures")
OUTPUT_DIR = Path("lfs_output")

def main():
    INPUT_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Command based on documentation
    cmd = [
        "./build/LichtFeld-Studio",
        "-d", str(INPUT_DIR),
        "-o", str(OUTPUT_DIR)
    ]

    print("Running:", " ".join(cmd))
    subprocess.run(cmd)

if __name__ == "__main__":
    main()
