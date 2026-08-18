"""Sampling a heightfield the way MuJoCo builds it.

MuJoCo does not interpolate an hfield cell bilinearly. It splits each cell into
two triangles across the MAIN diagonal -- the one joining `(row, col)` to
`(row+1, col+1)` -- and interpolates within whichever triangle the point falls
in. Sampling bilinearly instead leaves a real error between nodes: measured
against 400 ray casts on a 64-node noise field, bilinear was off by a mean of
3.6 mm and a max of 30.0 mm, while main-diagonal triangle interpolation was exact
at all 400 points. The anti-diagonal was worse than bilinear, which rules out a
coin flip.

That error is not academic. It set how deep a composed model was seated: an
under-estimated surface put the model below the triangles MuJoCo actually
collides against, so it started an episode already penetrating the ground.

Both heightfield users go through here -- the `rough` tile and the uniform
random/sinusoidal surfaces -- so neither can drift back to an approximation.
"""

from __future__ import annotations

import numpy as np


def sample(grid: np.ndarray, u: float, v: float) -> float:
    """Interpolate `grid` at fractional index (u, v), MuJoCo's way.

    `u` indexes columns and `v` rows, both in node units (so `u = 2.5` is halfway
    between columns 2 and 3). Values outside the grid are clamped to the edge.
    """
    nrow, ncol = grid.shape
    u = max(0.0, min(float(ncol - 1), u))
    v = max(0.0, min(float(nrow - 1), v))

    col = min(int(np.floor(u)), ncol - 2) if ncol > 1 else 0
    row = min(int(np.floor(v)), nrow - 2) if nrow > 1 else 0
    tu = u - col
    tv = v - row

    z00 = float(grid[row, col])
    z01 = float(grid[row, min(col + 1, ncol - 1)])
    z10 = float(grid[min(row + 1, nrow - 1), col])
    z11 = float(grid[min(row + 1, nrow - 1), min(col + 1, ncol - 1)])

    # The main diagonal runs from z00 to z11; tu >= tv is the triangle below it.
    if tu >= tv:
        return z00 + (z01 - z00) * tu + (z11 - z01) * tv
    return z00 + (z11 - z10) * tu + (z10 - z00) * tv
