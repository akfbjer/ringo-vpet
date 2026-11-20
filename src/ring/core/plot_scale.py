"""Display-only symmetric axis range, independent of sensor configuration."""
import math
import numpy as np


def axis_limit(values, minimum: float, previous: float) -> float:
    """Expand before clipping, shrink only across a large range change.

    Values cover the visible six-second window, so an excursion stays represented
    until it leaves the window. A 2.5x hysteresis avoids a breathing vertical axis.
    """
    finite = np.asarray(values)[np.isfinite(values)]
    peak = float(np.max(np.abs(finite))) if finite.size else 0.0
    needed = max(minimum, peak * 1.15)
    decade = 10 ** math.floor(math.log10(needed))
    target = next(multiplier * decade for multiplier in (1, 2, 5, 10)
                  if multiplier * decade >= needed)
    return float(target if target > previous or target <= previous * .4 else previous)
