from Products.Archetypes.debug import log_exc, log, _default_logger
from Products.Archetypes.interfaces.base import IBaseObject
from Products.Archetypes.interfaces.base import IBaseUnit
from Products.Archetypes.utils import DisplayList
from Products.Archetypes.utils import mapply
from Products.Archetypes.utils import fixSchema
from Products.Archetypes.utils import getRelURL
from Products.Archetypes.utils import getRelPath
from Products.Archetypes.utils import shasattr
from Products.Archetypes.Field import StringField
from Products.Archetypes.Field import TextField
from Products.Archetypes.Field import STRING_TYPES
from Products.Archetypes.Renderer import renderer
from Products.Archetypes.Schema import Schema
from Products.Archetypes.Storage import AttributeStorage
from Products.Archetypes.Widget import IdWidget
from Products.Archetypes.Widget import StringWidget
from Products.Archetypes.Marshall import RFC822Marshaller
from Products.Archetypes.interfaces.field import IFileField
from Products.Archetypes.config import ATTRIBUTE_SECURITY

from AccessControl import ClassSecurityInfo
from AccessControl import Unauthorized
from Acquisition import Implicit
from Acquisition import aq_base
from Acquisition import aq_acquire
from Acquisition import aq_inner
from Acquisition import aq_parent
from Acquisition import ExplicitAcquisitionWrapper
from Acquisition import Explicit
from Globals import InitializeClass
from OFS.ObjectManager import ObjectManager
from Products.CMFCore  import CMFCorePermissions
from Products.CMFCore.utils import getToolByName
from Products.CMFCore.utils import _checkPermission as checkPerm
from ZODB.POSException import ConflictError
from ComputedAttribute import ComputedAttribute

from Referenceable import Referenceable
from types import TupleType, ListType, UnicodeType

from ZPublisher import xmlrpc

_marker = []

class AttributeValidator(Implicit):
    """ (Ab)Use the security policy implementation

    This class will be used to protect attributes managed by
    AttributeStorage with the same permission as the accessor method.

    It does so by abusing a feature of the security policy
    implementation that the
    '__allow_access_to_unprotected_subobjects__' attribute can be (0,
    1) or a dictionary of {name: 0|1} or a callable instance taking
    'name' and 'value' arguments.

    The said attribute is accessed through getattr(), so by
    subclassing from Implicit we get the accessed object as our
    aq_parent.

    Next step is to check if the name is indeed a field name, and if
    so, if it's using AttributeStorage, and if so, check the
    read_permission against the object being accessed. All other cases
    return '1' which means allow.
    """

    def __call__(self, name, value):
        context = aq_parent(self)
        schema = context.Schema()
        if not schema.has_key(name):
            return 1
        field = schema[name]
        if not isinstance(field.getStorage(), AttributeStorage):
            return 1
        perm = field.read_permission
        if checkPerm(perm, context):
            return 1
        return 0

content_type = Schema((
    StringField('id',
                required=0, ## Still actually required, but
                            ## the widget will supply the missing value
                            ## on non-submits
                mode="rw",
                accessor="getId",
                mutator="setId",
                default=None,
                widget=IdWidget(
    label="Short Name",
    label_msgid="label_short_name",
    description="Should not contain spaces, underscores or mixed case. "\
    "Short Name is part of the item's web address.",
    description_msgid="help_shortname",
    visible={'view' : 'invisible'},
    i18n_domain="plone"),
                ),

    StringField('title',
                required=1,
                searchable=1,
                default='',
                accessor='Title',
                widget=StringWidget(
    label_msgid="label_title",
    visible={'view' : 'invisible'},
    i18n_domain="plone"),
                )),

    marshall = RFC822Marshaller()
                      )

