"""
Open Library Plugin.
"""
import web
import simplejson
import os
import re
import urllib
import socket

import infogami
from infogami.utils import types, delegate
from infogami.utils.view import render, public
from infogami.infobase import client, dbstore

try:
    from infogami.plugins.api import code as api
except:
    api = None

# http header extension for OL API
infogami.config.http_ext_header_uri = "http://openlibrary.org/dev/docs/api"

# setup special connection with caching support
import connection
client._connection_types['ol'] = connection.OLConnection
infogami.config.infobase_parameters = dict(type="ol")

types.register_type('^/a/[^/]*$', '/type/author')
types.register_type('^/b/[^/]*$', '/type/edition')

# set up infobase schema. required when running in standalone mode.
import schema
dbstore.default_schema = schema.get_schema()

# this adds /show-marc/xxx page to infogami
import showmarc

# add zip and tuple to the list of public functions
public(zip)
public(tuple)
web.template.Template.globals['NEWLINE'] = "\n"

@infogami.action
def sampledump():
    """Creates a dump of objects from OL database for creating a sample database."""
    def expand_keys(keys):
        def f(k):
            if isinstance(k, dict):
                return web.ctx.site.things(k)
            elif k.endswith('*'):
                return web.ctx.site.things({'key~': k})
            else:
                return [k]
        result = []
        for k in keys:
            d = f(k)
            result += d
        return result
        
    def get_references(data, result=None):
        if result is None:
            result = []
            
        if isinstance(data, dict):
            if 'key' in data:
                result.append(data['key'])
            else:
                get_references(data.values(), result)
        elif isinstance(data, list):
            for v in data:
                get_references(v, result)
        return result
        
    visiting = {}
    visited = set()
    
    def visit(key):
        if key in visited:
            return
        elif key in visiting:
            # This is a case of circular-dependency. Add a stub object to break it.
            print simplejson.dumps({'key': key, 'type': visiting[key]['type']})
            visited.add(key)
            return
        
        thing = web.ctx.site.get(key)
        if not thing:
            return

        d = thing.dict()
        d.pop('permission', None)
        d.pop('child_permission', None)
        d.pop('table_of_contents', None)
        
        visiting[key] = d
        for ref in get_references(d.values()):
            visit(ref)
        visited.add(key)
        
        print simplejson.dumps(d)

    keys = [
        '/', 
        '/recentchanges',
        '/index.*', 
        '/about*', 
        '/dev*', 
        '/css*',
        '/js*',
        '/scan_record',
        '/scanning_center',
        {'type': '/type/template', 'key~': '/templates*'},
        {'type': '/type/macro', 'key~': '/macros*'},
        {'type': '/type/type'}, 
        {'type': '/type/scan_record', 'limit': 10},
    ]
    keys = expand_keys(keys) + ['/b/OL%dM' % i for i in range(1, 100)]
    visited = set()

    for k in keys:
        visit(k)
    
@infogami.action
def sampleload(filename="sampledump.txt.gz"):
    if filename.endswith('.gz'):
        import gzip
        f = gzip.open(filename)
    else:
        f = open(filename)
    
    queries = [simplejson.loads(line) for  line in f]
    print web.ctx.site.save_many(queries)

class addbook(delegate.page):
    def GET(self):
        d = {'type': web.ctx.site.get('/type/edition')}

        i = web.input()
        author = i.get('author') and web.ctx.site.get(i.author)
        if author:
            d['authors'] = [author]
        
        page = web.ctx.site.new("", d)
        return render.edit(page, '/addbook', 'Add Book')
        
    def POST(self):
        from infogami.core.code import edit
        key = web.ctx.site.new_key('/type/edition')
        web.ctx.path = key
        return edit().POST(key)

class addauthor(delegate.page):
    def POST(self):
        i = web.input("name")
        if len(i.name) < 2:
            return web.badrequest()
        key = web.ctx.site.new_key('/type/author')
        web.ctx.path = key
        web.ctx.site.save({'key': key, 'name': i.name, 'type': dict(key='/type/author')}, comment='New Author')
        raise web.HTTPError("200 OK", {}, key)

