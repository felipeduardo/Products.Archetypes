from AccessControl import ClassSecurityInfo
from Acquisition import Explicit
from Globals import InitializeClass
from OFS.Image import File
from OFS.ObjectManager import ObjectManager, REPLACEABLE
from Products.CMFCore import CMFCorePermissions
from Products.CMFCore.utils import getToolByName
from Products.transform import transformer, registry
from Products.transform.interfaces import idatastream
from Products.transform.sourceAdapter import sourceAdapter
from StringIO import StringIO
from content_driver import getDefaultPlugin, lookupContentType, getConverter
from content_driver import selectPlugin, lookupContentType
from debug import log, log_exc
from interfaces.base import IBaseUnit
from adapters import TransformCache
from types import DictType
from utils import basename
from webdav.WriteLockInterface import WriteLockInterface
import os.path
import re
import urllib

from config import *


class newBaseUnit(File):
    __implements__ = (WriteLockInterface,)

    security = ClassSecurityInfo()

    def __init__(self, name, file='', mime_type=None):
        self.id = name
        self.update(file, mime_type)

    def update(self, data, mimetype=None):
        #Convert from file/str to str/unicode as needed
        data, filename, mimetype = sourceAdapter()(data, mimetype=mimetype)

        self.mimetype = mimetype
        self.raw  = data and str(data) or ''
        self.size = len(data)
        self.filename = filename

        ##force default transform policy, this needs to come out
        str(self)

    def __getitem__(self, key):
        return self.transform(key)

    def transform(self, mt, cache=0):
        """Takes a mimetype so object.foo['text/plain'] should return
        a plain text version of the raw content
        """
        cache = TransformCache(self)
        data = cache.getCache(mt)
        #Do we have a cached transform for this key?
        if data is None:
            data = transformer.convertTo(mt,
                                         self.raw,
                                         usedby=self.id,
                                         mimetype=self.mimetype,
                                         filename=self.filename)

            ## XXX the transform tool should keep the cache policy
            if cache:
                cache.setCache(mt, data)

        if data:
            data = data.getData()
            if type(data) == DictType and data.has_key('html'):
                return data['html']
            return data

        #XXX debug
        mt = registry.lookup(mt)
        if mt and mt[0].binary:
            return self.raw

        return None

    def __str__(self):
        ## XXX make sure default view points to a RFC-2046 name
        data = self.transform('text/html', cache=1)
        if not data:
            data = self.transform('text/plain', cache=1)
        if not data:
            return ''

        if idatastream.isImplementedBy(data):
            data = data.getData()
        if type(data) == DictType and data.has_key('html'):
            return data['html']
        return data

    # Hook needed for catalog
    __call__ = __str__

    def isBinary(self):
        mt = registry.lookup(self.getContentType())
        if not mt: return 1 #if we don't hear otherwise its binary
        return mt[0].binary

    # File handling
    def get_size(self):
        return self.size

    def getRaw(self):
        return self.raw

    def getContentType(self):
        return self.mimetype

    def SearchableText(self):
        return self.transform('text/plain')

    ### index_html
    security.declareProtected(CMFCorePermissions.View, "index_html")
    def index_html(self, REQUEST, RESPONSE):
        """download method"""
        filename = self.filename
        if self.filename:
            RESPONSE.setHeader('Content-Disposition', 'attachment; filename=%s' % self.filename)
        RESPONSE.setHeader('Content-Type', self.getContentType())
        RESPONSE.setHeader('Content-Length', self.get_size())

        RESPONSE.write(self.raw)
        return ''

    ### webDAV me this, webDAV me that
    security.declareProtected( CMFCorePermissions.ModifyPortalContent, 'PUT' )
    def PUT(self, REQUEST, RESPONSE):
        """Handle HTTP PUT requests"""
        self.dav__init(REQUEST, RESPONSE)
        self.dav__simpleifhandler(REQUEST, RESPONSE, refresh=1)
        mime_type=REQUEST.get_header('Content-Type', None)

        file=REQUEST['BODYFILE']
        data = file.read()

        self.update(data, mime_type=mime_type)

        self.aq_parent.reindexObject()
        RESPONSE.setStatus(204)
        return RESPONSE

    def manage_FTPget(self, REQUEST, RESPONSE):
        "Get the raw content for this unit(also used for the WebDAV SRC)"
        RESPONSE.setHeader('Content-Type', self.getContentType())
        RESPONSE.setHeader('Content-Length', self.get_size())

        if type(self.raw) is type(''): return raw

        return ''


