"""What MRT uses of Maya's dockable widget mixin, typed.

Autodesk ships the mixin without types, so a window inheriting from it
carries none unless they are declared here.

Only what is used is declared. Its keyword arguments are the host's own and
are not narrowed: what each one accepts is Maya's to say, not this file's.
"""

class MayaQWidgetDockableMixin:
    def show(self, **kwargs: object) -> None: ...
    def hide(self) -> None: ...
    def isDockable(self) -> bool: ...  # noqa: N802 - the host's own name
