"""Helpers classes and functions for ANOD."""

import e3.log
from e3.anod.error import AnodError
from e3.fs import find
from e3.fs import rm
from e3.os.fs import unixpath
from e3.yaml import custom_repr

from StringIO import StringIO

import os
import re
import yaml


log = e3.log.getLogger('anod.helpers')


class Make(object):
    """Wrapper around GNU Make."""

    def __init__(self, anod_instance,
                 makefile=None, exec_dir=None, jobs=None):
        """Initialize a Make object.

        :param anod_instance: an Anod instance
        :type anod_instance: e3.anod.spec.Anod
        :param makefile: the Makefile to use
        :type makefile: str | None
        :param exec_dir: path to the directory from where the make should be
            called
        :type exec_dir: str | None
        :param jobs: number of jobs to run in parallel
        :type jobs: int | None
        """
        self.anod_instance = anod_instance
        self.exec_dir = exec_dir
        if self.exec_dir is None:
            self.exec_dir = self.anod_instance.build_space.build_dir
        self.makefile = makefile
        self.jobs = jobs
        if jobs is None:
            self.jobs = anod_instance.jobs
        self.var_list = {}
        self.default_target = None

    def set_var(self, name, value):
        """Set a Make variable.

        :param name: name of the variable
        :type name: str
        :param value: value of the variable, can be a string or a list
            if it's the list, it will be stored in a string with each
            value separated by a space character
        :type value: str | list[str]
        """
        if isinstance(value, basestring):
            self.var_list[name] = value
        else:
            # Assume we get a list
            self.var_list[name] = " ".join(value)

    def set_default_target(self, target):
        """Set default make target.

        :param target: the target name to use if __call__ is called with
            target=None
        :type target: str
        """
        self.default_target = target

    def __call__(self, target=None, jobs=None, exec_dir=None, timeout=None):
        """Call a make target.

        :param target: the target to use (use default_target if None)
        :type target: str | None
        :param jobs: see __init__ documentation
        :type jobs: int | None
        :param exec_dir: see __init__ documentation
        :type exec_dir: str | None
        :param timeout: timeout to pass to ex.Run
        :type timeout: int | None
        """
        cmd, options = self.cmdline(
            target, jobs, exec_dir, timeout=timeout)
        return self.anod_instance.shell(*cmd, **options)

    def cmdline(self, target=None, jobs=None, exec_dir=None, timeout=None):
        """Return the make command line.

        :param target: the target to use (use default_target if None)
        :type target: str | None
        :param jobs: see __init__ documentation
        :type jobs: int | None
        :param exec_dir: see __init__ documentation
        :type exec_dir: str | None
        :param timeout: timeout to pass to ex.Run
        :type timeout: int | None

        :return: a dictionary with the following keys
           - cmd: containing the command line to pass to gnatpython.ex.Run
           - options: options to pass to gnatpython.ex.Run
        :rtype: dict
        """
        cmd_arg_list = ['make']

        if self.makefile is not None:
            cmd_arg_list += ['-f', unixpath(self.makefile)]

        cmd_arg_list += [
            '-j', '%s' % str(jobs) if jobs is not None else str(self.jobs)]

        for key in self.var_list:
            cmd_arg_list.append("%s=%s" % (key, self.var_list[key]))

        if target is None:
            target = self.default_target

        if target is not None:
            if isinstance(target, list):
                cmd_arg_list += target
            else:
                cmd_arg_list.append(target)

        options = {
            'cwd': exec_dir or self.exec_dir,
            'timeout': timeout}

        return {'cmd': self.anod_instance.parse_command(cmd_arg_list),
                'options': options}


class Configure(object):
    """Wrapper around ./configure."""

    def __init__(self, anod_instance, src_dir=None, exec_dir=None,
                 auto_target=True):
        """Initialize a Configure object.

        :param anod_instance: an Anod instance
        :type anod_instance: Anod
        :param src_dir: path to the directory containing the project sources
        :type src_dir: str | None
        :param exec_dir: path to the directory from where the configure should
            be called
        :type exec_dir: str | None
        :param auto_target: if True, automatically pass --target, --host and
            --build
        :type auto_target: bool
        """
        self.anod_instance = anod_instance
        self.src_dir = src_dir
        if self.src_dir is None:
            self.src_dir = self.anod_instance.build_space.src_dir
        self.exec_dir = exec_dir
        if self.exec_dir is None:
            self.exec_dir = self.anod_instance.build_space.build_dir
        self.args = []

        # Value of the --target, --host and --build arguments
        self.target = None
        self.host = None
        self.build = None

        if auto_target:
            e = anod_instance.env
            if e.is_canadian:
                self.target = e.target.triplet
                self.host = e.host.triplet
                self.build = e.build.triplet
            elif e.is_cross:
                self.target = e.target.triplet
                self.build = e.build.triplet
            else:
                self.build = e.target.triplet

        self.env = {}

    def add(self, *args):
        """Add configure options.

        :param args: list of options to pass when calling configure
        :type args: list[str]
        """
        self.args += args

    def add_env(self, key, value):
        """Set environment variable when calling configure.

        :param key: environment variable name
        :type key: str
        :param value: environment variable value
        :type value: str
        """
        self.env[key] = value

    def cmdline(self):
        """Return the configure command line.

        :return: a dictionary with the following keys
           - cmd: containing the command line to pass to gnatpython.ex.Run
           - options: options to pass to gnatpython.ex.Run
        :rtype: dict

        If CONFIG_SHELL environment variable is set, the configure will be
        called with this shell.
        """
        cmd = []
        if 'CONFIG_SHELL' in os.environ:
            cmd.append(os.environ['CONFIG_SHELL'])
        cmd += [unixpath(os.path.relpath(
            os.path.join(self.src_dir, 'configure'), self.exec_dir))]
        cmd += self.args

        if self.target is not None:
            cmd.append('--target=' + self.target)

        if self.host is not None:
            cmd.append('--host=' + self.host)

        if self.build is not None:
            cmd.append('--build=' + self.build)

        cmd_options = {'cwd': self.exec_dir,
                       'ignore_environ': False,
                       'env': self.env}

        return {'cmd': self.anod_instance.parse_command(cmd),
                'options': cmd_options}

    def __call__(self):
        cmd, options = self.cmdline()
        return self.anod_instance.shell(*cmd, **options)


