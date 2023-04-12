from __future__ import annotations
from e3.python.pypi import PyPIClosure
from e3.python.wheel import Wheel
from e3.anod.checkout import CheckoutManager
from pkg_resources import Requirement
from e3.main import Main
from e3.fs import mkdir, cp
import argparse
import os
import re
import yaml
import logging


DESCRIPTION = """
This script generates a directory containing the full closure of a set
of Python requirements for a set of platforms and a given Python version

Config file has the following format:

    wheels:
        name1: url1#branch1
        name2: url2
    requirements:
        - "req1"
        - "req2"
        - "req3"
    discard_from_closure: "regexp"
    frozen_requirement_file: "requirements.txt"
    platforms:
        - x86_64-linux
        - x86_64-windows
        - aarch64-linux

wheels contains the list of wheel that should be locally built
from source located at a git repository url (branch is specified after
a #, if no branch is specified master is assumed

requirements are additional python requirements as string

discard_from_closure are packages that should not be copied into the
target dir (packages do not appears also in the generated requirement
file)

frozen_requirement_file is the basename of the generated frozen requirement
file.

platforms is the list of platforms for which wheel should be fetched
"""


def main() -> None:
    m = Main()
    m.argument_parser.formatter_class = argparse.RawDescriptionHelpFormatter
    m.argument_parser.description = DESCRIPTION.strip()
    m.argument_parser.add_argument("config_file", help="configuration files")
    m.argument_parser.add_argument(
        "--python3-version", help="Python 3 version (default:10)", type=int, default=10
    )
    m.argument_parser.add_argument("target_dir", help="target directory")
    m.argument_parser.add_argument(
        "--cache-dir", help="cache directory (default ./cache)", default="./cache"
    )
    m.argument_parser.add_argument(
        "--skip-repo-updates",
        action="store_true",
        help="Don't update clones in the cache",
    )
    m.argument_parser.add_argument(
        "--local-clones",
        help="Use local clones. When set look for git clones in a directory",
        default=None,
    )
    m.parse_args()
    assert m.args is not None

    vcs_cache_dir = os.path.abspath(os.path.join(m.args.cache_dir, "vcs"))
    wheel_cache_dir = os.path.abspath(os.path.join(m.args.cache_dir, "wheels"))
    mkdir(vcs_cache_dir)
    mkdir(wheel_cache_dir)
    mkdir(m.args.target_dir)

    # Load the configuration file
    with open(m.args.config_file) as fd:
        config = yaml.safe_load(fd.read())

    # First build the local wheels
    local_wheels = []

    for name, url in config.get("wheels", {}).items():
        logging.info(f"Fetch {name} sources")
        if "#" in url:
            url, rev = url.split("#", 1)
        else:
            rev = "master"
        checkout_manager = CheckoutManager(
            name=name, working_dir=os.path.join(vcs_cache_dir), compute_changelog=False
        )

        if m.args.local_clones is not None:
            checkout_manager.update(
                vcs="external",
                url=os.path.join(m.args.local_clones, url.split("/")[-1]),
                revision=rev,
            )
        else:
            if not m.args.skip_repo_updates:
                checkout_manager.update(vcs="git", url=url, revision=rev)

        local_wheels.append(
            Wheel.build(
                source_dir=checkout_manager.working_dir, dest_dir=wheel_cache_dir
            )
        )

    # Compute the list of toplevel requirements
    toplevel_reqs = {Requirement.parse(wheel) for wheel in config.get("wheels", {})} | {
        Requirement.parse(r) for r in config.get("requirements", [])
    }

    with PyPIClosure(
        cache_file=os.path.join(m.args.cache_dir, "pip.cache"),
        cache_dir=wheel_cache_dir,
        python3_version=m.args.python3_version,
        platforms=config["platforms"],
    ) as pypi:
        for wheel in local_wheels:
            logging.info(f"Register wheel {wheel.path}")
            pypi.add_wheel(wheel.path)

        for req in toplevel_reqs:
            logging.info(f"Add top-level requirement {str(req)}")
            pypi.add_requirement(req)

        for f in pypi.file_closure():
            pkg_name = os.path.basename(f).split("-")[0].replace("_", "-")
            if "discard_from_closure" not in config or not re.search(
                config["discard_from_closure"], pkg_name
            ):
                cp(f, m.args.target_dir)

        with open(
            os.path.join(
                m.args.target_dir,
                config.get("frozen_requirement_file", "requirements.txt"),
            ),
            "w",
        ) as fd:
            for req in pypi.closure_as_requirements():
                if "discard_from_closure" not in config or not re.search(
                    config["discard_from_closure"], req.project_name
                ):
                    fd.write(f"{str(req)}\n")