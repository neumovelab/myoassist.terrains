"""Allow `python -m myoassist_terrains ...` to dispatch through the CLI."""

import sys

from myoassist_terrains.cli import main

if __name__ == "__main__":
    # sys.exit, not a bare call: without it `python -m` reported success for
    # every failure, so a script checking the return code walked straight past a
    # missing config. The console script has always exited properly, which is why
    # the two invocations disagreed despite the docs calling them equivalent.
    sys.exit(main())
