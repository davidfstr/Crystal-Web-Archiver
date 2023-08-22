from crystal.util.xos import is_windows
from tqdm import tqdm
from tqdm.std import EMA
from typing import Optional, Tuple


class ProgressBarCalculator:
    """
    Calculates statistics about a process in progress,
    such as estimated time remaining.
    """
    _VERBOSE = False
    
    # Calibration notes:
    # - 0.10 seems too low
    # - 0.15 seems too high
    _MINIMUM_RATE_TO_REPORT = 0.13
    
    _MAXIMUM_DELAY_BETWEEN_GROWTH_UPDATES = 10.0  # seconds
    
    # HACK: Avoid printing characters outside the Windows-1252 encoding (cp1252)
    #       when running on Windows because Windows seems to generally expect
    #       stdout/stderr on Windows to be decodable using that encoding.
    _DELTA = 'Δ' if not is_windows() else 'd'
    
    def __init__(self, initial: int, total: int) -> None:
        self._rc_n = RateCalculator(initial, total)
        self._rc_total = RateCalculator(total)
    
    # === Properties ===
    
    @property
    def n(self) -> int:
        return self._rc_n.n
    
    def _get_total(self) -> int:
        return self._rc_n.total
    def _set_total(self, total: int) -> None:
        delta_total = total - self._rc_n.total
        if delta_total:
            self._rc_n.total = total
            self._rc_total.update(delta_total)
    total = property(_get_total, _set_total)
    
    def remaining_str_and_time_per_item_str(self) -> Tuple[str, str]:
        """Compute estimated remaining time, in format "MM:SS" or "HH:MM:SS"."""
        n = self.n
        total = self.total
        
        growth_rate_of_n = self._rc_n.rate
        growth_rate_of_total = self._rc_total.rate
        rate = (growth_rate_of_n or 0.0) - (growth_rate_of_total or 0.0)
        
        remaining = (
            (total - n) / rate
            if rate > self._MINIMUM_RATE_TO_REPORT and total
            else 0
        )
        # TODO: Call ProgressBarCalculator.format_interval() directly,
        #       rather than through a monkeypatch
        remaining_str = (
            tqdm.format_interval(remaining)
            if rate > self._MINIMUM_RATE_TO_REPORT
            else '?'
        )
        
        time_per_item_done = 1 / growth_rate_of_n if growth_rate_of_n else None
        time_per_item_add = 1 / growth_rate_of_total if growth_rate_of_total else None
        time_per_item_str = (
            f'{time_per_item_done:.2f}s'
            if time_per_item_done is not None
            else '?'
        ) + '/item'
        if (growth_rate_of_total or 0.0) > self._MINIMUM_RATE_TO_REPORT:
            assert time_per_item_add is not None
            time_per_item_str += ', ' + (
                f'{time_per_item_add:.2f}s'
            ) + '/growth'
        
        if self._VERBOSE:
            def format_floatlike(value: object) -> str:
                return (
                    f'{value:.2f}'
                    if isinstance(value, (float, int))
                    else f'{value}'
                )
            rate_str = (
                f'{rate:.2f}'
                if isinstance(rate, (float, int))
                else f'{rate}'
            )
            time_per_item_str += (
                f', rate={format_floatlike(rate)}, '
                f'{self._DELTA}n={format_floatlike(self._rc_n._tqdm._ema_dn())}/'
                f'{format_floatlike(self._rc_n._tqdm._ema_dt())}, '
                f'{self._DELTA}total={format_floatlike(self._rc_total._tqdm._ema_dn())}/'
                f'{format_floatlike(self._rc_total._tqdm._ema_dt())}'
            )
        
        return (remaining_str, time_per_item_str)
    
    # === Operations ===
    
    def update(self, delta_n: int) -> None:
        if not (delta_n >= 0):
            raise ValueError()
        self._rc_n._tqdm.update(delta_n)
        
        time_since_last_growth_update = (
            self._rc_n.last_print_t - self._rc_total.last_print_t
        )
        if time_since_last_growth_update > self._MAXIMUM_DELAY_BETWEEN_GROWTH_UPDATES:
            self._rc_total.update(0)
    
    def close(self) -> None:
        self._rc_n.close()
        self._rc_total.close()
    
    # === Utility ===
    
    @staticmethod
    def format_interval(t: int) -> str:
        """
        Formats a number of seconds as a clock time,
        `[H:]MM:SS` or `Dd + H:MM:SS`
        """
        mins, s = divmod(int(t), 60)
        hours, m = divmod(mins, 60)
        d, h = divmod(hours, 24)
        if d:
            # ex: '1d + 7:08:54'
            return '{0:d}d + {1:d}:{2:02d}:{3:02d}'.format(d, h, m, s)
        elif h:
            # ex: '7:08:54'
            return '{0:d}:{1:02d}:{2:02d}'.format(h, m, s)
        else:
            # ex: '08:54'
            return '{0:02d}:{1:02d}'.format(m, s)


class RateCalculator:
    def __init__(self, initial: int, total: Optional[int]=None) -> None:
        self._tqdm = _TqdmWithoutDisplay(
            initial=initial,  # self.n = initial
            total=total,
            file=_DevNullFile(),
            
            # Recompute remaining time after each update() call unless many
            # calls made in a short time interval (<= `mininterval`).
            miniters=0,
            mininterval=0.1,  # tqdm's default value
            
            # Calibrate EMA (exponential moving average) smoothing factors for speed estimates.
            # Ranges from 0.0 (average speed) to 1.0 (current/instantaneous speed).
            smoothing=0.1,  # NOTE: default is 0.3
        )
    
    # === Properties ===
    
    @property
    def n(self) -> int:
        return self._tqdm.n
    
    def _get_total(self) -> Optional[int]:
        return self._tqdm.total
    def _set_total(self, total: Optional[int]) -> None:
        self._tqdm.total = total
    total = property(_get_total, _set_total)
    
    @property
    def rate(self) -> Optional[float]:
        dn = self._tqdm._ema_dn()  # cache
        dt = self._tqdm._ema_dt()  # cache
        rate = dn / dt if dt else None
        return rate
    
    @property
    def last_print_t(self) -> float:
        return self._tqdm.last_print_t
    
    # === Operations ===
    
    def update(self, delta_n: int) -> None:
        if not (delta_n >= 0):
            raise ValueError()
        if delta_n == 0:
            # Force the effect of: self._tqdm.update(0)
            cur_t = self._tqdm._time()
            dt = cur_t - self._tqdm.last_print_t
            dn = 0
            self._tqdm._ema_dn(dn)
            self._tqdm._ema_dt(dt)
            self._tqdm.last_print_t = cur_t
        else:
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


# ------------------------------------------------------------------------------

# Monkeypatch tqdm.format_interval() so that tqdm.format_meter() will use it
# when formatting timedeltas
tqdm.format_interval = ProgressBarCalculator.format_interval
