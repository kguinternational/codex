import os
import yaml
import subprocess

# Paths
python_exe = r"C:\Users\Jccof\OneDrive\Documents\KGU International\kgu-avatar-generator\.venv\Scripts\python.exe"
inference_script = r"C:\Users\Jccof\OneDrive\Documents\KGU International\kgu-avatar-generator\MuseTalk\scripts\inference.py"
video_path = r"C:\Users\Jccof\OneDrive\Documents\KGU International\kgu-avatar-generator\static\uploads\jc-coffey-foundation\ceo\base.mp4"
audio_path = r"C:\Users\Jccof\OneDrive\Documents\KGU International\kgu-avatar-generator\static\audio\render_ceo_1785612814.wav"
output_path = r"C:\Users\Jccof\OneDrive\Documents\KGU International\kgu-avatar-generator\MuseTalk\results\test_inference_output.mp4"

# Create a temporary config yaml file
config_data = {
    "task_0": {
        "video_path": video_path,
        "audio_path": audio_path,
        "result_name": output_path
    }
}

config_path = r"C:\Users\Jccof\OneDrive\Documents\KGU International\kgu-avatar-generator\MuseTalk\configs\inference\temp_run.yaml"
os.makedirs(os.path.dirname(config_path), exist_ok=True)
with open(config_path, "w") as f:
    yaml.dump(config_data, f)

print("[*] Launching MuseTalk inference.py...")
cmd = [
    python_exe,
    inference_script,
    "--inference_config", config_path,
    "--output_vid_name", output_path,
    "--unet_config", "./models/musetalkV15/musetalk.json",
    "--use_float16"
]

print(f"[*] Executing command: {' '.join(cmd)}")
process = subprocess.run(cmd, cwd=r"C:\Users\Jccof\OneDrive\Documents\KGU International\kgu-avatar-generator\MuseTalk")
if process.returncode == 0:
    print("[SUCCESS] MuseTalk inference completed!")
else:
    print(f"[FAIL] MuseTalk inference failed with exit code: {process.returncode}")
