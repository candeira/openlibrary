import web
import config

_categories = None
_db = None

def getdb():
    global _db
    if _db is None:
        _db = web.database(config.db_parameters)
    return _db

def get_category_id(category):
    global _categories
    if _categories is None:
        _categories = {}
        for c in getdb().select('category'):
            _categories[c.name] = c.id
    return _categories.get(category)
    
def new(category, olid, filename, author, ip, source_url, width, height):
    category_id = get_category_id(category)
    return getdb().insert('cover', category_id=category_id, 
        olid=olid, filename=filename, author=author, ip=ip,
        source_url=source_url, width=width, height=height)
        
def query(category, olid, offset=0, limit=10):
    category_id = get_category_id(category)
    
    if isinstance(olid, list):
        where = web.reparam('deleted=false AND category_id = $category_id AND ', locals()) \
                + web.sqlors('olid=', olid)
    elif olid is None:
        where = web.reparam('deleted=false AND category_id=$category_id', locals())
    else:
        where = web.reparam('deleted=false AND category_id=$category_id AND olid=$olid', locals())
    
    result = getdb().select('cover',
        what='*',
        where= where,
        order='last_modified desc', 
        offset=offset,
        limit=limit)
    return result.list()

def details(id):
    return getdb().select('cover', what='*', where="id=$id", vars=locals()).list()
    
def touch(id):
    """Sets the last_modified of the specified cover to the current timestamp.
    By doing so, this cover become comes in the top in query because the results are ordered by last_modified.
    """
    getdb().query("UPDATE cover SET last_modified=(current_timestamp at time zone 'utc') where id=$id", vars=locals())

def delete(id):
    getdb().query('UPDATE cover set deleted=true WHERE id=$id', vars=locals())

def get_filename(id):
    d = getdb().select('cover', what='filename', where='id=$id',vars=locals())
    return d and d[0].filename or None
