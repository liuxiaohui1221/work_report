"""TIAS - Team Intelligence Alignment System"""
__version__ = "0.1.0"

from .config import TIASConfig, ProjectConfig, PersonConfig, load_config

__all__ = ["TIASConfig", "ProjectConfig", "PersonConfig", "load_config"]