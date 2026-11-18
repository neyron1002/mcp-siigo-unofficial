# Override of PyInstaller's hook: same dependencies, minus the Qt plugins,
# libraries, and translations the app does not use (plan D20).
from PyInstaller.utils.hooks.qt import add_qt6_dependencies
from qt_filter import keep

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
binaries = [entry for entry in binaries if keep(entry[0])]
datas = [entry for entry in datas if keep(entry[0])]
