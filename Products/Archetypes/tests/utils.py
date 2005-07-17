# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2002-2005, Benjamin Saller <bcsaller@ideasuite.com>, and
#                              the respective authors. All rights reserved.
# For a list of Archetypes contributors see docs/CREDITS.txt.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
# * Neither the name of the author nor the names of its contributors may be used
#   to endorse or promote products derived from this software without specific
#   prior written permission.
#
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#
################################################################################
"""
"""

import re
from TAL import ndiff
from Globals import package_home

from Products.Archetypes.atapi import registerType
from Products.Archetypes.atapi import process_types
from Products.Archetypes.atapi import listTypes
from Products.Archetypes.atapi import BaseContent
from Products.Archetypes.config import PKG_NAME

PACKAGE_HOME = package_home(globals())

def gen_class(klass, schema=None):
    """generats and registers the klass
    """
    if schema is not None:
        klass.schema = schema.copy()
    registerType(klass, 'Archetypes')
    content_types, constructors, ftis = process_types(listTypes(), PKG_NAME)

def mkDummyInContext(klass, oid, context, schema=None):
    gen_class(klass, schema)
    dummy = klass(oid=oid).__of__(context)
    setattr(context, oid, dummy)
    dummy.initializeArchetype()
    return dummy

def makeContent( container, portal_type, id='document', **kw ):
    container.invokeFactory( type_name=portal_type, id=id )
    return getattr( container, id )

class Dummy(BaseContent):
    def Title(self):
        return 'title'

def normalize_html(s):
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"(?s)\s+<", "<", s)
    s = re.sub(r"(?s)>\s+", ">", s)
    return s

def nicerange(lo, hi):
    if hi <= lo+1:
        return str(lo+1)
    else:
        return "%d,%d" % (lo+1, hi)

def showdiff(a, b):
    cruncher = ndiff.SequenceMatcher(ndiff.IS_LINE_JUNK, a, b)
    for tag, alo, ahi, blo, bhi in cruncher.get_opcodes():
        if tag == "equal":
            continue
        print nicerange(alo, ahi) + tag[0] + nicerange(blo, bhi)
        ndiff.dump('<', a, alo, ahi)
        if a and b:
            print '---'
        ndiff.dump('>', b, blo, bhi)

def start_http(address, port):
    import sys
    from ZServer import asyncore
    from ZServer import zhttp_server, zhttp_handler
    import socket

    import Zope # Sigh, make product initialization happen
    try:
        Zope.startup()
    except: # Zope > 2.6
        pass

    from ZServer import setNumberOfThreads
    setNumberOfThreads(4)

    try:
        hs = zhttp_server(
            ip=address,
            port=port,
            resolver=None,
            logger_object=None)
    except socket.error, why:
        if why[0] == 98: # address in use
            raise port_err % {'port':port,
                              'socktype':'TCP',
                              'protocol':'HTTP',
                              'switch':'-w'}
        raise
    # Handler for a published module. zhttp_handler takes 3 arguments:
    # The name of the module to publish, and optionally the URI base
    # which is basically the SCRIPT_NAME, and optionally a dictionary
    # with CGI environment variables which override default
    # settings. The URI base setting is useful when you want to
    # publish more than one module with the same HTTP server. The CGI
    # environment setting is useful when you want to proxy requests
    # from another web server to ZServer, and would like the CGI
    # environment to reflect the CGI environment of the other web
    # server.
    zh = zhttp_handler('Zope', '', {})
    zh._force_connection_close = 1
    hs.install_handler(zh)
    sys.ZServerExitCode=0
    asyncore.loop()
    sys.exit(sys.ZServerExitCode)

def populateFolder(folder, folder_type, doc_type):
    """ Creates a structure like:

    \index_html
    \doc1
    \folder1
       \folder11
       \folder12
       \doc11
    \folder2
       \folder21
       \doc21
       \index_html
       \folder22
          \folder221
             \doc2211
             \doc2212
          \folder222
             \doc2221
             \doc2222
          \folder223
             \doc2231
             \doc2232
    """
    folder.invokeFactory(doc_type, id='index_html')
    folder.invokeFactory(doc_type, id='doc1')
    folder.invokeFactory(folder_type, id='folder1')
    folder.invokeFactory(folder_type, id='folder2')
    f1 = folder.folder1
    f2 = folder.folder2
    f1.invokeFactory(folder_type, id='folder11')
    f1.invokeFactory(folder_type, id='folder12')
    f1.invokeFactory(doc_type, id='doc11')
    f2.invokeFactory(folder_type, id='folder21')
    f2.invokeFactory(folder_type, id='folder22')
    f2.invokeFactory(doc_type, id='doc21')
    f2.invokeFactory(doc_type, id='index_html')
    f22 = f2.folder22
    f22.invokeFactory(folder_type, id='folder221')
    f221 = f22.folder221
    f221.invokeFactory(doc_type, id='doc2211')
    f221.invokeFactory(doc_type, id='doc2212')
    f22.invokeFactory(folder_type, id='folder222')
    f222 = f22.folder222
    f222.invokeFactory(doc_type, id='doc2221')
    f222.invokeFactory(doc_type, id='doc2222')
    f22.invokeFactory(folder_type, id='folder223')
    f223 = f22.folder223
    f223.invokeFactory(doc_type, id='doc2231')
    f223.invokeFactory(doc_type, id='doc2232')

WRAPPER = '__at_is_wrapper_method__'
ORIG_NAME = '__at_original_method_name__'
def isWrapperMethod(meth):
    return getattr(meth, WRAPPER, False)

def wrap_method(klass, name, method, pattern='__at_wrapped_%s__'):
    old_method = getattr(klass, name)
    if isWrapperMethod(old_method):
        log('Wrapping already wrapped method at %s.%s' %
            (klass.__name__, name))
    new_name = pattern % name
    setattr(klass, new_name, old_method)
    setattr(method, ORIG_NAME, new_name)
    setattr(method, WRAPPER, True)
    setattr(klass, name, method)

def unwrap_method(klass, name):
    old_method = getattr(klass, name)
    if not isWrapperMethod(old_method):
        raise ValueError, ('Trying to unwrap non-wrapped '
                           'method at %s.%s' % (klass.__name__, name))
    orig_name = getattr(old_method, ORIG_NAME)
    new_method = getattr(klass, orig_name)
    delattr(klass, orig_name)
    setattr(klass, name, new_method)
