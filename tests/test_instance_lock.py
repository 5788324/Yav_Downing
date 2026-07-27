import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from backend.runtime import InstanceLock, clear_runtime_state, instance_path, read_runtime_state, write_runtime_state


class InstanceLockTests(unittest.TestCase):
    def test_second_lock_cannot_replace_live_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = InstanceLock(root, 8765)
            self.assertTrue(first.acquire())
            original = json.loads(instance_path(root).read_text(encoding="utf-8"))

            second = InstanceLock(root, 8766)
            self.assertFalse(second.acquire())
            current = json.loads(instance_path(root).read_text(encoding="utf-8"))
            self.assertEqual(current["instance_id"], original["instance_id"])
            self.assertEqual(current["port"], 8765)

            first.release()
            third = InstanceLock(root, 8766)
            self.assertTrue(third.acquire())
            third.release()

    def test_stale_lock_file_without_owner_is_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            lock_file = root / "runtime" / "instance.lock"
            lock_file.parent.mkdir(parents=True)
            lock_file.write_bytes(b"0")
            write_runtime_state(root, pid=99999999, port=8765, instance_id="stale", token="old")
            lock = InstanceLock(root, 8766)
            self.assertTrue(lock.acquire())
            self.assertEqual(json.loads(instance_path(root).read_text(encoding="utf-8"))["instance_id"], lock.instance_id)
            lock.release()

    def test_release_does_not_delete_foreign_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            lock = InstanceLock(root, 8765)
            self.assertTrue(lock.acquire())
            write_runtime_state(root, pid=os.getpid(), port=8766, instance_id="foreign", token="foreign-secret")
            lock.release()
            info, token = read_runtime_state(root)
            self.assertEqual(info["instance_id"], "foreign")
            self.assertEqual(token, "foreign-secret")
            self.assertTrue(clear_runtime_state(root, expected_instance_id="foreign"))

    def test_parallel_processes_choose_one_owner(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            start = root / "start"
            release = root / "release"
            markers = [root / "one.json", root / "two.json"]
            code = r'''
import json, sys, time
from pathlib import Path
from backend.runtime import InstanceLock
root, marker, start, release = map(Path, sys.argv[1:5])
deadline = time.time() + 10
while not start.exists() and time.time() < deadline:
    time.sleep(0.01)
lock = InstanceLock(root, 18765)
acquired = lock.acquire()
marker.write_text(json.dumps({"acquired": acquired, "instance_id": lock.instance_id}), encoding="utf-8")
if acquired:
    while not release.exists() and time.time() < deadline:
        time.sleep(0.01)
    lock.release()
'''
            repo_root = Path(__file__).resolve().parents[1]
            processes = [
                subprocess.Popen(
                    [sys.executable, "-c", code, str(root), str(marker), str(start), str(release)],
                    cwd=repo_root,
                )
                for marker in markers
            ]
            try:
                start.touch()
                deadline = time.time() + 10
                while time.time() < deadline and not all(marker.exists() for marker in markers):
                    time.sleep(0.02)
                self.assertTrue(all(marker.exists() for marker in markers))
                results = [json.loads(marker.read_text(encoding="utf-8")) for marker in markers]
                winners = [result for result in results if result["acquired"]]
                self.assertEqual(len(winners), 1)
                active = json.loads(instance_path(root).read_text(encoding="utf-8"))
                self.assertEqual(active["instance_id"], winners[0]["instance_id"])
            finally:
                release.touch()
                for process in processes:
                    process.wait(timeout=10)
                    self.assertEqual(process.returncode, 0)


if __name__ == "__main__":
    unittest.main()
