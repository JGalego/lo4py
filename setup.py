import sys
from pathlib import Path

from setuptools import Distribution, setup
from setuptools.command.bdist_wheel import bdist_wheel
from setuptools.command.build_py import build_py

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_runtime import build_runtime, get_target  # noqa: E402


class BuildPy(build_py):
    def run(self):
        if not self.editable_mode:
            build_runtime()
        super().run()


class BinaryWheel(bdist_wheel):
    def get_tag(self):
        return "py3", "none", get_target().wheel_platform


class BinaryDistribution(Distribution):
    def has_ext_modules(self):
        return True


setup(
    distclass=BinaryDistribution,
    cmdclass={"build_py": BuildPy, "bdist_wheel": BinaryWheel},
)