class clonebook(delegate.page):
    def GET(self):
        from infogami.core.code import edit
        i = web.input("key")
        page = web.ctx.site.get(i.key)
        if page is None:
            raise web.seeother(i.key)
        else:
            d =page._getdata()
            for k in ['isbn_10', 'isbn_13', 'lccn', "oclc"]:
                 d.pop(k, None)
            return render.edit(page, '/addbook', 'Clone Book')

class search(delegate.page):
    path = "/suggest/search"
    
    def GET(self):
        i = web.input(prefix="")
        if len(i.prefix) > 2:
            q = {'type': '/type/author', 'name~': i.prefix + '*', 'sort': 'name', 'limit': 5}
            things = web.ctx.site.things(q)
            things = [web.ctx.site.get(key) for key in things]
        
            result = [dict(type=[{'id': t.key, 'name': t.key}], name=web.utf8(t.name), guid=t.key, id=t.key, article=dict(id=t.key)) for t in things]
        else:
            result = []
        callback = i.pop('callback', None)
        d = dict(status="200 OK", query=dict(i, escape='html'), code='/api/status/ok', result=result)

        if callback:
            data = '%s(%s)' % (callback, simplejson.dumps(d))
        else:
            data = simplejson.dumps(d)
        raise web.HTTPError('200 OK', {}, data)
        
class blurb(delegate.page):
    path = "/suggest/blurb/(.*)"
    def GET(self, path):
        i = web.input()        
        callback = i.pop('callback', None)
        author = web.ctx.site.get('/' +path)
        body = ''
        if author.birth_date or author.death_date:
            body = "%s - %s" % (author.birth_date, author.death_date)
        else:
            body = "%s" % author.date

        body += "<br/>"
        if author.bio:
            body += web.utf8(author.bio)

        result = dict(body=body, media_type="text/html", text_encoding="utf-8")
        d = dict(status="200 OK", code="/api/status/ok", result=result)
        if callback:
            data = '%s(%s)' % (callback, simplejson.dumps(d))
        else:
            data = simplejson.dumps(d)

        raise web.HTTPError('200 OK', {}, data)

class thumbnail(delegate.page):
    path = "/suggest/thumbnail"

@public
def get_property_type(type, name):
    for p in type.properties:
        if p.name == name:
            return p.expected_type
    return web.ctx.site.get("/type/string")

def save(filename, text):
    root = os.path.dirname(__file__)
    path = root + filename
    dir = os.path.dirname(path)
    if not os.path.exists(dir):
        os.makedirs(dir)
    f = open(path, 'w')
    f.write(text)
    f.close()

def change_ext(filename, ext):
    filename, _ = os.path.splitext(filename)
    if ext:
        filename = filename + ext
    return filename

def get_pages(type, processor):
    pages = web.ctx.site.things(dict(type=type))
    for p in pages:
        processor(web.ctx.site.get(p))

def get_templates():
    get_pages('/type/template', lambda page: save(change_ext(page.key,'.html'), page.body))

def get_macros():
    get_pages('/type/macro', lambda page: save(change_ext(page.key, '.html'), page.macro))

def get_i18n():
    from infogami.plugins.i18n.code import unstringify
    def process(page):
        text = "\n".join("%s = %s" % (k, repr(v)) for k, v in unstringify(page.dict()).items())
        save(page.key, text)
    get_pages('/type/i18n', process)

@infogami.action
def pull_templates():
    """Pull templates, macros and i18n strings to checkin them repository."""
    get_templates()
    get_macros()
    get_i18n()

class flipbook(delegate.page):
    path = "/details/([a-zA-Z0-9_-]*)(?:/leaf(\d+))?"

    SCRIPT_PATH = "/petabox/sw/bin/find_item.php"

    def GET(self, identifier, leaf):
        import os

        if os.path.exists(self.SCRIPT_PATH):
            server, path = self.find_location(identifier)
        else:
            server, path = self.find_location_from_archive(identifier)

        if  not server:
            raise web.notfound()
        else:
            title = identifier
            
            params = dict(identifier=identifier, dataserver=server, datapath=path)
            if leaf:
                params['leaf'] = leaf
            url = "http://%s/flipbook/flipbook.php?%s" % (server, urllib.urlencode(params))     
            data = render.flipbook(url, title)
            raise web.HTTPError("200 OK", {}, web.safestr(data))

    def find_location_from_archive(self, identifier):
        """Use archive.org to get the location.
        """
        from xml.dom import minidom

        base_url = "http://www.archive.org/services/find_file.php?loconly=1&file="

        try:
            data= urllib.urlopen(base_url + identifier).read()
            doc = minidom.parseString(data)
            vals = [(e.getAttribute('host'), e.getAttribute('dir')) for e in doc.getElementsByTagName('location')]
            return vals and vals[0]
        except Exception:
            return None, None
            
    def find_location(self, identifier):
        import os
        data = os.popen(self.SCRIPT_PATH + ' ' + identifier).read().strip()
        if ':' in data:
            return data.split(':', 1)
        else:
            return None, None

