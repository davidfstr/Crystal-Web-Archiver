from typing import Tuple
from tqdm import tqdm
from tqdm.std import EMA


class ProgressBarCalculator:
    """
    Calculates statistics about a process in progress,
    such as estimated time remaining.
    """
    _VERBOSE = False
    
    def __init__(self, initial: int, total: int) -> None:
        self._tqdm = _TqdmWithoutDisplay(
            initial=initial,  # self.n = initial
            total=total,  # self.total = total
            file=_DevNullFile(),
            
            # Recompute remaining time after each update() call unless many
            # calls made in a short time interval (<= `mininterval`).
            miniters=1,
            mininterval=0.1,  # tqdm's default value
        )
        
        # Calibrate EMA (exponential moving average) smoothing factors for speed estimates.
        # Ranges from 0.0 (average speed) to 1.0 (current/instantaneous speed).
        assert isinstance(getattr(self._tqdm, '_ema_dn', None), EMA)
        assert isinstance(getattr(self._tqdm, '_ema_dt', None), EMA)
        # Bias toward current speed (usually 1.0 items/call) when estimating
        # how many items completed per update() call (so long as calls are
        # at least `mininterval` apart)
        self._tqdm._ema_dn = EMA(0.7)
        # Bias toward average speed when estimating time between each update() call
        self._tqdm._ema_dt = EMA(0.3)  # tqdm's default value
    
    # === Properties ===
    
    @property
    def n(self) -> int:
        return self._tqdm.n
    
    def _get_total(self) -> int:
        return self._tqdm.total
    def _set_total(self, total: int) -> None:
        self._tqdm.total = total
    total = property(_get_total, _set_total)
    
    def remaining_str_and_time_per_item_str(self) -> Tuple[str, str]:
        """Compute estimated remaining time, in format "MM:SS" or "HH:MM:SS"."""
        format_dict = self._tqdm.format_dict
        remaining_str = self._tqdm.format_meter(
            **{
                **format_dict,
                **dict(
                    # NOTE: Many more format variables are supported. See documentation:
                    #       https://tqdm.github.io/docs/tqdm/#format_meter
                    bar_format='{remaining}'
                )
            })
        if self._VERBOSE:
            def format_floatlike(value: object) -> str:
                return (
                    f'{value:.2f}'
                    if isinstance(value, (float, int))
                    else f'{value}'
                )
            rate_str = (
                f'{format_dict["rate"]:.2f}'
                if isinstance(format_dict["rate"], (float, int))
                else f'{format_dict["rate"]}'
            )
            remaining_str += (
                f' (rate={format_floatlike(format_dict["rate"])}, '
                f'ema_dn={format_floatlike(self._tqdm._ema_dn())}, '
                f'ema_dt={format_floatlike(self._tqdm._ema_dt())})'
            )
        
        try:
            time_per_item = self._tqdm._ema_dt() / self._tqdm._ema_dn()
        except (ZeroDivisionError, TypeError):
            time_per_item = None
        time_per_item_str = (
            f'{time_per_item:.2f}s'
            if time_per_item is not None
            else '?'
        )
        
        return (remaining_str, time_per_item_str)
    
    # === Operations ===
    
    def update(self, delta_n: int) -> None:
        if not (delta_n >= 0):
            raise ValueError()
        self._tqdm.update(delta_n)
    
    def close(self) -> None:
        self._tqdm.close()


class _TqdmWithoutDisplay(tqdm):
    def display(self, *args, **kwargs):  # override
        pass  # do nothing


class _DevNullFile:
    def write(self, value: str) -> None:
        pass
    
    def flush(self) -> None:
        pass
