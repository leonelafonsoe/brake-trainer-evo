from __future__ import annotations

from brake_trainer.config import Settings
from brake_trainer.engine import BrakeEngine
from brake_trainer.models import SectorRun, TrackData
from brake_trainer.storage import DeleteEntry, DeleteRun, DeleteSector

from .conftest import Driver

CORNERS = [0.20, 0.50, 0.80]


def _stored(store) -> TrackData:
    data = TrackData.empty("Monza", "Car A", 3)
    data.sectors[0] = [SectorRun(18.0, [0.05]), SectorRun(18.5, [0.06]), SectorRun(19.0, [])]
    data.sectors[1] = [SectorRun(20.0, [0.4])]
    store.save(data)
    return data


def test_delete_one_run_keeps_the_rest(store):
    _stored(store)
    assert store.apply(DeleteRun("Monza", "Car A", 0, 18.0, (0.05,)))
    data = store.load("Monza", "Car A", 3)
    assert [r.t for r in data.sectors[0]] == [18.5, 19.0]
    assert len(data.sectors[1]) == 1
    assert not store.apply(DeleteRun("Monza", "Car A", 0, 18.0, (0.05,)))  # already gone


def test_delete_sector_and_entry(store):
    _stored(store)
    assert store.apply(DeleteSector("Monza", "Car A", 0))
    data = store.load("Monza", "Car A", 3)
    assert data.sectors[0] == [] and len(data.sectors[1]) == 1
    assert not store.apply(DeleteSector("Monza", "Car A", 0))  # nothing left to delete
    assert not store.apply(DeleteSector("Monza", "Car A", 9))  # no such sector
    assert store.apply(DeleteEntry("Monza", "Car A"))
    assert store.entries() == []


def test_deleting_the_entry_in_use_is_not_undone_by_the_running_engine(store):
    engine = BrakeEngine(Settings(use_game_log=False, warmup_laps=0), store)
    driver = Driver(engine)
    for _ in range(3):
        driver.lap(CORNERS)
    assert store.load("Monza", "Car A", 3).total_runs() > 0

    engine.queue_edit(DeleteEntry("Monza", "Car A"))
    assert engine.apply_pending()
    engine.flush()  # what happens when the app quits
    assert store.entries() == []  # the old in-memory copy was not saved back

    driver.lap(CORNERS)  # driving on starts a fresh entry
    assert store.load("Monza", "Car A", 3).total_runs() > 0


def test_deleting_one_run_of_the_entry_in_use_survives_exit_and_more_laps(store):
    changes = []
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=0),
        store,
        on_data_changed=lambda: changes.append(1),
    )
    driver = Driver(engine)
    for _ in range(4):
        driver.lap(CORNERS)
    before = store.load("Monza", "Car A", 3)
    victim = before.sectors[1][0]

    engine.queue_edit(DeleteRun("Monza", "Car A", 1, victim.t, tuple(victim.onsets)))
    assert engine.apply_pending() and changes
    expected = len(before.sectors[1]) - 1
    assert len(store.load("Monza", "Car A", 3).sectors[1]) == expected

    engine.flush()  # quitting must not bring the run back
    assert len(store.load("Monza", "Car A", 3).sectors[1]) == expected
    driver.lap(CORNERS)  # the entry reloads and keeps working
    assert store.load("Monza", "Car A", 3).total_runs() > 0


def test_settings_window_data_tree_and_selected_edits(store, qapp):
    from brake_trainer.ui.settings import SettingsWindow

    _stored(store)
    window = SettingsWindow(lambda: Settings(), store.directory)
    window.render_data(store.snapshot())
    tree = window._tree
    assert tree.topLevelItemCount() == 1
    entry = tree.topLevelItem(0)
    assert entry is not None
    sector = entry.child(0)
    assert sector is not None
    run = sector.child(0)
    assert run is not None
    assert entry.childCount() == 3 and sector.childCount() == 3

    run.setSelected(True)  # one run
    other = entry.child(1)
    assert other is not None
    other.setSelected(True)  # one whole sector
    assert window.selected_edits() == [
        DeleteRun("Monza", "Car A", 0, 18.0, (0.05,)),
        DeleteSector("Monza", "Car A", 1),
    ]

    tree.clearSelection()
    entry.setSelected(True)
    sector.setSelected(True)  # covered by the entry
    assert window.selected_edits() == [DeleteEntry("Monza", "Car A")]
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_icon_renders_and_packs_into_a_valid_ico(qapp):
    import struct

    from brake_trainer.ui.icon import ICON_SIZES, app_icon, draw_icon, pack_ico, png_bytes

    for size in ICON_SIZES:
        image = draw_icon(size)
        assert (image.width(), image.height()) == (size, size)
        assert image.pixelColor(size // 2, size // 2).alpha() > 0  # not blank
        assert image.pixelColor(0, 0).alpha() == 0  # transparent corner
    assert not app_icon().isNull()

    from brake_trainer.ui.icon import dib_bytes, ico_entry

    pngs = {16: ico_entry(16), 32: ico_entry(32), 256: ico_entry(256)}
    assert pngs[256].startswith(b"\x89PNG") and pngs[256] == png_bytes(256)
    for size in (16, 32):  # small sizes are plain bitmaps, not PNG
        data = pngs[size]
        assert not data.startswith(b"\x89PNG")
        header_size, width, height, planes, bits = struct.unpack("<IiiHH", data[:16])
        assert (header_size, width, height, planes, bits) == (40, size, size * 2, 1, 32)
        mask = ((size + 31) // 32) * 4 * size
        assert len(data) == 40 + 4 * size * size + mask
    blue = draw_icon(16)
    bottom_left = dib_bytes(blue)[40 : 40 + 4]  # first stored row is the bottom row
    pixel = blue.pixelColor(0, 15)
    assert bottom_left == bytes([pixel.blue(), pixel.green(), pixel.red(), pixel.alpha()])
    ico = pack_ico(pngs)
    reserved, kind, count = struct.unpack("<HHH", ico[:6])
    assert (reserved, kind, count) == (0, 1, 3)
    width, _, _, _, _, bits, length, offset = struct.unpack("<BBBBHHII", ico[6:22])
    assert (width, bits) == (16, 32)
    assert ico[offset : offset + length] == pngs[16]
    last = struct.unpack("<BBBBHHII", ico[6 + 32 : 6 + 48])
    assert last[0] == 0  # 256 is stored as 0
