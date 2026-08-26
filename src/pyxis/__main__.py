"""Module entry point so ``python -m pyxis`` works.

Uses an absolute self-import (not a relative one) so that the package is
fully initialized and the relative imports inside ``pyxis.main`` resolve
correctly whether we're launched via ``python -m pyxis``, the ``pyxis``
console script, or PyInstaller.
"""

from pyxis.main import main

if __name__ == "__main__":
    main()