class oldBaseUnit(File, ObjectManager):
    """ """
    security = ClassSecurityInfo()
    __replaceable__ = REPLACEABLE
    __implements__ = (WriteLockInterface, IBaseUnit)
    isUnit = 1

    def __init__(self, name, file='', mime_type=None):
        self.id = name
        self.filename = ''
        self.data = ''
        self.size = 0
        self.content_type = None

        self.update(file, mime_type)

    def __str__(self):
        #This should return the default transform for the type,
        #usually HTML. Keep in mind that non-text fields don't
        #get baseunits
        return self.getHTML()

    __call__ = __str__

    def reConvert(self):
        """reconvert an existing field"""
        driver = self.content_type.getConverter()
        self._update_data(self.data, self.content_type, driver)
        self.aq_parent.reindexObject()
        return self.getHTML()

    def update(self, file, mime_type=None):
        if file and (type(file) is not type('')):
            if hasattr(file, 'filename') and file.filename != '':
                self.fullfilename = getattr(file, 'filename')
                self.filename = basename(self.fullfilename)

        driver, mime_type = self._driverFromType(mime_type, file)

        self.content_type = mime_type
        self._update_data(file, mime_type, driver)

    def _driverFromType(self, mime_type, file=None):
        driver = None
        try:
            plugin = selectPlugin(file=file, mime_type=mime_type)
            mime_type = str(plugin)
            driver    = plugin.getConverter()
        except:
            log_exc()
            plugin = lookupContentType('text/plain')
            mime_type = str(plugin)
            driver    = plugin.getConverter()

        return driver, mime_type


    def _update_data(self, file, content_type, driver):
        # This will populate its first arg with
        # .html .text and whatever else it needs to
        # satisfy the interface
        if file and (type(file) is not type('')):
            if hasattr(file, 'read'):
                contents = file.read()
                if contents:
                    self.data = contents
                file.seek(0)
                self.size = len(self.data)
        else:
            self.data = file
            self.size = 0

        driver.convertData(self, self.data)
        if hasattr(driver, 'fixSubObjects'):
            driver.fixSubObjects("%s/" % self.id, self)

        self._p_changed = 1

    security.declarePublic('getContentType')
    def getContentType(self):
        """The content type of the unit"""
        if not self.content_type:
            self.content_type = getDefaultPlugin().getMimeType()
        elif type(self.content_type) != type(''): #Fix source of this
            self.content_type = self.content_type.getMimeType()
        return self.content_type

    def getContentObject(self):
        return lookupContentType(self.getContentType())

    security.declareProtected(CMFCorePermissions.View, 'isBinary')
    def isBinary(self):
        """Is the content displable as text"""
        return self.getContentObject().isBinary()

    security.declareProtected(CMFCorePermissions.View, "index_html")
    def index_html(self, REQUEST, RESPONSE):
        """download method"""
        RESPONSE.setHeader('Content-Disposition', 'attachment; filename=%s' % self.Filename())
        RESPONSE.setHeader('Content-Type', self.getContentType())
        RESPONSE.setHeader('Content-Length', self.get_size())
        return File.index_html(self, REQUEST, RESPONSE)

    security.declarePublic('Filename')
    def Filename(self):
        return getattr(self, 'filename', '')

    security.declareProtected(CMFCorePermissions.View, 'getHTML')
    def getHTML(self):
        """The HTML version of the Unit"""
        return self.html

    security.declareProtected(CMFCorePermissions.View, 'getRaw')
    def getRaw(self):
        """Raw Unaltered Content"""
        return self.data

    security.declareProtected(CMFCorePermissions.View, 'getText')
    def getText(self):
        """Strip HTML"""
        ##Strip entities too?
        text = re.sub('<[^>]*>(?i)(?m)', '', self.getHTML())
        return urllib.unquote(re.sub('\n+', '\n', text)).strip()

    #security.declareProtected(CMFCorePermissions.View, 'get_size')
    security.declarePublic("get_size")
    def get_size(self):
        """aprox size of element"""
        return self.size

    security.declarePublic("getIcon")
    def getIcon(self):
        """Icon for the content type"""
        return self.getContentObject().getIcon()

    security.declareProtected(CMFCorePermissions.View, 'SearchableText')
    def SearchableText(self):
        """Indexable text"""
        return self.getText()


    security.declareProtected( CMFCorePermissions.View, 'manage_FTPget' )
    def manage_FTPget(self, REQUEST, RESPONSE):
        "Get the raw content for this unit(also used for the WebDAV SRC)"

        RESPONSE.setHeader('Content-Type', self.getContentType())
        RESPONSE.setHeader('Content-Length', self.get_size())

        data=self.data
        if type(data) is type(''): return data

        while data is not None:
            RESPONSE.write(data.data)
            data=data.next

        return ''

    security.declareProtected( CMFCorePermissions.ModifyPortalContent, 'PUT' )
    def PUT(self, REQUEST, RESPONSE):
        """Handle HTTP PUT requests"""
        self.dav__init(REQUEST, RESPONSE)
        self.dav__simpleifhandler(REQUEST, RESPONSE, refresh=1)
        type=REQUEST.get_header('Content-Type', None)

        file=REQUEST['BODYFILE']
        data = file.read()
        driver, mime_type = self._driverFromType(type, file)
        self._update_data(data, mime_type, driver)
        self.size = len(data)

        self.aq_parent.reindexObject()
        RESPONSE.setStatus(204)
        return RESPONSE

if USE_NEW_BASEUNIT:
    BaseUnit = newBaseUnit
else:
    BaseUnit = oldBaseUnit

InitializeClass(BaseUnit)
