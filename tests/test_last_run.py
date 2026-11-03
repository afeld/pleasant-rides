from datetime import datetime, timezone

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
        datetime(2026, 10, 17, 7, 30, tzinfo=timezone.utc),
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


def test_runs_are_complete_unless_saved_as_partial():
    assert a_run(80.5).complete
    partial = LastRun(NAMES, a_run(80.5).results, a_run(80.5).finished, 1, False)
    last_run._stored.clear()
    last_run.save(partial)
    assert last_run.load(NAMES) == partial


def test_runs_saved_before_partial_ones_were_are_complete():
    run = a_run(80.5)
    # as unpickled from a run saved before `complete` was added
    del run.__dict__["complete"]
    assert run.complete