class bookreader(delegate.page):
    path = "/bookreader/(.*)"

    def GET(self, id):
        data = render.bookreader(id)
        raise web.HTTPError("200 OK", {}, data)

class robotstxt(delegate.page):
    path = "/robots.txt"
    def GET(self):
        web.header('Content-Type', 'text/plain')
        try:
            data = open('static/robots.txt').read()
            raise web.HTTPError("200 OK", {}, data)
        except IOError:
            raise web.notfound()

class change_cover(delegate.mode):
    def GET(self, key):
        page = web.ctx.site.get(key)
        if page is None or page.type.key not in  ['/type/edition', '/type/author']:
            raise web.seeother(key)
        return render.change_cover(page)

class bookpage(delegate.page):
    path = r"/(isbn|oclc|lccn|ISBN|OCLC|LCCN)/([^.]*)"

    def GET(self, key, value):
        key = key.lower()
        if key == "isbn":
            if len(value) == 13:
                key = "isbn_13"
            else:
                key = "isbn_10"
        elif key == "oclc":
            key = "oclc_numbers"

        value = value.replace('_', ' ')

        if web.ctx.encoding and web.ctx.path.endswith("." + web.ctx.encoding): 
            ext = "." + web.ctx.encoding
        else:
            ext = ""

        q = {"type": "/type/edition", key: value}
        try:
            result = web.ctx.site.things(q)
            if result:
                raise web.seeother(result[0] + ext)
            else:
                raise web.notfound()
        except web.HTTPError:
            pass
        except:
            raise web.notfound()

delegate.media_types['application/rdf+xml'] = 'rdf'
class rdf(delegate.mode):
    name = 'view'
    encoding = 'rdf'

    def GET(self, key):
        page = web.ctx.site.get(key)
        if not page:
            raise web.notfound("")
        else:
            from infogami.utils import template
            try:
                result = template.typetemplate('rdf')(page)
            except:
                raise web.notfound("")
            else:
                return delegate.RawText(result, content_type="application/rdf+xml; charset=utf-8")

def can_write():
    user = delegate.context.user and delegate.context.user.key
    usergroup = web.ctx.site.get('/usergroup/api')
    return usergroup and user in [u.key for u in usergroup.members]

class Forbidden(web.HTTPError):
    def __init__(self, msg=""):
        web.HTTPError.__init__(self, "403 Forbidden", {}, msg)

class BadRequest(web.HTTPError):
    def __init__(self, msg=""):
        web.HTTPError.__init__(self, "400 Bad Request", {}, msg)

class new:
    """API to create new author/edition/work/publisher/series.
    """
    def prepare_query(self, query):
        """Add key to query and returns the key.
        If query is a list multiple queries are returned.
        """
        if isinstance(query, list):
            return [self.prepare_query(q) for q in query]
        else:
            type = query['type']
            if isinstance(type, dict):
                type = type['key']
            query['key'] = web.ctx.site.new_key(type)
            return query['key']
            
    def verify_types(self, query):
        if isinstance(query, list):
            for q in query:
                self.verify_types(q)
        else:
            if 'type' not in query:
                raise BadRequest("Missing type")
            type = query['type']
            if isinstance(type, dict):
                if 'key' not in type:
                    raise BadRequest("Bad Type: " + simplejson.dumps(type))
                type = type['key']
                
            if type not in ['/type/author', '/type/edition', '/type/work', '/type/series', '/type/publisher']:
                raise BadRequest("Bad Type: " + simplejson.dumps(type))
 
    def POST(self):
        if not can_write():
            raise Forbidden("Permission Denied.")
            
        try:
            query = simplejson.loads(web.data())
            h = api.get_custom_headers()
            comment = h.get('comment')
            action = h.get('action')
        except Exception, e:
            raise BadRequest(str(e))
            
        self.verify_types(query)
        keys = self.prepare_query(query)
        
        try:
            if not isinstance(query, list):
                query = [query]
            web.ctx.site.save_many(query, comment=comment, action=action)
        except client.ClientException, e:
            raise BadRequest(str(e))
        return simplejson.dumps(keys)
        
