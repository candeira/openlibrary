from catalog.importer.db_read import withKey, get_things
from catalog.read_rc import read_rc
from catalog.utils import key_int
from unicodedata import normalize
import web, re, sys, codecs
sys.path.append('/home/edward/src/olapi')
from olapi import OpenLibrary, unmarshal

sys.stdout = codecs.getwriter('utf-8')(sys.stdout)

rc = read_rc()
ol = OpenLibrary("http://openlibrary.org")
ol.login('EdwardBot', rc['EdwardBot']) 

def copy_fields(from_author, to_author, name):
    new_fields = { 'name': name, 'personal_name': name }
    for k, v in from_author.iteritems():
        if k in ('name', 'personal_name', 'key', 'last_modified', 'type', 'id', 'revision'):
            continue
        if k in to_author:
            assert v == to_author[k]
        else:
            new_fields[k] = v
    return new_fields

def test_copy_fields():
    f = {'name': 'Sheila K. McCullagh', 'personal_name': 'Sheila K. McCullagh', 'last_modified': {'type': '/type/datetime', 'value': '2008-08-30 20:40:41.784992'}, 'key': '/a/OL4340365A', 'birth_date': '1920', 'type': {'key': '/type/author'}, 'id': 18087251, 'revision': 1}
    t = {'name': 'Sheila K. McCullagh', 'last_modified': {'type': '/type/datetime', 'value': '2008-04-29 13:35:46.87638'}, 'key': '/a/OL2622088A', 'type': {'key': '/type/author'}, 'id': 9890186, 'revision': 1}

    assert copy_fields(f, t, 'Sheila K. McCullagh') == {'birth_date': '1920', 'name': 'Sheila K. McCullagh', 'personal_name': 'Sheila K. McCullagh'}


def update_author(key, new):
    q = { 'key': key, }
    for k, v in new.iteritems():
        q[k] = { 'connect': 'update', 'value': v }
    print q
    print ol.write(q, comment='merge author')
    print

def switch_author(old, new):
    q = { 'authors': old['key'], 'type': '/type/edition', }
    for key in get_things(q):
        edition = withKey(key)
        authors = []
        for author in edition['authors']:
            if author['key'] == old['key']:
                author_key = new['key']
            else:
                author_key = author['key']
            authors.append({ 'key': author_key })

        q = {
            'key': key,
            'authors': { 'connect': 'update_list', 'value': authors }
        }
        print ol.write(q, comment='merge authors')

def make_redirect(old, new):
    q = {
        'key': old['key'],
        'location': {'connect': 'update', 'value': new['key'] },
        'type': {'connect': 'update', 'value': '/type/redirect' },
    }
    for k in old.iterkeys():
        if k not in ('key', 'last_modified', 'type', 'id', 'revision'):
            q[str(k)] = { 'connect': 'update', 'value': None }
    print q
    print ol.write(q, comment='replace with redirect')

def do_normalize(author, new_name):
    a = ol.get(author['key'])
    need_update = False
    if a['name'] != new_name:
        a['name'] = new_name
        need_update = True
    for k, v in a.items():
        if isinstance(v, unicode) and v != norm(v):
            a[k] = norm(v)
            need_update = True
    if not need_update:
        return
    print a
    print ol.save(author['key'], a, 'merge authors')

def merge_authors(author, merge_with, new_name):
    new_name = norm(new_name)
    print 'merge author %s:"%s" and %s:"%s"' % (author['key'], author['name'], merge_with['key'], merge_with['name'])
    print 'becomes: "%s"' % `new_name`
    if key_int(author) < key_int(merge_with):
        new_key = author['key']
        print "copy fields from merge_with to", new_key
#        new = copy_fields(merge_with, author, new_name)
#        update_author(new_key, new)
        do_normalize(author, new_name)
        switch_author(merge_with, author)
#        print "delete merge_with"
        make_redirect(merge_with, author)
    else:
        new_key = merge_with['key']
        print "copy fields from author to", new_key
#        new = copy_fields(merge_with, author, new_name)
#        update_author(new_key, new)
        do_normalize(merge_with, new_name)
        switch_author(author, merge_with)
#        print "delete author"
        make_redirect(author, merge_with)
    print

author = withKey(sys.argv[1])
merge_with = withKey(sys.argv[2])

print author
print merge_with

def norm(s):
    return normalize('NFC', s)

name1 = author['name']
name2 = merge_with['name']

print sys.argv
if len(sys.argv) > 3:
    name = norm(sys.argv[3].decode('utf8'))
else:
    assert name1 == name2 or norm(name1) == norm(name2)
    name = norm(name1)

assert not name.startswith('/')

assert author['type']['key'] == '/type/author'
assert merge_with['type']['key'] == '/type/author'

merge_authors(author, merge_with, name)
