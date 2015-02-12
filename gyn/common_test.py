#!/usr/bin/env python

# Copyright (c) 2012 Google Inc. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for the common.py file."""

import gyn.common
import unittest
import sys


class TestTopologicallySorted(unittest.TestCase):
  def test_Valid(self):
    """Test that sorting works on a valid graph with one possible order."""
    graph = {
        'a': ['b', 'c'],
        'b': [],
        'c': ['d'],
        'd': ['b'],
        }
    def GetEdge(node):
      return tuple(graph[node])
    self.assertEqual(
      gyn.common.TopologicallySorted(graph.keys(), GetEdge),
      ['a', 'c', 'd', 'b'])

  def test_Cycle(self):
    """Test that an exception is thrown on a cyclic graph."""
    graph = {
        'a': ['b'],
        'b': ['c'],
        'c': ['d'],
        'd': ['a'],
        }
    def GetEdge(node):
      return tuple(graph[node])
    self.assertRaises(
      gyn.common.CycleError, gyn.common.TopologicallySorted,
      graph.keys(), GetEdge)


class TestGetFlavor(unittest.TestCase):
  """Test that gyn.common.GetFlavor works as intended"""
  original_platform = ''

  def setUp(self):
    self.original_platform = sys.platform

  def tearDown(self):
    sys.platform = self.original_platform

  def assertFlavor(self, expected, argument, param):
    sys.platform = argument
    self.assertEqual(expected, gyn.common.GetFlavor(param))

  def test_platform_default(self):
    self.assertFlavor('freebsd', 'freebsd9' , {})
    self.assertFlavor('freebsd', 'freebsd10', {})
    self.assertFlavor('openbsd', 'openbsd5' , {})
    self.assertFlavor('solaris', 'sunos5'   , {});
    self.assertFlavor('solaris', 'sunos'    , {});
    self.assertFlavor('linux'  , 'linux2'   , {});
    self.assertFlavor('linux'  , 'linux3'   , {});

  def test_param(self):
    self.assertFlavor('foobar', 'linux2' , {'flavor': 'foobar'})


if __name__ == '__main__':
  unittest.main()
