"""Existing interactive ANIMA CLI, sharing P1's composition root."""

from anima.core.assembly import build_core
from anima.interfaces.cli import run_cli


def main():
    core = build_core()
    run_cli(
        runtime=core.runtime,
        anima=core.state,
        identity=core.identity,
        memory=core.memory,
    )


if __name__ == "__main__":
    main()
