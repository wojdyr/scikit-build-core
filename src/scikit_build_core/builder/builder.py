from __future__ import annotations

import dataclasses
import re
import sys
import sysconfig
from pathlib import Path
from typing import Mapping

from packaging.version import Version

from .. import __version__
from ..builder.sysconfig import get_python_include_dir, get_python_library
from ..cmake import CMakeConfig
from ..errors import NinjaNotFoundError
from ..program_search import best_program, get_make_programs, get_ninja_programs
from ..resources import find_python
from ..settings.skbuild_model import ScikitBuildSettings

__all__: list[str] = ["Builder"]

DIR = Path(__file__).parent.resolve()


def __dir__() -> list[str]:
    return __all__


@dataclasses.dataclass
class Builder:
    settings: ScikitBuildSettings
    config: CMakeConfig

    # TODO: cross-compile support for other platforms
    def get_archs(self) -> list[str]:
        """
        Takes macOS platform settings and returns a list of platforms.

        Example (macOS):
            ARCHFLAGS="-arch x86_64" -> ["x86_64"]
            ARCHFLAGS="-arch x86_64 -arch arm64" -> ["x86_64", "arm64"]
            ARCHFLAGS="-arch universal2" -> ["universal2"]

        Returns an empty list otherwise or if ARCHFLAGS is not set.

        If the extra_tags setting is True, then the list of platforms is
        expanded to include extra matching platforms (universal2 also produces
        x86_64 and arm64).
        """

        if sys.platform.startswith("darwin"):
            archs = re.findall(r"-arch (\S+)", self.config.env.get("ARCHFLAGS", ""))
            if (
                self.settings.wheel.expand_macos_universal_tags
                and ["universal2"] == archs
            ):
                archs += ["x86_64", "arm64"]
            return archs

        return []

    def configure(
        self,
        *,
        defines: Mapping[str, str],
        name: str | None = None,
        version: Version | None = None,
        limited_abi: bool | None = None,
    ) -> None:
        cmake_defines = dict(defines)
        cmake_args: list[str] = []

        site_packages = Path(sysconfig.get_path("purelib"))
        self.config.prefix_dirs.append(site_packages)
        if site_packages != DIR.parent.parent:
            self.config.prefix_dirs.append(DIR.parent.parent)

        if self.config.cmake.version < Version("3.24"):
            self.config.module_dirs.append(Path(find_python.__file__).parent.resolve())

        if sys.platform.startswith("win32"):
            # TODO: support cross-compilation
            is_64bit = sys.maxsize > 2**32
            if not is_64bit:
                cmake_args += ["-A", "Win32"]
        else:
            # Ninja is currently required on Unix
            ninja = best_program(
                get_ninja_programs(),
                minimum_version=Version(self.settings.ninja.minimum_version),
            )
            if ninja is None:
                msg = "Ninja or make is required to build"
                if not self.settings.ninja.make_fallback:
                    raise NinjaNotFoundError(msg)

                make_programs = list(get_make_programs())
                if not make_programs:
                    raise NinjaNotFoundError(msg)
                self.config.env.setdefault("CMAKE_MAKE_PROGRAM", str(make_programs[0]))
                self.config.env.setdefault("CMAKE_GENERATOR", "Unix Makefiles")
            else:
                self.config.env.setdefault("CMAKE_GENERATOR", "Ninja")
                self.config.env.setdefault("CMAKE_MAKE_PROGRAM", str(ninja.path))

        cache_config: dict[str, str | Path] = {
            "SKBUILD": "2",
            "SKBUILD_CORE_VERSION": __version__,
        }

        if name is not None:
            canonical_name = name.replace("-", "_").replace(".", "_")
            cache_config["SKBUILD_PROJECT_NAME"] = canonical_name
        if version is not None:
            cache_config["SKBUILD_PROJECT_VERSION"] = str(version)

        # Classic Find Python
        python_library = get_python_library()
        python_include_dir = get_python_include_dir()
        cache_config["PYTHON_EXECUTABLE"] = sys.executable
        cache_config["PYTHON_INCLUDE_DIR"] = python_include_dir
        if python_library:
            cache_config["PYTHON_LIBRARY"] = python_library

        # Modern Find Python
        for prefix in ["Python", "Python3"]:
            cache_config[f"{prefix}_EXECUTABLE"] = sys.executable
            cache_config[f"{prefix}_ROOT_DIR"] = sys.prefix
            cache_config[f"{prefix}_INCLUDE_DIR"] = python_include_dir
            cache_config[f"{prefix}_FIND_REGISTRY"] = "NEVER"

        if limited_abi is None:
            limited_abi = self.settings.wheel.py_api.startswith("cp3")

        if limited_abi:
            cache_config["SKBUILD_SOABI"] = (
                "" if sys.platform.startswith("win") else "abi3"
            )
        else:
            # Workaround for bug in PyPy and packaging that is not handled in CMake
            # According to PEP 3149, SOABI and EXT_SUFFIX are interchangeable (and
            # the latter is much more likely to be correct as it is used elsewhere)
            ext_suffix = sysconfig.get_config_var("EXT_SUFFIX")
            assert ext_suffix
            cache_config["SKBUILD_SOABI"] = ext_suffix.rsplit(".", 1)[0].lstrip(".")

        self.config.init_cache(cache_config)

        # Adding CMake arguments set as environment variable
        # (needed e.g. to build for ARM OSX on conda-forge)
        cmake_args += [
            item for item in self.config.env.get("CMAKE_ARGS", "").split(" ") if item
        ]

        if sys.platform.startswith("darwin"):
            # Cross-compile support for macOS - respect ARCHFLAGS if set
            archs = self.get_archs()
            if archs:
                cmake_defines["CMAKE_OSX_ARCHITECTURES"] = ";".join(archs)

        self.config.configure(
            defines=cmake_defines,
            cmake_args=cmake_args,
        )

    def build(self, build_args: list[str]) -> None:
        # TODO: configure verbose
        self.config.build(build_args=build_args, verbose=1)

    def install(self, install_dir: Path) -> None:
        self.config.install(install_dir)
