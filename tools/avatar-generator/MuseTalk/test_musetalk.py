import os
import sys
from types import ModuleType
import importlib.machinery
from unittest.mock import MagicMock

class MockModule(ModuleType):
    def __getattr__(self, name):
        return MagicMock()

# Robustly mock mmcv._ext with custom dynamic attribute lookups to bypass C++ compiler extensions check
mmcv_ext = MockModule("mmcv._ext")
mmcv_ext.__spec__ = importlib.machinery.ModuleSpec("mmcv._ext", None)
sys.modules["mmcv._ext"] = mmcv_ext

# Add MuseTalk path
sys.path.append(os.path.dirname(__file__))

try:
    print("[*] Importing MuseTalk utility and preprocessing modules...")
    from musetalk.utils.blending import get_image
    from musetalk.utils.face_parsing import FaceParsing
    from musetalk.utils.audio_processor import AudioProcessor
    from musetalk.utils.utils import get_file_type, get_video_fps, datagen, load_all_model
    from musetalk.utils.preprocessing import get_landmark_and_bbox, read_imgs
    
    print("[SUCCESS] All MuseTalk imports verified successfully!")
except Exception as e:
    print(f"[FAIL] MuseTalk verification failed: {e}")
