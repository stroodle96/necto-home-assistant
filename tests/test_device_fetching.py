import importlib.util
from pathlib import Path
import sys
import unittest


path = Path(__file__).parents[1] / "custom_components" / "necto" / "model.py"
spec = importlib.util.spec_from_file_location("necto_model", path)
model = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = model
spec.loader.exec_module(model)


def page(page_number, last_page, ids):
    return {"props": {"user": {"meta": {"unit": "f"}}, "devices": {
        "data": [{"device_id": identifier, "name": identifier, "latest_report": None}
                 for identifier in ids],
        "meta": {"current_page": page_number, "last_page": last_page},
    }}}


class FakeClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def get_device_page(self, page_number):
        self.calls.append(page_number)
        return self.pages[page_number - 1]


def run_immediate(coro):
    """Run this fake client's non-suspending coroutines without sockets."""
    try:
        coro.send(None)
    except StopIteration as result:
        return result.value
    raise AssertionError("Fake client unexpectedly suspended")


class DeviceFetchingTests(unittest.TestCase):
    def test_fetches_all_pages_once(self):
        client = FakeClient([page(1, 2, ["a"]), page(2, 2, ["b"])])
        devices = run_immediate(model.fetch_devices(client))
        self.assertEqual(list(devices), ["a", "b"])
        self.assertEqual(client.calls, [1, 2])

    def test_rejects_wrong_page_and_duplicate_ids(self):
        for pages in ([page(2, 2, ["a"])], [page(1, 2, ["a"]), page(2, 2, ["a"]) ]):
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                run_immediate(model.fetch_devices(FakeClient(pages)))

    def test_rejects_excessive_page_count(self):
        with self.assertRaises(ValueError):
            run_immediate(model.fetch_devices(FakeClient([page(1, 101, [])])))