api and api.add_hook('new', new)

def readable_url_processor(handler):
    patterns = [
        (r'/b/OL\d+M', '/type/edition', 'title'),
        (r'/a/OL\d+A', '/type/author', 'name'),
        (r'/w/OL\d+W', '/type/work', 'title'),
        (r'/s/OL\d+S', '/type/series', 'title'),
    ]
    def get_readable_path():
        path = get_real_path()
        if web.ctx.get('encoding') is not None:
            return web.ctx.path
        
        for pat, type, property in patterns:
            if web.re_compile('^' + pat + '$').match(path):
                thing = web.ctx.site.get(path)
                if thing is not None and thing.type.key == type and thing[property]:
                    title = thing[property].replace(' ', '-').encode('utf-8')
                    return path + '/' + urllib.quote(title)
        return web.ctx.path
    
    def get_real_path():
        pat = '^(' + '|'.join(p[0] for p in patterns) + ')(?:/.*)?'
        rx = web.re_compile(pat)
        m = rx.match(web.ctx.path)
        if m:
            path = m.group(1)
            return m.group(1)
        else:
            return web.ctx.path
            
    readable_path = get_readable_path()

    #@@ web.ctx.path is either quoted or unquoted depends on whether the application is running
    #@@ using builtin-server or lighttpd. Thats probably a bug in web.py. 
    #@@ take care of that case here till that is fixed.
    # @@ Also, the redirection must be done only for GET requests.
    if readable_path != web.ctx.path and readable_path != urllib.quote(web.utf8(web.ctx.path)) and web.ctx.method == "GET":
        raise web.seeother(readable_path + web.ctx.query.encode('utf-8'))

    web.ctx.readable_path = readable_path
    web.ctx.path = get_real_path()
    web.ctx.fullpath = web.ctx.path + web.ctx.query
    return handler()

@public
def changequery(query=None, **kw):
    if query is None:
        query = web.input(_method='get', _unicode=False)
    for k, v in kw.iteritems():
        if v is None:
            query.pop(k, None)
        else:
            query[k] = v

    query = dict((k, web.safestr(v)) for k, v in query.items())
    out = web.ctx.readable_path
    if query:
        out += '?' + urllib.urlencode(query)
    return out

# Hack to limit recent changes offset.
# Large offsets are blowing up the database.

from infogami.core.db import get_recent_changes as _get_recentchanges
@public
def get_recent_changes(*a, **kw):
    if 'offset' in kw and kw['offset'] > 5000:
        return []
    else:
        return _get_recentchanges(*a, **kw)
    
def wget(url):
    try:
        return urllib.urlopen(url).read()
    except:
        return ""
    
@public
def get_cover_id(key):
    try:
        _, cat, oln = key.split('/')
        return simplejson.loads(wget('http://covers.openlibrary.org/%s/query?olid=%s&limit=1' % (cat, oln)))[0]
    except (ValueError, IndexError, TypeError):
        return None

local_ip = None
class invalidate(delegate.page):
    path = "/system/invalidate"
    def POST(self):
        global local_ip
        if local_ip is None:
            local_ip = socket.gethostbyname(socket.gethostname())

        if web.ctx.ip != "127.0.0.1" and web.ctx.ip.rsplit(".", 1)[0] != local_ip.rsplit(".", 1)[0]:
            raise Forbidden("Allowed only in the local network.")

        data = simplejson.loads(web.data())
        if not isinstance(data, list):
            data = [data]
        for d in data:
            thing = client.Thing(web.ctx.site, d['key'], client.storify(d))
            client._run_hooks('on_new_version', thing)

delegate.app.add_processor(readable_url_processor)
