# Copyright (c) 2012 Google Inc. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""
TestGyp.py:  a testing framework for GYP integration tests.
"""

from contextlib import contextmanager
import os
import shutil
import subprocess
import sys
import tempfile

import TestCommon
from TestCommon import __all__

__all__.extend([
  'TestGyp',
])


def remove_debug_line_numbers(contents):
  """Function to remove the line numbers from the debug output
  of gyp and thus reduce the extreme fragility of the stdout
  comparison tests.
  """
  lines = contents.splitlines()
  # split each line on ":"
  lines = [l.split(":", 3) for l in lines]
  # join each line back together while ignoring the
  # 3rd column which is the line number
  lines = [len(l) > 3 and ":".join(l[3:]) or l for l in lines]
  return "\n".join(lines)


def match_modulo_line_numbers(contents_a, contents_b):
  """File contents matcher that ignores line numbers."""
  contents_a = remove_debug_line_numbers(contents_a)
  contents_b = remove_debug_line_numbers(contents_b)
  return TestCommon.match_exact(contents_a, contents_b)


@contextmanager
def LocalEnv(local_env):
  """Context manager to provide a local OS environment."""
  old_env = os.environ.copy()
  os.environ.update(local_env)
  try:
    yield
  finally:
    os.environ.clear()
    os.environ.update(old_env)


class TestGypBase(TestCommon.TestCommon):
  """
  Class for controlling end-to-end tests of gyp generators.

  Instantiating this class will create a temporary directory and
  arrange for its destruction (via the TestCmd superclass) and
  copy all of the non-gyptest files in the directory hierarchy of the
  executing script.

  The default behavior is to test the 'gyp' or 'gyp.bat' file in the
  current directory.  An alternative may be specified explicitly on
  instantiation, or by setting the TESTGYP_GYP environment variable.

  This class should be subclassed for each supported gyp generator
  (format).  Various abstract methods below define calling signatures
  used by the test scripts to invoke builds on the generated build
  configuration and to run executables generated by those builds.
  """

  formats = []
  build_tool = None
  build_tool_list = []

  _exe = TestCommon.exe_suffix
  _obj = TestCommon.obj_suffix
  shobj_ = TestCommon.shobj_prefix
  _shobj = TestCommon.shobj_suffix
  lib_ = TestCommon.lib_prefix
  _lib = TestCommon.lib_suffix
  dll_ = TestCommon.dll_prefix
  _dll = TestCommon.dll_suffix

  # Constants to represent different targets.
  ALL = '__all__'
  DEFAULT = '__default__'

  # Constants for different target types.
  EXECUTABLE = '__executable__'
  STATIC_LIB = '__static_lib__'
  SHARED_LIB = '__shared_lib__'

  def __init__(self, gyp=None, *args, **kw):
    self.origin_cwd = os.path.abspath(os.path.dirname(sys.argv[0]))
    self.extra_args = sys.argv[1:]

    if not gyp:
      gyp = os.environ.get('TESTGYP_GYP')
      if not gyp:
        if sys.platform == 'win32':
          gyp = 'gyp-run.bat'
        else:
          gyp = 'gyp-run'
    self.gyp = os.path.abspath(gyp)
    self.no_parallel = False

    self.formats = [self.format]

    self.initialize_build_tool()

    kw.setdefault('match', TestCommon.match_exact)

    # Put test output in out/testworkarea by default.
    # Use temporary names so there are no collisions.
    workdir = os.path.join('out', kw.get('workdir', 'testworkarea'))
    # Create work area if it doesn't already exist.
    if not os.path.isdir(workdir):
      os.makedirs(workdir)

    kw['workdir'] = tempfile.mktemp(prefix='testgyp.', dir=workdir)

    formats = kw.pop('formats', [])

    super(TestGypBase, self).__init__(*args, **kw)

    real_format = self.format.split('-')[-1]
    excluded_formats = set([f for f in formats if f[0] == '!'])
    included_formats = set(formats) - excluded_formats
    if ('!'+real_format in excluded_formats or
        included_formats and real_format not in included_formats):
      msg = 'Invalid test for %r format; skipping test.\n'
      self.skip_test(msg % self.format)

    self.copy_test_configuration(self.origin_cwd, self.workdir)
    self.set_configuration(None)

    # Set $HOME so that gyp doesn't read the user's actual
    # ~/.gyp/include.gypi file, which may contain variables
    # and other settings that would change the output.
    os.environ['HOME'] = self.workpath()
    # Clear $GYP_DEFINES for the same reason.
    if 'GYP_DEFINES' in os.environ:
      del os.environ['GYP_DEFINES']
    # Override the user's language settings, which could
    # otherwise make the output vary from what is expected.
    os.environ['LC_ALL'] = 'C'

  def built_file_must_exist(self, name, type=None, **kw):
    """
    Fails the test if the specified built file name does not exist.
    """
    return self.must_exist(self.built_file_path(name, type, **kw))

  def built_file_must_not_exist(self, name, type=None, **kw):
    """
    Fails the test if the specified built file name exists.
    """
    return self.must_not_exist(self.built_file_path(name, type, **kw))

  def built_file_must_match(self, name, contents, **kw):
    """
    Fails the test if the contents of the specified built file name
    do not match the specified contents.
    """
    return self.must_match(self.built_file_path(name, **kw), contents)

  def built_file_must_not_match(self, name, contents, **kw):
    """
    Fails the test if the contents of the specified built file name
    match the specified contents.
    """
    return self.must_not_match(self.built_file_path(name, **kw), contents)

  def built_file_must_not_contain(self, name, contents, **kw):
    """
    Fails the test if the specified built file name contains the specified
    contents.
    """
    return self.must_not_contain(self.built_file_path(name, **kw), contents)

  def copy_test_configuration(self, source_dir, dest_dir):
    """
    Copies the test configuration from the specified source_dir
    (the directory in which the test script lives) to the
    specified dest_dir (a temporary working directory).

    This ignores all files and directories that begin with
    the string 'gyptest', and all '.svn' subdirectories.
    """
    for root, dirs, files in os.walk(source_dir):
      if '.svn' in dirs:
        dirs.remove('.svn')
      dirs = [ d for d in dirs if not d.startswith('gyptest') ]
      files = [ f for f in files if not f.startswith('gyptest') ]
      for dirname in dirs:
        source = os.path.join(root, dirname)
        destination = source.replace(source_dir, dest_dir)
        os.mkdir(destination)
        if sys.platform != 'win32':
          shutil.copystat(source, destination)
      for filename in files:
        source = os.path.join(root, filename)
        destination = source.replace(source_dir, dest_dir)
        shutil.copy2(source, destination)

  def initialize_build_tool(self):
    """
    Initializes the .build_tool attribute.

    Searches the .build_tool_list for an executable name on the user's
    $PATH.  The first tool on the list is used as-is if nothing is found
    on the current $PATH.
    """
    for build_tool in self.build_tool_list:
      if not build_tool:
        continue
      if os.path.isabs(build_tool):
        self.build_tool = build_tool
        return
      build_tool = self.where_is(build_tool)
      if build_tool:
        self.build_tool = build_tool
        return

    if self.build_tool_list:
      self.build_tool = self.build_tool_list[0]

  def relocate(self, source, destination):
    """
    Renames (relocates) the specified source (usually a directory)
    to the specified destination, creating the destination directory
    first if necessary.

    Note:  Don't use this as a generic "rename" operation.  In the
    future, "relocating" parts of a GYP tree may affect the state of
    the test to modify the behavior of later method calls.
    """
    destination_dir = os.path.dirname(destination)
    if not os.path.exists(destination_dir):
      self.subdir(destination_dir)
    os.rename(source, destination)

  def report_not_up_to_date(self):
    """
    Reports that a build is not up-to-date.

    This provides common reporting for formats that have complicated
    conditions for checking whether a build is up-to-date.  Formats
    that expect exact output from the command (make) can
    just set stdout= when they call the run_build() method.
    """
    print "Build is not up-to-date:"
    print self.banner('STDOUT ')
    print self.stdout()
    stderr = self.stderr()
    if stderr:
      print self.banner('STDERR ')
      print stderr

  def run_gyp(self, gyp_file, *args, **kw):
    """
    Runs gyp against the specified gyp_file with the specified args.
    """

    # When running gyp, and comparing its output we use a comparitor
    # that ignores the line numbers that gyp logs in its debug output.
    if kw.pop('ignore_line_numbers', False):
      kw.setdefault('match', match_modulo_line_numbers)

    # TODO:  --depth=. works around Chromium-specific tree climbing.
    depth = kw.pop('depth', '.')
    run_args = ['--depth='+depth]
    run_args.append(gyp_file)
    if self.no_parallel:
      run_args += ['--no-parallel']
    # TODO: if extra_args contains a '--build' flag
    # we really want that to only apply to the last format (self.format).
    run_args.extend(self.extra_args)
    # Default xcode_ninja_target_pattern to ^.*$ to fix xcode-ninja tests
    xcode_ninja_target_pattern = kw.pop('xcode_ninja_target_pattern', '.*')
    run_args.extend(
      ['-G', 'xcode_ninja_target_pattern=%s' % xcode_ninja_target_pattern])
    run_args.extend(args)
    return self.run(program=self.gyp, arguments=run_args, **kw)

  def run(self, *args, **kw):
    """
    Executes a program by calling the superclass .run() method.

    This exists to provide a common place to filter out keyword
    arguments implemented in this layer, without having to update
    the tool-specific subclasses or clutter the tests themselves
    with platform-specific code.
    """
    if kw.has_key('SYMROOT'):
      del kw['SYMROOT']
    super(TestGypBase, self).run(*args, **kw)

  def set_configuration(self, configuration):
    """
    Sets the configuration, to be used for invoking the build
    tool and testing potential built output.
    """
    self.configuration = configuration

  def configuration_dirname(self):
    if self.configuration:
      return self.configuration.split('|')[0]
    else:
      return 'Default'

  def configuration_buildname(self):
    if self.configuration:
      return self.configuration
    else:
      return 'Default'

  #
  # Abstract methods to be defined by format-specific subclasses.
  #

  def build(self, gyp_file, target=None, **kw):
    """
    Runs a build of the specified target against the configuration
    generated from the specified gyp_file.

    A 'target' argument of None or the special value TestGyp.DEFAULT
    specifies the default argument for the underlying build tool.
    A 'target' argument of TestGyp.ALL specifies the 'all' target
    (if any) of the underlying build tool.
    """
    raise NotImplementedError

  def built_file_path(self, name, type=None, **kw):
    """
    Returns a path to the specified file name, of the specified type.
    """
    raise NotImplementedError

  def built_file_basename(self, name, type=None, **kw):
    """
    Returns the base name of the specified file name, of the specified type.

    A bare=True keyword argument specifies that prefixes and suffixes shouldn't
    be applied.
    """
    if not kw.get('bare'):
      if type == self.EXECUTABLE:
        name = name + self._exe
      elif type == self.STATIC_LIB:
        name = self.lib_ + name + self._lib
      elif type == self.SHARED_LIB:
        name = self.dll_ + name + self._dll
    return name

  def run_built_executable(self, name, *args, **kw):
    """
    Runs an executable program built from a gyp-generated configuration.

    The specified name should be independent of any particular generator.
    Subclasses should find the output executable in the appropriate
    output build directory, tack on any necessary executable suffix, etc.
    """
    raise NotImplementedError

  def up_to_date(self, gyp_file, target=None, **kw):
    """
    Verifies that a build of the specified target is up to date.

    The subclass should implement this by calling build()
    (or a reasonable equivalent), checking whatever conditions
    will tell it the build was an "up to date" null build, and
    failing if it isn't.
    """
    raise NotImplementedError


class TestGypCustom(TestGypBase):
  """
  Subclass for testing the GYP with custom generator
  """

  def __init__(self, gyp=None, *args, **kw):
    self.format = kw.pop("format")
    super(TestGypCustom, self).__init__(*args, **kw)


def ConvertToCygpath(path):
  """Convert to cygwin path if we are using cygwin."""
  if sys.platform == 'cygwin':
    p = subprocess.Popen(['cygpath', path], stdout=subprocess.PIPE)
    path = p.communicate()[0].strip()
  return path


def FindMSBuildInstallation(msvs_version = 'auto'):
  """Returns path to MSBuild for msvs_version or latest available.

  Looks in the registry to find install location of MSBuild.
  MSBuild before v4.0 will not build c++ projects, so only use newer versions.
  """
  import TestWin
  registry = TestWin.Registry()

  msvs_to_msbuild = {
      '2013': r'12.0',
      '2012': r'4.0',  # Really v4.0.30319 which comes with .NET 4.5.
      '2010': r'4.0'}

  msbuild_basekey = r'HKLM\SOFTWARE\Microsoft\MSBuild\ToolsVersions'
  if not registry.KeyExists(msbuild_basekey):
    print 'Error: could not find MSBuild base registry entry'
    return None

  msbuild_version = None
  if msvs_version in msvs_to_msbuild:
    msbuild_test_version = msvs_to_msbuild[msvs_version]
    if registry.KeyExists(msbuild_basekey + '\\' + msbuild_test_version):
      msbuild_version = msbuild_test_version
    else:
      print ('Warning: Environment variable GYP_MSVS_VERSION specifies "%s" '
             'but corresponding MSBuild "%s" was not found.' %
             (msvs_version, msbuild_version))
  if not msbuild_version:
    for msvs_version in sorted(msvs_to_msbuild, reverse=True):
      msbuild_test_version = msvs_to_msbuild[msvs_version]
      if registry.KeyExists(msbuild_basekey + '\\' + msbuild_test_version):
        msbuild_version = msbuild_test_version
        break
  if not msbuild_version:
    print 'Error: could not find MSBuild registry entry'
    return None

  msbuild_path = registry.GetValue(msbuild_basekey + '\\' + msbuild_version,
                                   'MSBuildToolsPath')
  if not msbuild_path:
    print 'Error: could not get MSBuild registry entry value'
    return None

  return os.path.join(msbuild_path, 'MSBuild.exe')


def FindVisualStudioInstallation():
  """Returns appropriate values for .build_tool and .uses_msbuild fields
  of TestGypBase for Visual Studio.

  We use the value specified by GYP_MSVS_VERSION.  If not specified, we
  search %PATH% and %PATHEXT% for a devenv.{exe,bat,...} executable.
  Failing that, we search for likely deployment paths.
  """
  possible_roots = ['%s:\\Program Files%s' % (chr(drive), suffix)
                    for drive in range(ord('C'), ord('Z') + 1)
                    for suffix in ['', ' (x86)']]
  possible_paths = {
      '2013': r'Microsoft Visual Studio 12.0\Common7\IDE\devenv.com',
      '2012': r'Microsoft Visual Studio 11.0\Common7\IDE\devenv.com',
      '2010': r'Microsoft Visual Studio 10.0\Common7\IDE\devenv.com',
      '2008': r'Microsoft Visual Studio 9.0\Common7\IDE\devenv.com',
      '2005': r'Microsoft Visual Studio 8\Common7\IDE\devenv.com'}

  possible_roots = [ConvertToCygpath(r) for r in possible_roots]

  msvs_version = 'auto'
  for flag in (f for f in sys.argv if f.startswith('msvs_version=')):
    msvs_version = flag.split('=')[-1]
  msvs_version = os.environ.get('GYP_MSVS_VERSION', msvs_version)

  if msvs_version in possible_paths:
    # Check that the path to the specified GYP_MSVS_VERSION exists.
    path = possible_paths[msvs_version]
    for r in possible_roots:
      build_tool = os.path.join(r, path)
      if os.path.exists(build_tool):
        uses_msbuild = msvs_version >= '2010'
        msbuild_path = FindMSBuildInstallation(msvs_version)
        return build_tool, uses_msbuild, msbuild_path
    else:
      print ('Warning: Environment variable GYP_MSVS_VERSION specifies "%s" '
              'but corresponding "%s" was not found.' % (msvs_version, path))
  # Neither GYP_MSVS_VERSION nor the path help us out.  Iterate through
  # the choices looking for a match.
  for version in sorted(possible_paths, reverse=True):
    path = possible_paths[version]
    for r in possible_roots:
      build_tool = os.path.join(r, path)
      if os.path.exists(build_tool):
        uses_msbuild = msvs_version >= '2010'
        msbuild_path = FindMSBuildInstallation(msvs_version)
        return build_tool, uses_msbuild, msbuild_path
  print 'Error: could not find devenv'
  sys.exit(1)

class TestGypOnMSToolchain(TestGypBase):
  """
  Common subclass for testing generators that target the Microsoft Visual
  Studio toolchain (cl, link, dumpbin, etc.)
  """
  @staticmethod
  def _ComputeVsvarsPath(devenv_path):
    devenv_dir = os.path.split(devenv_path)[0]
    vsvars_path = os.path.join(devenv_path, '../../Tools/vsvars32.bat')
    return vsvars_path

  def initialize_build_tool(self):
    super(TestGypOnMSToolchain, self).initialize_build_tool()
    if sys.platform in ('win32', 'cygwin'):
      build_tools = FindVisualStudioInstallation()
      self.devenv_path, self.uses_msbuild, self.msbuild_path = build_tools
      self.vsvars_path = TestGypOnMSToolchain._ComputeVsvarsPath(
          self.devenv_path)

  def run_dumpbin(self, *dumpbin_args):
    """Run the dumpbin tool with the specified arguments, and capturing and
    returning stdout."""
    assert sys.platform in ('win32', 'cygwin')
    cmd = os.environ.get('COMSPEC', 'cmd.exe')
    arguments = [cmd, '/c', self.vsvars_path, '&&', 'dumpbin']
    arguments.extend(dumpbin_args)
    proc = subprocess.Popen(arguments, stdout=subprocess.PIPE)
    output = proc.communicate()[0]
    assert not proc.returncode
    return output

class TestGypNinja(TestGypOnMSToolchain):
  """
  Subclass for testing the GYP Ninja generator.
  """
  format = 'ninja'
  build_tool_list = ['ninja']
  ALL = 'all'
  DEFAULT = 'all'

  def run_gyp(self, gyp_file, *args, **kw):
    TestGypBase.run_gyp(self, gyp_file, *args, **kw)

  def build(self, gyp_file, target=None, **kw):
    arguments = kw.get('arguments', [])[:]

    # Add a -C output/path to the command line.
    arguments.append('-C')
    arguments.append(os.path.join('out', self.configuration_dirname()))

    if target is None:
      target = 'all'
    arguments.append(target)

    kw['arguments'] = arguments
    return self.run(program=self.build_tool, **kw)

  def run_built_executable(self, name, *args, **kw):
    # Enclosing the name in a list avoids prepending the original dir.
    program = [self.built_file_path(name, type=self.EXECUTABLE, **kw)]
    if sys.platform == 'darwin':
      configuration = self.configuration_dirname()
      os.environ['DYLD_LIBRARY_PATH'] = os.path.join('out', configuration)
    return self.run(program=program, *args, **kw)

  def built_file_path(self, name, type=None, **kw):
    result = []
    chdir = kw.get('chdir')
    if chdir:
      result.append(chdir)
    result.append('out')
    result.append(self.configuration_dirname())
    if type == self.STATIC_LIB:
      if sys.platform != 'darwin':
        result.append('obj')
    elif type == self.SHARED_LIB:
      if sys.platform != 'darwin' and sys.platform != 'win32':
        result.append('lib')
    subdir = kw.get('subdir')
    if subdir and type != self.SHARED_LIB:
      result.append(subdir)
    result.append(self.built_file_basename(name, type, **kw))
    return self.workpath(*result)

  def up_to_date(self, gyp_file, target=None, **kw):
    result = self.build(gyp_file, target, **kw)
    if not result:
      stdout = self.stdout()
      if 'ninja: no work to do' not in stdout:
        self.report_not_up_to_date()
        self.fail_test()
    return result


def TestGyp(*args, **kw):
  """
  Returns an appropriate TestGyp* instance for a specified GYP format.
  """
  format = kw.pop('format', os.environ.get('TESTGYP_FORMAT'))
  if format != 'ninja':
    raise Exception("unknown format %r" % format)
  return TestGypNinja(*args, **kw)