class BaseObject(Referenceable):

    security = ClassSecurityInfo()

    # Protect AttributeStorage-based attributes. See the docstring of
    # AttributeValidator for the low-down.
    if ATTRIBUTE_SECURITY:
        attr_security = AttributeValidator()
        security.setDefaultAccess(attr_security)
        # Delete so it cannot be accessed anymore.
        del attr_security

    schema = type = content_type
    _signature = None

    installMode = ['type', 'actions', 'indexes']

    typeDescMsgId = ''
    typeDescription = ''
    _at_rename_after_creation = False # rename object according to title?

    __implements__ = (IBaseObject, ) + Referenceable.__implements__

    def __init__(self, oid, **kwargs):
        self.id = oid

    security.declareProtected(CMFCorePermissions.ModifyPortalContent,
                              'initializeArchetype')
    def initializeArchetype(self, **kwargs):
        """called by the generated addXXX factory in types tool
        """
        try:
            self.initializeLayers()
            self.markCreationFlag()
            self.setDefaults()
            if kwargs:
                self.edit(**kwargs)
            self._signature = self.Schema().signature()
        except ConflictError:
            raise
        except:
            log_exc()
            #_default_logger.log_exc()
            #raise

    security.declarePrivate('manage_afterAdd')
    def manage_afterAdd(self, item, container):
        __traceback_info__ = (self, item, container)
        Referenceable.manage_afterAdd(self, item, container)
        self.initializeLayers(item, container)

    security.declarePrivate('manage_afterClone')
    def manage_afterClone(self, item):
        __traceback_info__ = (self, item)
        Referenceable.manage_afterClone(self, item)

    security.declarePrivate('manage_beforeDelete')
    def manage_beforeDelete(self, item, container):
        __traceback_info__ = (self, item, container)
        self.cleanupLayers(item, container)
        Referenceable.manage_beforeDelete(self, item, container)

    security.declarePrivate('initializeLayers')
    def initializeLayers(self, item=None, container=None):
        self.Schema().initializeLayers(self, item, container)

    security.declarePrivate('cleanupLayers')
    def cleanupLayers(self, item=None, container=None):
        self.Schema().cleanupLayers(self, item, container)

    security.declareProtected(CMFCorePermissions.View, 'title_or_id')
    def title_or_id(self):
        """Utility that returns the title if it is not blank and the id otherwise.
        """
        if shasattr(self, 'Title'):
            if callable(self.Title):
                return self.Title() or self.getId()

        return self.getId()

    security.declareProtected(CMFCorePermissions.View, 'getId')
    def getId(self):
        """get the object id
        """
        return self.id

    security.declareProtected(CMFCorePermissions.ModifyPortalContent,
                              'setId')
    def setId(self, value):
        """set the object id
        """
        if value != self.getId():
            parent = aq_parent(aq_inner(self))
            if parent is not None:
                self._v_cp_refs = 1 # See Referenceable, keep refs on
                                    # what is a move/rename
                parent.manage_renameObject(
                    self.id, value,
                    )
            self._setId(value)

    security.declareProtected(CMFCorePermissions.View, 'Type')
    def Type(self):
        """Dublin Core element - Object type

        this method is redefined in ExtensibleMetadata but we need this
        at the object level (i.e. with or without metadata) to interact
        with the uid catalog
        """
        if shasattr(self, 'getTypeInfo'):
            ti = self.getTypeInfo()
            if ti is not None:
                return ti.Title()
        return self.meta_type

    security.declareProtected(CMFCorePermissions.View, 'getField')
    def getField(self, key, wrapped=False):
        """Return a field object
        """
        return self.Schema().get(key)

    security.declareProtected(CMFCorePermissions.View, 'getWrappedField')
    def getWrappedField(self, key):
        """Get a field by id which is explicitly wrapped

        XXX Maybe we should subclass field from Acquisition.Explicit?
        """
        return ExplicitAcquisitionWrapper(self.getField(key), self)

    security.declareProtected(CMFCorePermissions.View, 'getDefault')
    def getDefault(self, field):
        """Return the default value of a field
        """
        field = self.getField(field)
        return field.getDefault(self)

    security.declareProtected(CMFCorePermissions.View, 'isBinary')
    def isBinary(self, key):
        """Return wether a field contains binary data
        """
        element = getattr(self, key, None)
        if element and shasattr(element, 'isBinary'):
            return element.isBinary()
        mimetype = self.getContentType(key)
        if mimetype and shasattr(mimetype, 'binary'):
            return mimetype.binary
        elif mimetype and mimetype.find('text') >= 0:
            return 0
        return 1

    security.declareProtected(CMFCorePermissions.View, 'isTransformable')
    def isTransformable(self, name):
        """Returns wether a field is transformable
        """
        field = self.getField(name)
        return isinstance(field, TextField) or not self.isBinary(name)

    security.declareProtected(CMFCorePermissions.View, 'widget')
    def widget(self, field_name, mode="view", field=None, **kwargs):
        """Returns the rendered widget
        """
        if field is None:
            field = self.Schema()[field_name]
        widget = field.widget
        return renderer.render(field_name, mode, widget, self, field=field,
                               **kwargs)

    security.declareProtected(CMFCorePermissions.View, 'getFilename')
    def getFilename(self, key=None):
        """Returns the filename from a field.
        """
        value = None

        if key is None:
            field = self.getPrimaryField()
        else:
            field = self.getField(key) or getattr(self, key, None)

        if field and shasattr(field, 'getFilename'):
            return field.getFilename(self)

        return value

    security.declareProtected(CMFCorePermissions.View, 'getContentType')
    def getContentType(self, key=None):
        """Returns the content type from a field.
        """
        value = 'text/plain'

        if key is None:
            field = self.getPrimaryField()
        else:
            field = self.getField(key) or getattr(self, key, None)

        if field and shasattr(field, 'getContentType'):
            return field.getContentType(self)

        return value

    # Backward compatibility
    security.declareProtected(CMFCorePermissions.View, 'content_type')
    content_type = ComputedAttribute(getContentType, 1)

    # XXX Where's get_content_type comes from??? There's no trace at both
    # Zope and CMF. It should be removed ASAP!
    security.declareProtected(CMFCorePermissions.View, 'get_content_type')
    get_content_type = getContentType

    security.declareProtected(CMFCorePermissions.ModifyPortalContent,
                              'setContentType')
    def setContentType(self, value, key=None):
        """Sets the content type of a field.
        """
        if key is None:
            field = self.getPrimaryField()
        else:
            field = self.getField(key) or getattr(self, key, None)

        if field and IFileField.isImplementedBy(field):
            field.setContentType(self, value)

    security.declareProtected(CMFCorePermissions.ModifyPortalContent,
                              'setFilename')
    def setFilename(self, value, key=None):
        """Sets the filename of a field.
        """
        if key is None:
            field = self.getPrimaryField()
        else:
            field = self.getField(key) or getattr(self, key, None)

        if field and IFileField.isImplementedBy(field):
            field.setFilename(self, value)

    security.declareProtected(CMFCorePermissions.View, 'getPrimaryField')
    def getPrimaryField(self):
        """The primary field is some object that responds to
        PUT/manage_FTPget events.
        """
        fields = self.Schema().filterFields(primary=1)
        if fields:
            return fields[0]
        return None

    security.declareProtected(CMFCorePermissions.View, 'get_portal_metadata')
    def get_portal_metadata(self, field):
        """Returns the portal_metadata for a field
        """
        pmt = getToolByName(self, 'portal_metadata')
        policy = None
        try:
            spec = pmt.getElementSpec(field.accessor)
            policy = spec.getPolicy(self.portal_type)
        except ConflictError:
            raise
        except:
            log_exc()
            return None, 0

        if not policy:
            policy = spec.getPolicy(None)

        return DisplayList(map(lambda x: (x,x), policy.allowedVocabulary())), \
               policy.enforceVocabulary()

    security.declareProtected(CMFCorePermissions.View, 'Vocabulary')
    def Vocabulary(self, key):
        """Returns the vocabulary for a specified field
        """
        vocab, enforce = None, 0
        field = self.getField(key)
        if field:
            if field.isMetadata:
                vocab, enforce = self.get_portal_metadata(field)

            if vocab is None:
                vocab, enforce = field.Vocabulary(self), \
                                 field.enforceVocabulary

        if vocab is None:
            vocab = DisplayList()

        return vocab, enforce

    def __getitem__(self, key):
        """Play nice with externaleditor again
        """
        # don't allow key access to hidden attributes
        if key.startswith('_'):
            raise Unauthorized, key

        schema = self.Schema()
        keys = schema.keys()

        if key not in keys and not key.startswith('_'):
            # XXX fix this in AT 1.4
            value= getattr(aq_inner(self).aq_explicit, key, _marker) or \
                   getattr(aq_parent(aq_inner(self)).aq_explicit, key, _marker)
            if value is _marker:
                raise KeyError, key
            else:
                return value

        field = schema[key]
        accessor = field.getEditAccessor(self)
        if not accessor:
            accessor = field.getAccessor(self)

        # This is the access mode used by external editor. We need the
        # handling provided by BaseUnit when its available
        kw = {'raw':1, 'field': field.__name__}
        value = mapply(accessor, **kw)

        return value


    security.declarePrivate('setDefaults')
    def setDefaults(self):
        """Set field values to the default values
        """
        self.Schema().setDefaults(self)

    security.declareProtected(CMFCorePermissions.ModifyPortalContent, 'edit')
    def edit(self, **kwargs):
        """Alias for update()
        """
        self.update(**kwargs)

    security.declareProtected(CMFCorePermissions.ModifyPortalContent, 'update')
    def update(self, **kwargs):
        """Change the values of the field and reindex the object
        """
        self.Schema().updateAll(self, **kwargs)
        self._p_changed = 1
        self.reindexObject()

    security.declareProtected(CMFCorePermissions.View,
                              'validate_field')
    def validate_field(self, name, value, errors):
        """
        write a method: validate_foo(new_value) -> "error" or None
        If there is a validate method defined for a given field invoke
        it by name
        name -- the name to register errors under
        value -- the proposed new value
        errors -- dict to record errors in
        """

        methodName = "validate_%s" % name
        result = None

        if shasattr(self, methodName):
            method = getattr(self, methodName)
            result = method(value)
            if result is not None:
                errors[name] = result
        return result

    ## Pre/post validate hooks that will need to write errors
    ## into the errors dict directly using errors[fieldname] = ""
    security.declareProtected(CMFCorePermissions.View, 'pre_validate')
    def pre_validate(self, REQUEST=None, errors=None):
        pass

    security.declareProtected(CMFCorePermissions.View, 'post_validate')
    def post_validate(self, REQUEST=None, errors=None):
        pass

    security.declareProtected(CMFCorePermissions.View, 'validate')
    def validate(self, REQUEST=None, errors=None, data=None, metadata=None):
        """Validates the form data from the request
        """
        if errors is None:
            errors = {}

        self.pre_validate(REQUEST, errors)
        if errors:
            return errors

        self.Schema().validate(instance=self, REQUEST=REQUEST,
                               errors=errors, data=data, metadata=metadata)

        self.post_validate(REQUEST, errors)

        return errors

    security.declareProtected(CMFCorePermissions.View, 'SearchableText')
    def SearchableText(self):
        """All fields marked as 'searchable' are concatenated together
        here for indexing purpose"""
        data = []
        charset = self.getCharset()
        for field in self.Schema().fields():
            if not field.searchable:
                continue
            method = field.getAccessor(self)
            try:
                datum =  method(mimetype="text/plain")
            except TypeError:
                # retry in case typeerror was raised because accessor doesn't
                # handle the mimetype argument
                try:
                    datum =  method()
                except ConflictError:
                    raise
                except:
                    continue

            if datum:
                type_datum = type(datum)
                vocab = field.Vocabulary(self)
                if type_datum is ListType or type_datum is TupleType:
                    # Unmangle vocabulary: we index key AND value
                    vocab_values = map(lambda value, vocab=vocab: vocab.getValue(value, ''), datum)
                    datum = list(datum)
                    datum.extend(vocab_values)
                    datum = ' '.join(datum)
                elif type_datum in STRING_TYPES:
                    if type_datum is UnicodeType:
                        datum = datum.encode(charset)
                    datum = "%s %s" % (datum, vocab.getValue(datum, ''), )

                # FIXME: we really need an unicode policy !
                type_datum = type(datum)
                if type_datum is UnicodeType:
                    datum = datum.encode(charset)
                data.append(str(datum))

        data = ' '.join(data)
        return data

    security.declareProtected(CMFCorePermissions.View, 'getCharset')
    def getCharset(self):
        """ Return site default charset, or utf-8
        """
        properties = getToolByName(self, 'portal_properties', None)
        if properties is not None:
            site_properties = getattr(properties, 'site_properties', None)
            if site_properties is not None:
                return site_properties.getProperty('default_charset')

        return 'utf-8'

    security.declareProtected(CMFCorePermissions.View, 'get_size')
    def get_size( self ):
        """ Used for FTP and apparently the ZMI now too """
        size = 0
        for field in self.Schema().fields():
            size+=field.get_size(self)
        return size

    security.declarePrivate('_processForm')
    def _processForm(self, data=1, metadata=None, REQUEST=None, values=None):
        request = REQUEST or self.REQUEST
        if values:
            form = values
        else:
            form = request.form
        fieldset = form.get('fieldset', None)
        schema = self.Schema()
        schemata = self.Schemata()
        fields = []

        if fieldset is not None:
            fields = schemata[fieldset].fields()
        else:
            if data: fields += schema.filterFields(isMetadata=0)
            if metadata: fields += schema.filterFields(isMetadata=1)

        form_keys = form.keys()

        for field in fields:
            ## Delegate to the widget for processing of the form
            ## element.  This means that if the widget needs _n_
            ## fields under a naming convention it can handle this
            ## internally.  The calling API is process_form(instance,
            ## field, form) where instance should rarely be needed,
            ## field is the field object and form is the dict. of
            ## kv_pairs from the REQUEST
            ##
            ## The product of the widgets processing should be:
            ##   (value, **kwargs) which will be passed to the mutator
            ##   or None which will simply pass

            if not field.writeable(self):
                # If the field has no 'w' in mode, or the user doesn't
                # have the required permission, or the mutator doesn't
                # exist just bail out.
                continue

            widget = field.widget
            result = widget.process_form(self, field, form,
                                         empty_marker=_marker)
            if result is _marker or result is None: continue

            # Set things by calling the mutator
            mutator = field.getMutator(self)
            __traceback_info__ = (self, field, mutator)
            result[1]['field'] = field.__name__
            mapply(mutator, result[0], **result[1])

        self.reindexObject()

    security.declareProtected(CMFCorePermissions.ModifyPortalContent,
                              'processForm')
    def processForm(self, data=1, metadata=0, REQUEST=None, values=None):
        """Process the schema looking for data in the form"""
        is_new_object = self.checkCreationFlag()

        self._processForm(data=data, metadata=metadata,
                          REQUEST=REQUEST, values=values)

        self.unmarkCreationFlag()
        if self._at_rename_after_creation and is_new_object:
            self._renameAfterCreation(check_auto_id=True)

    security.declareProtected(CMFCorePermissions.ModifyPortalContent,
                              'markCreationFlag')
    def markCreationFlag(self):
        """Sets flag on the instance to indicate that the object hasn't been
        saved properly (unset in content_edit); this will only be done if a REQUEST
        is present to ensure that objects created programmatically are considered 
        fully created.
        """
        if shasattr(self, 'REQUEST'):
            self._at_creation_flag = True

    security.declareProtected(CMFCorePermissions.ModifyPortalContent,
                              'unmarkCreationFlag')
    def unmarkCreationFlag(self):
        """Remove creation flag
        """
        if shasattr(aq_inner(self), '_at_creation_flag'):
            self._at_creation_flag = False
        post_create = getattr(self, 'at_post_create_script', None)
        if post_create is not None:
            try:
                post_create()
            except TypeError:
                log("unmarkCreationFlag: at_post_create_script not callable")
                pass

    security.declareProtected(CMFCorePermissions.ModifyPortalContent,
                              'checkCreationFlag')
    def checkCreationFlag(self):
        """returns True if the object has been fully saved, False otherwise
        """
        return getattr(aq_base(self), '_at_creation_flag', False)
  
    def _renameAfterCreation(self, check_auto_id=False):
        """Renames an object like its normalized title
        """
        plone_tool = getToolByName(self, 'plone_utils', None)
        if plone_tool is None or not shasattr(plone_tool, 'normalizeString'):
            # plone tool is not available or too old
            # XXX log?
            return None
        
        title = self.Title()
        if not title:
            # Can't work w/o a title
            return False
        
        old_id = self.getId()
        if check_auto_id and not self._isIDAutoGenerated(old_id):
            # no auto generated id
            return False
        
        new_id = plone_tool.normalizeString(title)
        invalid_id = False
        check_id = getattr(self, 'check_id', None)
        if check_id is not None:
            invalid_id = check_id(new_id, required=1) #, alternative_id=old_id)
        else:
            # If check_id is not available just look for conflicting ids
            parent = aq_parent(aq_inner(self))
            invalid_id = new_id in parent.objectIds()

        if not invalid_id:
            # Can't rename without a subtransaction commit when using
            # portal_factory!
            get_transaction().commit(1)
            self.setId(new_id)
            return new_id
        
        return False
 
    def _isIDAutoGenerated(self, id):
        """Avoid busting setDefaults if we don't have a proper acquisition context
        """
        plone_tool = getToolByName(self, 'plone_utils', None)
        if plone_tool is not None and shasattr(plone_tool,
                                                        'isIDAutoGenerated'):
            return plone_tool.isIDAutoGenerated(id)
        # Plone 2.0 compatibility
        script = getattr(self, 'isIDAutoGenerated', None)
        if script is not None:
            return script(id)
        return False


    security.declareProtected(CMFCorePermissions.View, 'Schemata')
    def Schemata(self):
        """Returns the Schemata for the Object
        """
        from Products.Archetypes.Schema import getSchemata
        return getSchemata(self)

    security.declarePrivate('_isSchemaCurrent')
    def _isSchemaCurrent(self):
        """Determine whether the current object's schema is up to date."""
        from Products.Archetypes.ArchetypeTool import getType, _guessPackage
        package = _guessPackage(self.__module__)
        return getType(self.meta_type, package)['signature'] == self._signature


    security.declarePrivate('_updateSchema')
    def _updateSchema(self, excluded_fields=[], out=None):
        """Update an object's schema when the class schema changes.

        For each field we use the existing accessor to get its value,
        then we re-initialize the class, then use the new schema
        mutator for each field to set the values again.

        We also copy over any class methods to handle product
        refreshes gracefully (when a product refreshes, you end up
        with both the old version of the class and the new in memory
        at the same time -- you really should restart zope after doing
        a schema update).
        """
        from Products.Archetypes.ArchetypeTool import getType, _guessPackage
        import sys

        if out:
            print >> out, 'Updating %s' % (self.getId())

        package = _guessPackage(self.__module__)
        new_schema = getType(self.meta_type, package)['schema']

        # read all the old values into a dict
        values = {}
        for f in new_schema.fields():
            name = f.getName()
            if name in excluded_fields: continue
            if f.type == "reference": continue
            try:
                values[name] = self._migrateGetValue(name, new_schema)
            except ValueError:
                if out != None:
                    print >> out, ('Unable to get %s.%s'
                                   % (str(self.getId()), name))

        obj_class = self.__class__
        current_class = getattr(sys.modules[self.__module__],
                                self.__class__.__name__)
        if obj_class.schema != current_class.schema:
            # XXX This is kind of brutish.  We do this to make sure that old
            # class instances have the proper methods after a refresh.  The
            # best thing to do is to restart Zope after doing an update, and
            # the old versions of the class will disappear.

            for k in current_class.__dict__.keys():
                obj_class.__dict__[k] = current_class.__dict__[k]


        # replace the schema
        self.schema = new_schema.copy()
        self.initializeArchetype()

        for f in new_schema.fields():
            name = f.getName()
            kw = {}
            if name not in excluded_fields and values.has_key(name):
                # XXX commented out because we are trying to directly use
                # the new base unit
                # kw['mimetype'] = f.getContentType(self)
                try:
                    self._migrateSetValue(name, values[name], **kw)
                except ValueError:
                    if out != None:
                        print >> out, ('Unable to set %s.%s to '
                                       '%s' % (str(self.getId()),
                                               name, str(values[name])))

        self._p_changed = 1 # make sure the changes are persisted

        if out:
            return out


    security.declarePrivate('_migrateGetValue')
    def _migrateGetValue(self, name, new_schema=None):
        """Try to get a value from an object using a variety of methods."""
        schema = self.Schema()

        # Migrate pre-AT 1.3 schemas.
        schema = fixSchema(schema)

        # First see if the new field name is managed by the current schema
        field = schema.get(getattr(new_schema.get(name,None),'old_field_name',name), None)
        if field:
            # at very first try to use the BaseUnit itself
            try:
                if IFileField.isImplementedBy(field):
                    return field.getBaseUnit(self)
            except ConflictError:
                raise
            except:
                pass
            # first try the edit accessor
            try:
                editAccessor = field.getEditAccessor(self)
                if editAccessor:
                    return editAccessor()
            except ConflictError:
                raise
            except:
                pass
            # no luck -- now try the accessor
            try:
                accessor = field.getAccessor(self)
                if accessor:
                    return accessor()
            except ConflictError:
                raise
            except:
                pass
            #no luck use standard method to get the value 
            return field.get(self)

            # still no luck -- try to get the value directly
            # this part should be remove because for some fields this will fail
            # if you get the value directly for example for FixPointField
            # stored value is (0,0) but the input value is a string.
            # at this time FixPointField fails if he got a tuple as input value
            #because of this line value = value.replace(',','.')
            try:
                return self[field.getName()]
            except ConflictError:
                raise
            except:
                pass

        # Nope -- see if the new accessor method is present
        # in the current object.
        if new_schema:
            new_field = new_schema.get(name)
            # try the new edit accessor
            try:
                editAccessor = new_field.getEditAccessor(self)
                if editAccessor:
                    return editAccessor()
            except ConflictError:
                raise
            except:
                pass

            # nope -- now try the accessor
            try:
                accessor = new_field.getAccessor(self)
                if accessor:
                    return accessor()
            except ConflictError:
                raise
            except:
                pass
            # still no luck -- try to get the value directly using the new name
            try:
                return self[new_field.getName()]
            except ConflictError:
                raise
            except:
                pass

        # Nope -- now see if the current object has an attribute
        # with the same name
        # as the new field
        if shasattr(self, name):
            return getattr(self, name)

        raise ValueError, 'name = %s' % (name)


    security.declarePrivate('_migrateSetValue')
    def _migrateSetValue(self, name, value, old_schema=None, **kw):
        """Try to set an object value using a variety of methods."""
        schema = self.Schema()

        # Migrate pre-AT 1.3 schemas.
        schema = fixSchema(schema)

        field = schema.get(name, None)
        # try using the field's mutator
        if field:
            mutator = field.getMutator(self)
            if mutator is not None:
                try:
                    args = [value,]
                    mapply(mutator, *args, **kw)
                    return
                except ConflictError:
                    raise
                except:
                    log_exc()
        else:
            # try setting an existing attribute
            if shasattr(self, name):
                setattr(self, name, value)
                return
        raise ValueError, 'name = %s, value = %s' % (name, value)

    security.declareProtected(CMFCorePermissions.View, 'isTemporary')
    def isTemporary(self):
        """Check to see if we are created as temporary object by portal factory"""
        parent = aq_parent(aq_inner(self))
        return shasattr(parent, 'meta_type') and parent.meta_type == 'TempFolder'

    def getFolderWhenPortalFactory(self):
        """Return the folder where this object was created temporarily
        """
        ctx = aq_inner(self)
        if not ctx.isTemporary():
            # not a temporary object!
            return aq_parent(ctx)
        utool = getToolByName(self, 'portal_url')
        portal_object = utool.getPortalObject()

        while ctx.getId() != 'portal_factory':
            # find the portal factory object
            if ctx == portal_object:
                # uups, shouldn't happen!
                return ctx
            ctx = aq_parent(ctx)
        # ctx is now the portal_factory in our parent folder
        return aq_parent(ctx)


    # subobject access ########################################################
    #
    # some temporary objects could be set by fields (for instance additional
    # images that may result from the transformation of a pdf field to html)
    #
    # those objects are specific to a session

    security.declareProtected(CMFCorePermissions.ModifyPortalContent,
                              'addSubObjects')
    def addSubObjects(self, objects, REQUEST=None):
        """add a dictionary of objects to a volatile attribute
        """
        if objects:
            storage = getattr(aq_base(self), '_v_at_subobjects', None)
            if storage is None:
                setattr(self, '_v_at_subobjects', {})
                storage = getattr(aq_base(self), '_v_at_subobjects')
            for name, obj in objects.items():
                storage[name] = aq_base(obj)

    security.declareProtected(CMFCorePermissions.View, 'getSubObject')
    def getSubObject(self, name, REQUEST, RESPONSE=None):
        """Get a dictionary of objects from a volatile attribute
        """
        storage = getattr(aq_base(self), '_v_at_subobjects', None)
        if storage is None:
            return None

        data = storage.get(name, None)
        if data is None:
            return None

        mtr = self.mimetypes_registry
        mt = mtr.classify(data, filename=name)
        return Wrapper(data, name, str(mt) or 'application/octet').__of__(self)

    def __bobo_traverse__(self, REQUEST, name, RESPONSE=None):
        """ transparent access to session subobjects
        """
        # is it a registered sub object
        data = self.getSubObject(name, REQUEST, RESPONSE)
        if data is not None:
            return data
        # or a standard attribute (maybe acquired...)
        target = None
        method = REQUEST.get('REQUEST_METHOD', 'GET').upper()
        # logic from "ZPublisher.BaseRequest.BaseRequest.traverse"
        # to check whether this is a browser request
        if (len(REQUEST.get('TraversalRequestNameStack', ())) == 0 and
            not (method in ('GET', 'POST') and not
                 isinstance(RESPONSE, xmlrpc.Response))):
            if shasattr(self, name):
                target = getattr(self, name)
        else:
            # we are allowed to acquire
            target = getattr(self, name, None)
        if target is not None:
            return target
        if (method in ('PUT', 'MKCOL') and not
            isinstance(RESPONSE, xmlrpc.Response)):
            from webdav.NullResource import NullResource
            return NullResource(self, name, REQUEST).__of__(self)

        # Nothing has been found. Raise an AttributeError and be done with it.
        raise AttributeError(name)

InitializeClass(BaseObject)

class Wrapper(Explicit):
    """wrapper object for access to sub objects """
    __allow_access_to_unprotected_subobjects__ = 1

    def __init__(self, data, filename, mimetype):
        self._data = data
        self._filename = filename
        self._mimetype = mimetype

    def __call__(self, REQUEST=None, RESPONSE=None):
        if RESPONSE is None:
            RESPONSE = REQUEST.RESPONSE
        if RESPONSE is not None:
            mt = self._mimetype
            name =self._filename
            RESPONSE.setHeader('Content-type', str(mt))
            RESPONSE.setHeader('Content-Disposition',
                               'inline;filename=%s' % name)
            RESPONSE.setHeader('Content-Length', len(self._data))
        return self._data

MinimalSchema = BaseObject.schema

__all__ = ('BaseObject', 'MinimalSchema', )