def text_replace(filename, pattern):
    """Replace patterns in a file.

    :param filename: file path
    :type filename: str
    :param pattern: list of tuple (pattern, replacement)
    :type pattern: list[(str, str)]

    Do not modify the file if no substitution is done. Note that substitutions
    are applied sequentially (order provided by the list `pattern`) and this
    is done line per line.

    :return: the number of substitution performed for each pattern
    :rtype: list[int]
    """
    output = StringIO()
    nb_substitution = [0 for _ in pattern]
    with open(filename, 'rb') as f:
        for line in f:
            for pattern_index, (regexp, replacement) in enumerate(pattern):
                line, count = re.subn(regexp,
                                      replacement, line)
                if count:
                    nb_substitution[pattern_index] += count
            output.write(line)
    if any((nb for nb in nb_substitution)):
        # file changed, update it
        with open(filename, 'wb') as f:
            f.write(output.getvalue())
    output.close()
    return nb_substitution


def gplize(anod_instance, src_dir, force=False):
    """Remove GPL specific exception.

    This operate recursively on all .h .c .ad* .gp* files
    present in the directory passed as parameter

    :param anod_instance: an Anod instance
    :type anod_instance: Anod
    :param src_dir: the directory to process
    :type src_dir: str
    :param force: force transformation to gpl
    :type force: bool
    """
    def remove_paragraph(filename):
        begin = '-- .*As a .*special .*exception.* if other '\
            'files .*instantiate .*generics from .*(this)? .*|'\
            '-- .*As a .*special .*exception under Section 7 of GPL '\
            'version 3, you are.*|'\
            ' \* .*As a .*special .*exception.* if you .*link .*this'\
            ' file .*with other .*files to.*|'\
            ' \* .*As a .*special .*exception under Section 7 of GPL '\
            'version 3, you are.*|'\
            '\/\/ .*As a .*special .*exception.* if other files '\
            '.*instantiate .*generics from this.*|'\
            '\/\/ .*As a .*special .*exception under Section 7 of GPL '\
            'version 3, you are.*'
        end = '-- .*covered .*by .*the .*GNU Public License.*|'\
            '-- .*version 3.1, as published by the Free Software '\
            'Foundation.*--|'\
            '\/\/ .*covered by the  GNU Public License.*|'\
            '.*file .*might be covered by the  GNU Public License.*|'\
            '\/\/ .*version 3.1, as published by the Free Software'\
            ' Foundation.*\/\/|'\
            ' \* .*version 3.1, as published by the Free Software'\
            ' Foundation.*\*'

        output = StringIO()
        state = 2
        i = 0
        try:
            with open(filename) as f:
                for line in f:
                    # Detect comment type
                    if i == 1:
                        comment = line[0:2]
                        comment1 = comment
                        comment2 = comment
                        if comment == ' *':
                            comment2 = '* '
                    i += 1
                    # Detect begining of exception paragraph
                    if re.match(begin, line):
                        state = 0
                        output.write(
                            comment1 + (74 * " ") + comment2 + "\n")
                        continue
                    # Detect end of exception paragraph
                    if re.match(end, line):
                        if state == 0:
                            state = 1
                            output.write(
                                comment1 + (74 * " ") + comment2 + "\n")
                            continue
                    # Skip one line after the paragraph
                    if state == 1:
                        state = 3
                    # Replace exception lines with blank comment lines
                    if state == 0:
                        output.write(
                            comment1 + (74 * " ") + comment2 + "\n")
                        continue
                    # Write non exception lines
                    if (state == 2) or (state == 3):
                        output.write(line)
                if state == 0:
                    raise AnodError(
                        'gplize: End of paragraph was not detected in %s' % (
                            filename))
                with open(filename, "w") as dest_f:
                    dest_f.write(output.getvalue())
        finally:
            output.close()

    if anod_instance.sandbox.config.get('release_mode', '') == 'gpl' or force:
        anod_instance.log.debug('move files to GPL license')

        rm(os.path.join(src_dir, 'COPYING.RUNTIME'))
        gpb_files = find(src_dir, "*.gp*")
        ada_files = find(src_dir, "*.ad*")
        c_files = find(src_dir, "*.[hc]")
        java_files = find(src_dir, "*.java")

        for l in (gpb_files, ada_files, c_files, java_files):
            for k in l:
                remove_paragraph(k)


yaml.add_representer(Make, custom_repr('cmdline'))
yaml.add_representer(Configure, custom_repr('cmdline'))