import os
import tempfile
import atexit

_test_temp_dir = tempfile.TemporaryDirectory()
os.environ["ANTIENTER_CONFIG_DIR"] = _test_temp_dir.name
atexit.register(_test_temp_dir.cleanup)
