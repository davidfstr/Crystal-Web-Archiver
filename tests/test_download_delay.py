from crystal import task
import pytest
from unittest.mock import patch


def test_download_delay_jitters_around_configured_interval() -> None:
    with (
        patch.object(task, 'DELAY_BETWEEN_DOWNLOADS', 1.0),
        patch.object(task, 'DOWNLOAD_DELAY_JITTER', 0.1),
        patch.object(task.random, 'uniform', side_effect=[-0.1, 0.1]) as uniform,
    ):
        assert task._download_delay_seconds() == pytest.approx(0.9)
        assert task._download_delay_seconds() == pytest.approx(1.1)
    assert uniform.call_args_list == [
        ((-0.1, 0.1),),
        ((-0.1, 0.1),),
    ]


def test_download_delay_clamps_to_zero_when_base_interval_is_minimized() -> None:
    with (
        patch.object(task, 'DELAY_BETWEEN_DOWNLOADS', 0),
        patch.object(task, 'DOWNLOAD_DELAY_JITTER', 0.1),
        patch.object(task.random, 'uniform', return_value=-0.1),
    ):
        assert task._download_delay_seconds() == 0.0
