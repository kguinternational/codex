import os
from huggingface_hub import snapshot_download, hf_hub_download

checkpoints_dir = "models"
os.makedirs(checkpoints_dir, exist_ok=True)

# Set mirror endpoint for robust connection
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

print("[*] Starting robust HuggingFace model weight downloads...")

# 1. MuseTalk core weights
print("\n[*] Downloading MuseTalk weights...")
try:
    snapshot_download(
        repo_id="TMElyralab/MuseTalk",
        local_dir=checkpoints_dir,
        ignore_patterns=["*.git*", "*.gitattributes"]
    )
    print("[SUCCESS] MuseTalk weights downloaded!")
except Exception as e:
    print(f"[-] MuseTalk download error: {e}")

# 2. SD VAE
print("\n[*] Downloading SD VAE weights...")
try:
    for filename in ["config.json", "diffusion_pytorch_model.bin"]:
        hf_hub_download(
            repo_id="stabilityai/sd-vae-ft-mse",
            filename=filename,
            local_dir=os.path.join(checkpoints_dir, "sd-vae")
        )
    print("[SUCCESS] SD VAE weights downloaded!")
except Exception as e:
    print(f"[-] SD VAE download error: {e}")

# 3. Whisper Tiny
print("\n[*] Downloading Whisper weights...")
try:
    for filename in ["config.json", "pytorch_model.bin", "preprocessor_config.json"]:
        hf_hub_download(
            repo_id="openai/whisper-tiny",
            filename=filename,
            local_dir=os.path.join(checkpoints_dir, "whisper")
        )
    print("[SUCCESS] Whisper weights downloaded!")
except Exception as e:
    print(f"[-] Whisper download error: {e}")

# 4. DWPose
print("\n[*] Downloading DWPose weights...")
try:
    hf_hub_download(
        repo_id="yzd-v/DWPose",
        filename="dw-ll_ucoco_384.pth",
        local_dir=os.path.join(checkpoints_dir, "dwpose")
    )
    print("[SUCCESS] DWPose weights downloaded!")
except Exception as e:
    print(f"[-] DWPose download error: {e}")

# 5. SyncNet (ByteDance/LatentSync)
print("\n[*] Downloading SyncNet weights...")
try:
    hf_hub_download(
        repo_id="ByteDance/LatentSync",
        filename="latentsync_syncnet.pt",
        local_dir=os.path.join(checkpoints_dir, "syncnet")
    )
    print("[SUCCESS] SyncNet weights downloaded!")
except Exception as e:
    print(f"[-] SyncNet download error: {e}")

# 6. Face Parse BiSent
print("\n[*] Downloading Face Parse weights...")
try:
    for filename in ["79999_iter.pth", "resnet18-5c106cde.pth"]:
        hf_hub_download(
            repo_id="ManyOtherFunctions/face-parse-bisent",
            filename=filename,
            local_dir=os.path.join(checkpoints_dir, "face-parse-bisent")
        )
    print("[SUCCESS] Face Parse weights downloaded!")
except Exception as e:
    print(f"[-] Face Parse download error: {e}")

print("\n[+] All weights completed successfully!")
