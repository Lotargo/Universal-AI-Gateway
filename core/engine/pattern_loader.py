# magic_proxy/react_pattern_loader.py
import importlib
import logging
from pathlib import Path
from typing import Dict, Optional, List, Union

logger = logging.getLogger("UniversalAIGateway")

# Adjusted path to find react_patterns from core/engine/pattern_loader.py (root/react_patterns)
REACT_PATTERNS_DIR = Path(__file__).parents[2] / "react_patterns"
_REACT_PATTERNS = {}


def load_react_patterns():
    """Scans the react_patterns directory for Python modules and loads prompt structures.

    Looks for modules ending in '_react.py'.
    """
    if _REACT_PATTERNS:
        return
    logger.info(f"Scanning for ReAct patterns in: {REACT_PATTERNS_DIR}")
    for file_path in REACT_PATTERNS_DIR.glob("*_react.py"):
        module_name = file_path.stem
        try:
            full_module_path = f"react_patterns.{module_name}"
            module = importlib.import_module(full_module_path)
            if hasattr(module, "get_prompt_structure"):
                structure = module.get_prompt_structure()
                # If the module returns a dict (new smart caching structure), use it as is.
                # If it returns a list (legacy structure), use it as is.
                _REACT_PATTERNS[module_name] = structure
                logger.info(f"✅ Successfully loaded ReAct pattern: '{module_name}'")
        except Exception as e:
            logger.error(
                f"❌ Failed to load ReAct pattern from '{file_path.name}': {e}",
                exc_info=True,
            )


def get_react_pattern(name: str) -> Optional[Union[List[Dict], Dict[str, str]]]:
    """Retrieves a loaded ReAct pattern by its name.

    Args:
        name: The name of the pattern.

    Returns:
        The pattern structure (list of message dicts OR dict with static/dynamic keys),
        or None if not found.
    """
    if not _REACT_PATTERNS:
        load_react_patterns()
    return _REACT_PATTERNS.get(name)


def get_available_react_patterns() -> List[str]:
    """
    Returns a list of names of all available ReAct patterns.
    """
    if not _REACT_PATTERNS:
        load_react_patterns()
    return list(_REACT_PATTERNS.keys())
