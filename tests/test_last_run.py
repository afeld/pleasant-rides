from datetime import datetime

from pleasant_rides.benchmark import last_run
from pleasant_rides.benchmark.last_run import LastRun
from pleasant_rides.benchmark.runner import Results, TripScore

NAMES = ["Valhalla (current)", "BRouter (current)"]


def a_run(score: float):
    return LastRun(
        NAMES,
        Results(
            {
                "Valhalla (current)": {
                    "Long: Brooklyn→Beacon": TripScore(score, 137.2, 2.1)
                },
                "BRouter (current)": {
                    "Long: Brooklyn→Beacon": "ProviderError: BRouter 500: "
                },
            },
            {},
        ),
        datetime(2026, 10, 17, 7, 30),
        65.4,
    )


def test_load_what_was_saved():
    last_run._stored.clear()
    run = a_run(80.5)
    last_run.save(run)
    assert last_run.load(NAMES) == run


def test_saving_replaces_the_last_run():
    last_run._stored.clear()
    last_run.save(a_run(80.5))
    last_run.save(a_run(70))
    assert last_run.load(NAMES) == a_run(70)


def test_nothing_saved_for_other_variants():
    last_run._stored.clear()
    last_run.save(a_run(80.5))
    assert last_run.load(NAMES[:1]) is None
