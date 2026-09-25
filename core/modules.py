"""
The Osmia module system.

A module is an ordinary Django app whose AppConfig subclasses
``OsmiaModuleConfig`` and sets a ``manifest``, much like an Odoo
``__manifest__.py``. The registry below reads those manifests to build the
navigation, mount each module's URLs and order modules by dependency.
"""
from dataclasses import dataclass
from importlib.util import find_spec

from django.apps import AppConfig, apps


@dataclass(frozen=True)
class MenuItem:
    label: str
    url_name: str  # e.g. "tasks:list"


@dataclass(frozen=True)
class Module:
    title: str
    description: str = ""
    icon: str = "📦"
    depends: tuple[str, ...] = ()
    menu: tuple[MenuItem, ...] = ()
    sequence: int = 100
    url_prefix: str | None = None  # defaults to the app label
    home_url: str | None = None  # defaults to the first menu item


class OsmiaModuleConfig(AppConfig):
    """Base AppConfig for every Osmia module."""

    manifest: Module

    # Modules import this base class into their apps.py, so Django would see two
    # AppConfig candidates and pick neither. Mark the base as non-default and
    # every subclass as default so the module's own config is always chosen.
    default = False

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.default = cls.__dict__.get('default', True)

    @property
    def prefix(self):
        return self.manifest.url_prefix if self.manifest.url_prefix is not None else self.label

    @property
    def home_url_name(self):
        if self.manifest.home_url:
            return self.manifest.home_url
        return self.manifest.menu[0].url_name if self.manifest.menu else None


def installed_modules():
    """Installed modules ordered by sequence, then title."""
    configs = [c for c in apps.get_app_configs() if isinstance(c, OsmiaModuleConfig)]
    return sorted(configs, key=lambda c: (c.manifest.sequence, c.manifest.title))


def get_module(label):
    for config in installed_modules():
        if config.label == label:
            return config
    return None


def dependency_order():
    """Modules sorted so that every module comes after its dependencies."""
    by_label = {c.label: c for c in installed_modules()}
    ordered, seen = [], set()

    def visit(config, stack=()):
        if config.label in seen:
            return
        if config.label in stack:
            raise RuntimeError(f"Circular module dependency: {' -> '.join(stack + (config.label,))}")
        for dep in config.manifest.depends:
            if dep in by_label:
                visit(by_label[dep], stack + (config.label,))
        seen.add(config.label)
        ordered.append(config)

    for config in by_label.values():
        visit(config)
    return ordered


def module_urlpatterns():
    """Mount ``<app>/urls.py`` of every module under its prefix, namespaced by label."""
    from django.urls import include, path

    patterns = []
    for config in installed_modules():
        if find_spec(f"{config.name}.urls") is None:
            continue
        prefix = f"{config.prefix}/" if config.prefix else ""
        patterns.append(path(prefix, include((f"{config.name}.urls", config.label))))
    return patterns
